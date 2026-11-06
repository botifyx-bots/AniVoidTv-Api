import asyncio
import logging
import math
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import accounts, admin, cache, catalog, crawler, extractors, flags, media, scheduler, scraper, security, shop, social, store, telemetry, upstream, db as database
from .config import settings
from .errors import ApiError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.scheduler = scheduler.start() if settings.enable_scheduler else None
    if crawler.needs_crawl():
        if settings.crawl_on_startup:
            log.info("completed.json / upcoming.json missing -> starting crawl in background")
            crawler.start_background("startup")
    else:
        log.info("existing data files found -> no startup crawl; next rebuild at the scheduled time")
        catalog.seed_if_missing()
    yield
    if app.state.scheduler:
        app.state.scheduler.shutdown(wait=False)
    await asyncio.gather(upstream.close(), scraper.close())


app = FastAPI(title="AniVoid API", version="2.0.0", lifespan=lifespan,
              docs_url=None if settings.disable_docs else "/docs", redoc_url=None, openapi_url=None if settings.disable_docs else "/openapi.json",
              description="Own API layer on top of the official AniKoto public API.")
if settings.cors_origins:   # default: none. The browser only talks to the same-origin Vercel proxy, never to this server directly.
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Content-Type", "X-AVTV", "X-Admin-CSRF"], allow_credentials="*" not in settings.cors_origins)
if settings.trusted_hosts:
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.include_router(accounts.router)
app.include_router(social.router)
app.include_router(media.router)
app.include_router(shop.router)
app.include_router(admin.router)
app.include_router(telemetry.router)


def fail(status: int, message: str) -> JSONResponse:
    return JSONResponse({"success": False, "message": message}, status_code=status)


@app.exception_handler(ApiError)
async def _api_error(_: Request, e: ApiError):
    return JSONResponse({"success": False, "message": e.message, **e.extra}, status_code=e.status)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, e: RequestValidationError):
    first = e.errors()[0] if e.errors() else {}
    where = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    return JSONResponse({"success": False, "message": f"Invalid input{': ' + where if where else ''}",
                         "detail": jsonable_errors(e.errors())}, status_code=422)


def jsonable_errors(errors):
    return [{"loc": list(x.get("loc", [])), "msg": x.get("msg", ""), "type": x.get("type", "")} for x in errors]


PUBLIC_PATHS = {"/", "/health", "/heartbeat"}
MAINTENANCE_EXEMPT = ("/api/admin/", "/api/auth/logout", "/api/t/ping", "/api/config")


@app.middleware("http")
async def guard(request: Request, call_next):
    """Layered request gate: proxy-only access, global rate limit, CSRF header, size limits, maintenance mode, security headers."""
    path, method = request.url.path, request.method
    api = path.startswith("/api/")
    if settings.require_proxy and settings.proxy_secret and path not in PUBLIC_PATHS and not path.startswith(("/docs", "/openapi")):
        if not accounts.via_proxy(request):
            return JSONResponse({"success": False, "message": "Forbidden"}, status_code=403)   # nothing about why
    if api and not security.limiter.allow("g:" + accounts.client_ip(request), settings.global_rate_per_min, 60):
        return fail(429, "Too many requests. Slow down.")
    if method in ("POST", "PUT", "PATCH", "DELETE") and api:
        if request.headers.get("x-avtv") != "1":
            return fail(403, "Missing X-AVTV header.")
        limit = settings.max_upload_bytes + 4096 if path == "/api/me/pictures" else 200_000
        try:
            if int(request.headers.get("content-length", "0")) > limit:
                return fail(413, "Request too large.")
        except ValueError:
            return fail(400, "Bad Content-Length.")
        if not path.startswith(MAINTENANCE_EXEMPT) and database.enabled():
            try:
                msg = flags.maintenance(database.get_db())
            except Exception:  # noqa: BLE001 - never let a flags lookup take the API down
                msg = None
            if msg:
                return JSONResponse({"success": False, "message": msg, "maintenance": True}, status_code=503)
    resp = await call_next(request)
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
    h.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if settings.cookie_secure:
        h.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload")
    if api:
        h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if path != "/api/media" and not path.startswith("/api/media/") and "cache-control" not in h:
            h["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(scraper.ScrapeError)
async def _scrape_error(_: Request, e: scraper.ScrapeError):
    return fail(502, f"Source site unavailable: {e}")


@app.exception_handler(Exception)
async def _unhandled(_: Request, e: Exception):
    log.exception("unhandled error")
    return fail(500, "Internal server error")


# ------------------------------------------------------------------ meta
@app.get("/")
async def root():
    return {
        "name": "AniVoid API",
        "endpoints": {
            "search": "/api/search?keyword=solo+leveling&page=1",
            "schedule": "/api/schedule?date=YYYY-MM-DD",
            "random": "/api/random",
            "top-ten": "/api/top-ten",
            "completed": "/api/completed?page=1&per_page=20",
            "upcoming": "/api/upcoming?page=1&per_page=20",
            "accounts": "/api/config, /api/auth/*, /api/me, /api/me/pictures, /api/media/{id}, /api/shop, /api/comments, /api/list, /api/continue, /api/users/{name}",
            "status": "/api/status",
            "heartbeat": "/heartbeat",
            "docs": "/docs",
        },
    }


@app.api_route("/heartbeat", methods=["GET", "HEAD"])
@app.api_route("/health", methods=["GET", "HEAD"])
async def heartbeat():
    """Keep-alive / uptime route. Cheap, no upstream calls. HEAD is supported because UptimeRobot's
    free plan pings with HEAD by default."""
    return {"ok": True, "status": "alive", "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


@app.get("/api/status")
async def status():
    job = app.state.scheduler.get_job("weekly-crawl") if app.state.scheduler else None
    files = {}
    for name in (crawler.COMPLETED, crawler.UPCOMING, catalog.FILE):
        p = store.path_of(name)
        files[name] = {"exists": p.exists(), "bytes": p.stat().st_size if p.exists() else 0}
    return {
        "success": True,
        "results": {
            "crawl": crawler.state,
            "next_scheduled_crawl": job.next_run_time.isoformat() if job and job.next_run_time else None,
            "timezone": settings.refresh_tz,
            "catalog_entries": catalog.size(),
            "files": files,
        },
    }


# ------------------------------------------------------------------ completed / upcoming (from JSON files)
def _paged(filename: str, page: int, per_page: int):
    data = store.read_json(filename)
    if data is None:
        msg = "Data is still being built (first crawl takes a few minutes), try again shortly."
        return fail(503, msg)
    items = data["data"]
    total_pages = max(1, math.ceil(len(items) / per_page))
    chunk = items[(page - 1) * per_page: page * per_page]
    return {
        "success": True,
        "results": {
            "updated_at": data.get("updated_at"),
            "data": chunk,
            "pagination": {"currentPage": page, "totalPages": total_pages, "totalItems": len(items),
                           "itemsPerPage": per_page, "hasNext": page < total_pages, "hasPrev": page > 1},
        },
    }


@app.get("/api/completed")
async def completed(page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)):
    return _paged(crawler.COMPLETED, page, per_page)


@app.get("/api/upcoming")
async def upcoming(page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)):
    return _paged(crawler.UPCOMING, page, per_page)


# ------------------------------------------------------------------ scraped endpoints
@app.get("/api/search")
async def search(response: Response, keyword: str = Query("", max_length=200), page: int = Query(1, ge=1)):
    keyword = keyword.strip()
    if not keyword:
        return fail(400, "Keyword is required")
    key = f"search:{keyword.lower()}:{page}"
    if (hit := cache.get(key)) is not None:
        return {"success": True, "results": hit}
    try:
        result = await extractors.search(keyword, page)
    except scraper.ScrapeError:
        if not catalog.size():
            raise
        response.headers["X-Data-Source"] = "local-catalog"  # site blocked -> official-API catalog
        return {"success": True, "results": extractors.search_local(keyword, page)}
    cache.set(key, result, settings.ttl_search)
    return {"success": True, "results": result}


@app.get("/api/schedule")
async def schedule(date: str = Query("")):
    if not date:
        return fail(400, "Date is required (YYYY-MM-DD)")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return fail(400, "Date must be in YYYY-MM-DD format")
    key = f"schedule:{date}"
    if (hit := cache.get(key)) is not None:
        return {"success": True, "results": hit}
    result = await extractors.schedule(date)
    cache.set(key, result, settings.ttl_schedule)
    return {"success": True, "results": result}


@app.get("/api/random")
async def random_anime(response: Response):
    try:
        result = await extractors.random_anime()
        if result["id"] is None or not result["title"]:
            raise scraper.ScrapeError("random page could not be parsed")
    except scraper.ScrapeError:
        result = extractors.random_local()
        if result is None:
            raise
        response.headers["X-Data-Source"] = "local-catalog"
    return {"success": True, "results": result}


@app.get("/api/top-ten")
async def top_ten():
    if (hit := cache.get("top-ten")) is not None:
        return {"success": True, "results": hit}
    result = await extractors.top_ten()
    cache.set("top-ten", result, settings.ttl_topten)
    return {"success": True, "results": result}
