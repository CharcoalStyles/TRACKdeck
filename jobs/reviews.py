"""
jobs/reviews.py
----------------
Sunday weekly review and the monthly review of the previous month. Both
are written by the writer model from files read by date range
(utils/day_context.py), saved to the vault under Reviews/Weekly/ and
Reviews/Monthly/, and announced through Gotify.

The weekly review covers the ISO week containing the run date; the monthly
review covers the previous calendar month and leans on that month's weekly
reviews (and daily commentary files, when the trial setting is on) rather
than re-reading every day in full.
"""
from __future__ import annotations

import asyncio
import calendar
import logging
from datetime import date, datetime, timedelta

from agent.settings import settings
from jobs.common import WRITING_RULES, or_none, write
from utils import day_context, reviews
from utils.notify import notify_error, send_gotify

logger = logging.getLogger(__name__)

REVIEW_PRIORITY = 3
PUSH_CHARS = 900

WEEKLY_PROMPT = """You are the user's personal assistant, writing their weekly review for \
{label}. Write three short paragraphs: what the week held, what carried over or stayed \
open, and one or two things worth deciding for next week. A pattern counts only if the \
material shows it on 3 or more separate days. If the week was quiet, say so briefly.

{rules}

The week, day by day (days with nothing recorded are left out):
{days}

Calendar for the week:
{calendar}

Last week's review (for continuity only; do not repeat it):
{previous}
"""

MONTHLY_PROMPT = """You are the user's personal assistant, writing their monthly review for \
{label}. Write three or four short paragraphs: the shape of the month, what got done, what \
kept slipping or staying open, and a suggestion or two for the month ahead. Only call \
something a trend if it appears in at least two separate weeks below.

{rules}

Weekly reviews from the month:
{weeklies}

Daily commentary from the month:
{dailies}

Day-by-day record (heavily condensed; days with nothing recorded are left out):
{days}
"""


def week_bounds(on: date) -> tuple[date, date]:
    monday = on - timedelta(days=on.weekday())
    return monday, monday + timedelta(days=6)


def previous_month_bounds(on: date) -> tuple[date, date]:
    last = on.replace(day=1) - timedelta(days=1)
    return last.replace(day=1), last


def build_weekly_prompt(on: date) -> tuple[str, str]:
    monday, sunday = week_bounds(on)
    key = reviews.period_key("weekly", on)
    previous = reviews.period_key("weekly", monday - timedelta(days=7))
    prompt = WEEKLY_PROMPT.format(
        label=f"{key} ({monday.strftime('%d %B')} to {sunday.strftime('%d %B %Y')})",
        rules=WRITING_RULES,
        days=or_none(day_context.render_days(monday, sunday)),
        calendar=or_none(day_context.render_calendar(monday, sunday)),
        previous=or_none(day_context.render_reviews("weekly", [previous])),
    )
    return key, prompt


def build_monthly_prompt(on: date) -> tuple[str, str]:
    first, last = previous_month_bounds(on)
    key = reviews.period_key("monthly", first)
    week_keys = []
    day = first
    while day <= last:
        wk = reviews.period_key("weekly", day)
        if wk not in week_keys:
            week_keys.append(wk)
        day += timedelta(days=1)
    daily_keys = [reviews.period_key("daily", first + timedelta(days=i)) for i in range(last.day)]
    prompt = MONTHLY_PROMPT.format(
        label=f"{first.strftime('%B %Y')}",
        rules=WRITING_RULES,
        weeklies=or_none(day_context.render_reviews("weekly", week_keys, per_review_chars=2000)),
        dailies=or_none(day_context.render_reviews("daily", daily_keys, per_review_chars=400)),
        days=or_none(day_context.render_days(first, last, per_day_chars=300, total_chars=6000)),
    )
    return key, prompt


def compose_weekly_review(on: date | None = None):
    """Blocking — run via asyncio.to_thread. Writes the file; returns (path, text)."""
    on = on or datetime.now(settings.zoneinfo()).date()
    key, prompt = build_weekly_prompt(on)
    text = write(prompt, temperature=0.6)
    monday, sunday = week_bounds(on)
    title = f"Weekly review — {key} ({monday.strftime('%d %b')} to {sunday.strftime('%d %b %Y')})"
    return reviews.write_review("weekly", key, title, text), text


def compose_monthly_review(on: date | None = None):
    """Blocking — run via asyncio.to_thread. Writes the file; returns (path, text)."""
    on = on or datetime.now(settings.zoneinfo()).date()
    key, prompt = build_monthly_prompt(on)
    text = write(prompt, temperature=0.6)
    first, _ = previous_month_bounds(on)
    title = f"Monthly review — {calendar.month_name[first.month]} {first.year}"
    return reviews.write_review("monthly", key, title, text), text


def _push_text(text: str) -> str:
    return text if len(text) <= PUSH_CHARS else text[: PUSH_CHARS - 3].rstrip() + "..."


async def send_weekly_review() -> None:
    try:
        path, text = await asyncio.to_thread(compose_weekly_review)
        await asyncio.to_thread(send_gotify, "Weekly review", _push_text(text), REVIEW_PRIORITY)
        logger.info("Weekly review written to %s.", path.name)
    except Exception as e:
        logger.error("Weekly review failed: %s", e)
        notify_error("Weekly review failed", e)


async def send_monthly_review() -> None:
    try:
        path, text = await asyncio.to_thread(compose_monthly_review)
        await asyncio.to_thread(send_gotify, "Monthly review", _push_text(text), REVIEW_PRIORITY)
        logger.info("Monthly review written to %s.", path.name)
    except Exception as e:
        logger.error("Monthly review failed: %s", e)
        notify_error("Monthly review failed", e)
