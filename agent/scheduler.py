"""
agent/scheduler.py
-------------------
Shared APScheduler instance and cron trigger builders. Lives here (not in
main.py, where it originated) so tool code (agent/tools/alerts.py) can
register/cancel per-reminder jobs without main.py and agent.tools.* ending
up importing each other.

Jobs currently registered against this scheduler (see main.py's lifespan):
  - "morning_message" — jobs/morning.py, cron via morning_trigger()
  - "evening_message" — jobs/evening.py, cron via evening_trigger()
  - "weekly_review" — jobs/reviews.py, Sundays via weekly_trigger()
  - "monthly_review" — jobs/reviews.py, last evening or first morning via monthly_trigger()
  - "bedtime_reminder" — jobs/bedtime.py, cron via bedtime_trigger()
  - "calendar_reminder_sync" — jobs/calendar_sync.py, interval via
    calendar_sync_trigger()
  - "reminder:<id>" — jobs/reminders.py, one-shot DateTrigger per ad-hoc
    reminder, added/removed directly by agent/tools/alerts.py
  - "day_start" — jobs/day_start.py, cron via checkin_start_trigger()
  - "checkin:<id>" / "checkin_expire:<id>" — jobs/checkin.py, one-shot
    DateTrigger per mental-health check-in prompt and its answer-window
    expiry, added/removed directly by jobs/checkin.py
"""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agent.settings import settings

scheduler = AsyncIOScheduler(timezone=settings.zoneinfo())


def evening_trigger() -> CronTrigger:
    hour, minute = (int(p) for p in settings.evening_time.split(":"))
    return CronTrigger(hour=hour, minute=minute, timezone=settings.zoneinfo())


def weekly_trigger() -> CronTrigger:
    hour, minute = (int(p) for p in settings.weekly_review_time.split(":"))
    return CronTrigger(day_of_week="sun", hour=hour, minute=minute, timezone=settings.zoneinfo())


def monthly_trigger() -> CronTrigger:
    """Last day of the month at the evening time, or the 1st at the morning time."""
    if settings.monthly_review_timing == "first_morning":
        day, clock = "1", settings.monthly_review_morning_time
    else:
        day, clock = "last", settings.monthly_review_evening_time
    hour, minute = (int(p) for p in clock.split(":"))
    return CronTrigger(day=day, hour=hour, minute=minute, timezone=settings.zoneinfo())


def bedtime_trigger() -> CronTrigger:
    hour, minute = (int(p) for p in settings.bedtime.split(":"))
    return CronTrigger(hour=hour, minute=minute, timezone=settings.zoneinfo())


def calendar_sync_trigger() -> IntervalTrigger:
    return IntervalTrigger(minutes=settings.calendar_sync_interval_minutes)


def morning_trigger() -> CronTrigger:
    hour, minute = (int(p) for p in settings.morning_time.split(":"))
    return CronTrigger(hour=hour, minute=minute, timezone=settings.zoneinfo())


def checkin_start_trigger() -> CronTrigger:
    hour, minute = (int(p) for p in settings.checkin_start_time.split(":"))
    return CronTrigger(hour=hour, minute=minute, timezone=settings.zoneinfo())


_TIME_JOB_TRIGGERS = {
    "morning_message": morning_trigger,
    "evening_message": evening_trigger,
    "weekly_review": weekly_trigger,
    "monthly_review": monthly_trigger,
    "bedtime_reminder": bedtime_trigger,
    "day_start": checkin_start_trigger,
}


def reschedule_time_jobs(*job_ids: str) -> None:
    """Rebuild the cron triggers of the named fixed-time jobs from current
    settings (all of them if none named). Jobs not registered yet are skipped."""
    for job_id in job_ids or _TIME_JOB_TRIGGERS:
        if scheduler.get_job(job_id) is not None:
            scheduler.reschedule_job(job_id, trigger=_TIME_JOB_TRIGGERS[job_id]())
