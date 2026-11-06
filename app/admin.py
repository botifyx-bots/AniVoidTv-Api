"""Admin console API (UI lives at /AnimeVoid on the frontend).

Security model
  * separate from member accounts: username + password (scrypt hash) + TOTP 2FA, all from environment variables
  * unconfigured / wrong IP => 404, so the surface is invisible
  * HttpOnly SameSite=Strict cookie, idle timeout, absolute lifetime, CSRF token on every write
  * 5 wrong attempts from one IP lock it for 30 minutes, codes can't be replayed
  * everything that changes something is written to the audit log
"""
import secrets
import time
from datetime import timedelta

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field

from . import catalog, crawler, effects, flags, progress, security, telemetry
from .accounts import client_ip, iso, oid, require_user, throttle
from .config import settings
from .db import enabled, get_db
from .errors import ApiError
from .media import drop_main

router = APIRouter(prefix="/api")
LOCK_AFTER, LOCK_MINUTES = 5, 30


def cookie_name() -> str:
    return "__Host-avtv_admin" if settings.cookie_secure else "avtv_admin"


def configured() -> bool:
    return bool(settings.admin_username and settings.admin_password_hash and settings.admin_totp_secret and enabled())


def _ip_ok(request: Request) -> bool:
    return not settings.admin_ips or client_ip(request) in settings.admin_ips


def _mask(ip: str) -> str:
    parts = ip.split(".")
    return ".".join(parts[:2] + ["x", "x"]) if len(parts) == 4 else (ip.split(":")[0] + ":…" if ":" in ip else "unknown")


def audit(db, actor: str, action: str, target: str = "", ok: bool = True, ip: str = "", detail: str = "") -> None:
    db.audit.insert_one({"at": progress.now(), "actor": actor, "action": action, "target": target[:80], "ok": ok, "ip": _mask(ip), "detail": detail[:200]})


def require_admin(request: Request, write: bool = False) -> dict:
    if not configured() or not _ip_ok(request):
        raise ApiError(404, "Not found")
    body = security.unsign(request.cookies.get(cookie_name()) or request.cookies.get("avtv_admin"), "a")
    if not body:
        raise ApiError(401, "Sign in required", admin_auth_required=True)
    db, now = get_db(), progress.now()
    s = db.admin_sessions.find_one({"_id": body["sid"]})
    if not s or s["expires"] < now or now - s["last_seen"] > timedelta(minutes=settings.admin_idle_minutes):
        if s:
            db.admin_sessions.delete_one({"_id": s["_id"]})
        raise ApiError(401, "Session expired, sign in again", admin_auth_required=True)
    if write and not security.safe_equal(request.headers.get("x-admin-csrf", ""), s["csrf"]):
        raise ApiError(403, "Missing or wrong CSRF token")
    db.admin_sessions.update_one({"_id": s["_id"]}, {"$set": {"last_seen": now}})
    return s


class LoginIn(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=200)
    otp: str = Field(max_length=12)


@router.post("/admin/login")
def login(body: LoginIn, request: Request, response: Response):
    if not configured() or not _ip_ok(request):
        raise ApiError(404, "Not found")
    db, ip, now = get_db(), client_ip(request), progress.now()
    throttle(request, "adminlogin", 12, 600)
    fail = db.admin_fail.find_one({"_id": ip})
    if fail and fail.get("until") and fail["until"] > now:
        audit(db, "?", "login_blocked", "", False, ip)
        raise ApiError(429, f"Too many attempts. Locked for {LOCK_MINUTES} minutes.")
    user_ok = security.safe_equal(body.username.strip().lower(), settings.admin_username.lower())
    pass_ok = security.verify_password(body.password, settings.admin_password_hash)       # always run: constant work either way
    counter = security.totp_verify(settings.admin_totp_secret, body.otp)
    last = (db.admin_state.find_one({"_id": "totp"}) or {}).get("last", 0)
    ok = user_ok and pass_ok and counter is not None and counter > last
    if not ok:
        f = db.admin_fail.find_one_and_update({"_id": ip}, {"$inc": {"n": 1}, "$set": {"expires": now + timedelta(minutes=LOCK_MINUTES)}}, upsert=True, return_document=True)
        if f.get("n", 0) >= LOCK_AFTER:
            db.admin_fail.update_one({"_id": ip}, {"$set": {"until": now + timedelta(minutes=LOCK_MINUTES), "n": 0}})
        audit(db, body.username.strip()[:40], "login_failed", "", False, ip)
        time.sleep(0.4)
        raise ApiError(401, "Invalid credentials")
    db.admin_state.update_one({"_id": "totp"}, {"$max": {"last": counter}}, upsert=True)
    db.admin_fail.delete_one({"_id": ip})
    sid, csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    ttl = settings.admin_max_hours * 3600
    db.admin_sessions.insert_one({"_id": sid, "created": now, "last_seen": now, "expires": now + timedelta(seconds=ttl), "ip": _mask(ip), "ua": request.headers.get("user-agent", "")[:160], "csrf": csrf})
    response.set_cookie(cookie_name(), security.sign({"t": "a", "sid": sid}, ttl), max_age=ttl, httponly=True, secure=settings.cookie_secure, samesite="strict", path="/")
    audit(db, settings.admin_username, "login", "", True, ip)
    return {"success": True, "results": {"username": settings.admin_username, "csrf": csrf}}


@router.post("/admin/logout")
def logout(request: Request, response: Response):
    s = require_admin(request, write=True)
    get_db().admin_sessions.delete_one({"_id": s["_id"]})
    audit(get_db(), settings.admin_username, "logout", "", True, client_ip(request))
    response.delete_cookie(cookie_name(), path="/")
    return {"success": True}


@router.get("/admin/me")
def me(request: Request):
    s = require_admin(request)
    return {"success": True, "results": {"username": settings.admin_username, "csrf": s["csrf"], "idle_minutes": settings.admin_idle_minutes}}


# ------------------------------------------------------------------ member reports (queue shown in the console)
class ReportIn(BaseModel):
    type: str = Field(pattern="^(comment|media|user)$")
    target: str = Field(max_length=60)
    reason: str = Field(default="", max_length=300)


@router.post("/report")
def report(body: ReportIn, request: Request):
    db, u = get_db(), require_user(request)
    throttle(request, "report", 10, 3600, str(u["_id"]))
    db.reports.insert_one({"type": body.type, "target": body.target, "reason": body.reason.strip(), "by": u["_id"], "created": progress.now(), "open": True})
    return {"success": True, "message": "Thanks, a moderator will take a look."}


# ------------------------------------------------------------------ analytics
@router.get("/admin/overview")
def overview(request: Request):
    require_admin(request)
    db = get_db()
    return {"success": True, "results": {**telemetry.overview(db), "crawl": crawler.state, "flags": flags.all_flags(db)}}


@router.get("/admin/timeseries")
def timeseries(request: Request, days: int = Query(14, ge=1, le=90)):
    require_admin(request)
    return {"success": True, "results": telemetry.timeseries(get_db(), days)}


@router.get("/admin/devices")
def devices(request: Request, filter: str = Query("all", pattern="^(all|online|pwa|android|ios|desktop|loggedin)$"), page: int = Query(1, ge=1), per_page: int = Query(25, ge=1, le=100)):
    require_admin(request)
    db, now = get_db(), progress.now()
    q: dict = {}
    if filter == "online":
        q = {"last_seen": {"$gte": now - timedelta(minutes=2)}}
    elif filter == "pwa":
        q = {"standalone": True}
    elif filter == "android":
        q = {"os": "Android"}
    elif filter == "ios":
        q = {"os": {"$in": ["iOS", "iPadOS"]}}
    elif filter == "desktop":
        q = {"kind": "desktop"}
    elif filter == "loggedin":
        q = {"user_id": {"$exists": True}}
    total = db.devices.count_documents(q)
    rows = list(db.devices.find(q).sort("last_seen", -1).skip((page - 1) * per_page).limit(per_page))
    users = {u["_id"]: u["username"] for u in db.users.find({"_id": {"$in": [r["user_id"] for r in rows if r.get("user_id")]}}, {"username": 1})}
    return {"success": True, "results": {"total": total, "page": page, "data": [{
        "id": r["_id"][:6] + "…", "os": r.get("os"), "browser": r.get("browser"), "kind": r.get("kind"), "app": bool(r.get("standalone")), "country": r.get("country"),
        "first_seen": iso(r.get("first_seen")), "last_seen": iso(r.get("last_seen")), "views": r.get("views", 0), "page": r.get("last_path"), "user": users.get(r.get("user_id")),
        "online": bool(r.get("last_seen") and now - r["last_seen"] < timedelta(minutes=2))} for r in rows]}}


# ------------------------------------------------------------------ users
@router.get("/admin/users")
def users(request: Request, q: str = Query("", max_length=40), page: int = Query(1, ge=1), per_page: int = Query(25, ge=1, le=100)):
    require_admin(request)
    db = get_db()
    flt = {"$or": [{"username_lower": {"$regex": "^" + __import__("re").escape(q.lower())}}, {"display_name": {"$regex": "^" + __import__("re").escape(q), "$options": "i"}}]} if q else {}
    total = db.users.count_documents(flt)
    rows = list(db.users.find(flt).sort("created_at", -1).skip((page - 1) * per_page).limit(per_page))
    return {"success": True, "results": {"total": total, "page": page, "data": [{
        "username": u["username"], "name": u.get("display_name") or u["username"], "vp": u.get("vp", 0), "rank": progress.rank_info(u.get("vp", 0))["title"],
        "joined": iso(u.get("created_at")), "comments": u.get("stats", {}).get("comments", 0), "episodes": u.get("stats", {}).get("episodes", 0),
        "google": bool(u.get("google_sub")), "banned": bool(u.get("banned")), "sessions": db.sessions.count_documents({"user_id": u["_id"]})} for u in rows]}}


def _user(db, username: str) -> dict:
    u = db.users.find_one({"username_lower": username.lower()})
    if not u:
        raise ApiError(404, "User not found.")
    return u


@router.post("/admin/users/{username}/ban")
def ban(username: str, request: Request):
    require_admin(request, write=True)
    db = get_db(); u = _user(db, username)
    db.users.update_one({"_id": u["_id"]}, {"$set": {"banned": True}}); db.sessions.delete_many({"user_id": u["_id"]})
    audit(db, settings.admin_username, "ban", u["username"], True, client_ip(request))
    return {"success": True}


@router.post("/admin/users/{username}/unban")
def unban(username: str, request: Request):
    require_admin(request, write=True)
    db = get_db(); u = _user(db, username)
    db.users.update_one({"_id": u["_id"]}, {"$set": {"banned": False}})
    audit(db, settings.admin_username, "unban", u["username"], True, client_ip(request))
    return {"success": True}


@router.post("/admin/users/{username}/signout")
def force_signout(username: str, request: Request):
    require_admin(request, write=True)
    db = get_db(); u = _user(db, username)
    n = db.sessions.delete_many({"user_id": u["_id"]}).deleted_count
    audit(db, settings.admin_username, "force_signout", u["username"], True, client_ip(request), f"{n} sessions")
    return {"success": True, "results": {"signed_out": n}}


class VPIn(BaseModel):
    delta: int = Field(ge=-100000, le=100000)
    reason: str = Field(default="", max_length=80)


@router.post("/admin/users/{username}/vp")
def grant_vp(username: str, body: VPIn, request: Request):
    require_admin(request, write=True)
    db = get_db(); u = _user(db, username)
    db.users.update_one({"_id": u["_id"]}, {"$inc": {"vp": body.delta}})
    db.vp_log.insert_one({"user_id": u["_id"], "delta": body.delta, "reason": "admin", "at": progress.now()})
    audit(db, settings.admin_username, "vp", u["username"], True, client_ip(request), f"{body.delta:+d} {body.reason}")
    return {"success": True}


# ------------------------------------------------------------------ moderation
@router.get("/admin/reports")
def reports(request: Request):
    require_admin(request)
    db = get_db()
    out = []
    for r in db.reports.find({"open": True}).sort("created", -1).limit(100):
        preview = None
        if r["type"] == "comment":
            c = db.comments.find_one({"_id": oid(r["target"])}) if len(r["target"]) == 24 else None
            preview = c["text"][:200] if c else "(already deleted)"
        out.append({"id": str(r["_id"]), "type": r["type"], "target": r["target"], "reason": r["reason"], "preview": preview, "created": iso(r["created"])})
    return {"success": True, "results": out}


@router.post("/admin/reports/{report_id}/resolve")
def resolve(report_id: str, request: Request):
    require_admin(request, write=True)
    db = get_db()
    db.reports.update_one({"_id": oid(report_id)}, {"$set": {"open": False}})
    audit(db, settings.admin_username, "report_resolved", report_id, True, client_ip(request))
    return {"success": True}


@router.delete("/admin/comments/{comment_id}")
def delete_comment(comment_id: str, request: Request):
    require_admin(request, write=True)
    db = get_db()
    c = db.comments.find_one({"_id": oid(comment_id)})
    if not c:
        raise ApiError(404, "Comment not found.")
    n = 1 + (db.comments.delete_many({"parent_id": c["_id"]}).deleted_count if not c.get("parent_id") else 0)
    db.comments.delete_one({"_id": c["_id"]})
    db.reports.update_many({"type": "comment", "target": comment_id}, {"$set": {"open": False}})
    audit(db, settings.admin_username, "comment_deleted", comment_id, True, client_ip(request))
    return {"success": True, "results": {"removed": n}}


@router.delete("/admin/media/{media_id}")
def delete_media(media_id: str, request: Request):
    require_admin(request, write=True)
    db = get_db()
    m = db.media.find_one({"_id": oid(media_id)}, {"data": 0})
    if not m:
        raise ApiError(404, "Picture not found.")
    db.media.delete_one({"_id": m["_id"]}); drop_main(db, None, m)
    db.reports.update_many({"type": "media", "target": media_id}, {"$set": {"open": False}})
    audit(db, settings.admin_username, "media_deleted", media_id, True, client_ip(request))
    return {"success": True}


# ------------------------------------------------------------------ feature flags / announcement
@router.get("/admin/flags")
def get_flags(request: Request):
    require_admin(request)
    db = get_db()
    return {"success": True, "results": {"values": flags.all_flags(db, fresh=True), "info": {k: {"description": v[1], "type": "bool" if isinstance(v[0], bool) else "text"} for k, v in flags.FLAGS.items()}}}


@router.put("/admin/flags")
def put_flags(body: dict, request: Request):
    require_admin(request, write=True)
    db = get_db()
    vals = flags.set_flags(db, body)
    audit(db, settings.admin_username, "flags", ",".join(sorted(body))[:80], True, client_ip(request))
    return {"success": True, "results": vals}


# ------------------------------------------------------------------ audit / security / system
@router.get("/admin/audit")
def get_audit(request: Request, page: int = Query(1, ge=1)):
    require_admin(request)
    db = get_db()
    rows = db.audit.find({}).sort("at", -1).skip((page - 1) * 50).limit(50)
    return {"success": True, "results": [{"at": iso(r["at"]), "actor": r["actor"], "action": r["action"], "target": r.get("target", ""), "ok": r["ok"], "ip": r.get("ip", ""), "detail": r.get("detail", "")} for r in rows]}


def security_checks() -> list[dict]:
    uri = settings.mongodb_uri
    items = [
        ("SESSION_SECRET is set and strong", len(settings.session_secret) >= 32, "Set a random 64-char SESSION_SECRET on Render."),
        ("PROXY_SECRET is set", bool(settings.proxy_secret), "Set the same random PROXY_SECRET on Render and Vercel."),
        ("Only the Vercel proxy may call the API (REQUIRE_PROXY)", settings.require_proxy and bool(settings.proxy_secret), "Needs PROXY_SECRET; direct internet calls to the backend are then rejected."),
        ("Cookies are Secure (COOKIE_SECURE)", settings.cookie_secure, "Keep COOKIE_SECURE=true in production."),
        ("/docs and /openapi.json are hidden", settings.disable_docs, "Set DISABLE_DOCS=true."),
        ("Admin 2FA (TOTP) is configured", bool(settings.admin_totp_secret), "Run tools/admin_setup.py."),
        ("Admin password is stored as a hash", settings.admin_password_hash.startswith("scrypt$"), "Use ADMIN_PASSWORD_HASH from tools/admin_setup.py."),
        ("Admin IP allow-list (optional hardening)", bool(settings.admin_ips), "Set ADMIN_IPS to your own IPs if they are stable."),
        ("TRUSTED_HOSTS is set (optional hardening)", bool(settings.trusted_hosts), "Set TRUSTED_HOSTS to your Render hostname."),
        ("MongoDB connection uses TLS", uri.startswith("mongodb+srv://") or "tls=true" in uri.lower(), "Use the mongodb+srv:// Atlas string."),
        ("Wide-open CORS is off", "*" not in settings.cors_origins, "Leave CORS_ORIGINS empty."),
    ]
    return [{"name": n, "ok": bool(ok), "fix": fix} for n, ok, fix in items]


@router.get("/admin/security")
def security_view(request: Request):
    require_admin(request)
    db = get_db()
    since = progress.now() - timedelta(hours=24)
    return {"success": True, "results": {"checks": security_checks(), "failed_logins_24h": db.audit.count_documents({"action": "login_failed", "at": {"$gte": since}}),
                                         "admin_sessions": db.admin_sessions.count_documents({}), "banned_users": db.users.count_documents({"banned": True})}}


@router.post("/admin/sessions/revoke-all")
def revoke_admin_sessions(request: Request, response: Response):
    require_admin(request, write=True)
    db = get_db()
    n = db.admin_sessions.delete_many({}).deleted_count
    audit(db, settings.admin_username, "admin_sessions_revoked", str(n), True, client_ip(request))
    response.delete_cookie(cookie_name(), path="/")
    return {"success": True, "results": {"revoked": n}}


@router.get("/admin/system")
def system(request: Request):
    require_admin(request)
    return {"success": True, "results": {"crawl": crawler.state, "catalog_entries": catalog.size(), "effects": effects.EFFECT_COUNT, "decorations": effects.DECORATIONS, "items": len(effects.ITEMS)}}


@router.post("/admin/crawl")
def start_crawl(request: Request):
    require_admin(request, write=True)
    if crawler._lock.locked():
        return {"success": True, "message": "A crawl is already running"}
    crawler.start_background("admin")
    audit(get_db(), settings.admin_username, "crawl_started", "", True, client_ip(request))
    return {"success": True, "message": "Crawl started"}
