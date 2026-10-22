"""
routes/calendar_events.py
---------------------------
Hand edits to the calendar from the Today view: add, change or delete an
event. Each one is logged to the event log with the same shape the assistant's
own calendar writes use, plus source "dashboard", so a later review (or a
training label) can tell a user fixing what the assistant did from the
assistant's own work:

  create -> "artifact" event, op "create"
  change -> "edit" event, action "update", fields / before / after
  delete -> "edit" event, action "delete", before = the event as it was

`origin_interaction_id` is the interaction that first created the event
(origin_of), or null when the event was made outside the assistant. start and
end in before/after are iCalendar UTC strings, like the assistant's events.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
from utils import event_log
from utils.caldav_client import create_or_update_event, delete_event, get_event
from utils.datetime import add_time_to_UTC_text, text_to_utc

router = APIRouter()
_UID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]*$")
_FIELDS = ("title", "start", "end", "location", "description")


class CalendarEventCreate(BaseModel):
    title: str
    start: str  # local "YYYY-MM-DD HH:MM"
    end: Optional[str] = None  # defaults to one hour after start
    location: Optional[str] = None
    description: Optional[str] = None


class CalendarEventEdit(BaseModel):
    title: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None


class CalendarEventResult(BaseModel):
    uid: str


def _check_uid(uid: str) -> str:
    if not _UID_RE.match(uid):
        raise HTTPException(status_code=422, detail="invalid event id")
    return uid


def _utc(value: str) -> str:
    try:
        return text_to_utc(value)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail=f"couldn't understand the time '{value}'")


def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%dT%H%M%SZ")


def _snapshot(event: dict) -> dict:
    return {
        "title": event.get("summary") or "",
        "start": event.get("start"),
        "end": event.get("end"),
        "location": event.get("location") or "",
        "description": event.get("description") or "",
    }


def _save(uid: str, snap: dict) -> None:
    result = create_or_update_event(
        uid=uid, summary=snap["title"], start_iso=snap["start"], end_iso=snap["end"],
        description=snap["description"], location=snap["location"], rrule=None,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=str(result.get("error") or "could not save the event"))


@router.post("/calendar-events", response_model=CalendarEventResult)
async def add_event(body: CalendarEventCreate, _: Annotated[None, Depends(auth.require_session_or_token)]):
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="title cannot be empty")
    start = _utc(body.start)
    end = _utc(body.end) if body.end else add_time_to_UTC_text(start, timedelta(hours=1))
    if end <= start:
        raise HTTPException(status_code=422, detail="the end must be after the start")
    uid = str(uuid.uuid4())
    snap = {
        "title": title, "start": start, "end": end,
        "location": (body.location or "").strip(), "description": (body.description or "").strip(),
    }
    await asyncio.to_thread(_save, uid, snap)
    event_log.log_event(
        "artifact", type="calendar_event", id=uid, op="create", title=title, start=start, end=end,
        source="dashboard", origin_interaction_id=None,
    )
    return {"uid": uid}


@router.patch("/calendar-events/{uid}", response_model=CalendarEventResult)
async def edit_event(
    uid: str, body: CalendarEventEdit, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    _check_uid(uid)
    found = await asyncio.to_thread(get_event, uid)
    if not found.get("success") or not found["event"].get("uid"):
        raise HTTPException(status_code=404, detail="event not found")
    event = found["event"]
    if event.get("rrule"):
        raise HTTPException(status_code=400, detail="This event repeats; change it in your calendar app.")

    before = _snapshot(event)
    after = dict(before)
    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(status_code=422, detail="title cannot be empty")
        after["title"] = body.title.strip()
    if body.start is not None:
        after["start"] = _utc(body.start)
        if body.end is None:
            span = _parse_utc(before["end"]) - _parse_utc(before["start"])
            after["end"] = (_parse_utc(after["start"]) + span).strftime("%Y%m%dT%H%M%SZ")
    if body.end is not None:
        after["end"] = _utc(body.end)
    if body.location is not None:
        after["location"] = body.location.strip()
    if body.description is not None:
        after["description"] = body.description.strip()
    if after["end"] <= after["start"]:
        raise HTTPException(status_code=422, detail="the end must be after the start")

    changed = [f for f in _FIELDS if before[f] != after[f]]
    if changed:
        await asyncio.to_thread(_save, uid, after)
        event_log.log_event(
            "edit", artifact_type="calendar_event", action="update", id=uid, fields=changed,
            before={f: before[f] for f in changed}, after={f: after[f] for f in changed},
            source="dashboard", origin_interaction_id=event_log.origin_of("calendar_event", uid),
        )
    return {"uid": uid}


@router.delete("/calendar-events/{uid}", response_model=CalendarEventResult)
async def remove_event(uid: str, _: Annotated[None, Depends(auth.require_session_or_token)]):
    _check_uid(uid)
    found = await asyncio.to_thread(get_event, uid)
    if not found.get("success") or not found["event"].get("uid"):
        raise HTTPException(status_code=404, detail="event not found")
    before = _snapshot(found["event"])
    before["repeats"] = bool(found["event"].get("rrule"))
    result = await asyncio.to_thread(delete_event, uid)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=str(result.get("error") or result.get("message")))
    event_log.log_event(
        "edit", artifact_type="calendar_event", action="delete", id=uid, fields=list(_FIELDS),
        before=before, after=None, source="dashboard",
        origin_interaction_id=event_log.origin_of("calendar_event", uid),
    )
    return {"uid": uid}
