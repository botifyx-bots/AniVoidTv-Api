"""All configuration comes from environment variables (see .env.example)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [x.strip().rstrip("/") for x in os.getenv(name, default).split(",") if x.strip()]


class Settings:
    # server
    port = int(os.getenv("PORT", "8000"))
    cors_origins = _list("CORS_ORIGINS", "")          # browsers talk to the Vercel proxy, so no CORS is needed by default
    trusted_hosts = _list("TRUSTED_HOSTS", "")        # e.g. anivoid-api.onrender.com (empty = any host header)
    global_rate_per_min = int(os.getenv("GLOBAL_RATE_PER_MIN", "600"))

    # admin console (https://<site>/AnimeVoid): password + TOTP 2FA, see SECURITY.md and tools/admin_setup.py
    admin_username = os.getenv("ADMIN_USERNAME", "").strip()
    admin_password_hash = os.getenv("ADMIN_PASSWORD_HASH", "").strip()
    admin_totp_secret = os.getenv("ADMIN_TOTP_SECRET", "").strip().replace(" ", "").upper()
    admin_ips = [x.strip() for x in os.getenv("ADMIN_IPS", "").split(",") if x.strip()]   # optional allow-list
    admin_idle_minutes = int(os.getenv("ADMIN_IDLE_MINUTES", "30"))
    admin_max_hours = int(os.getenv("ADMIN_MAX_HOURS", "8"))

    # official upstream API
    upstream_base = os.getenv("UPSTREAM_BASE", "https://anikotoapi.site").rstrip("/")
    rate_limit_requests = int(os.getenv("RATE_LIMIT_REQUESTS", "55"))
    rate_limit_window = float(os.getenv("RATE_LIMIT_WINDOW", "120"))
    crawl_per_page = min(int(os.getenv("CRAWL_PER_PAGE", "100")), 100)

    # weekly job
    enable_scheduler = _bool("ENABLE_SCHEDULER", True)
    refresh_tz = os.getenv("REFRESH_TZ", "UTC")
    refresh_day = os.getenv("REFRESH_DAY", "sun")
    refresh_hour = int(os.getenv("REFRESH_HOUR", "0"))
    refresh_minute = int(os.getenv("REFRESH_MINUTE", "0"))
    crawl_on_startup = _bool("CRAWL_ON_STARTUP", True)
    stale_after_days = float(os.getenv("STALE_AFTER_DAYS", "0"))

    # storage
    data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
    json_pretty = _bool("JSON_PRETTY", False)

    # site scraping
    site_mirrors = _list(
        "SITE_MIRRORS",
        "https://anikototv.to,https://anikoto.cz,https://anikoto.me,https://anikoto.net,https://anikototv.se",
    )
    scraper_api_key = os.getenv("SCRAPER_API_KEY", "").strip()
    flaresolverr_url = os.getenv("FLARESOLVERR_URL", "").strip().rstrip("/")

    # accounts (MongoDB) -------------------------------------------------
    mongodb_uri = os.getenv("MONGODB_URI", "").strip()
    mongodb_db = os.getenv("MONGODB_DB", "anivoid")
    session_secret = os.getenv("SESSION_SECRET", "").strip()
    session_days = int(os.getenv("SESSION_DAYS", "30"))
    cookie_secure = _bool("COOKIE_SECURE", True)
    disable_docs = _bool("DISABLE_DOCS", cookie_secure)   # docs are hidden in production unless DISABLE_DOCS=false
    google_client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    proxy_secret = os.getenv("PROXY_SECRET", "").strip()   # shared with the Vercel proxy, to trust X-Client-IP
    require_proxy = _bool("REQUIRE_PROXY", bool(os.getenv("PROXY_SECRET", "").strip()))   # only the Vercel proxy may call /api

    # pictures / uploads
    max_avatars = int(os.getenv("MAX_AVATARS", "30"))
    max_banners = int(os.getenv("MAX_BANNERS", "12"))
    max_upload_bytes = int(os.getenv("MAX_UPLOAD_BYTES", str(2_500_000)))
    user_media_cap = int(os.getenv("USER_MEDIA_CAP_BYTES", str(40_000_000)))

    # cache
    ttl_search = int(os.getenv("TTL_SEARCH", "300"))
    ttl_schedule = int(os.getenv("TTL_SCHEDULE", "600"))
    ttl_topten = int(os.getenv("TTL_TOPTEN", "600"))


settings = Settings()
