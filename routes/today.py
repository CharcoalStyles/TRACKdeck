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

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import auth
from agent.settings import settings
from utils import checkin_log, reminders_store
from utils.caldav_client import get_events_in_range
from utils.day_context import _ICS_FORMAT, _parse_ics

logger = logging.getLogger(__name__)
router = APIRouter()


class TodayEvent(BaseModel):
    title: str
    start: str
    end: Optional[str] = None


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
            "title": event.get("summary") or "(untitled)",
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
async def today(_: Annotated[None, Depends(auth.require_session_or_token)]):
    now = datetime.now(settings.zoneinfo())
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    date_str = f"{now:%Y-%m-%d}"
    events, reminders, entries = await asyncio.gather(
        asyncio.to_thread(_events, day_start, day_end),
        asyncio.to_thread(_reminders, day_start, day_end),
        asyncio.to_thread(checkin_log.read_entries, date_str),
    )
    return {
        "date": date_str,
        "weekday": f"{now:%A}",
        "events": events,
        "reminders": reminders,
        "checkins": [
            {"time": e["time"], "prompt": e["prompt"], "answer": e["answer"]}
            for e in entries
            if e["answer"]
        ],
    }
