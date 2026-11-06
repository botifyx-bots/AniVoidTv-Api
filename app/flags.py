"""Feature flags + site announcement, editable live from the admin console (no redeploy).
To add a new switch: add a line to FLAGS, then call flags.require(db, "your_flag") in the endpoint
and read AVTV.config.flags.your_flag in the frontend."""
import time

from .errors import ApiError

FLAGS: dict[str, tuple] = {   # name -> (default, description, public?)
    "registration_enabled": (True, "Allow new sign-ups", True),
    "comments_enabled": (True, "Allow comments, replies and reactions", True),
    "uploads_enabled": (True, "Allow picture and banner uploads", True),
    "shop_enabled": (True, "Allow Void Shop purchases and equipping", True),
    "maintenance_mode": (False, "Read-only mode: every write is blocked (admins can still sign in)", True),
    "maintenance_message": ("We're making things better. Back in a few minutes!", "Shown to visitors in maintenance mode", True),
    "announcement_enabled": (False, "Show the announcement bar on every page", True),
    "announcement_text": ("", "Announcement text (plain text, max 200 chars)", True),
    "announcement_level": ("info", "info | warning | success", True),
}
_cache: tuple[float, dict] | None = None
TTL = 8.0


def _defaults() -> dict:
    return {k: v[0] for k, v in FLAGS.items()}


def all_flags(db, fresh: bool = False) -> dict:
    global _cache
    if not fresh and _cache and time.monotonic() - _cache[0] < TTL:
        return _cache[1]
    out = _defaults()
    doc = db.settings.find_one({"_id": "flags"}) or {}
    for k in FLAGS:
        if k in doc:
            out[k] = doc[k]
    _cache = (time.monotonic(), out)
    return out


def invalidate() -> None:
    global _cache
    _cache = None


def public(db) -> dict:
    f = all_flags(db) if db is not None else _defaults()
    return {
        "registration_enabled": f["registration_enabled"], "comments_enabled": f["comments_enabled"], "uploads_enabled": f["uploads_enabled"], "shop_enabled": f["shop_enabled"],
        "maintenance": {"on": f["maintenance_mode"], "message": f["maintenance_message"]},
        "announcement": {"on": bool(f["announcement_enabled"] and f["announcement_text"]), "text": f["announcement_text"], "level": f["announcement_level"]},
    }


def set_flags(db, changes: dict) -> dict:
    clean = {}
    for k, v in changes.items():
        if k not in FLAGS:
            raise ApiError(400, f"Unknown flag: {k}")
        default = FLAGS[k][0]
        if isinstance(default, bool):
            if not isinstance(v, bool):
                raise ApiError(400, f"{k} must be true or false")
        else:
            if not isinstance(v, str):
                raise ApiError(400, f"{k} must be text")
            v = v.strip()[:200]
            if k == "announcement_level" and v not in ("info", "warning", "success"):
                raise ApiError(400, "announcement_level must be info, warning or success")
        clean[k] = v
    if clean:
        db.settings.update_one({"_id": "flags"}, {"$set": clean}, upsert=True)
        invalidate()
    return all_flags(db, fresh=True)


def require(db, name: str, message: str | None = None) -> None:
    if not all_flags(db).get(name, True):
        raise ApiError(403, message or "This feature is temporarily turned off.", feature_disabled=name)


def maintenance(db) -> str | None:
    f = all_flags(db)
    return f["maintenance_message"] if f["maintenance_mode"] else None
