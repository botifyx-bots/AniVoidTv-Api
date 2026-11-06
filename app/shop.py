"""Void Shop: buy and equip cosmetics with Void Points."""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from . import effects, inventory, progress
from .accounts import require_user, throttle
from .db import get_db
from .errors import ApiError

router = APIRouter(prefix="/api")


class BuyIn(BaseModel):
    item: str = Field(max_length=60)


class EquipIn(BaseModel):
    slot: str = Field(max_length=20)
    item: str | None = Field(default=None, max_length=60)


class ColorIn(BaseModel):
    color: int | None = None


@router.get("/shop")
def shop(request: Request):
    u = require_user(request)
    rank = progress.rank_index(u.get("vp", 0))
    usable = inventory.usable_ids(u)
    items = []
    for it in effects.ITEMS.values():
        items.append({**it, "owned": it["id"] in usable, "rank_ok": rank >= it["min_rank"], "free": it["price"] == 0,
                      "unlock_rank": effects.RANK_NAMES[it["min_rank"]]})
    return {"success": True, "results": {
        "vp": u.get("vp", 0), "rank": rank, "rank_names": effects.RANK_NAMES, "items": items, "equipped": inventory.equipped_of(u),
        "stickers": effects.STICKERS, "reactions": effects.REACTIONS, "title_colors": effects.TITLE_COLORS}}


@router.post("/shop/buy")
def buy(body: BuyIn, request: Request):
    db, u = get_db(), require_user(request)
    from . import flags
    flags.require(db, "shop_enabled", "The shop is closed for a moment.")
    throttle(request, "shop", 30, 600, str(u["_id"]))
    it = effects.ITEMS.get(body.item)
    if not it:
        raise ApiError(404, "Unknown item.")
    rank = progress.rank_index(u.get("vp", 0))
    if rank < it["min_rank"]:
        raise ApiError(403, f"Unlocks at rank {effects.RANK_NAMES[it['min_rank']]}.")
    if it["id"] in inventory.usable_ids(u):
        raise ApiError(409, "You already have this item.")
    res = db.users.find_one_and_update({"_id": u["_id"], "vp": {"$gte": it["price"]}, "owned": {"$nin": [it["id"]]}},
                                       {"$inc": {"vp": -it["price"]}, "$push": {"owned": it["id"]}}, return_document=True)
    if not res:
        raise ApiError(402, f"Not enough Void Points ({it['price']} VP needed).")
    db.vp_log.insert_one({"user_id": u["_id"], "delta": -it["price"], "reason": "shop", "item": it["id"], "at": progress.now()})
    return {"success": True, "results": {"vp": res["vp"], "item": it["id"]}}


@router.post("/shop/equip")
def equip(body: EquipIn, request: Request):
    db, u = get_db(), require_user(request)
    if body.slot not in effects.KIND_SLOTS:
        raise ApiError(400, "Unknown slot.")
    if body.item is None:
        db.users.update_one({"_id": u["_id"]}, {"$unset": {f"equipped.{body.slot}": ""}})
    else:
        it = effects.ITEMS.get(body.item)
        if not it or it["kind"] != body.slot:
            raise ApiError(400, "That item doesn't fit this slot.")
        if not inventory.can_use(u, body.item):
            raise ApiError(403, "You don't own this item yet.")
        db.users.update_one({"_id": u["_id"]}, {"$set": {f"equipped.{body.slot}": body.item}})
    u = db.users.find_one({"_id": u["_id"]})
    return {"success": True, "results": {"equipped": inventory.equipped_of(u)}}


@router.post("/shop/title-color")
def title_color(body: ColorIn, request: Request):
    db, u = get_db(), require_user(request)
    if body.color is not None and not 0 <= body.color < effects.TITLE_COLORS:
        raise ApiError(400, "Invalid colour.")
    db.users.update_one({"_id": u["_id"]}, {"$set": {"equipped.title_color": body.color}})
    return {"success": True}
