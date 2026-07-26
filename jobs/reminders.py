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
from utils import reminders_store
from utils.notify import notify_error, send_gotify

logger = logging.getLogger(__name__)

REMINDER_PRIORITY = 7  # below the error convention (8), above silent routine pushes (3)
TEST_REMINDER_DELAY = timedelta(seconds=10)


async def fire_reminder(reminder_id: str) -> None:
    try:
        reminder = await asyncio.to_thread(reminders_store.get_reminder, reminder_id)
        if reminder is None or reminder["status"] != "pending":
            return

        await asyncio.to_thread(send_gotify, "Reminder", reminder["message"], REMINDER_PRIORITY)
        await asyncio.to_thread(reminders_store.mark_status, reminder_id, "fired")
        logger.info("Fired reminder %s: %s", reminder_id, reminder["message"])
    except Exception as e:
        logger.error("Reminder %s failed to fire: %s", reminder_id, e)
        notify_error(f"Reminder failed to fire ({reminder_id})", e)


async def create_test_reminder() -> str:
    """Debug-only round-trip test (see main.py's POST /debug/reminder):
    creates a real pending row in reminders.db and schedules it on the
    shared scheduler, exercising the full store -> scheduler ->
    fire_reminder -> Gotify pipeline rather than faking any step.
    Returns the new reminder_id."""
    reminder_id = str(uuid.uuid4())
    due_at_utc = datetime.now(timezone.utc) + TEST_REMINDER_DELAY
    await asyncio.to_thread(
        reminders_store.create_reminder,
        reminder_id,
        "Test reminder from the dashboard",
        int(due_at_utc.timestamp()),
    )
    scheduler.add_job(
        fire_reminder,
        trigger=DateTrigger(run_date=due_at_utc),
        args=[reminder_id],
        id=f"reminder:{reminder_id}",
        replace_existing=True,
    )
    logger.info("Scheduled test reminder %s, due in %ds", reminder_id, TEST_REMINDER_DELAY.total_seconds())
    return reminder_id
