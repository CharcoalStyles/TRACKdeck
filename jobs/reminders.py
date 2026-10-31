"""
jobs/reminders.py
------------------
Fires a single ad-hoc reminder (agent/tools/alerts.py's set_reminder/
set_timer). Scheduled per-reminder as a one-shot APScheduler DateTrigger
job with id f"reminder:{reminder_id}" — see agent/scheduler.py.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from apscheduler.triggers.date import DateTrigger

from agent.scheduler import scheduler
from agent.settings import settings
from utils import reminders_store
from utils.caldav_client import get_event
from utils.notify import notify_error, send_gotify

logger = logging.getLogger(__name__)

REMINDER_PRIORITY = 7  # below the error convention (8), above silent routine pushes (3)
TEST_REMINDER_DELAY = timedelta(seconds=10)


def push_text(reminder: dict) -> str:
    """The reminder's text for the Gotify push. A generated schedule block's
    reminder gets its length and end time appended here, so the stored text
    (what the device and dashboard list) stays short. Any lookup failure
    falls back to the plain message."""
    try:
        if not reminder.get("event_uid"):
            return reminder["message"]
        result = get_event(reminder["event_uid"])
        event = result.get("event") if result.get("success") else None
        if not event or not event.get("generated"):
            return reminder["message"]
        start = datetime.strptime(event["start"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        end = datetime.strptime(event["end"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        until = end.astimezone(settings.zoneinfo()).strftime("%H:%M")
        return f"{reminder['message']} — {round((end - start).total_seconds() / 60)} min, until {until}"
    except Exception:
        return reminder["message"]


async def fire_reminder(reminder_id: str) -> None:
    try:
        reminder = await asyncio.to_thread(reminders_store.get_reminder, reminder_id)
        if reminder is None or reminder["status"] != "pending":
            return

        await asyncio.to_thread(send_gotify, "Reminder", await asyncio.to_thread(push_text, reminder), REMINDER_PRIORITY)
        await asyncio.to_thread(reminders_store.mark_status, reminder_id, "fired")
        logger.info("Fired reminder %s: %s", reminder_id, reminder["message"])
    except Exception as e:
        logger.error("Reminder %s failed to fire: %s", reminder_id, e)
        notify_error(f"Reminder failed to fire ({reminder_id})", e)


async def create_test_reminder(delay_seconds: int | None = None, alert_sound_id: str | None = None) -> str:
    """Debug-only round-trip test (see main.py's POST /debug/reminder):
    creates a real pending row in reminders.db and schedules it on the
    shared scheduler, exercising the full store -> scheduler ->
    fire_reminder -> Gotify pipeline rather than faking any step.
    alert_sound_id optionally pins which alert sound the device should
    play instead of its default random pick — delivered via
    jobs/device_sync.py, not through Gotify itself.
    Returns the new reminder_id."""
    delay = timedelta(seconds=delay_seconds) if delay_seconds is not None else TEST_REMINDER_DELAY
    reminder_id = str(uuid.uuid4())
    due_at_utc = datetime.now(timezone.utc) + delay
    await asyncio.to_thread(
        reminders_store.create_reminder,
        reminder_id,
        "Test reminder from the dashboard",
        int(due_at_utc.timestamp()),
        None,
        alert_sound_id,
    )
    scheduler.add_job(
        fire_reminder,
        trigger=DateTrigger(run_date=due_at_utc),
        args=[reminder_id],
        id=f"reminder:{reminder_id}",
        replace_existing=True,
    )
    logger.info("Scheduled test reminder %s, due in %ds", reminder_id, delay.total_seconds())
    return reminder_id
