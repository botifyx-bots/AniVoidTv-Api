"""Offline tests: the network layer is mocked, parsing/crawl/endpoint logic is real."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import catalog, crawler, scraper, store, upstream
from app.main import app


def row(i, status, title="Anime", slug=None, **kw):
    return {"id": i, "title": f"{title} {i}", "alternative": f"Alt {i}", "titles": "", "native": "",
            "slug": slug or f"anime-{i}-abc{i}", "poster": f"https://cdn/{i}.jpg", "status": status,
            "terms_by_type": {"genre": ["Action"], "type": ["TV"]}, **kw}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_crawl_splits_by_status_and_swaps_atomically(monkeypatch):
    pages = {
        1: [row(1, "Finished Airing"), row(2, "Not yet aired"), row(3, "Currently Airing")],
        2: [row(4, "Finished Airing"), row(2, "Not yet aired")],  # id 2 repeated (page shift) -> de-duped
        3: [row(5, "Not yet aired")],
    }

    async def fake_recent(page=1, per_page=100):
        return {"ok": True, "data": pages[page], "pagination": {"page": page, "total": 5, "total_pages": 3}}

    monkeypatch.setattr(upstream, "recent_anime", fake_recent)
    assert asyncio.run(crawler.run_crawl("test")) is True
    done = store.read_json("completed.json")
    up = store.read_json("upcoming.json")
    assert [r["id"] for r in done["data"]] == [1, 4]
    assert sorted(r["id"] for r in up["data"]) == [2, 5]
    assert catalog.lookup("anime-3-abc3")["id"] == 3
    assert crawler.state["last_success"]


def test_failed_crawl_keeps_old_files(monkeypatch):
    before = store.read_json("completed.json")

    async def boom(page=1, per_page=100):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(upstream, "recent_anime", boom)
    assert asyncio.run(crawler.run_crawl("test")) is False
    assert store.read_json("completed.json") == before
    assert "upstream down" in crawler.state["last_error"]


def test_completed_upcoming_endpoints(client):
    r = client.get("/api/completed?page=1&per_page=1").json()
    assert r["success"] and r["results"]["pagination"]["totalItems"] == 2
    assert r["results"]["pagination"]["hasNext"] is True
    assert client.get("/api/upcoming").json()["results"]["data"][0]["status"] == "Not yet aired"
    assert client.get("/api/completed?per_page=500").status_code == 422


SEARCH_HTML = """
<div class="pagination"><ul><li><a>1</a></li><li><a>3</a></li></ul></div>
<div id="list-items">
 <div class="item">
  <div class="ani poster tip" data-tip="999"><a href="/watch/anime-1-abc1/ep-1"><img src="https://cdn/1.jpg"></a></div>
  <div class="info"><div class="b1"><a class="name d-title" href="/watch/anime-1-abc1" data-jp="Jp">Anime 1</a></div>
  <div class="meta"><div class="m-item"><label>x</label></div><div class="m-item"><label>TV</label></div></div></div>
 </div>
 <div class="item">
  <div class="ani poster tip" data-tip="6224"><a href="/watch/unknown-slug-zzz/ep-1"><img src="https://cdn/u.jpg"></a></div>
  <div class="info"><div class="b1"><a class="name d-title" href="/watch/unknown-slug-zzz">Unknown</a></div></div>
 </div>
</div>"""

TOP_HTML = """
<div id="top-anime">
 <div class="tab-content" data-name="day"><a class="item" href="/watch/anime-1-abc1"><div class="poster"><img src="https://cdn/1.jpg"></div><div class="name">Anime 1</div></a></div>
 <div class="tab-content" data-name="week"><a class="item" href="/watch/anime-4-abc4"><div class="poster"><img src="https://cdn/4.jpg"></div><div class="name">Anime 4</div></a></div>
 <div class="tab-content" data-name="month"></div>
</div>"""

RANDOM_HTML = """
<link rel="canonical" href="https://anikototv.to/watch/anime-4-abc4">
<div id="watch-main" data-id="12345"></div>
<h1 itemprop="name" class="title d-title" data-jp="jp">Anime 4</h1><img itemprop="image" src="https://cdn/4.jpg">
<div class="bmeta"><div class="meta"><div><span>Movie</span></div></div></div>"""

SCHEDULE_JSON = json.dumps({"status": 200, "result":
    '<div class="item"><span class="time">09:00</span><span class="title" data-jp="Alt 4">Different Name</span><div class="ep"><span>EP 2</span></div></div>'
    '<div class="item"><span class="time">10:00</span><span class="title" data-jp="Jp">Some Show!</span><div class="ep"><span>EP 6</span></div></div>'})


def fake_fetch(pages):
    async def _f(path, headers=None, attempts=2):
        for prefix, text in pages.items():
            if path.startswith(prefix):
                return scraper.Page(text, "https://anikototv.to/random" if prefix == "/random" else "https://x" + path, "m")
        raise scraper.ScrapeError("blocked")
    return _f


def test_search_renames_and_trims(client, monkeypatch):
    monkeypatch.setattr(scraper, "fetch", fake_fetch({"/filter": SEARCH_HTML}))
    r = client.get("/api/search?keyword=anime").json()["results"]
    assert r["totalPages"] == 3
    # known slug -> official id (1) wins over scraped data-tip (999); unknown slug -> scraped id
    assert r["data"] == [{"id": 1, "poster": "https://cdn/1.jpg", "title": "Anime 1"},
                         {"id": 6224, "poster": "https://cdn/u.jpg", "title": "Unknown"}]
    assert "creator" not in client.get("/api/search?keyword=anime").text
    assert client.get("/api/search").status_code == 400


def test_search_falls_back_to_catalog(client, monkeypatch):
    monkeypatch.setattr(scraper, "fetch", fake_fetch({}))
    resp = client.get("/api/search?keyword=anime 4")
    assert resp.headers["x-data-source"] == "local-catalog"
    assert resp.json()["results"]["data"][0]["id"] == 4


def test_top_ten_adds_id_and_renames(client, monkeypatch):
    monkeypatch.setattr(scraper, "fetch", fake_fetch({"/home": TOP_HTML}))
    r = client.get("/api/top-ten").json()["results"]
    assert r["today"] == [{"id": 1, "title": "Anime 1", "rank": 1, "poster": "https://cdn/1.jpg"}]
    assert r["week"][0]["id"] == 4 and r["month"] == []


def test_random_uses_canonical_slug(client, monkeypatch):
    monkeypatch.setattr(scraper, "fetch", fake_fetch({"/random": RANDOM_HTML}))
    r = client.get("/api/random").json()["results"]
    assert r == {"id": 4, "title": "Anime 4", "poster": "https://cdn/4.jpg", "type": "Movie"}


def test_schedule(client, monkeypatch):
    monkeypatch.setattr(scraper, "fetch", fake_fetch({"/ajax/schedule": SCHEDULE_JSON}))
    async def no_refresh(force=False):
        return None
    monkeypatch.setattr(catalog, "refresh_recent", no_refresh)
    r = client.get("/api/schedule?date=2026-10-24").json()["results"]
    assert r == [
        # matched through the Japanese/alternative title -> id + poster from the catalog
        {"slug": "different-name", "id": 4, "title": "Different Name", "japaneseTitle": "Alt 4",
         "poster": "https://cdn/4.jpg", "time": "09:00", "episode_no": 2},
        # unknown show -> null id, empty poster
        {"slug": "some-show", "id": None, "title": "Some Show!", "japaneseTitle": "Jp",
         "poster": "", "time": "10:00", "episode_no": 6},
    ]
    assert client.get("/api/schedule?date=24-10-2026").status_code == 400


def test_admin_and_status(client, monkeypatch):
    assert client.post("/api/admin/crawl", headers={"X-AVTV": "1"}).status_code == 404      # admin console is invisible until configured
    assert client.get("/api/status").json()["results"]["catalog_entries"] >= 5


def test_heartbeat_get_and_head(client):
    assert client.get("/heartbeat").json()["status"] == "alive"
    assert client.head("/heartbeat").status_code == 200   # UptimeRobot free plan uses HEAD
    assert client.get("/health").status_code == 200


def test_existing_files_mean_no_startup_crawl_and_catalog_is_seeded():
    assert crawler.needs_crawl() is False                  # completed.json + upcoming.json present
    store.path_of(catalog.FILE).unlink()
    assert catalog.lookup("anime-1-abc1") is None
    assert catalog.seed_if_missing() is True               # rebuilt from the two uploaded files
    assert catalog.lookup("anime-1-abc1")["id"] == 1


def test_missing_files_trigger_crawl():
    store.path_of("upcoming.json").unlink()
    assert crawler.needs_crawl() is True
