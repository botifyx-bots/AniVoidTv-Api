"""HTML extractors for anikototv.to — ported from AniKotoAPI (src/extractors/*.js) with the
output reshaped for our API:

  search    -> {id, poster, title}                       (animeId renamed to id)
  random    -> {id, title, poster, type}
  top-ten   -> {id, title, rank, poster}                  (name renamed to title, id added)
  schedule  -> {slug, id, title, japaneseTitle, poster, time, episode_no}  (id/poster matched by title)
"""
import json
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from . import catalog, scraper


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _text(el, sel: str) -> str:
    n = el.select_one(sel)
    return n.get_text(strip=True) if n else ""


def _attr(el, sel: str, name: str) -> str:
    n = el.select_one(sel)
    return (n.get(name) or "") if n else ""


def _int(s: str) -> int:
    m = re.search(r"\d+", s or "")
    return int(m.group()) if m else 0


def _slug(href: str | None) -> str:
    return href.split("/watch/")[-1] if href else ""


def _count_pages(soup) -> int:
    nums = [int(a.get_text(strip=True)) for a in soup.select(".pagination li a") if a.get_text(strip=True).isdigit()]
    return max(nums) if nums else 1


def pagination(total_pages: int, page: int, count: int, per_page: int = 30) -> dict:
    """Same shape as the AniKotoAPI addPaginationMeta helper."""
    return {
        "currentPage": page,
        "totalPages": total_pages,
        "totalItems": count + (total_pages - 1) * per_page,
        "itemsPerPage": per_page,
        "hasNext": page < total_pages,
        "hasPrev": page > 1,
    }


# ------------------------------------------------------------------ search
async def search(keyword: str, page: int = 1) -> dict:
    path = f"/filter?keyword={quote(keyword, safe='')}" + (f"&page={page}" if page > 1 else "")
    soup = _soup((await scraper.fetch(path)).text)
    total_pages = _count_pages(soup)

    data = []
    for el in soup.select("#list-items > .item"):
        a = el.select_one("a")
        slug = _slug(a.get("href") if a else None)
        if not slug:
            continue
        scraped_id = _attr(el, ".ani.poster.tip", "data-tip")
        data.append({
            "id": catalog.resolve_id(slug, scraped_id),
            "poster": _attr(el, ".ani.poster.tip > a > img", "src"),
            "title": _text(el, ".info .b1 a.name.d-title"),
        })
    return {"totalPages": total_pages, "data": data, "pagination": pagination(total_pages, page, len(data))}


def search_local(keyword: str, page: int = 1, per_page: int = 30) -> dict:
    """Fallback when the site can't be scraped: search the official-API catalog instead."""
    hits = catalog.search(keyword)
    total_pages = max(1, -(-len(hits) // per_page))
    chunk = hits[(page - 1) * per_page: page * per_page]
    data = [{"id": e["id"], "poster": e["poster"], "title": e["title"]} for e in chunk]
    return {
        "totalPages": total_pages,
        "data": data,
        "pagination": {"currentPage": page, "totalPages": total_pages, "totalItems": len(hits),
                       "itemsPerPage": per_page, "hasNext": page < total_pages, "hasPrev": page > 1},
    }


# ------------------------------------------------------------------ random
async def random_anime() -> dict:
    page = await scraper.fetch("/random")
    soup = _soup(page.text)

    slug = _slug(page.url) if "/watch/" in page.url else ""
    if not slug:  # the site may serve the page directly at /random -> read canonical URL instead
        for sel, attr in (("link[rel=canonical]", "href"), ("meta[property='og:url']", "content")):
            slug = _slug(_attr(soup, sel, attr)) if "/watch/" in _attr(soup, sel, attr) else ""
            if slug:
                break

    scraped_id = _attr(soup, "#watch-main", "data-id")
    return {
        "id": catalog.resolve_id(slug, scraped_id),
        "title": _text(soup, "h1[itemprop='name'].title.d-title"),
        "poster": _attr(soup, "img[itemprop='image']", "src"),
        "type": _text(soup, ".bmeta .meta:first-child > div:nth-child(1) span"),
    }


def random_local() -> dict | None:
    e = catalog.random_entry()
    return {"id": e["id"], "title": e["title"], "poster": e["poster"], "type": e["type"]} if e else None


# ------------------------------------------------------------------ top ten
async def top_ten() -> dict:
    soup = _soup((await scraper.fetch("/home")).text)
    raw: dict[str, list[dict]] = {}
    for key, tab in (("today", "day"), ("week", "week"), ("month", "month")):
        items = []
        for i, el in enumerate(soup.select(f"#top-anime .tab-content[data-name='{tab}'] a.item")):
            slug = _slug(el.get("href"))
            if slug:
                items.append({"slug": slug, "rank": i + 1, "title": _text(el, ".name"), "poster": _attr(el, ".poster img", "src")})
        raw[key] = items

    ids = await catalog.resolve_many(sorted({it["slug"] for v in raw.values() for it in v}))
    return {
        key: [{"id": ids.get(it["slug"]), "title": it["title"], "rank": it["rank"], "poster": it["poster"]} for it in items]
        for key, items in raw.items()
    }


# ------------------------------------------------------------------ schedule
async def schedule(date: str) -> list[dict]:
    page = await scraper.fetch(f"/ajax/schedule?date={date}", headers={"X-Requested-With": "XMLHttpRequest"})
    raw = page.text
    try:
        html = json.loads(raw).get("result", "")
    except (ValueError, AttributeError):
        pre = _soup(raw).select_one("pre")  # FlareSolverr wraps JSON in <pre>
        try:
            html = json.loads(pre.get_text()).get("result", "") if pre else ""
        except ValueError:
            html = ""
    soup = _soup(html)

    raw = []
    for el in soup.select(".item"):
        title = _text(el, ".title")
        if not title:
            continue
        raw.append({
            "slug": re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", title.lower())),
            "title": title,
            "japaneseTitle": _attr(el, ".title", "data-jp"),
            "time": _text(el, ".time"),
            "episode_no": _int(re.sub(r"\D", "", _text(el, ".ep span"))),
        })

    def match(it):
        return catalog.find_by_title(it["title"], it["japaneseTitle"])

    if any(match(it) is None for it in raw):
        await catalog.refresh_recent()  # new show not in the catalog yet -> top up from the official API

    out = []
    for it in raw:
        e = match(it)
        out.append({
            "slug": it["slug"],
            "id": e["id"] if e else None,
            "title": it["title"],
            "japaneseTitle": it["japaneseTitle"],
            "poster": e["poster"] if e else "",
            "time": it["time"],
            "episode_no": it["episode_no"],
        })
    return out
