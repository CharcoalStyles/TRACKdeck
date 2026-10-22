"""
routes/captures.py
--------------------
Dashboard access to the Daily Notes capture list: read the last few days,
add a capture by hand, edit its text or tick it off, and convert it into a
reminder, a calendar event or a planning task. Every change is logged to the
event log (kinds "capture", "edit", "convert") with the interaction that first
created the capture, so a review can trace a conversion back to what was said.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import auth
from agent.settings import settings
from agent.tools.jot import save_capture
from agent.tools.planning import save_planning_tasks
from utils import daily_notes, event_log

router = APIRouter()
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Capture(BaseModel):
    id: str
    time: str
    text: str
    done: bool


class CaptureDay(BaseModel):
    date: str
    captures: list[Capture]


class CapturesResponse(BaseModel):
    days: list[CaptureDay]
    unticked: int


class CaptureCreate(BaseModel):
    text: str


class CaptureEdit(BaseModel):
    text: Optional[str] = None
    done: Optional[bool] = None


class CaptureConvert(BaseModel):
    to: Literal["reminder", "event", "task"]
    # Local date/time for a reminder or event ("2026-10-23 15:00"); local
    # date ("2026-10-23") for a task, defaulting to the capture's own day.
    when: Optional[str] = None
    minutes: Optional[int] = None


def _check_date(date_str: str) -> str:
    if not _DATE_RE.match(date_str):
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    return date_str


def _today() -> datetime:
    return datetime.now(settings.zoneinfo())


@router.get("/captures", response_model=CapturesResponse)
async def list_captures(
    _: Annotated[None, Depends(auth.require_session_or_token)],
    days: Annotated[int, Query(ge=1, le=60)] = 7,
):
    """Captures for today and the previous days-1 days, newest day first;
    days without captures are left out (today is always present)."""
    today = _today().date()
    out, unticked = [], 0
    for offset in range(days):
        date_str = (today - timedelta(days=offset)).isoformat()
        captures = await asyncio.to_thread(daily_notes.read_captures, date_str)
        unticked += sum(1 for c in captures if not c["done"])
        if captures or offset == 0:
            out.append({"date": date_str, "captures": captures})
    return {"days": out, "unticked": unticked}


@router.post("/captures", response_model=Capture)
async def add_capture(body: CaptureCreate, _: Annotated[None, Depends(auth.require_session_or_token)]):
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text cannot be empty")
    capture_id = await asyncio.to_thread(save_capture, body.text, "dashboard", "form")
    now = _today()
    return {"id": capture_id, "time": f"{now:%H:%M}", "text": " ".join(body.text.split()), "done": False}


@router.patch("/captures/{date_str}/{capture_id}", response_model=Capture)
async def edit_capture(
    date_str: str,
    capture_id: str,
    body: CaptureEdit,
    _: Annotated[None, Depends(auth.require_session_or_token)],
):
    _check_date(date_str)
    before = next((c for c in daily_notes.read_captures(date_str) if c["id"] == capture_id), None)
    try:
        updated = await asyncio.to_thread(
            daily_notes.update_capture, date_str, capture_id, text=body.text, done=body.done
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="text cannot be empty")
    if updated is None or before is None:
        raise HTTPException(status_code=404, detail="capture not found")
    changed = [f for f in ("text", "done") if updated[f] != before[f]]
    if changed:
        event_log.log_event(
            "edit", artifact_type="capture", capture_id=capture_id, date=date_str,
            fields=changed, before={f: before[f] for f in changed},
            after={f: updated[f] for f in changed}, source="dashboard",
            origin_interaction_id=event_log.origin_of("capture", capture_id),
        )
    return updated


@router.post("/captures/{date_str}/{capture_id}/convert", response_model=Capture)
async def convert_capture(
    date_str: str,
    capture_id: str,
    body: CaptureConvert,
    _: Annotated[None, Depends(auth.require_session_or_token)],
):
    """Turn a capture into a reminder, a calendar event or a planning task,
    then tick it off. Nothing is created if the time is rejected."""
    _check_date(date_str)
    capture = next((c for c in daily_notes.read_captures(date_str) if c["id"] == capture_id), None)
    if capture is None:
        raise HTTPException(status_code=404, detail="capture not found")
    text = capture["text"]
    when = (body.when or "").strip()

    if body.to == "task":
        task_date = when or date_str
        _check_date(task_date)
        await asyncio.to_thread(save_planning_tasks, task_date, [(text, body.minutes or 30)])
    else:
        if not when:
            raise HTTPException(status_code=422, detail="a date and time are required")
        if body.to == "reminder":
            from agent.tools.alerts import _create_reminder

            result = await asyncio.to_thread(_create_reminder, text, when)
            ok = result.startswith("Got it")
        else:
            from agent.tools.calendar import add_calendar_event

            result = await asyncio.to_thread(add_calendar_event.func, title=text, start=when)
            ok = result.startswith("Event added successfully")
        if not ok:
            raise HTTPException(status_code=400, detail=result)

    updated = await asyncio.to_thread(daily_notes.update_capture, date_str, capture_id, done=True)
    event_log.log_event(
        "convert", artifact_type="capture", capture_id=capture_id, date=date_str, to=body.to,
        when=when or None, minutes=body.minutes, source="dashboard",
        origin_interaction_id=event_log.origin_of("capture", capture_id),
    )
    return updated or {**capture, "done": True}
