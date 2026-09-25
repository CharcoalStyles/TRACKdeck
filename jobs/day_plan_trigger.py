"""
jobs/day_plan_trigger.py
--------------------------
Fires the one LLM turn a scheduled day plan ever needs: ~15 minutes
before its start time (utils/day_plans_store.py), build the exact
message DayPlanningPage.tsx's buildMessage already sends for a "no
tasks typed here" submission (tasks/fixed blocks were saved directly,
LLM-free, at plan-creation time via agent/tools/planning.py's
save_planning_tasks/save_fixed_blocks — see routes/day_plans.py), and
run it through run_agent exactly like jobs/checkin.py's fire_checkin
does for check-in prompts. No new tool, no prompt changes:
agent/graph.py's DAY_PLANNING_ADDENDUM's "generate from tasks already
saved" branch already covers this.

schedule_or_run is the single entry point routes/day_plans.py and
main.py's lifespan rehydration both use: if the T-15 trigger time has
already passed (the "generate now" case, or a plan whose window was
missed while the app was down), it runs fire_day_plan inline and
returns the reply synchronously; otherwise it registers a one-shot
DateTrigger job and returns None.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.date import DateTrigger

from agent.runtime import run_agent
from agent.scheduler import scheduler
from agent.settings import settings
from utils import day_plans_store
from utils.datetime import parse_local_datetime
from utils.notify import notify_error, send_gotify

logger = logging.getLogger(__name__)

TRIGGER_LEAD_TIME = timedelta(minutes=15)
NOTIFY_PRIORITY = 3  # silent/routine, same as the digest/reminder pushes this mirrors


def _job_id(plan_id: str) -> str:
    return f"day_plan:{plan_id}"


def trigger_at_for(plan: dict) -> datetime:
    start_time = plan["start_time"] or settings.wake_time
    return parse_local_datetime(f"{plan['date']} {start_time}:00") - TRIGGER_LEAD_TIME


async def fire_day_plan(plan_id: str) -> str | None:
    """Re-fetches fresh from the DB, no-ops if the row is gone,
    cancelled, or already generated (guards against a stale/duplicate
    scheduler job, same convention as jobs/reminders.py's fire_reminder
    and jobs/checkin.py's fire_checkin)."""
    try:
        plan = await asyncio.to_thread(day_plans_store.get, plan_id)
        if plan is None or plan["status"] != "scheduled":
            return None

        notes_block = f"\n\nGuidance on how to arrange these: {plan['notes']}" if plan["notes"] else ""
        window_block = (
            f"\n\nSchedule window: {plan['start_time']} to {plan['end_time']}"
            if plan["start_time"] and plan["end_time"]
            else ""
        )
        text = (
            f"Generate my schedule for {plan['date']} from the tasks already saved in its "
            f"planning note.{notes_block}{window_block}"
        )
        result = await run_agent(text, thread_id=f"day_planning:{plan['date']}", mode="day_planning")
        await asyncio.to_thread(day_plans_store.mark_generated, plan_id, result.reply)
        await asyncio.to_thread(
            send_gotify, f"Day plan ready — {plan['date']}", result.reply, NOTIFY_PRIORITY
        )
        return result.reply
    except Exception as e:
        logger.error("Day plan %s failed to generate: %s", plan_id, e)
        notify_error(f"Day plan failed to generate ({plan_id})", e)
        return None


async def schedule_or_run(plan_id: str, plan: dict) -> str | None:
    """Schedules plan_id's T-15 trigger, or — if that time is already in
    the past — runs it immediately and returns the reply. Used by
    routes/day_plans.py on create/edit and by main.py's lifespan
    rehydration."""
    trigger_at = trigger_at_for(plan)
    if trigger_at <= datetime.now(settings.zoneinfo()):
        return await fire_day_plan(plan_id)

    scheduler.add_job(
        fire_day_plan,
        trigger=DateTrigger(run_date=trigger_at.astimezone(timezone.utc)),
        args=[plan_id],
        id=_job_id(plan_id),
        replace_existing=True,
    )
    return None


def cancel_job(plan_id: str) -> None:
    try:
        scheduler.remove_job(_job_id(plan_id))
    except JobLookupError:
        pass
