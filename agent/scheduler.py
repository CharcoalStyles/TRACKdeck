"""
agent/scheduler.py
-------------------
Shared APScheduler instance and cron trigger builders. Lives here (not in
main.py, where it originated) so tool code (agent/tools/alerts.py) can
register/cancel per-reminder jobs without main.py and agent.tools.* ending
up importing each other.

Jobs currently registered against this scheduler (see main.py's lifespan):
  - "daily_digest" — jobs/digest.py, cron via digest_trigger()
  - "bedtime_reminder" — jobs/bedtime.py, cron via bedtime_trigger()
  - "calendar_reminder_sync" — jobs/calendar_sync.py, interval via
    calendar_sync_trigger()
  - "reminder:<id>" — jobs/reminders.py, one-shot DateTrigger per ad-hoc
    reminder, added/removed directly by agent/tools/alerts.py
"""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agent.settings import settings

scheduler = AsyncIOScheduler(timezone=settings.zoneinfo())


def digest_trigger() -> CronTrigger:
    hour, minute = (int(p) for p in settings.digest_time.split(":"))
    return CronTrigger(hour=hour, minute=minute, timezone=settings.zoneinfo())


def bedtime_trigger() -> CronTrigger:
    hour, minute = (int(p) for p in settings.bedtime.split(":"))
    return CronTrigger(hour=hour, minute=minute, timezone=settings.zoneinfo())


def calendar_sync_trigger() -> IntervalTrigger:
    return IntervalTrigger(minutes=settings.calendar_sync_interval_minutes)
