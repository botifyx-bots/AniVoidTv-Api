"""MongoDB access (sync pymongo; endpoints are plain `def` so FastAPI runs them in its thread pool)."""
import logging

from .config import settings
from .errors import ApiError

log = logging.getLogger("db")
_db = None


def set_db(db) -> None:
    """Tests inject a mongomock database here."""
    global _db
    _db = db
    init_indexes()


def enabled() -> bool:
    return _db is not None or bool(settings.mongodb_uri)


def get_db():
    global _db
    if _db is None:
        if not settings.mongodb_uri:
            raise ApiError(503, "Accounts are not enabled on this server (MONGODB_URI is not set).")
        from pymongo import MongoClient
        _db = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=8000, tz_aware=True)[settings.mongodb_db]
        init_indexes()
    return _db


def _ix(coll, keys, **kw):
    try:
        coll.create_index(keys, **kw)
    except Exception as e:  # noqa: BLE001
        log.warning("index %s %s skipped: %s", coll.name, keys, e)


def init_indexes() -> None:
    d = _db
    _ix(d.users, "username_lower", unique=True)
    _ix(d.users, "email_lower", unique=True, partialFilterExpression={"email_lower": {"$type": "string"}})
    _ix(d.users, "google_sub", unique=True, partialFilterExpression={"google_sub": {"$type": "string"}})
    _ix(d.captcha_used, "at", expireAfterSeconds=900)
    _ix(d.comments, [("anime_id", 1), ("parent_id", 1), ("created_at", -1)])
    _ix(d.comments, [("anime_id", 1), ("parent_id", 1), ("score", -1)])
    _ix(d.anime_list, [("user_id", 1), ("anime_id", 1)], unique=True)
    _ix(d.continue_watching, [("user_id", 1), ("anime_id", 1)], unique=True)
    _ix(d.watched, [("user_id", 1), ("anime_id", 1), ("episode", 1)], unique=True)
    _ix(d.vp_log, [("user_id", 1), ("at", -1)])
    _ix(d.sessions, [("user_id", 1), ("created", -1)])
    _ix(d.sessions, "expires", expireAfterSeconds=0)
    _ix(d.login_fail, "expires", expireAfterSeconds=0)
    _ix(d.media, [("user_id", 1), ("kind", 1), ("created", -1)])
    _ix(d.reports, [("created", -1)])
    _ix(d.devices, "days")
    _ix(d.devices, [("last_seen", -1)])
    _ix(d.devices, "last_seen", expireAfterSeconds=400 * 86400)
    _ix(d.devices, "first_seen")
    _ix(d.admin_sessions, "expires", expireAfterSeconds=0)
    _ix(d.admin_fail, "expires", expireAfterSeconds=0)
    _ix(d.audit, [("at", -1)])
    _ix(d.audit, "at", expireAfterSeconds=400 * 86400)
