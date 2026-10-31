"""
jobs/evening.py
----------------
The evening message, pushed through Gotify (and emailed when email_to is set)
at settings.evening_time. Deliberately NOT a recap of the day: the assistant
cannot know what the user actually did, so it would invent. The message is
assembled entirely by code, with no model call:
  1. bedtime tonight
  2. how many captures are still unticked, with a link to the Captures page
  3. tomorrow's calendar and reminders
Check-in answers are not in it; they stay in the vault's Check-ins/ notes.
With settings.daily_commentary on, the same text is saved to
Reviews/Daily/YYYY-MM-DD.md.

Also the nightly housekeeping that used to ride on the digest: sweep the
thread/keyword registry (keyword-addressed threads are a same-day
concept), prune stale thread locks and old raw voice recordings. The
sweep runs even if the message failed — silently keeping yesterday's
keywords alive would be the worse failure.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date, datetime, timedelta

from agent.runtime import app_state, prune_thread_locks
from agent.settings import settings
from jobs.common import deliver
from utils import day_context, reviews
from utils.notify import notify_error
from voice import UPLOAD_DIR

logger = logging.getLogger(__name__)

RECEIVED_NOTES_MAX_AGE_SECONDS = 24 * 60 * 60
EVENING_PRIORITY = 3

def captures_line(today: date) -> str:
    open_ = day_context.open_captures(today)
    count = len(open_)
    if not count:
        return "No unticked captures."
    noun = "capture" if count == 1 else "captures"
    older = sum(1 for c in open_ if c["date"] != today.isoformat())
    line = f"{count} unticked {noun}" + (f" ({older} from earlier days)." if older else ".")
    if settings.public_base_url:
        line += f" {settings.public_base_url.rstrip('/')}/captures"
    return line


def tomorrow_section(today: date) -> str:
    tomorrow = today + timedelta(days=1)
    rows = [
        r for r in (
            day_context.render_calendar(tomorrow, tomorrow),
            day_context.render_reminders(tomorrow, tomorrow),
        ) if r
    ]
    return "\n".join(rows) if rows else "Nothing on the calendar or reminders yet."


def compose_evening_message(today: date | None = None) -> tuple[str, date]:
    """Blocking — run via asyncio.to_thread. Returns the text and the day it covers."""
    today = today or datetime.now(settings.zoneinfo()).date()
    parts = [
        f"Bedtime tonight: {settings.bedtime}.",
        captures_line(today),
        f"Tomorrow:\n{tomorrow_section(today)}",
    ]
    return "\n\n".join(parts), today


def save_daily_commentary(text: str, day: date):
    return reviews.write_review(
        "daily", reviews.period_key("daily", day), f"Daily commentary — {day.strftime('%A %d %B %Y')}", text
    )


def _prune_received_notes() -> int:
    """Blocking filesystem sweep — run via asyncio.to_thread. Raw voice
    recordings are only ever useful briefly (debugging a misheard command)."""
    if not os.path.isdir(UPLOAD_DIR):
        return 0
    cutoff = time.time() - RECEIVED_NOTES_MAX_AGE_SECONDS
    pruned = 0
    for name in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                pruned += 1
        except OSError:
            continue
    return pruned


async def sweep_threads() -> None:
    freed = len(app_state.threads)
    app_state.threads.clear()
    app_state.keywords.clear()
    app_state.default_thread_id = None
    pruned = prune_thread_locks()
    logger.info(
        "Cleared %d addressable thread keyword(s) for the new day (%d stale lock(s) pruned).",
        freed, pruned,
    )
    try:
        notes_pruned = await asyncio.to_thread(_prune_received_notes)
        logger.info("Pruned %d received voice recording(s) older than a day.", notes_pruned)
    except Exception as e:
        logger.error("Failed to prune received_notes: %s", e)
        notify_error("Received-notes cleanup failed", e)


async def send_evening_message() -> None:
    try:
        text, day = await asyncio.to_thread(compose_evening_message)
        if settings.daily_commentary:
            path = await asyncio.to_thread(save_daily_commentary, text, day)
            logger.info("Daily commentary saved to %s.", path.name)
        await asyncio.to_thread(deliver, "Evening", text, EVENING_PRIORITY)
        logger.info("Evening message sent.")
    except Exception as e:
        logger.error("Evening message failed: %s", e)
        notify_error("Evening message failed", e)
    await sweep_threads()
