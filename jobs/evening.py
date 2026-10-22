"""
jobs/evening.py
----------------
The evening message, pushed through Gotify at settings.evening_time:
a short wrap-up of the day (captures, check-ins, what was asked), what
is left unticked, and a peek at tomorrow. With settings.daily_commentary
on, the same text is saved to Reviews/Daily/YYYY-MM-DD.md.

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
from jobs.common import WRITING_RULES, or_none, write
from utils import day_context, reviews
from utils.notify import notify_error, send_gotify
from voice import UPLOAD_DIR

logger = logging.getLogger(__name__)

RECEIVED_NOTES_MAX_AGE_SECONDS = 24 * 60 * 60
EVENING_PRIORITY = 3

EVENING_PROMPT = """You are the user's personal assistant, writing a short, warm \
end-of-day message. Today is {today}. Write a few short sentences: what the day held, what \
is still open, and a one-line heads-up about tomorrow. If the day was quiet, say so in a \
sentence. Mention a theme only if the material below really shows one.

{rules}

Today's record:
{record}

Captures still unticked:
{leftovers}

Tomorrow's calendar:
{tomorrow}

Tomorrow's reminders:
{reminders}
"""


def build_prompt(today: date) -> str:
    tomorrow = today + timedelta(days=1)
    return EVENING_PROMPT.format(
        today=today.strftime("%A %d %B %Y"),
        rules=WRITING_RULES,
        record=or_none(day_context.render_day(today, with_replies=True)),
        leftovers=or_none(day_context.render_leftover_captures(today)),
        tomorrow=or_none(day_context.render_calendar(tomorrow, tomorrow)),
        reminders=or_none(day_context.render_reminders(tomorrow, tomorrow)),
    )


def compose_evening_message(today: date | None = None) -> tuple[str, date]:
    """Blocking — run via asyncio.to_thread. Returns the text and the day it covers."""
    today = today or datetime.now(settings.zoneinfo()).date()
    return write(build_prompt(today)), today


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
        await asyncio.to_thread(send_gotify, "Evening", text, EVENING_PRIORITY)
        logger.info("Evening message sent.")
        if settings.daily_commentary:
            path = await asyncio.to_thread(save_daily_commentary, text, day)
            logger.info("Daily commentary saved to %s.", path.name)
    except Exception as e:
        logger.error("Evening message failed: %s", e)
        notify_error("Evening message failed", e)
    await sweep_threads()
