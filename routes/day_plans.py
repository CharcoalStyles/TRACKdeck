"""
routes/day_plans.py
----------------------
Backend for the Day Planning page's scheduled-plan features: saving a
plan's tasks/fixed-blocks directly (no agent turn — see
agent/tools/planning.py's save_planning_tasks/save_fixed_blocks),
tracking when it should actually generate (utils/day_plans_store.py),
and triggering that generation immediately or ~15 minutes ahead of its
start time via jobs/day_plan_trigger.py.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
from agent.settings import settings
from agent.tools.planning import (
    FIXED_BLOCKS_SECTION,
    TASKS_SECTION,
    save_fixed_blocks,
    save_planning_tasks,
)
from jobs.day_plan_trigger import cancel_job, schedule_or_run, trigger_at_for
from utils import day_plans_store, vault
from utils.planning import parse_fixed_blocks, parse_target_tasks

router = APIRouter()


class TaskInput(BaseModel):
    task: str
    minutes: int


class FixedBlockInput(BaseModel):
    name: str
    start_time: str
    end_time: str


class DayPlanCreate(BaseModel):
    date: str
    tasks: list[TaskInput] = []
    fixed_blocks: list[FixedBlockInput] = []
    notes: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class DayPlanResponse(BaseModel):
    id: str
    date: str
    start_time: Optional[str]
    end_time: Optional[str]
    notes: Optional[str]
    status: str
    reply: Optional[str] = None
    trigger_at: Optional[str] = None


class DayPlanDetail(DayPlanResponse):
    tasks: list[TaskInput]
    fixed_blocks: list[FixedBlockInput]


def _to_response(plan: dict) -> dict:
    response = dict(plan)
    if plan["status"] == "scheduled":
        response["trigger_at"] = trigger_at_for(plan).isoformat()
    return response


@router.get("/day-plans", response_model=list[DayPlanResponse])
async def list_day_plans(_: Annotated[None, Depends(auth.require_session_or_token)]):
    today = datetime.now(settings.zoneinfo()).strftime("%Y-%m-%d")
    plans = await asyncio.to_thread(day_plans_store.list_upcoming, today)
    return [_to_response(p) for p in plans]


@router.post("/day-plans", response_model=DayPlanResponse)
async def create_day_plan(
    body: DayPlanCreate, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    if body.tasks:
        save_planning_tasks(body.date, [(t.task, t.minutes) for t in body.tasks])
    if body.fixed_blocks:
        save_fixed_blocks(body.date, [(b.name, b.start_time, b.end_time) for b in body.fixed_blocks])

    plan_id = str(uuid.uuid4())
    await asyncio.to_thread(
        day_plans_store.create, plan_id, body.date, body.start_time, body.end_time, body.notes
    )
    plan = await asyncio.to_thread(day_plans_store.get, plan_id)
    reply = await schedule_or_run(plan_id, plan)
    plan = await asyncio.to_thread(day_plans_store.get, plan_id)
    return {**_to_response(plan), "reply": reply}


@router.get("/day-plans/{plan_id}", response_model=DayPlanDetail)
async def get_day_plan(
    plan_id: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    plan = await asyncio.to_thread(day_plans_store.get, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Day plan not found")

    note = vault.parse_note(vault.planning_note_path(plan["date"]))
    tasks = parse_target_tasks(vault.get_section(note.body, TASKS_SECTION) or "") if note else []
    fixed_blocks = (
        parse_fixed_blocks(vault.get_section(note.body, FIXED_BLOCKS_SECTION) or "") if note else []
    )
    return {
        **_to_response(plan),
        "tasks": [{"task": t, "minutes": m} for t, m in tasks],
        "fixed_blocks": [{"name": n, "start_time": s, "end_time": e} for n, s, e in fixed_blocks],
    }


@router.put("/day-plans/{plan_id}", response_model=DayPlanResponse)
async def update_day_plan(
    plan_id: str, body: DayPlanCreate, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    existing = await asyncio.to_thread(day_plans_store.get, plan_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Day plan not found")
    if existing["status"] != "scheduled":
        raise HTTPException(status_code=400, detail="Only a scheduled (not yet generated) plan can be edited")

    note = vault.get_or_create_planning_note(body.date)
    task_lines = "\n".join(
        f"- [ ] {t.task.strip()} — Est: {t.minutes} mins" for t in body.tasks
    )
    fixed_block_lines = "\n".join(
        f"- [ ] {b.name.strip()} — {b.start_time} to {b.end_time}" for b in body.fixed_blocks
    )
    note.body = vault.replace_section(note.body, TASKS_SECTION, task_lines)
    note.body = vault.replace_section(note.body, FIXED_BLOCKS_SECTION, fixed_block_lines)
    note.updated = vault.now_iso()
    vault.write_note_atomic(note.path, vault.serialize_note(note))

    cancel_job(plan_id)
    await asyncio.to_thread(
        day_plans_store.update, plan_id, body.start_time, body.end_time, body.notes
    )
    plan = await asyncio.to_thread(day_plans_store.get, plan_id)
    reply = await schedule_or_run(plan_id, plan)
    plan = await asyncio.to_thread(day_plans_store.get, plan_id)
    return {**_to_response(plan), "reply": reply}


@router.post("/day-plans/{plan_id}/cancel", response_model=DayPlanResponse)
async def cancel_day_plan(
    plan_id: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    plan = await asyncio.to_thread(day_plans_store.get, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Day plan not found")
    cancel_job(plan_id)
    await asyncio.to_thread(day_plans_store.cancel, plan_id)
    plan = await asyncio.to_thread(day_plans_store.get, plan_id)
    return _to_response(plan)
