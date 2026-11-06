"""Weekly crawl of the official API -> completed.json, upcoming.json (+ catalog.json).

Flow:  page 1..N of /recent-anime?per_page=100 (rate limited)  ->  split by `status`
         "Finished Airing" -> completed.json      "Not yet aired" -> upcoming.json
       new files are built completely in memory, then swapped in atomically, so the API keeps
       serving the old data until the new data is ready (and keeps it if the crawl fails).

Run manually:  python -m app.crawler
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

from . import catalog, store, upstream
from .config import settings

log = logging.getLogger("crawler")

COMPLETED, UPCOMING, STATUS = "completed.json", "upcoming.json", "status.json"
MIN_COVERAGE = 0.9  # refuse to replace files if we collected < 90% of what upstream reports

_lock = asyncio.Lock()
_tasks: set[asyncio.Task] = set()
state: dict = {"state": "idle", "last_success": None, "last_error": None, "progress": None}


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def classify(status: str | None) -> str | None:
    s = (status or "").strip().lower()
    if s == "finished airing":
        return "completed"
    if s == "not yet aired":
        return "upcoming"
    return None


def _load_state() -> None:
    saved = store.read_json(STATUS)
    if saved:
        state.update({k: saved.get(k) for k in ("last_success", "last_error", "completed", "upcoming", "total_seen")})


def needs_crawl() -> bool:
    """Startup rule: crawl only if completed.json or upcoming.json is missing.

    If both files are already there (e.g. uploaded to the server) nothing is crawled on boot;
    the next rebuild happens at the scheduled time. STALE_AFTER_DAYS > 0 optionally adds an age check.
    """
    _load_state()
    if not (store.path_of(COMPLETED).exists() and store.path_of(UPCOMING).exists()):
        return True
    if settings.stale_after_days > 0:
        ts = state.get("last_success")
        if not ts:
            return True
        age = datetime.now(timezone.utc) - datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return age.total_seconds() > settings.stale_after_days * 86400
    return False


async def crawl_all() -> tuple[list[dict], int]:
    """Return (all unique rows, total reported by upstream)."""
    per_page = settings.crawl_per_page
    first = await upstream.recent_anime(1, per_page)
    pg = first.get("pagination", {})
    total_pages, total = int(pg.get("total_pages", 1)), int(pg.get("total", 0))
    rows: dict[int, dict] = {r["id"]: r for r in first.get("data", [])}
    state["progress"] = {"page": 1, "total_pages": total_pages}
    for page in range(2, total_pages + 1):
        data = (await upstream.recent_anime(page, per_page)).get("data", [])
        for r in data:
            rows[r["id"]] = r  # de-dupe: rows can shift between pages while the crawl runs
        state["progress"] = {"page": page, "total_pages": total_pages}
        if page % 10 == 0:
            log.info("crawl %d/%d pages, %d rows", page, total_pages, len(rows))
    return list(rows.values()), total


async def run_crawl(reason: str = "manual") -> bool:
    """Full rebuild. Returns True on success. Only one crawl runs at a time."""
    if _lock.locked():
        log.info("crawl already running, skipping (%s)", reason)
        return False
    async with _lock:
        started = time.monotonic()
        state.update(state="running", last_error=None)
        log.info("crawl started (%s)", reason)
        try:
            rows, total = await crawl_all()
            if total and len(rows) < total * MIN_COVERAGE:
                raise RuntimeError(f"incomplete crawl: got {len(rows)} of {total} rows; keeping old files")

            buckets: dict[str, list[dict]] = {"completed": [], "upcoming": []}
            for r in rows:
                kind = classify(r.get("status"))
                if kind:
                    buckets[kind].append(r)

            now = _iso()
            for name, kind in ((COMPLETED, "completed"), (UPCOMING, "upcoming")):
                store.write_json(name, {"updated_at": now, "source": settings.upstream_base,
                                        "total": len(buckets[kind]), "data": buckets[kind]})
            catalog.save_all(rows)

            state.update(last_success=now, completed=len(buckets["completed"]),
                         upcoming=len(buckets["upcoming"]), total_seen=len(rows))
            log.info("crawl done in %.0fs: %d completed, %d upcoming, %d total",
                     time.monotonic() - started, len(buckets["completed"]), len(buckets["upcoming"]), len(rows))
            return True
        except Exception as e:  # noqa: BLE001
            state["last_error"] = f"{_iso()} {e}"
            log.exception("crawl failed")
            return False
        finally:
            state.update(state="idle", progress=None)
            store.write_json(STATUS, {k: state.get(k) for k in
                                      ("last_success", "last_error", "completed", "upcoming", "total_seen")})


def start_background(reason: str) -> None:
    t = asyncio.create_task(run_crawl(reason))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    async def _main() -> int:
        ok = await run_crawl("cli")
        await upstream.close()
        return 0 if ok else 1

    raise SystemExit(asyncio.run(_main()))
