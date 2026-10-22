"""
jobs/morning.py
----------------
The wake-up day-ahead message: today's and tomorrow's weather, today's
calendar and reminders, what's left unticked from yesterday's captures.
Pushed through Gotify at settings.wake_time. All context is gathered by
plain code (utils/day_context.py) and handed to the writer model.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from agent.settings import settings
from jobs.common import WRITING_RULES, or_none, write
from utils import day_context
from utils.notify import notify_error, send_gotify

logger = logging.getLogger(__name__)

MORNING_PRIORITY = 5

MORNING_PROMPT = """You are the user's personal assistant, writing the short good-morning \
message that sets up their day. Today is {today}. Keep it to a few short sentences or a \
very short list: lead with what is on today, then anything worth knowing about the weather \
(today and tomorrow), then loose ends left from yesterday. If the day is empty, say so \
briefly.

{rules}

Today's calendar:
{calendar}

Today's reminders:
{reminders}

Tomorrow's calendar (a heads-up only):
{tomorrow}

Forecast (today and tomorrow):
{forecast}

Captures left unticked yesterday:
{leftovers}
"""


def build_prompt(today: date) -> str:
    tomorrow = today + timedelta(days=1)
    return MORNING_PROMPT.format(
        today=today.strftime("%A %d %B %Y"),
        rules=WRITING_RULES,
        calendar=or_none(day_context.render_calendar(today, today)),
        reminders=or_none(day_context.render_reminders(today, today)),
        tomorrow=or_none(day_context.render_calendar(tomorrow, tomorrow)),
        forecast=or_none(day_context.render_forecast(today, tomorrow)),
        leftovers=or_none(day_context.render_leftover_captures(today - timedelta(days=1))),
    )


def compose_morning_message(today: date | None = None) -> str:
    """Blocking (CalDAV, weather, LLM) — run via asyncio.to_thread."""
    today = today or datetime.now(settings.zoneinfo()).date()
    return write(build_prompt(today))


async def send_morning_message() -> None:
    try:
        text = await asyncio.to_thread(compose_morning_message)
        await asyncio.to_thread(send_gotify, "Good morning", text, MORNING_PRIORITY)
        logger.info("Morning message sent.")
    except Exception as e:
        logger.error("Morning message failed: %s", e)
        notify_error("Morning message failed", e)
