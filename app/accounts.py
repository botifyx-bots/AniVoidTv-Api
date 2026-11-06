"""Accounts: captcha, register / login (password or Google), DB-backed sessions, profile & settings."""
import re
import secrets
from datetime import datetime, timedelta

import httpx
from bson import ObjectId
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from . import effects, inventory, progress, security
from .config import settings
from .db import enabled, get_db
from .errors import ApiError

router = APIRouter(prefix="/api")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
PASSWORD_RE = re.compile(r"^[\x21-\x7E]{8,64}$")  # letters, digits and special characters, no spaces
RESERVED = {"admin", "administrator", "root", "support", "moderator", "mod", "staff", "system", "anivoid", "anivoidtv", "null", "undefined", "official", "owner"}
LINK_RE = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(com|net|org|io|me|tv|to|cz|xyz|gg|ly|cc|co|info|site|app)\b)", re.I)
STATUSES = ["watching", "completed", "on_hold", "dropped", "plan_to_watch"]
NAME_EXTRA = set(" _-.'!~")
MAX_SESSIONS = 10
LOCK_AFTER, LOCK_MINUTES = 8, 15


def cookie_name() -> str:
    return "__Host-avtv_session" if settings.cookie_secure else "avtv_session"   # __Host- = Secure, Path=/, no Domain


# ------------------------------------------------------------------ helpers
def client_ip(request: Request) -> str:
    if settings.proxy_secret and security.safe_equal(request.headers.get("x-proxy-secret", ""), settings.proxy_secret):
        return request.headers.get("x-client-ip", "")[:64] or "unknown"
    return request.client.host if request.client else "unknown"


def via_proxy(request: Request) -> bool:
    """True when the request carries the shared secret of our Vercel proxy (so X-Client-IP / X-Client-Country can be trusted)."""
    return bool(settings.proxy_secret) and security.safe_equal(request.headers.get("x-proxy-secret", ""), settings.proxy_secret)


def throttle(request: Request, action: str, limit: int, window: float, extra: str = "") -> None:
    if not security.limiter.allow(f"{action}:{client_ip(request)}:{extra}", limit, window):
        raise ApiError(429, "Too many attempts. Please wait a bit and try again.")


def oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception:  # noqa: BLE001
        raise ApiError(404, "Not found")


def iso(d) -> str | None:
    return d.isoformat() if isinstance(d, datetime) else None


def _mask_ip(ip: str) -> str:
    if ":" in ip:
        return ip.split(":")[0] + ":…"
    parts = ip.split(".")
    return ".".join(parts[:2] + ["x", "x"]) if len(parts) == 4 else "unknown"


def _device(ua: str) -> str:
    ua = ua or ""
    browser = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari")) if k in ua), "Browser")
    os_ = next((n for k, n in (("Android", "Android"), ("iPhone", "iOS"), ("iPad", "iPadOS"), ("Windows", "Windows"), ("Mac OS", "macOS"), ("Linux", "Linux")) if k in ua), "unknown OS")
    return f"{browser} on {os_}"


# ------------------------------------------------------------------ sessions (revocable, listed in Settings)
def set_session(response: Response, request: Request, user: dict) -> str:
    db = get_db()
    now = progress.now()
    ttl = settings.session_days * 86400
    sid = secrets.token_urlsafe(18)
    db.sessions.insert_one({"_id": sid, "user_id": user["_id"], "created": now, "last_seen": now, "expires": now + timedelta(seconds=ttl),
                            "ua": request.headers.get("user-agent", "")[:200], "ip": _mask_ip(client_ip(request))})
    old = list(db.sessions.find({"user_id": user["_id"]}).sort("created", -1).skip(MAX_SESSIONS))
    if old:
        db.sessions.delete_many({"_id": {"$in": [s["_id"] for s in old]}})
    token = security.sign({"t": "s", "u": str(user["_id"]), "sid": sid, "pv": user.get("pw_ver", 0)}, ttl)
    response.set_cookie(cookie_name(), token, max_age=ttl, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/")
    return sid


def _session_token(request: Request) -> dict | None:
    return security.unsign(request.cookies.get(cookie_name()) or request.cookies.get("avtv_session"), "s")


def current_user(request: Request) -> dict | None:
    if not enabled():
        return None
    body = _session_token(request)
    if not body or not body.get("sid"):
        return None
    db = get_db()
    sess = db.sessions.find_one({"_id": body["sid"], "user_id": oid(body["u"])})
    if not sess or sess["expires"] < progress.now():
        return None
    u = db.users.find_one({"_id": sess["user_id"]})
    if not u or u.get("pw_ver", 0) != body.get("pv", 0) or u.get("banned"):
        return None
    request.state.sid = body["sid"]
    if progress.now() - sess["last_seen"] > timedelta(minutes=10):
        db.sessions.update_one({"_id": sess["_id"]}, {"$set": {"last_seen": progress.now()}})
    return u


def require_user(request: Request) -> dict:
    u = current_user(request)
    if not u:
        raise ApiError(401, "Please sign in first.", auth_required=True)
    return u


# ------------------------------------------------------------------ profile views
def list_counts(db, uid) -> dict:
    counts = {s: 0 for s in STATUSES}
    for row in db.anime_list.aggregate([{"$match": {"user_id": uid}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = row["n"]
    return counts


def stats_of(db, u: dict) -> dict:
    counts = list_counts(db, u["_id"])
    st = u.get("stats", {})
    vp = u.get("vp", 0)
    joined = u.get("created_at")
    days = max(0, (progress.now() - joined).days) if isinstance(joined, datetime) else 0
    return {
        "episodes": st.get("episodes", 0), "minutes": st.get("minutes", 0),
        "hours": round(st.get("minutes", 0) / 60, 1), "comments": st.get("comments", 0),
        "list_counts": counts, "list_total": sum(counts.values()), "completed": counts["completed"],
        "best_streak": u.get("best_streak", 0), "days_on_site": days, "rank": progress.rank_index(vp),
        "pics": db.media.count_documents({"user_id": u["_id"], "kind": "avatar"}), "owned": len(u.get("owned", [])),
    }


def name_of(u: dict) -> str:
    return u.get("display_name") or u["username"]


def avatar_of(u: dict) -> dict:
    a = u.get("avatar") or {}
    default_bg = sum(map(ord, u["username_lower"])) % progress.AVATAR_BG_COUNT  # stable across restarts
    icon = a.get("icon", "initial")
    return {"bg": a.get("bg", default_bg), "icon": icon if icon in effects.AVATAR_GLYPHS else "initial",
            "pic": str(u["avatar_main"]) if u.get("avatar_main") else None}


def banner_of(u: dict) -> dict:
    pic = str(u["banner_main"]) if u.get("banner_main") else None
    return {"pic": pic, "preset": None if pic else (u.get("banner_preset") or "p1")}


def brief(u: dict) -> dict:
    """Tiny public card used inside comments, lists, friends."""
    return {"username": u["username"], "name": name_of(u), "avatar": avatar_of(u), "fx": inventory.fx_public(u),
            "rank": progress.rank_info(u.get("vp", 0))["title"]}


def public_view(db, u: dict, me: bool = False) -> dict:
    stats = stats_of(db, u)
    vp = u.get("vp", 0)
    pics = [str(m["_id"]) for m in db.media.find({"user_id": u["_id"], "kind": "avatar"}).sort("created", -1).limit(30)]
    out = {
        "username": u["username"], "name": name_of(u), "avatar": avatar_of(u), "banner": banner_of(u), "accent": u.get("accent", 0),
        "fx": inventory.fx_public(u), "bio": u.get("bio", ""), "joined": iso(u.get("created_at")), "vp": vp,
        "rank": progress.rank_info(vp), "stats": stats, "favorites": u.get("favorites", []), "badges": progress.badges_for(stats),
        "streak": u.get("streak", 0), "privacy": u.get("privacy", {"show_list": True}), "pictures": pics,
    }
    if me:
        out.update({
            "id": str(u["_id"]), "display_name": u.get("display_name"), "email": u.get("email"), "has_password": bool(u.get("pw_hash")),
            "google_linked": bool(u.get("google_sub")), "checked_in_today": u.get("last_checkin") == progress.today(),
            "owned": sorted(u.get("owned", [])), "equipped": inventory.equipped_of(u), "avatar_glyphs": effects.AVATAR_GLYPHS,
            "avatar_bg_count": progress.AVATAR_BG_COUNT, "banner_presets": effects.BANNER_PRESETS, "packs": sorted(inventory.packs_usable(u)),
        })
    return out


# ------------------------------------------------------------------ validation
def validate_username(name: str) -> str:
    name = (name or "").strip()
    if not USERNAME_RE.match(name):
        raise ApiError(400, "Username must be 3-20 characters: letters, numbers and underscore only.")
    if name.lower() in RESERVED:
        raise ApiError(400, "That username is reserved.")
    return name


def validate_password(pw: str, username: str = "") -> str:
    if not PASSWORD_RE.match(pw or ""):
        raise ApiError(400, "Password must be 8-64 characters (letters, numbers, symbols; no spaces).")
    if username and pw.lower() == username.lower():
        raise ApiError(400, "Password can't be the same as your username.")
    if pw.lower() in security.COMMON_PASSWORDS or len(set(pw)) < 4:
        raise ApiError(400, "That password is too common. Pick something harder to guess.")
    return pw


def validate_display_name(db, name: str, me: dict | None) -> str:
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not 2 <= len(name) <= 24:
        raise ApiError(400, "Display name must be 2-24 characters.")
    if not all(c.isalnum() or c in NAME_EXTRA for c in name) or not any(c.isalnum() for c in name):
        raise ApiError(400, "Display name can use letters, numbers, spaces and _ - . ' ! ~ only.")
    if LINK_RE.search(name):
        raise ApiError(400, "Display name can't contain links.")
    low = name.casefold()
    if low in RESERVED:
        raise ApiError(400, "That name is reserved.")
    other = db.users.find_one({"username_lower": low})
    if other and (not me or other["_id"] != me["_id"]):
        raise ApiError(409, "That name matches another member's username. Pick a different one.")
    return name


def create_user(db, username: str, *, pw_hash: str | None = None, email: str | None = None, google_sub: str | None = None) -> dict:
    now = progress.now()
    doc = {
        "username": username, "username_lower": username.lower(), "pw_hash": pw_hash, "pw_ver": 0,
        "email": email, "email_lower": email.lower() if email else None, "google_sub": google_sub,
        "created_at": now, "bio": "", "favorites": [], "avatar": {}, "privacy": {"show_list": True},
        "vp": 0, "stats": {"episodes": 0, "minutes": 0, "comments": 0}, "streak": 0, "best_streak": 0,
        "owned": [], "equipped": {}, "accent": 0,
    }
    for k in ("email", "email_lower", "google_sub"):
        if doc[k] is None:
            del doc[k]  # keep partial unique indexes clean
    try:
        doc["_id"] = db.users.insert_one(doc).inserted_id
    except DuplicateKeyError:
        raise ApiError(409, "That username is already taken.")
    progress.award(db, doc, "welcome")
    return doc


# ------------------------------------------------------------------ models
class CaptchaIn(BaseModel):
    captcha_token: str = Field(default="", max_length=600)
    captcha_answer: str = Field(default="", max_length=12)


class RegisterIn(CaptchaIn):
    username: str = Field(max_length=40)
    password: str = Field(max_length=100)
    confirm: str | None = Field(default=None, max_length=100)


class LoginIn(CaptchaIn):
    username: str = Field(max_length=80)
    password: str = Field(max_length=100)


class GoogleIn(BaseModel):
    credential: str = Field(max_length=4000)


class GoogleCompleteIn(BaseModel):
    ticket: str = Field(max_length=800)
    username: str = Field(max_length=40)


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=60)
    bio: str | None = Field(default=None, max_length=400)
    avatar: dict | None = None
    banner: dict | None = None
    accent: int | None = None
    favorites: list[dict] | None = Field(default=None, max_length=20)
    privacy: dict | None = None


class PasswordIn(BaseModel):
    current: str = Field(default="", max_length=100)
    new: str = Field(max_length=100)


class UsernameIn(BaseModel):
    username: str = Field(max_length=40)
    password: str = Field(default="", max_length=100)


# ------------------------------------------------------------------ public config + captcha
@router.get("/config")
def config():
    from . import flags
    return {"success": True, "results": {"accounts": enabled(), "google_client_id": settings.google_client_id or None, "flags": flags.public(get_db() if enabled() else None)}}


@router.get("/auth/captcha")
def captcha(request: Request):
    throttle(request, "captcha", 40, 600)
    return {"success": True, "results": security.new_captcha()}


# ------------------------------------------------------------------ register / login
@router.post("/auth/register")
def register(body: RegisterIn, request: Request, response: Response):
    db = get_db()
    from . import flags
    flags.require(db, "registration_enabled", "Sign-ups are paused right now. Please try again later.")
    throttle(request, "register", 8, 3600)
    if not security.check_captcha(db, body.captcha_token, body.captcha_answer):
        raise ApiError(400, "Captcha is wrong or expired. Try the new one.", captcha_failed=True)
    username = validate_username(body.username)
    validate_password(body.password, username)
    if body.confirm is not None and body.confirm != body.password:
        raise ApiError(400, "Passwords don't match.")
    if db.users.find_one({"username_lower": username.lower()}):
        raise ApiError(409, "That username is already taken.")
    user = create_user(db, username, pw_hash=security.hash_password(body.password))
    set_session(response, request, user)
    return {"success": True, "results": public_view(db, user, me=True)}


def _locked(db, ident: str) -> bool:
    f = db.login_fail.find_one({"_id": ident})
    return bool(f and f.get("until") and f["until"] > progress.now())


def _fail(db, ident: str) -> None:
    now = progress.now()
    f = db.login_fail.find_one_and_update({"_id": ident}, {"$inc": {"n": 1}, "$set": {"expires": now + timedelta(minutes=LOCK_MINUTES)}}, upsert=True,
                                          return_document=True)
    if f and f.get("n", 0) >= LOCK_AFTER:
        db.login_fail.update_one({"_id": ident}, {"$set": {"until": now + timedelta(minutes=LOCK_MINUTES), "n": 0}})


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response):
    db = get_db()
    throttle(request, "login", 15, 600)
    ident = body.username.strip().lower()
    if _locked(db, ident):
        raise ApiError(429, f"Too many wrong passwords. This account is locked for {LOCK_MINUTES} minutes.")
    if not security.check_captcha(db, body.captcha_token, body.captcha_answer):
        raise ApiError(400, "Captcha is wrong or expired. Try the new one.", captcha_failed=True)
    user = db.users.find_one({"username_lower": ident}) or db.users.find_one({"email_lower": ident})
    if not user or not security.verify_password(body.password, user.get("pw_hash")):
        _fail(db, ident)
        raise ApiError(401, "Wrong username or password." if not (user and not user.get("pw_hash"))
                       else "This account uses Google sign-in. Use the Google button.")
    if user.get("banned"):
        raise ApiError(403, "This account has been suspended.")
    db.login_fail.delete_one({"_id": ident})
    set_session(response, request, user)
    return {"success": True, "results": public_view(db, user, me=True)}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    body = _session_token(request)
    if body and body.get("sid") and enabled():
        get_db().sessions.delete_one({"_id": body["sid"]})
    response.delete_cookie(cookie_name(), path="/")
    return {"success": True}


@router.post("/auth/logout-all")
def logout_all(request: Request, response: Response):
    db, u = get_db(), require_user(request)
    n = db.sessions.delete_many({"user_id": u["_id"]}).deleted_count
    response.delete_cookie(cookie_name(), path="/")
    return {"success": True, "results": {"signed_out": n}}


# ------------------------------------------------------------------ Google
def _verify_google(credential: str) -> dict:
    if not settings.google_client_id:
        raise ApiError(503, "Google sign-in is not configured.")
    try:
        r = httpx.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": credential}, timeout=10)
    except httpx.HTTPError:
        raise ApiError(502, "Could not reach Google. Try again.")
    info = r.json() if r.status_code == 200 else {}
    if info.get("aud") != settings.google_client_id or str(info.get("email_verified")).lower() != "true" or not info.get("sub"):
        raise ApiError(401, "Google sign-in failed.")
    return info


@router.post("/auth/google")
def google_login(body: GoogleIn, request: Request, response: Response):
    db = get_db()
    throttle(request, "google", 20, 600)
    info = _verify_google(body.credential)
    sub, email = info["sub"], info["email"]
    user = db.users.find_one({"google_sub": sub}) or db.users.find_one({"email_lower": email.lower()})
    if user:  # existing account (same Google or same verified email): sign in and link
        if user.get("banned"):
            raise ApiError(403, "This account has been suspended.")
        if not user.get("google_sub"):
            db.users.update_one({"_id": user["_id"]}, {"$set": {"google_sub": sub}})
        set_session(response, request, user)
        return {"success": True, "results": {"status": "ok", "user": public_view(db, user, me=True)}}
    from . import flags
    flags.require(db, "registration_enabled", "Sign-ups are paused right now. Please try again later.")
    ticket = security.sign({"t": "g", "sub": sub, "email": email}, 600)
    return {"success": True, "results": {"status": "need_username", "ticket": ticket, "email": email}}


@router.post("/auth/google/complete")
def google_complete(body: GoogleCompleteIn, request: Request, response: Response):
    db = get_db()
    throttle(request, "google", 20, 600)
    t = security.unsign(body.ticket, "g")
    if not t:
        raise ApiError(400, "Sign-in session expired. Please try Google again.")
    username = validate_username(body.username)
    if db.users.find_one({"username_lower": username.lower()}):
        raise ApiError(409, "That username is already taken.")
    user = create_user(db, username, email=t["email"], google_sub=t["sub"])
    set_session(response, request, user)
    return {"success": True, "results": public_view(db, user, me=True)}


# ------------------------------------------------------------------ me
@router.get("/me")
def me(request: Request):
    u = require_user(request)
    return {"success": True, "results": public_view(get_db(), u, me=True)}


def _clean_favorites(items: list[dict]) -> list[dict]:
    out, seen = [], set()
    for it in items[:10]:
        try:
            aid = int(it.get("id"))
        except (TypeError, ValueError):
            continue
        if aid in seen or aid <= 0:
            continue
        seen.add(aid)
        out.append({"id": aid, "title": str(it.get("title", ""))[:160], "poster": str(it.get("poster", ""))[:400]})
    return out


@router.patch("/me")
def update_me(body: ProfileIn, request: Request):
    db, u = get_db(), require_user(request)
    sets: dict = {}
    unsets: dict = {}
    if body.display_name is not None:
        throttle(request, "dname", 10, 3600, str(u["_id"]))
        if body.display_name.strip() == "":
            unsets["display_name"] = ""
        else:
            sets["display_name"] = validate_display_name(db, body.display_name, u)
    if body.bio is not None:
        bio = re.sub(r"\n{3,}", "\n\n", body.bio.strip())
        if LINK_RE.search(bio):
            raise ApiError(400, "Bio is plain text only: no links or websites.")
        sets["bio"] = bio
    if body.avatar is not None:
        cur = avatar_of(u)
        bg, icon = body.avatar.get("bg", cur["bg"]), body.avatar.get("icon", cur["icon"])
        if not isinstance(bg, int) or not 0 <= bg < progress.AVATAR_BG_COUNT:
            raise ApiError(400, "Invalid avatar colour.")
        if icon not in effects.AVATAR_GLYPHS:
            raise ApiError(400, "Invalid avatar icon.")
        sets["avatar"] = {"bg": bg, "icon": icon}
    if body.banner is not None:
        preset = body.banner.get("preset")
        if preset not in effects.BANNER_PRESETS:
            raise ApiError(400, "Invalid banner preset.")
        sets["banner_preset"] = preset
        unsets["banner_main"] = ""      # a preset replaces the uploaded banner
    if body.accent is not None:
        if not 0 <= body.accent < progress.AVATAR_BG_COUNT:
            raise ApiError(400, "Invalid accent colour.")
        sets["accent"] = body.accent
    if body.favorites is not None:
        sets["favorites"] = _clean_favorites(body.favorites)
    if body.privacy is not None:
        sets["privacy"] = {"show_list": bool(body.privacy.get("show_list", True))}
    if sets or unsets:
        db.users.update_one({"_id": u["_id"]}, {**({"$set": sets} if sets else {}), **({"$unset": unsets} if unsets else {})})
        u = db.users.find_one({"_id": u["_id"]})
    return {"success": True, "results": public_view(db, u, me=True)}


@router.post("/me/password")
def change_password(body: PasswordIn, request: Request, response: Response):
    db, u = get_db(), require_user(request)
    throttle(request, "pwchange", 8, 3600, str(u["_id"]))
    if u.get("pw_hash") and not security.verify_password(body.current, u["pw_hash"]):
        raise ApiError(400, "Current password is wrong.")
    validate_password(body.new, u["username"])
    db.users.update_one({"_id": u["_id"]}, {"$set": {"pw_hash": security.hash_password(body.new)}, "$inc": {"pw_ver": 1}})
    db.sessions.delete_many({"user_id": u["_id"]})   # every device is signed out...
    u = db.users.find_one({"_id": u["_id"]})
    set_session(response, request, u)                # ...except this one
    return {"success": True, "message": "Password updated. Other devices were signed out."}


@router.post("/me/username")
def change_username(body: UsernameIn, request: Request):
    db, u = get_db(), require_user(request)
    name = validate_username(body.username)
    if u.get("pw_hash") and not security.verify_password(body.password, u["pw_hash"]):
        raise ApiError(400, "Password is wrong.")
    last = u.get("username_changed_at")
    if isinstance(last, datetime) and progress.now() - last < timedelta(days=30):
        raise ApiError(429, "You can change your username once every 30 days.")
    if name.lower() != u["username_lower"] and db.users.find_one({"username_lower": name.lower()}):
        raise ApiError(409, "That username is already taken.")
    try:
        db.users.update_one({"_id": u["_id"]}, {"$set": {"username": name, "username_lower": name.lower(),
                                                       "username_changed_at": progress.now()}})
    except DuplicateKeyError:
        raise ApiError(409, "That username is already taken.")
    u = db.users.find_one({"_id": u["_id"]})
    return {"success": True, "results": public_view(db, u, me=True)}


@router.get("/me/sessions")
def my_sessions(request: Request):
    db, u = get_db(), require_user(request)
    cur = getattr(request.state, "sid", None)
    rows = db.sessions.find({"user_id": u["_id"]}).sort("last_seen", -1)
    return {"success": True, "results": [{"id": s["_id"], "device": _device(s.get("ua", "")), "ip": s.get("ip", ""), "created": iso(s["created"]),
                                          "last_seen": iso(s["last_seen"]), "current": s["_id"] == cur} for s in rows]}


@router.delete("/me/sessions/{sid}")
def revoke_session(sid: str, request: Request):
    db, u = get_db(), require_user(request)
    n = db.sessions.delete_one({"_id": sid, "user_id": u["_id"]}).deleted_count
    if not n:
        raise ApiError(404, "Session not found.")
    return {"success": True}


@router.post("/me/checkin")
def daily_checkin(request: Request):
    db, u = get_db(), require_user(request)
    res = progress.checkin(db, u)
    u = db.users.find_one({"_id": u["_id"]})
    return {"success": True, "results": {**res, "rank": progress.rank_info(u.get("vp", 0))}}


@router.get("/me/vp")
def vp_history(request: Request):
    db, u = get_db(), require_user(request)
    rows = db.vp_log.find({"user_id": u["_id"]}).sort("at", -1).limit(50)
    return {"success": True, "results": [{"delta": r["delta"], "reason": r["reason"], "at": iso(r["at"])} for r in rows]}
