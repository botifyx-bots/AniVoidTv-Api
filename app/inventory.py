"""Who may use which cosmetic: bought items + free items unlocked by rank. Used by accounts, shop and comments."""
from . import effects, progress

SLOTS = effects.KIND_SLOTS


def usable_ids(u: dict) -> set[str]:
    rank = progress.rank_index(u.get("vp", 0))
    ids = set(u.get("owned", []))
    ids.update(i["id"] for i in effects.ITEMS.values() if i["price"] == 0 and i["min_rank"] <= rank)
    return ids


def can_use(u: dict, item_id: str) -> bool:
    return item_id in effects.ITEMS and item_id in usable_ids(u)


def equipped_of(u: dict) -> dict:
    """Equipped cosmetics, with anything no longer usable dropped (and old frame names migrated)."""
    eq = dict(u.get("equipped") or {})
    legacy = (u.get("avatar") or {}).get("frame")
    if "frame" not in eq and legacy in effects.LEGACY_FRAMES:
        eq["frame"] = effects.LEGACY_FRAMES[legacy]
    ok = usable_ids(u)
    out = {}
    for slot in SLOTS:
        iid = eq.get(slot)
        if iid and iid in ok and effects.ITEMS[iid]["kind"] == slot:
            out[slot] = iid
    out["title_color"] = eq.get("title_color") if isinstance(eq.get("title_color"), int) and 0 <= eq["title_color"] < effects.TITLE_COLORS else None
    return out


def title_view(eq: dict) -> dict | None:
    tid = eq.get("title")
    if not tid:
        return None
    it = effects.ITEMS[tid]
    return {"id": tid, "name": it["name"], "rarity": it["rarity"], "color": eq.get("title_color")}


def fx_public(u: dict) -> dict:
    """What other people need to render this user's name/avatar/card."""
    eq = equipped_of(u)
    return {"frame": eq.get("frame"), "name": eq.get("name"), "card": eq.get("card"), "banner": eq.get("banner"), "title": title_view(eq)}


def packs_usable(u: dict) -> set[str]:
    return {i[5:] for i in usable_ids(u) if i.startswith("pack.")}
