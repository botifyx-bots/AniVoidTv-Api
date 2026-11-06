"""Client for the official AniKoto public API (https://anikotoapi.site).

The upstream allows 60 requests / IP / 120 s.  EVERY call goes through one shared
sliding-window limiter, so the weekly crawl and on-demand lookups never exceed it.
"""
import asyncio
import time
from collections import deque

import httpx

from .config import settings

HEADERS = {"User-Agent": "AniVoid-API/1.0 (+self-hosted mirror)", "Accept": "application/json"}


class SlidingWindowLimiter:
    def __init__(self, max_calls: int, period: float):
        self.max_calls, self.period = max_calls, period
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self.period:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                await asyncio.sleep(self.period - (now - self._calls[0]) + 0.05)

    def penalize(self) -> None:
        """Upstream said 429: assume the window is full."""
        now = time.monotonic()
        self._calls.clear()
        self._calls.extend([now] * self.max_calls)


limiter = SlidingWindowLimiter(settings.rate_limit_requests, settings.rate_limit_window)
_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30, headers=HEADERS, follow_redirects=True)
    return _client


async def close() -> None:
    if _client and not _client.is_closed:
        await _client.aclose()


async def get_json(path: str, params: dict | None = None, retries: int = 6) -> dict:
    url = f"{settings.upstream_base}{path}"
    last: Exception | None = None
    for attempt in range(retries):
        await limiter.acquire()
        try:
            r = await client().get(url, params=params)
            if r.status_code == 429:
                limiter.penalize()
                await asyncio.sleep(min(float(r.headers.get("Retry-After", 5)), settings.rate_limit_window))
                last = RuntimeError("429 from upstream")
                continue
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            last = e
            await asyncio.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"upstream request failed: {url} {params} -> {last}")


async def recent_anime(page: int = 1, per_page: int = 100) -> dict:
    """GET /recent-anime?page=&per_page=  ->  {ok, data:[...], pagination:{...}}"""
    return await get_json("/recent-anime", {"page": page, "per_page": per_page})


async def series(anime_id: int) -> dict:
    """GET /series/{id}  ->  {anime, episodes}  (not used by the crawler, kept for convenience)"""
    return await get_json(f"/series/{anime_id}")
