"""Fetches pages from the anikototv.to family of mirrors (used by search/schedule/random/top-ten).

Ported from the AniKotoAPI (Node) mirror/proxy helpers: mirror fallback, Cloudflare-challenge
detection and optional ScraperAPI / FlareSolverr fallbacks.
"""
import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from .config import settings

log = logging.getLogger("scraper")

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",  # no brotli dependency needed
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}
CHALLENGE_MARKERS = ("Just a moment...", "Checking your browser", "Enable JavaScript")
MIRROR_COOLDOWN = 300  # seconds a failing mirror is skipped

_client: httpx.AsyncClient | None = None
_working: str | None = None
_failed_until: dict[str, float] = {}


class ScrapeError(Exception):
    pass


@dataclass
class Page:
    text: str
    url: str  # final URL after redirects
    mirror: str


def _client_() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=15, headers=BROWSER_HEADERS, follow_redirects=True)
    return _client


async def close() -> None:
    if _client and not _client.is_closed:
        await _client.aclose()


def _blocked(text: str) -> bool:
    head = text[:3000]
    return any(m in head for m in CHALLENGE_MARKERS)


async def _via_scraperapi(url: str) -> Page:
    r = await _client_().get(
        "http://api.scraperapi.com", params={"api_key": settings.scraper_api_key, "url": url, "render": "false"}, timeout=45
    )
    r.raise_for_status()
    return Page(r.text, url, "scraperapi")


async def _via_flaresolverr(url: str) -> Page:
    r = await _client_().post(
        f"{settings.flaresolverr_url}/v1", json={"cmd": "request.get", "url": url, "maxTimeout": 60000}, timeout=75
    )
    j = r.json()
    if j.get("status") != "ok":
        raise ScrapeError(f"FlareSolverr: {j.get('message')}")
    return Page(j["solution"]["response"], j["solution"].get("url", url), "flaresolverr")


async def fetch(path: str, headers: dict | None = None, attempts: int = 2) -> Page:
    """GET `path` from the first healthy mirror. Raises ScrapeError when everything fails."""
    global _working
    now = time.monotonic()
    mirrors = [m for m in settings.site_mirrors if _failed_until.get(m, 0) <= now] or list(settings.site_mirrors)
    if _working in mirrors:
        mirrors.remove(_working)
        mirrors.insert(0, _working)

    last = "no mirrors configured"
    for mirror in mirrors:
        url = f"{mirror}{path}"
        for attempt in range(attempts):
            try:
                r = await _client_().get(url, headers=headers)
                if r.status_code == 404:
                    raise ScrapeError(f"404 for {path}")
                r.raise_for_status()
                if _blocked(r.text):
                    raise ScrapeError("Cloudflare challenge")
                _working = mirror
                return Page(r.text, str(r.url), mirror)
            except ScrapeError as e:
                last = str(e)
                if "404" in last:
                    raise
            except httpx.HTTPError as e:
                last = f"{type(e).__name__}: {e}"
            await asyncio.sleep(0.5 * (attempt + 1))
        _failed_until[mirror] = time.monotonic() + MIRROR_COOLDOWN
        log.warning("mirror failed: %s (%s)", mirror, last)

    # direct access failed everywhere -> optional bypass services
    target = f"{mirrors[0]}{path}"
    for enabled, fn in ((settings.scraper_api_key, _via_scraperapi), (settings.flaresolverr_url, _via_flaresolverr)):
        if enabled:
            try:
                return await fn(target)
            except Exception as e:  # noqa: BLE001
                last = f"{fn.__name__}: {e}"
                log.warning("bypass failed: %s", last)
    raise ScrapeError(f"all mirrors failed ({last})")
