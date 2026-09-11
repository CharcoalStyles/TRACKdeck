"""
routes/reflection.py
----------------------
Backend for the dashboard's evening reflection page — a normal
authenticated SPA route (unlike static/checkin.html's zero-session
magic-link design), reached via a date+session deep link the daily
digest email includes when a planning note exists for that day (see
jobs/digest.py's _build_reflection_block). Reads and writes the same
planning note agent/tools/planning.py's tools already use.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
from agent.runtime import app_state
from agent.vault_watcher import index_note_file
from utils import vault
from utils.planning import format_reflection_section, parse_reflection_section

router = APIRouter()

SCHEDULE_SECTION = "Generated Schedule & Sprints"
REFLECTION_SECTION = "End of Day Reflection"


class ReflectionResponse(BaseModel):
    date: str
    session: str
    title: str
    schedule: str | None
    energy_rating: str | None
    what_worked_well: str | None
    what_had_friction: str | None
    adjustments: str | None


class ReflectionUpdate(BaseModel):
    date: str
    session: str = "planning"
    energy_rating: str | None = None
    what_worked_well: str | None = None
    what_had_friction: str | None = None
    adjustments: str | None = None


@router.get("/reflection", response_model=ReflectionResponse)
async def get_reflection(
    date: str,
    _: Annotated[None, Depends(auth.require_session_or_token)],
    session: str = "planning",
):
    note = vault.parse_note(vault.planning_note_path(date))
    if note is None:
        raise HTTPException(status_code=404, detail=f"No planning note found for {date}.")
    reflection = parse_reflection_section(vault.get_section(note.body, REFLECTION_SECTION))
    return {
        "date": date,
        "session": session,
        "title": note.title,
        "schedule": vault.get_section(note.body, SCHEDULE_SECTION),
        **reflection,
    }


@router.post("/reflection", response_model=ReflectionResponse)
async def save_reflection(
    update: ReflectionUpdate, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    note = vault.get_or_create_planning_note(update.date)
    values = {
        "energy_rating": update.energy_rating,
        "what_worked_well": update.what_worked_well,
        "what_had_friction": update.what_had_friction,
        "adjustments": update.adjustments,
    }
    note.body = vault.replace_section(note.body, REFLECTION_SECTION, format_reflection_section(values))
    note.updated = vault.now_iso()
    vault.write_note_atomic(note.path, vault.serialize_note(note))
    if app_state.memory is not None:
        await index_note_file(app_state.memory, note.path)

    return {
        "date": update.date,
        "session": update.session,
        "title": note.title,
        "schedule": vault.get_section(note.body, SCHEDULE_SECTION),
        **values,
    }
