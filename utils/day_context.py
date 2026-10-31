"""
utils/day_context.py
---------------------
Plain-code context gathering for the scheduled messages and reviews
(jobs/morning.py, jobs/evening.py, jobs/reviews.py). Reads the vault's
Daily Notes / Check-ins / Reviews files, the event log, CalDAV, reminders
and the weather by date range and returns text for the writer model. No
tools, no LLM — the model only ever sees what is handed to it here.

Every renderer degrades to an empty string / "(none)" marker rather than
raising: a missing calendar must not stop an evening message.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime

from agent.settings import settings
from utils import checkin_log, daily_notes, event_log, reviews

logger = logging.getLogger(__name__)

_ICS_FORMAT = "%Y%m%dT%H%M%SZ"
_ANSWER_CHARS = 300


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _day_start(day: date) -> datetime:
    return datetime.combine(day, dtime.min, tzinfo=settings.zoneinfo())


def interactions_for(day: date) -> list[dict]:
    start = _day_start(day)
    return event_log.events_between(start, start + timedelta(days=1), kind="interaction")


def render_day(day: date, *, max_chars: int = 3000) -> str:
    """One local day as text: captures (with done state), check-in answers,
    and what was asked of the assistant. Empty string if nothing happened."""
    date_str = day.isoformat()
    sections: list[str] = []

    captures = daily_notes.read_captures(date_str)
    if captures:
        lines = [f"- [{'x' if c['done'] else ' '}] {c['time']} {c['text']}" for c in captures]
        sections.append("Captures:\n" + "\n".join(lines))

    answered = [e for e in checkin_log.read_entries(date_str) if e["answer"]]
    if answered:
        lines = [
            f'- {e["time"]} "{_clip(e["prompt"], 120)}" -> {_clip(e["answer"], _ANSWER_CHARS)}'
            for e in answered
        ]
        sections.append("Check-ins answered:\n" + "\n".join(lines))

    asked = []
    for e in interactions_for(day):
        if e.get("fallback_capture"):
            continue  # already listed under Captures
        text = _clip(e.get("user_text", ""), 160)
        if not text:
            continue
        line = f"- {str(e.get('ts', ''))[11:16]} {text}"
        tools = [t.get("name") for t in e.get("tools", []) if t.get("name")]
        if tools:
            line += f" [tools: {', '.join(tools)}]"
        asked.append(line)
    if asked:
        sections.append("Asked the assistant:\n" + "\n".join(asked))

    text = "\n\n".join(sections)
    return text if len(text) <= max_chars else text[: max_chars - 3].rstrip() + "..."


def render_days(first: date, last: date, *, per_day_chars: int = 1200, total_chars: int = 12000) -> str:
    """Days first..last inclusive, oldest first, each headed by its date.
    Days with nothing recorded are omitted. The total is capped by clipping
    the tail, so a long range keeps its beginning."""
    blocks = []
    day = first
    while day <= last:
        body = render_day(day, max_chars=per_day_chars)
        if body:
            blocks.append(f"[{day.strftime('%A %d %B %Y')}]\n{body}")
        day += timedelta(days=1)
    text = "\n\n".join(blocks)
    return text if len(text) <= total_chars else text[: total_chars - 3].rstrip() + "..."


def open_captures(today: date) -> list[dict]:
    """All unticked captures up to today, oldest first — they carry over
    until done."""
    return daily_notes.open_captures(today.isoformat())


def render_open_captures(today: date) -> str:
    lines = []
    for c in open_captures(today):
        when = c["time"] if c["date"] == today.isoformat() else (
            f"{date.fromisoformat(c['date']).strftime('%a %d %b')} {c['time']}"
        )
        lines.append(f"- {when} {c['text']}")
    return "\n".join(lines)


def render_reviews(kind: str, keys: list[str], *, per_review_chars: int = 1500) -> str:
    blocks = []
    for key in keys:
        body = reviews.read_review_body(kind, key)
        if body:
            blocks.append(f"[{key}]\n{_clip(body, per_review_chars)}")
    return "\n\n".join(blocks)


def _parse_ics(value: str | None) -> datetime | None:
    try:
        return datetime.strptime(value or "", _ICS_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def render_calendar(first: date, last: date, *, generated: bool = True) -> str:
    """Calendar events from the start of `first` to the end of `last`, in
    local time, soonest first. Empty string when none or CalDAV is down.
    `generated=False` leaves out the sprint/break blocks a day plan creates."""
    from utils.caldav_client import get_events_in_range

    tz = settings.zoneinfo()
    start = _day_start(first)
    end = _day_start(last) + timedelta(days=1)
    try:
        result = get_events_in_range(
            start.astimezone(timezone.utc).strftime(_ICS_FORMAT),
            end.astimezone(timezone.utc).strftime(_ICS_FORMAT),
        )
    except Exception as e:
        logger.warning("Calendar fetch for context failed: %s", e)
        return ""
    if not result.get("success"):
        return ""
    rows = []
    for event in result.get("events", []):
        if event.get("generated") and not generated:
            continue
        begin = _parse_ics(event.get("start"))
        if begin is None:
            continue
        finish = _parse_ics(event.get("end"))
        begin_l = begin.astimezone(tz)
        when = f"{begin_l:%a %d %b %H:%M}"
        if finish:
            when += f"-{finish.astimezone(tz):%H:%M}"
        rows.append((begin, f"- {when} {event.get('summary') or '(untitled)'}"))
    rows.sort(key=lambda r: r[0])
    return "\n".join(line for _, line in rows)


def render_plan_window(day: date) -> str:
    """One line for a day plan's generated blocks ("sprints from 11:15 to
    17:05"), or "" when the day has none — the blocks themselves are noise
    in a spoken or written summary."""
    from utils.caldav_client import get_events_in_range

    tz = settings.zoneinfo()
    start = _day_start(day)
    try:
        result = get_events_in_range(
            start.astimezone(timezone.utc).strftime(_ICS_FORMAT),
            (start + timedelta(days=1)).astimezone(timezone.utc).strftime(_ICS_FORMAT),
        )
    except Exception as e:
        logger.warning("Plan window fetch failed: %s", e)
        return ""
    blocks = [e for e in result.get("events", []) if e.get("generated")] if result.get("success") else []
    spans = [(_parse_ics(e.get("start")), _parse_ics(e.get("end"))) for e in blocks]
    spans = [(b, f) for b, f in spans if b and f]
    if not spans:
        return ""
    first = min(b for b, _ in spans).astimezone(tz)
    last = max(f for _, f in spans).astimezone(tz)
    return f"A planned day of work sprints and breaks runs from {first:%H:%M} to {last:%H:%M}."


def render_reminders(first: date, last: date) -> str:
    """Pending reminders due between the start of `first` and end of `last`."""
    from utils import reminders_store

    tz = settings.zoneinfo()
    lo = _day_start(first).timestamp()
    hi = (_day_start(last) + timedelta(days=1)).timestamp()
    try:
        pending = reminders_store.list_pending()
    except Exception as e:
        logger.warning("Reminder fetch for context failed: %s", e)
        return ""
    rows = [
        f"- {datetime.fromtimestamp(r['due_at'], tz):%a %d %b %H:%M} {r['message']}"
        for r in pending
        if lo <= r["due_at"] < hi
    ]
    return "\n".join(rows)


def render_forecast(first: date, last: date) -> str:
    """Daily forecast lines for first..last, from the weather tool's own
    data function. Empty string when weather is switched off or fails."""
    if not settings.weather_enabled:
        return ""
    from agent.tools.weather import get_range_forecast

    try:
        raw = get_range_forecast.invoke({"start": first.isoformat(), "end": last.isoformat()})
        days = json.loads(raw)
    except Exception as e:
        logger.warning("Forecast fetch for context failed: %s", e)
        return ""
    lines = []
    for d in days:
        try:
            when = date.fromisoformat(d["time"]).strftime("%A %d %B")
            lines.append(
                f"- {when}: {d['temperature_2m_min']}-{d['temperature_2m_max']} C, "
                f"rain chance up to {d['precipitation_probability_max']}%"
            )
        except (KeyError, ValueError, TypeError):
            continue
    return "\n".join(lines)
