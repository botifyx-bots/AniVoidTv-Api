"""Local catalog built from the official API: slug -> {id, title, poster, type, ...}.

Why it exists
  * the site's top-ten / random pages don't expose the numeric id, but they DO expose the slug,
    and the official API returns both -> we translate slug -> official id here;
  * gives search / random a graceful fallback when scraping is blocked.
Stored in data/catalog.json, rebuilt by the weekly crawl and topped up from the newest pages.
"""
import asyncio
import random
import re
import time
from typing import Any

from . import store, upstream

FILE = "catalog.json"
RECENT_PAGES = 3
RECENT_COOLDOWN = 600  # seconds between "unknown slug" top-ups
_last_recent = 0.0
_lock = asyncio.Lock()


def entry_from_row(row: dict) -> dict:
    types = (row.get("terms_by_type") or {}).get("type") or []
    genres = (row.get("terms_by_type") or {}).get("genre") or []
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "alt": " | ".join(x for x in (row.get("alternative"), row.get("titles"), row.get("native")) if x),
        "poster": row.get("poster") or "",
        "type": types[0] if types else "",
        "genres": genres,
    }


def normalize_slug(s: str) -> str:
    """'solo-leveling-ilh08/ep-1' | '/watch/x?y' -> 'solo-leveling-ilh08'"""
    s = (s or "").split("?")[0].split("#")[0].strip("/")
    if "/watch/" in s:
        s = s.split("/watch/")[-1]
    return s.split("/")[0]


def _map() -> dict[str, dict]:
    data = store.read_json(FILE)
    return (data or {}).get("map", {})


def lookup(slug: str) -> dict | None:
    return _map().get(normalize_slug(slug))


def size() -> int:
    return len(_map())


def save_all(rows: list[dict]) -> None:
    store.write_json(FILE, {"updated_at": _now(), "total": len(rows),
                            "map": {r["slug"]: entry_from_row(r) for r in rows if r.get("slug") and r.get("id") is not None}})


def merge(rows: list[dict]) -> None:
    data = store.read_json(FILE) or {"map": {}}
    m = dict(data.get("map", {}))
    for r in rows:
        if r.get("slug") and r.get("id") is not None:
            m[r["slug"]] = entry_from_row(r)
    store.write_json(FILE, {"updated_at": _now(), "total": len(m), "map": m})


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def resolve_id(slug: str, fallback: Any = None) -> int | None:
    """Official id for a slug; if the slug is unknown use the (scraped) fallback value."""
    e = lookup(slug)
    if e:
        return e["id"]
    try:
        return int(fallback) if fallback not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        return None


async def refresh_recent(force: bool = False) -> None:
    """Pull the newest pages from the official API (rate-limited) to learn brand-new slugs."""
    global _last_recent
    async with _lock:
        if not force and time.monotonic() - _last_recent < RECENT_COOLDOWN:
            return
        _last_recent = time.monotonic()
        rows: list[dict] = []
        try:
            for p in range(1, RECENT_PAGES + 1):
                rows += (await upstream.recent_anime(p, 100)).get("data", [])
        except Exception:  # noqa: BLE001 - best effort only
            pass
        if rows:
            merge(rows)


async def resolve_many(slugs: list[str]) -> dict[str, int | None]:
    """Resolve ids for slugs that have no scraped id (top-ten). Tops up the catalog on a miss."""
    if any(lookup(s) is None for s in slugs):
        await refresh_recent()
    return {s: (lookup(s) or {}).get("id") for s in slugs}


def seed_if_missing() -> bool:
    """No catalog.json (only completed/upcoming were uploaded)? Build it from those two files.
    Currently-airing shows are then learned on demand via refresh_recent()."""
    if store.path_of(FILE).exists():
        return False
    rows: list[dict] = []
    for name in ("completed.json", "upcoming.json"):
        rows += (store.read_json(name) or {}).get("data", [])
    if not rows:
        return False
    save_all(rows)
    return True


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


_title_idx: tuple[Any, dict] | None = None


def _title_index() -> dict[str, dict]:
    global _title_idx
    data = store.read_json(FILE) or {}
    if _title_idx is None or _title_idx[0] is not data:
        idx: dict[str, dict] = {}
        entries = list(data.get("map", {}).values())
        for e in entries:                       # main titles win over alternative names
            idx.setdefault(_norm(e["title"]), e)
        for e in entries:
            for n in (e.get("alt") or "").split(" | "):
                idx.setdefault(_norm(n), e)
        idx.pop("", None)
        _title_idx = (data, idx)
    return _title_idx[1]


def find_by_title(*names: str) -> dict | None:
    """Match a title / Japanese title (as used by the schedule page) to a catalog entry."""
    idx = _title_index()
    for n in names:
        hit = idx.get(_norm(n))
        if hit:
            return hit
    return None


# ---------- local fallbacks ----------
def random_entry() -> dict | None:
    m = _map()
    return random.choice(list(m.values())) if m else None


def search(keyword: str) -> list[dict]:
    words = [w for w in re.split(r"\s+", keyword.lower().strip()) if w]
    if not words:
        return []
    out = []
    for e in _map().values():
        hay = f"{e['title']} {e['alt']}".lower()
        if all(w in hay for w in words):
            out.append(e)
    out.sort(key=lambda e: (not e["title"].lower().startswith(words[0]), len(e["title"])))
    return out
