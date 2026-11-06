"""Community features: comments, anime list, continue watching, watch stats, public profiles."""
import re
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from collections import Counter

from . import effects, inventory, progress
from .accounts import LINK_RE, STATUSES, brief, iso, list_counts, oid, public_view, require_user, current_user, throttle
from .db import get_db
from .errors import ApiError

router = APIRouter(prefix="/api")
CW_LIMIT = 30


def _anime_id(value: int) -> int:
    if value <= 0 or value > 10**9:
        raise ApiError(400, "Invalid anime id.")
    return value


def _short(s: str | None, n: int) -> str:
    return (s or "").strip()[:n]


# ================================================================== comments
class CommentIn(BaseModel):
    anime_id: int
    text: str = Field(default="", max_length=2000)
    parent_id: str | None = Field(default=None, max_length=40)
    sticker: str | None = Field(default=None, max_length=40)


class ReactIn(BaseModel):
    key: str | None = Field(default=None, max_length=12)  # one of effects.REACTIONS, or null to remove


def _reactions(c: dict) -> dict:
    rc = c.get("rc")
    if rc is None and c.get("likes"):           # comments written before reactions existed
        rc = {"like": c["likes"]}
    return {k: v for k, v in (rc or {}).items() if v > 0}


def _comment_view(c: dict, users: dict, me_id) -> dict:
    u = users.get(c["user_id"])
    ghost = {"username": "deleted", "name": "deleted user", "avatar": {"bg": 0, "icon": "initial", "pic": None}, "fx": {}, "rank": ""}
    return {
        "id": str(c["_id"]), "anime_id": c["anime_id"], "parent_id": str(c["parent_id"]) if c.get("parent_id") else None,
        "text": c["text"], "sticker": c.get("sticker"), "created_at": iso(c["created_at"]), "user": brief(u) if u else ghost,
        "reactions": _reactions(c), "my_reaction": (c.get("react") or {}).get(str(me_id)) if me_id else None,
        "reply_count": c.get("reply_count", 0), "mine": bool(me_id and c["user_id"] == me_id),
    }


def _users_for(db, comments: list[dict]) -> dict:
    ids = list({c["user_id"] for c in comments})
    return {u["_id"]: u for u in db.users.find({"_id": {"$in": ids}})}


@router.get("/comments")
def list_comments(request: Request, anime_id: int, page: int = Query(1, ge=1), per_page: int = Query(15, ge=1, le=30),
                  sort: str = Query("new", pattern="^(new|top)$")):
    db, me = get_db(), current_user(request)
    q = {"anime_id": _anime_id(anime_id), "parent_id": None}
    order = [("score", -1), ("created_at", -1)] if sort == "top" else [("created_at", -1)]
    total = db.comments.count_documents(q)
    rows = list(db.comments.find(q).sort(order).skip((page - 1) * per_page).limit(per_page))
    users = _users_for(db, rows)
    return {"success": True, "results": {
        "data": [_comment_view(c, users, me["_id"] if me else None) for c in rows],
        "pagination": {"currentPage": page, "totalItems": total, "itemsPerPage": per_page,
                       "totalPages": max(1, -(-total // per_page)), "hasNext": page * per_page < total}}}


@router.get("/comments/{comment_id}/replies")
def list_replies(comment_id: str, request: Request, page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=50)):
    db, me = get_db(), current_user(request)
    q = {"parent_id": oid(comment_id)}
    total = db.comments.count_documents(q)
    rows = list(db.comments.find(q).sort("created_at", 1).skip((page - 1) * per_page).limit(per_page))
    users = _users_for(db, rows)
    return {"success": True, "results": {"data": [_comment_view(c, users, me["_id"] if me else None) for c in rows],
                                         "pagination": {"currentPage": page, "totalItems": total, "hasNext": page * per_page < total}}}


@router.post("/comments")
def post_comment(body: CommentIn, request: Request):
    db, u = get_db(), require_user(request)
    from . import flags
    flags.require(db, "comments_enabled", "Comments are paused right now.")
    throttle(request, "comment", 6, 60, str(u["_id"]))
    text = re.sub(r"\n{3,}", "\n\n", body.text.strip())
    sticker = body.sticker or None
    if sticker:
        pack = sticker.partition(":")[0]
        if not effects.sticker_ok(sticker):
            raise ApiError(400, "Unknown sticker.")
        if pack not in inventory.packs_usable(u):
            raise ApiError(403, "Get this sticker pack in the Void Shop first.")
    if len(text) > 1000 or (not text and not sticker):
        raise ApiError(400, "Write 1-1000 characters or pick a sticker.")
    if LINK_RE.search(text):
        raise ApiError(400, "Links are not allowed in comments.")
    parent = None
    if body.parent_id:
        parent = db.comments.find_one({"_id": oid(body.parent_id)})
        if not parent or parent["anime_id"] != body.anime_id:
            raise ApiError(404, "The comment you're replying to no longer exists.")
        if parent.get("parent_id"):  # keep threads one level deep: reply to the root
            parent = db.comments.find_one({"_id": parent["parent_id"]}) or parent
    doc = {"anime_id": _anime_id(body.anime_id), "user_id": u["_id"], "text": text, "sticker": sticker, "created_at": progress.now(),
           "parent_id": parent["_id"] if parent else None, "score": 0, "react": {}, "rc": {}, "reply_count": 0}
    doc["_id"] = db.comments.insert_one(doc).inserted_id
    if parent:
        db.comments.update_one({"_id": parent["_id"]}, {"$inc": {"reply_count": 1}})
    db.users.update_one({"_id": u["_id"]}, {"$inc": {"stats.comments": 1}})
    gained = progress.award(db, u, "comment")
    return {"success": True, "results": {**_comment_view(doc, {u["_id"]: u}, u["_id"]), "vp_gained": gained}}


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: str, request: Request):
    db, u = get_db(), require_user(request)
    c = db.comments.find_one({"_id": oid(comment_id)})
    if not c:
        raise ApiError(404, "Comment not found.")
    if c["user_id"] != u["_id"]:
        raise ApiError(403, "You can only delete your own comments.")
    removed = 1
    if not c.get("parent_id"):
        removed += db.comments.delete_many({"parent_id": c["_id"]}).deleted_count
    else:
        db.comments.update_one({"_id": c["parent_id"]}, {"$inc": {"reply_count": -1}})
    db.comments.delete_one({"_id": c["_id"]})
    db.users.update_one({"_id": u["_id"]}, {"$inc": {"stats.comments": -1}})
    return {"success": True, "results": {"removed": removed}}


@router.post("/comments/{comment_id}/react")
def react_comment(comment_id: str, body: ReactIn, request: Request):
    db, u = get_db(), require_user(request)
    from . import flags
    flags.require(db, "comments_enabled", "Reactions are paused right now.")
    throttle(request, "react", 90, 60, str(u["_id"]))
    if body.key is not None and body.key not in effects.REACTIONS:
        raise ApiError(400, "Unknown reaction.")
    c = db.comments.find_one({"_id": oid(comment_id)})
    if not c:
        raise ApiError(404, "Comment not found.")
    react = dict(c.get("react") or {})
    if body.key:
        react[str(u["_id"])] = body.key
    else:
        react.pop(str(u["_id"]), None)
    counts = dict(Counter(react.values()))
    db.comments.update_one({"_id": c["_id"]}, {"$set": {"react": react, "rc": counts, "score": len(react)}})
    return {"success": True, "results": {"reactions": counts, "my_reaction": body.key}}


# ================================================================== anime list
class ListIn(BaseModel):
    status: str
    title: str = ""
    poster: str = ""


def _list_view(r: dict) -> dict:
    return {"anime_id": r["anime_id"], "status": r["status"], "title": r.get("title", ""), "poster": r.get("poster", ""),
            "updated_at": iso(r.get("updated_at"))}


@router.get("/list")
def my_list(request: Request, status: str = Query("all")):
    db, u = get_db(), require_user(request)
    q = {"user_id": u["_id"]}
    if status != "all":
        if status not in STATUSES:
            raise ApiError(400, "Unknown status.")
        q["status"] = status
    rows = db.anime_list.find(q).sort("updated_at", -1).limit(500)
    return {"success": True, "results": {"data": [_list_view(r) for r in rows], "counts": list_counts(db, u["_id"])}}


@router.get("/list/{anime_id}")
def list_entry(anime_id: int, request: Request):
    db, u = get_db(), require_user(request)
    r = db.anime_list.find_one({"user_id": u["_id"], "anime_id": _anime_id(anime_id)})
    return {"success": True, "results": {"status": r["status"] if r else None}}


@router.put("/list/{anime_id}")
def set_list(anime_id: int, body: ListIn, request: Request):
    db, u = get_db(), require_user(request)
    throttle(request, "list", 60, 60, str(u["_id"]))
    if body.status not in STATUSES:
        raise ApiError(400, "Unknown status.")
    anime_id = _anime_id(anime_id)
    now = progress.now()
    prev = db.anime_list.find_one_and_update(
        {"user_id": u["_id"], "anime_id": anime_id},
        {"$set": {"status": body.status, "updated_at": now, **({"title": _short(body.title, 160), "poster": _short(body.poster, 400)} if body.title else {})},
         "$setOnInsert": {"added_at": now}},
        upsert=True, return_document=ReturnDocument.BEFORE)
    gained = progress.award(db, u, "list_add") if prev is None else 0
    return {"success": True, "results": {"status": body.status, "vp_gained": gained}}


@router.delete("/list/{anime_id}")
def remove_list(anime_id: int, request: Request):
    db, u = get_db(), require_user(request)
    db.anime_list.delete_one({"user_id": u["_id"], "anime_id": _anime_id(anime_id)})
    return {"success": True}


# ================================================================== continue watching
class ContinueIn(BaseModel):
    title: str = ""
    poster: str = ""
    episode: int = Field(ge=0, le=100000)
    audio: str = "sub"


class MergeIn(BaseModel):
    items: list[dict]


def _cw_view(r: dict) -> dict:
    return {"anime_id": r["anime_id"], "title": r.get("title", ""), "poster": r.get("poster", ""), "episode": r.get("episode", 1),
            "audio": r.get("audio", "sub"), "updated_at": iso(r.get("updated_at"))}


def _cw_trim(db, uid) -> None:
    extra = db.continue_watching.count_documents({"user_id": uid}) - CW_LIMIT
    if extra > 0:
        old = [d["_id"] for d in db.continue_watching.find({"user_id": uid}).sort("updated_at", 1).limit(extra)]
        db.continue_watching.delete_many({"_id": {"$in": old}})


@router.get("/continue")
def get_continue(request: Request):
    db, u = get_db(), require_user(request)
    rows = db.continue_watching.find({"user_id": u["_id"]}).sort("updated_at", -1).limit(CW_LIMIT)
    return {"success": True, "results": [_cw_view(r) for r in rows]}


@router.put("/continue/{anime_id}")
def put_continue(anime_id: int, body: ContinueIn, request: Request):
    db, u = get_db(), require_user(request)
    throttle(request, "cw", 120, 60, str(u["_id"]))
    db.continue_watching.update_one(
        {"user_id": u["_id"], "anime_id": _anime_id(anime_id)},
        {"$set": {"title": _short(body.title, 160), "poster": _short(body.poster, 400), "episode": body.episode,
                  "audio": "dub" if body.audio == "dub" else "sub", "updated_at": progress.now()}}, upsert=True)
    _cw_trim(db, u["_id"])
    return {"success": True}


@router.post("/continue/merge")
def merge_continue(body: MergeIn, request: Request):
    """Guest history (localStorage) -> account, newest wins."""
    db, u = get_db(), require_user(request)
    for it in body.items[:CW_LIMIT]:
        try:
            aid, ep = _anime_id(int(it.get("anime_id"))), max(0, int(it.get("episode", 1)))
            ts = datetime.fromtimestamp(min(int(it.get("updated_at", 0)), 2**40) / 1000, tz=progress.now().tzinfo)
        except (TypeError, ValueError, OverflowError, OSError, ApiError):
            continue
        existing = db.continue_watching.find_one({"user_id": u["_id"], "anime_id": aid})
        if existing and existing["updated_at"] >= ts:
            continue
        db.continue_watching.update_one({"user_id": u["_id"], "anime_id": aid}, {"$set": {
            "title": _short(it.get("title"), 160), "poster": _short(it.get("poster"), 400), "episode": ep,
            "audio": "dub" if it.get("audio") == "dub" else "sub", "updated_at": ts}}, upsert=True)
    _cw_trim(db, u["_id"])
    return get_continue(request)


@router.delete("/continue/{anime_id}")
def delete_continue(anime_id: int, request: Request):
    db, u = get_db(), require_user(request)
    db.continue_watching.delete_one({"user_id": u["_id"], "anime_id": _anime_id(anime_id)})
    return {"success": True}


@router.delete("/continue")
def clear_continue(request: Request):
    db, u = get_db(), require_user(request)
    n = db.continue_watching.delete_many({"user_id": u["_id"]}).deleted_count
    return {"success": True, "results": {"removed": n}}


# ================================================================== watch stats
class WatchIn(BaseModel):
    anime_id: int
    episode: int = Field(ge=1, le=100000)


@router.post("/watch/complete")
def watch_complete(body: WatchIn, request: Request):
    """Call when an episode was actually watched. Counts once per (anime, episode)."""
    db, u = get_db(), require_user(request)
    throttle(request, "watch", 40, 600, str(u["_id"]))
    try:
        db.watched.insert_one({"user_id": u["_id"], "anime_id": _anime_id(body.anime_id), "episode": body.episode, "at": progress.now()})
    except DuplicateKeyError:
        return {"success": True, "results": {"counted": False, "vp_gained": 0}}
    db.users.update_one({"_id": u["_id"]}, {"$inc": {"stats.episodes": 1, "stats.minutes": progress.MINUTES_PER_EPISODE}})
    return {"success": True, "results": {"counted": True, "vp_gained": progress.award(db, u, "episode")}}


# ================================================================== public profiles
def _get_user(db, username: str) -> dict:
    u = db.users.find_one({"username_lower": (username or "").lower()})
    if not u:
        raise ApiError(404, "User not found.")
    return u


@router.get("/users/{username}")
def public_profile(username: str):
    db = get_db()
    u = _get_user(db, username)
    view = public_view(db, u)
    if not view["privacy"].get("show_list", True):
        view["stats"]["list_counts"] = None
    return {"success": True, "results": view}


@router.get("/users/{username}/list")
def public_list(username: str, status: str = Query("all")):
    db = get_db()
    u = _get_user(db, username)
    if not u.get("privacy", {}).get("show_list", True):
        raise ApiError(403, "This user keeps their list private.")
    q = {"user_id": u["_id"], **({"status": status} if status in STATUSES else {})}
    rows = db.anime_list.find(q).sort("updated_at", -1).limit(60)
    return {"success": True, "results": [_list_view(r) for r in rows]}
