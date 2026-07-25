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

from utils import reminders_store
from utils.notify import notify_error, send_gotify

logger = logging.getLogger(__name__)

REMINDER_PRIORITY = 7  # below the error convention (8), above silent routine pushes (3)


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
