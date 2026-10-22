"""
jobs/evening.py
----------------
The evening message, pushed through Gotify (and emailed when email_to is set)
at settings.evening_time. Deliberately NOT a recap of the day: the assistant
cannot know what the user actually did, so it would invent. The message is
assembled by code from what the user themselves wrote:
  1. bedtime tonight
  2. today's check-in prompts and the user's answers, verbatim
  3. a short grounded reading across the last few days' check-in answers
     (the only part the writer model produces; skipped if there are none)
  4. how many captures are still unticked, with a link to the Captures page
  5. tomorrow's calendar and reminders
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
from jobs.common import WRITING_RULES, deliver, write
from utils import checkin_log, day_context, reviews
from utils.notify import notify_error
from voice import UPLOAD_DIR

logger = logging.getLogger(__name__)

RECEIVED_NOTES_MAX_AGE_SECONDS = 24 * 60 * 60
EVENING_PRIORITY = 3
READING_DAYS = 5  # today plus the four days before it

READING_PROMPT = """You are the user's personal assistant. Below are the user's own answers to \
check-in prompts over the last few days. Write a short reading of what they say: three to five \
plain sentences.

How to write it:
- Quote the user's own words (in quotation marks) when you point at something.
- Offer observations, or ask a question or two. Do not give conclusions or advice.
- Never state why the user feels or does something; you do not know their motives.
- Call something a pattern only if it appears on two or more separate days.
- Do not summarise what the user did, and do not list their activities.
- Keep the tone plain and even: no cheerleading, no alarm.
- If there is too little to read, say so in one sentence.

{rules}

Check-in answers, oldest first:
{answers}
"""


def build_reading_prompt(answers: str) -> str:
    return READING_PROMPT.format(rules=WRITING_RULES, answers=answers)


def render_checkins_today(today: date) -> str:
    entries = checkin_log.read_entries(today.isoformat())
    if not entries:
        return "No check-ins today."
    lines = []
    for e in entries:
        lines.append(f'- {e["time"]} {e["prompt"]}')
        if e["answer"]:
            lines.extend(f"  > {line}" if line else "  >" for line in e["answer"].strip().splitlines())
        else:
            lines.append("  (no answer)")
    return "\n".join(lines)


def captures_line(today: date) -> str:
    count = len(day_context.leftover_captures(today))
    if not count:
        return "No unticked captures."
    noun = "capture" if count == 1 else "captures"
    line = f"{count} unticked {noun}."
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


def compose_reading(today: date) -> str:
    """Blocking. Empty string when there is nothing to read or the writer fails
    (the rest of the message is still worth sending)."""
    first = today - timedelta(days=READING_DAYS - 1)
    answers = day_context.render_checkin_answers(first, today)
    if not answers:
        return ""
    try:
        return write(build_reading_prompt(answers), temperature=0.5)
    except Exception as e:
        logger.warning("Evening reading skipped, writer failed: %s", e)
        return ""


def assemble_message(today: date, reading: str) -> str:
    parts = [f"Bedtime tonight: {settings.bedtime}.", f"Today's check-ins:\n{render_checkins_today(today)}"]
    if reading:
        parts.append(f"A reading across the last few days:\n{reading}")
    parts.append(captures_line(today))
    parts.append(f"Tomorrow:\n{tomorrow_section(today)}")
    return "\n\n".join(parts)


def compose_evening_message(today: date | None = None) -> tuple[str, date]:
    """Blocking — run via asyncio.to_thread. Returns the text and the day it covers."""
    today = today or datetime.now(settings.zoneinfo()).date()
    return assemble_message(today, compose_reading(today)), today


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
