"""
jobs/morning.py
----------------
The wake-up day-ahead message: today's and tomorrow's weather, today's
calendar and reminders, every capture still unticked (they carry over until done).
Pushed through Gotify (and emailed when email_to is set) at settings.morning_time. All context is gathered by
plain code (utils/day_context.py) and handed to the writer model.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from agent.settings import settings
from jobs.common import WRITING_RULES, deliver, or_none, write
from jobs import podcast
from utils import morning_context
from utils.notify import notify_error

logger = logging.getLogger(__name__)

MORNING_PRIORITY = 5

MORNING_PROMPT = """You are the user's personal assistant, writing the short good-morning \
message that sets up their day. Today is {today}. Keep it to a few short sentences or a \
very short list: lead with what is on today, then anything worth knowing about the weather \
(today and tomorrow), and nothing else about captures: the open captures are appended after your message. If the day is empty, say so \
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
"""


def build_prompt(today: date, ctx: morning_context.MorningContext | None = None) -> str:
    ctx = ctx or morning_context.get_context(today)
    return MORNING_PROMPT.format(
        today=today.strftime("%A %d %B %Y"),
        rules=WRITING_RULES,
        calendar=or_none(ctx.calendar),
        reminders=or_none(ctx.reminders),
        tomorrow=or_none(ctx.tomorrow),
        forecast=or_none(ctx.forecast),
    )


def compose_morning_parts(today: date | None = None) -> dict:
    """Blocking (CalDAV, weather, LLM) — run via asyncio.to_thread. The same
    snapshot the podcast used (utils/morning_context.py), so the two agree.
    `text` is the writer's message; the rest is appended by code."""
    today = today or datetime.now(settings.zoneinfo()).date()
    ctx = morning_context.get_context(today)
    link = podcast.podcast_link() if podcast.episode_exists(today) else ""
    return {
        "text": write(build_prompt(today, ctx)),
        "open": ctx.open_captures,
        "headlines": morning_context.render_headlines(ctx.headlines),
        "link": link,
    }


def _assemble(parts: dict) -> str:
    text = parts["text"].rstrip()
    if parts["open"]:
        text += f"\n\nStill open (unticked captures):\n{parts['open']}"
    if parts["headlines"]:
        text += f"\n\nCanberra headlines:\n{parts['headlines']}"
    if parts["link"]:
        text += f"\n\nListen to this morning's podcast: {parts['link']}"
    return text


def compose_morning_message(today: date | None = None) -> str:
    """The full morning message (the email): the writer's text, then, listed
    by code, every open capture, the Canberra headlines with links, and the
    podcast link when today's episode exists."""
    return _assemble(compose_morning_parts(today))


async def send_morning_message() -> None:
    try:
        parts = await asyncio.to_thread(compose_morning_parts)
        text = _assemble(parts)
        # The push is the message and the open captures; headlines are for the
        # email. Tapping the push opens the podcast when there is one.
        push = _assemble({**parts, "headlines": "", "link": ""})
        await asyncio.to_thread(
            lambda: deliver("Good morning", text, MORNING_PRIORITY, push_text=push, click_url=parts["link"] or None)
        )
        logger.info("Morning message sent.")
    except Exception as e:
        logger.error("Morning message failed: %s", e)
        notify_error("Morning message failed", e)
