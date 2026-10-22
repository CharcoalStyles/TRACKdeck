"""
agent/date_guard.py
-------------------
Deterministic cross-check between what the user said ("tonight", "tomorrow")
and the date the tool model put in a calendar/reminder call. The small model
sometimes copies a date out of recalled context instead of resolving the
relative word against the date it was given; when the user's message names
exactly one relative day and no explicit date, the call's date is corrected.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

# tool -> argument names holding a date/time. The first is the start; the
# rest shift by the same number of days as the start did.
DATE_ARGS: dict[str, tuple[str, ...]] = {
    "add_calendar_event": ("start", "end"),
    "update_calendar_event": ("start", "end"),
    "move_calendar_event": ("new_start",),
    "set_reminder": ("when",),
    "set_timer": ("when",),
}

_TODAY_RE = re.compile(r"\b(today|tonight|this (?:morning|afternoon|evening|arvo))\b", re.IGNORECASE)
_TOMORROW_RE = re.compile(r"\btomorrow\b", re.IGNORECASE)
_EXPLICIT_RE = re.compile(
    r"\bday after\b|\bnext (?:week|month)\b"
    r"|\b(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?\b"
    r"|\b(?:january|february|march|april|june|july|august|september|october|november|december)\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)\.?\s*\d|\d\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})")


def expected_date(user_message: str, today: date) -> date | None:
    """The one date the message unambiguously means, else None."""
    if _EXPLICIT_RE.search(user_message):
        return None
    is_today, is_tomorrow = bool(_TODAY_RE.search(user_message)), bool(_TOMORROW_RE.search(user_message))
    if is_today == is_tomorrow:
        return None
    return today if is_today else today + timedelta(days=1)


def _shift(value: str, days: int) -> str:
    m = _ISO_DATE_RE.match(value)
    if not m:
        return value
    shifted = date.fromisoformat(m.group(1)) + timedelta(days=days)
    return shifted.isoformat() + value[m.end(1):]


def fix_relative_dates(user_message: str, calls: list[dict], now: datetime) -> list[dict] | None:
    """Corrected copy of `calls`, or None when nothing needed changing."""
    want = expected_date(user_message or "", now.date())
    if want is None:
        return None
    out, changed = [], False
    for call in calls:
        arg_names = DATE_ARGS.get(call.get("name"))
        args = dict(call.get("args") or {})
        m = _ISO_DATE_RE.match(str(args.get(arg_names[0], ""))) if arg_names else None
        if m and date.fromisoformat(m.group(1)) != want:
            days = (want - date.fromisoformat(m.group(1))).days
            for name in arg_names:
                if isinstance(args.get(name), str):
                    args[name] = _shift(args[name], days)
            call = {**call, "args": args}
            changed = True
        out.append(call)
    return out if changed else None


SEARCH_QUERY_TOOLS = {"search_web", "search_news", "search_images", "search_videos"}
_MONTH = (
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)"
)
_QUERY_DATE_RE = re.compile(
    rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b"
    rf"|\b(?:(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?,?\s+)?"
    rf"(?:\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\.?(?:,?\s+\d{{4}})?|{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?)\b"
    rf"|\b(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)\b|\b(?:today|tonight|tomorrow)\b",
    re.IGNORECASE,
)


def clean_search_queries(user_message: str, calls: list[dict]) -> list[dict] | None:
    """Corrected copy of `calls` where search queries no longer carry a date or
    weekday the user never wrote (the tool model invents or miscounts them, and
    the engine then favours events on that date over the named one). None when
    nothing changed."""
    said = (user_message or "").lower()
    out, changed = [], False
    for call in calls:
        query = (call.get("args") or {}).get("query")
        if call.get("name") in SEARCH_QUERY_TOOLS and isinstance(query, str):
            cleaned = _QUERY_DATE_RE.sub(lambda m: m.group(0) if m.group(0).lower() in said else "", query)
            cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
            if cleaned != query and len(cleaned.split()) >= 2:
                call = {**call, "args": {**call["args"], "query": cleaned}}
                changed = True
        out.append(call)
    return out if changed else None
