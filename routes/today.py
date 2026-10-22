"""
routes/today.py
-----------------
GET /today: what the home page's Today pane shows — today's calendar events,
reminders still pending for today, and today's answered check-ins. Plain
reads; each source degrades to an empty list rather than failing the page.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import auth
from agent.settings import settings
from utils import checkin_log, reminders_store
from utils.caldav_client import get_events_in_range
from utils.day_context import _ICS_FORMAT, _parse_ics

logger = logging.getLogger(__name__)
router = APIRouter()


class TodayEvent(BaseModel):
    uid: Optional[str] = None
    title: str
    start: str
    end: Optional[str] = None
    location: str = ""
    description: str = ""
    repeats: bool = False
    generated: bool = False


class TodayReminder(BaseModel):
    id: str
    message: str
    time: str


class TodayCheckin(BaseModel):
    time: str
    prompt: str
    answer: str


class TodayResponse(BaseModel):
    date: str
    weekday: str
    is_today: bool
    events: list[TodayEvent]
    reminders: list[TodayReminder]
    checkins: list[TodayCheckin]


def _events(day_start: datetime, day_end: datetime) -> list[dict]:
    tz = settings.zoneinfo()
    try:
        result = get_events_in_range(
            day_start.astimezone(timezone.utc).strftime(_ICS_FORMAT),
            day_end.astimezone(timezone.utc).strftime(_ICS_FORMAT),
        )
    except Exception as e:
        logger.warning("Today: calendar fetch failed: %s", e)
        return []
    rows = []
    for event in result.get("events", []) if result.get("success") else []:
        begin = _parse_ics(event.get("start"))
        if begin is None:
            continue
        finish = _parse_ics(event.get("end"))
        rows.append((begin, {
            "uid": event.get("uid"),
            "title": event.get("summary") or "(untitled)",
            "location": event.get("location") or "",
            "description": event.get("description") or "",
            "repeats": bool(event.get("rrule")),
            "generated": bool(event.get("generated")),
            "start": f"{begin.astimezone(tz):%H:%M}",
            "end": f"{finish.astimezone(tz):%H:%M}" if finish else None,
        }))
    return [row for _, row in sorted(rows, key=lambda r: r[0])]


def _reminders(day_start: datetime, day_end: datetime) -> list[dict]:
    tz = settings.zoneinfo()
    try:
        pending = reminders_store.list_pending()
    except Exception as e:
        logger.warning("Today: reminder fetch failed: %s", e)
        return []
    lo, hi = day_start.timestamp(), day_end.timestamp()
    return [
        {"id": r["id"], "message": r["message"], "time": f"{datetime.fromtimestamp(r['due_at'], tz):%H:%M}"}
        for r in pending
        if lo <= r["due_at"] < hi
    ]


@router.get("/today", response_model=TodayResponse)
async def today(
    _: Annotated[None, Depends(auth.require_session_or_token)],
    date: Annotated[Optional[str], Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
):
    """One day's view — today by default, or any `date` (YYYY-MM-DD)."""
    tz = settings.zoneinfo()
    now = datetime.now(tz)
    try:
        day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=tz) if date else now
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be a real YYYY-MM-DD date")
    day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = (day_start.replace(tzinfo=None) + timedelta(days=1)).replace(tzinfo=tz)
    date_str = f"{day:%Y-%m-%d}"
    events, reminders, entries = await asyncio.gather(
        asyncio.to_thread(_events, day_start, day_end),
        asyncio.to_thread(_reminders, day_start, day_end),
        asyncio.to_thread(checkin_log.read_entries, date_str),
    )
    return {
        "date": date_str,
        "weekday": f"{day:%A}",
        "is_today": date_str == f"{now:%Y-%m-%d}",
        "events": events,
        "reminders": reminders,
        "checkins": [
            {"time": e["time"], "prompt": e["prompt"], "answer": e["answer"]}
            for e in entries
            if e["answer"]
        ],
    }
