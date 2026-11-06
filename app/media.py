"""Profile pictures and banners: raw upload -> validated, re-encoded to WebP (metadata stripped) -> stored in MongoDB."""
import io
from datetime import datetime

from bson import Binary, ObjectId
from fastapi import APIRouter, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from PIL import Image, ImageOps

from . import progress
from .accounts import oid, require_user, throttle
from .config import settings
from .db import get_db
from .errors import ApiError

router = APIRouter(prefix="/api")
Image.MAX_IMAGE_PIXELS = 36_000_000          # decompression-bomb guard
SIZES = {"avatar": (384, 384), "banner": (1500, 500)}
LIMITS = {"avatar": lambda: settings.max_avatars, "banner": lambda: settings.max_banners}


def process(raw: bytes, kind: str) -> bytes:
    try:
        img = Image.open(io.BytesIO(raw))
        if img.format not in ("JPEG", "PNG", "WEBP", "GIF"):
            raise ApiError(415, "Use a JPG, PNG, WebP or GIF image.")
        img.load()                                     # fully decode now (rejects truncated / hostile files)
    except ApiError:
        raise
    except Exception:  # noqa: BLE001 (PIL raises many types)
        raise ApiError(400, "That file isn't a valid image.")
    if min(img.size) < 64:
        raise ApiError(400, "Image is too small (min 64 px).")
    img = ImageOps.exif_transpose(img)
    if getattr(img, "is_animated", False):
        img.seek(0)                                    # animated GIF -> first frame
    alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
    img = img.convert("RGBA" if alpha else "RGB")
    img = ImageOps.fit(img, SIZES[kind], Image.LANCZOS, centering=(0.5, 0.5))
    out = io.BytesIO()
    img.save(out, "WEBP", quality=82, method=4)        # fresh file: no EXIF / ICC / comments survive
    return out.getvalue()


async def _read_limited(request: Request, limit: int) -> bytes:
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > limit:
            raise ApiError(413, f"Image is too large (max {limit // 1_000_000 or 1} MB).")
    return bytes(buf)


def _store(request: Request, kind: str, raw: bytes) -> dict:
    db, u = get_db(), require_user(request)
    from . import flags
    flags.require(db, "uploads_enabled", "Uploads are paused right now.")
    throttle(request, "upload", 15, 3600, str(u["_id"]))
    if db.media.count_documents({"user_id": u["_id"], "kind": kind}) >= LIMITS[kind]():
        raise ApiError(400, f"You've reached the limit of {LIMITS[kind]()} {kind} images. Delete one first.")
    used = sum(d["n"] for d in db.media.aggregate([{"$match": {"user_id": u["_id"]}}, {"$group": {"_id": None, "n": {"$sum": "$size"}}}]))
    data = process(raw, kind)
    if used + len(data) > settings.user_media_cap:
        raise ApiError(400, "Your picture storage is full. Delete some pictures first.")
    mid = db.media.insert_one({"user_id": u["_id"], "kind": kind, "data": Binary(data), "size": len(data), "created": progress.now()}).inserted_id
    field = "avatar_main" if kind == "avatar" else "banner_main"
    made_main = not u.get(field)
    if made_main:
        db.users.update_one({"_id": u["_id"]}, {"$set": {field: mid}})
    return {"id": str(mid), "kind": kind, "main": made_main, "bytes": len(data)}


@router.post("/me/pictures")
async def upload_picture(request: Request, kind: str = Query("avatar", pattern="^(avatar|banner)$")):
    if not request.headers.get("content-type", "").startswith(("application/octet-stream", "image/")):
        raise ApiError(415, "Send the image as raw bytes (application/octet-stream).")
    raw = await _read_limited(request, settings.max_upload_bytes)
    if not raw:
        raise ApiError(400, "Empty upload.")
    return {"success": True, "results": await run_in_threadpool(_store, request, kind, raw)}


@router.get("/me/pictures")
def my_pictures(request: Request):
    db, u = get_db(), require_user(request)
    out = {"avatar": [], "banner": []}
    for m in db.media.find({"user_id": u["_id"]}, {"data": 0}).sort("created", -1):
        main = u.get("avatar_main" if m["kind"] == "avatar" else "banner_main")
        out[m["kind"]].append({"id": str(m["_id"]), "main": main == m["_id"], "created": m["created"].isoformat()})
    return {"success": True, "results": {"avatars": out["avatar"], "banners": out["banner"],
                                         "limits": {"avatar": settings.max_avatars, "banner": settings.max_banners}}}


@router.post("/me/pictures/{media_id}/main")
def set_main(media_id: str, request: Request):
    db, u = get_db(), require_user(request)
    m = db.media.find_one({"_id": oid(media_id), "user_id": u["_id"]}, {"data": 0})
    if not m:
        raise ApiError(404, "Picture not found.")
    db.users.update_one({"_id": u["_id"]}, {"$set": {"avatar_main" if m["kind"] == "avatar" else "banner_main": m["_id"]}})
    return {"success": True}


@router.delete("/me/pictures/{media_id}")
def delete_picture(media_id: str, request: Request):
    db, u = get_db(), require_user(request)
    m = db.media.find_one({"_id": oid(media_id), "user_id": u["_id"]}, {"data": 0})
    if not m:
        raise ApiError(404, "Picture not found.")
    db.media.delete_one({"_id": m["_id"]})
    drop_main(db, u, m)
    return {"success": True}


def drop_main(db, u: dict, m: dict) -> None:
    """If the deleted picture was the main one, fall back to the newest remaining picture (or none)."""
    field = "avatar_main" if m["kind"] == "avatar" else "banner_main"
    owner = db.users.find_one({"_id": m["user_id"]})
    if owner and owner.get(field) == m["_id"]:
        nxt = db.media.find_one({"user_id": m["user_id"], "kind": m["kind"]}, {"data": 0}, sort=[("created", -1)])
        db.users.update_one({"_id": m["user_id"]}, {"$set": {field: nxt["_id"]}} if nxt else {"$unset": {field: ""}})


@router.get("/media/{media_id}")
def get_media(media_id: str):
    m = get_db().media.find_one({"_id": oid(media_id)})
    if not m:
        raise ApiError(404, "Not found")
    return Response(bytes(m["data"]), media_type="image/webp", headers={
        "Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox", "Content-Disposition": "inline"})
