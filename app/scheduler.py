"""Weekly job: rebuild completed.json / upcoming.json (default: Sunday 00:00 in REFRESH_TZ)."""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import crawler
from .config import settings


def start() -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=settings.refresh_tz)
    sched.add_job(
        crawler.run_crawl,
        CronTrigger(day_of_week=settings.refresh_day, hour=settings.refresh_hour,
                    minute=settings.refresh_minute, timezone=settings.refresh_tz),
        kwargs={"reason": "weekly"},
        id="weekly-crawl",
        misfire_grace_time=3600,  # still run if the app was briefly down at 00:00
        coalesce=True,
        max_instances=1,
    )
    sched.start()
    return sched
