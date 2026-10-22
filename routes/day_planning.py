"""
routes/day_planning.py
-----------------------
Day planning is ad hoc: the Day Planning page saves a day's tasks and fixed
blocks straight into its planning note (no agent turn, see
agent/tools/planning.py's save_planning_tasks/save_fixed_blocks), then one
button runs the day_planning agent turn that builds the schedule around the
calendar. Nothing is queued or stored besides the note itself.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import auth
from agent.runtime import run_agent
from agent.tools.planning import save_fixed_blocks, save_planning_tasks

router = APIRouter()


class TaskInput(BaseModel):
    task: str
    minutes: int


class FixedBlockInput(BaseModel):
    name: str
    start_time: str
    end_time: str


class DayPlanRun(BaseModel):
    date: str
    tasks: list[TaskInput] = []
    fixed_blocks: list[FixedBlockInput] = []
    notes: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class DayPlanRunResponse(BaseModel):
    reply: str


def build_run_message(body: DayPlanRun) -> str:
    notes_block = f"\n\nGuidance on how to arrange these: {body.notes}" if body.notes else ""
    window_block = (
        f"\n\nSchedule window: {body.start_time} to {body.end_time}"
        if body.start_time and body.end_time
        else ""
    )
    return (
        f"Generate my schedule for {body.date} from the tasks already saved in its "
        f"planning note.{notes_block}{window_block}"
    )


@router.post("/day-plans/run", response_model=DayPlanRunResponse)
async def run_day_plan(body: DayPlanRun, _: Annotated[None, Depends(auth.require_session_or_token)]):
    if body.tasks:
        save_planning_tasks(body.date, [(t.task, t.minutes) for t in body.tasks])
    if body.fixed_blocks:
        save_fixed_blocks(body.date, [(b.name, b.start_time, b.end_time) for b in body.fixed_blocks])
    result = await run_agent(
        build_run_message(body), thread_id=f"day_planning:{body.date}", mode="day_planning", source="dashboard"
    )
    return {"reply": result.reply}
