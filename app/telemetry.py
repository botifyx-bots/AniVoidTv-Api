"""Anonymous device analytics: how many devices are using the site, where and how (powers the admin console).
Stores a random device id (from the browser), user-agent class, display mode and country. No IP addresses are stored."""
import re
from datetime import timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from . import progress, security
from .accounts import client_ip, current_user, throttle, via_proxy
from .db import enabled, get_db
from .errors import ApiError
from .ua import parse_ua

router = APIRouter(prefix="/api")
DID_RE = re.compile(r"^[A-Za-z0-9_-]{16,40}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
PATH_RE = re.compile(r"^/[A-Za-z0-9_\-./]{0,60}$")
ONLINE_SECONDS = 120


class PingIn(BaseModel):
    d: str = Field(max_length=60)               # device id
    t: str = Field(default="beat", max_length=6)  # "view" | "beat"
    p: str = Field(default="/", max_length=80)   # page path
    s: bool = False                              # running as an installed app (standalone)


@router.post("/t/ping")
def ping(body: PingIn, request: Request):
    if not enabled():
        return {"success": True}
    if not DID_RE.match(body.d) or body.t not in ("view", "beat"):
        raise ApiError(400, "Bad ping")
    ua = parse_ua(request.headers.get("user-agent", ""))
    if ua["bot"]:
        return {"success": True}
    ip = client_ip(request)
    throttle(request, "ping", 40, 60, body.d)              # per device
    if not security.limiter.allow(f"pingip:{ip}", 200, 60):  # per network (many devices behind one NAT)
        raise ApiError(429, "Slow down")
    db, now = get_db(), progress.now()
    day = now.strftime("%Y-%m-%d")
    country = request.headers.get("x-client-country", "").upper()[:2] if via_proxy(request) else ""
    country = country if COUNTRY_RE.match(country) else None
    path = body.p if PATH_RE.match(body.p) else "/"
    user = None
    try:
        user = current_user(request)
    except ApiError:
        pass
    upd = {"$set": {"last_seen": now, "os": ua["os"], "browser": ua["browser"], "kind": ua["kind"], "standalone": bool(body.s), "last_path": path,
                    **({"country": country} if country else {}), **({"user_id": user["_id"]} if user else {})},
           "$addToSet": {"days": day}, "$inc": {"pings": 1, "views": 1 if body.t == "view" else 0}}
    existing = db.devices.find_one({"_id": body.d}, {"_id": 1})
    if not existing:
        if not security.limiter.allow(f"newdev:{ip}", 25, 3600):   # stops one source from inflating the device count
            raise ApiError(429, "Slow down")
        upd["$setOnInsert"] = {"first_seen": now}
        try:
            db.devices.update_one({"_id": body.d}, upd, upsert=True)
        except DuplicateKeyError:
            db.devices.update_one({"_id": body.d}, {k: v for k, v in upd.items() if k != "$setOnInsert"})
        db.daily.update_one({"_id": day}, {"$inc": {"new_devices": 1}}, upsert=True)
    else:
        db.devices.update_one({"_id": body.d}, upd)
    db.daily.update_one({"_id": day}, {"$inc": {"views": 1 if body.t == "view" else 0, "pings": 1}}, upsert=True)
    return {"success": True}


# ---------------------------------------------------------------- aggregation helpers used by the admin console
def _since(minutes=0, days=0):
    return progress.now() - timedelta(minutes=minutes, days=days)


def overview(db) -> dict:
    now = progress.now()
    today = now.strftime("%Y-%m-%d")
    day = lambda n: (now - timedelta(days=n)).strftime("%Y-%m-%d")
    D = db.devices
    active30 = {"last_seen": {"$gte": _since(days=30)}}

    def split(field):
        match = {**active30, field: {"$exists": True, "$ne": None}} if field == "country" else active30   # unknown countries are left out of the chart
        rows = D.aggregate([{"$match": match}, {"$group": {"_id": f"${field}", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}, {"$limit": 12}])
        return [{"name": r["_id"] or "Unknown", "count": r["n"]} for r in rows]

    return {
        "online_now": D.count_documents({"last_seen": {"$gte": _since(minutes=2)}}),
        "online_15m": D.count_documents({"last_seen": {"$gte": _since(minutes=15)}}),
        "online_pwa": D.count_documents({"last_seen": {"$gte": _since(minutes=2)}, "standalone": True}),
        "devices_total": D.count_documents({}),
        "active_today": D.count_documents({"days": today}),
        "active_7d": D.count_documents({"last_seen": {"$gte": _since(days=7)}}),
        "active_30d": D.count_documents(active30),
        "new_today": D.count_documents({"first_seen": {"$gte": now.replace(hour=0, minute=0, second=0, microsecond=0)}}),
        "installed_apps_30d": D.count_documents({**active30, "standalone": True}),
        "platforms": split("os"), "browsers": split("browser"), "kinds": split("kind"), "countries": split("country"),
        "users_total": db.users.count_documents({}),
        "users_new_7d": db.users.count_documents({"created_at": {"$gte": _since(days=7)}}),
        "users_banned": db.users.count_documents({"banned": True}),
        "logged_in_devices_online": D.count_documents({"last_seen": {"$gte": _since(minutes=15)}, "user_id": {"$exists": True}}),
        "comments_total": db.comments.count_documents({}),
        "pictures_total": db.media.count_documents({}),
        "picture_bytes": sum(r["n"] for r in db.media.aggregate([{"$group": {"_id": None, "n": {"$sum": "$size"}}}])),
        "reports_open": db.reports.count_documents({"open": True}),
        "views_today": (db.daily.find_one({"_id": today}) or {}).get("views", 0),
        "yesterday_active": D.count_documents({"days": day(1)}),
    }


def timeseries(db, days: int) -> list[dict]:
    now = progress.now()
    out = []
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        doc = db.daily.find_one({"_id": d}) or {}
        out.append({"date": d, "views": doc.get("views", 0), "new_devices": doc.get("new_devices", 0), "active_devices": db.devices.count_documents({"days": d})})
    return out
