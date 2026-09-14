"""
agent/tools/planning.py
------------------------
Tools for the Sunday/Saturday task-planning note: capturing tasks and
turning that list into a timeline of sprint/break blocks merged around
the day's actual calendar events.

add_planning_task is deliberately a single-item tool, same shape as
log_activity — a voice brain-dump of several tasks ("25 min dishes, 30
min laundry...") is handled by the LLM calling it once per item under
the system prompt's multi-part-request rule, not by a bespoke ingestion
pipeline.

generate_schedule_blocks talks to utils.caldav_client and
utils.reminders_store/agent.scheduler directly rather than through the
LLM-facing add_calendar_event/set_reminder tools — it needs each event's
uid back (to link its boundary reminder) and to pass generated=True (an
internal-only flag add_calendar_event deliberately never exposes to the
LLM), neither of which the tool wrappers' plain-string return values
support.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from apscheduler.triggers.date import DateTrigger
from langchain_core.tools import tool

from agent.scheduler import scheduler
from agent.settings import settings
from jobs.reminders import fire_reminder
from utils import reminders_store, vault
from utils.caldav_client import create_or_update_event, get_events_in_range
from utils.datetime import parse_local_datetime, text_to_utc
from utils.planning import (
    REFLECTION_SECTION_HEADING,
    compute_schedule_blocks,
    format_reflection_digest,
    format_schedule_section,
    occupied_from_calendar_events,
    parse_reflection_section,
    parse_target_tasks,
    reflection_is_filled,
)

TASKS_SECTION = "Tasks"
SCHEDULE_SECTION = "Generated Schedule & Sprints"

# How far back generate_schedule_blocks looks for reflections to surface —
# a week covers "same day last week" patterns without dredging up stale
# feedback.
RECENT_REFLECTION_DAYS = 7
RECENT_REFLECTION_LIMIT = 5


def _resolve_date_str(date_str: Optional[str]) -> str:
    if date_str:
        return parse_local_datetime(date_str).strftime("%Y-%m-%d")
    return datetime.now(settings.zoneinfo()).strftime("%Y-%m-%d")


def _recent_reflections(before_date_str: str, days: int = RECENT_REFLECTION_DAYS) -> str:
    """Digest of filled-in reflections from the `days` before
    `before_date_str`, for generate_schedule_blocks to append to its
    return value — see that function's docstring for why this rides in
    the tool result rather than a separate call/system-prompt addition."""
    cutoff_date = datetime.strptime(before_date_str, "%Y-%m-%d").date()
    entries = []
    for item in vault.list_planning_notes():
        if item["date"] >= before_date_str:
            continue
        note_date = datetime.strptime(item["date"], "%Y-%m-%d").date()
        if (cutoff_date - note_date).days > days:
            continue
        note = vault.parse_note(vault.planning_note_path(item["date"]))
        if note is None:
            continue
        values = parse_reflection_section(vault.get_section(note.body, REFLECTION_SECTION_HEADING))
        if reflection_is_filled(values):
            entries.append((item["date"], values))

    entries.sort(key=lambda e: e[0], reverse=True)
    return format_reflection_digest(entries[:RECENT_REFLECTION_LIMIT])


@tool
def add_planning_task(task: str, duration_minutes: int, date: Optional[str] = None) -> str:
    """Add one task with a time estimate to a day's planning note, for
    generate_schedule_blocks to arrange later. If the user lists several
    tasks at once, call this once per task, not a combined call.

    Args:
        task: A short description (e.g. "Kitchen dishes").
        duration_minutes: Estimated time to complete it, in minutes.
        date: The day this task is for, e.g. "2026-09-13". Defaults to
            today. Resolve relative language ("this Saturday") first,
            same as set_reminder.
    """
    date_str = _resolve_date_str(date)
    note = vault.get_or_create_planning_note(date_str, settings.planning_template_note_id)
    note.body = vault.append_to_section(
        note.body, TASKS_SECTION, f"- [ ] {task.strip()} — Est: {duration_minutes} mins"
    )
    note.updated = vault.now_iso()
    vault.write_note_atomic(note.path, vault.serialize_note(note))
    return f"Added '{task}' ({duration_minutes} mins) to the {date_str} planning note."


@tool
def generate_schedule_blocks(date: Optional[str] = None) -> str:
    """Build a day's schedule: reads the planning note's tasks, merges
    them around that day's calendar events with breaks between sprints,
    writes the timeline into the note, creates a calendar event per
    block, and schedules an end-of-block reminder for each. Also returns
    a digest of the past week's filled-in "End of Day Reflection"
    entries, if any — factor that feedback into how you talk about the
    new schedule.

    Args:
        date: The day to schedule, e.g. "2026-09-13". Defaults to today.
    """
    date_str = _resolve_date_str(date)
    note = vault.get_or_create_planning_note(date_str, settings.planning_template_note_id)
    tasks = parse_target_tasks(vault.get_section(note.body, TASKS_SECTION) or "")
    if not tasks:
        return (
            f"No unchecked tasks with time estimates found in the {date_str} "
            f"planning note's '{TASKS_SECTION}' section."
        )

    tz = settings.zoneinfo()
    day_start_utc = text_to_utc(f"{date_str} 00:00:00")
    day_end_utc = text_to_utc(f"{date_str} 23:59:59")
    calendar_response = get_events_in_range(day_start_utc, day_end_utc)
    events = calendar_response.get("events", []) if calendar_response.get("success") else []
    occupied = occupied_from_calendar_events(events, tz)

    window_start = parse_local_datetime(f"{date_str} {settings.wake_time}:00")
    window_end = parse_local_datetime(f"{date_str} {settings.bedtime}:00")

    blocks, unscheduled = compute_schedule_blocks(tasks, occupied, window_start, window_end)

    note.body = vault.replace_section(note.body, SCHEDULE_SECTION, format_schedule_section(blocks, unscheduled))
    note.updated = vault.now_iso()
    vault.write_note_atomic(note.path, vault.serialize_note(note))

    # Breaks get calendar events too, not just tasks — the device-side
    # active/next view (and interval-chime reminders below) reads the
    # day's schedule purely from the calendar, so a break it doesn't know
    # about would be an invisible gap in that view. generated=True tags
    # each event so the device can tell a sprint/break block apart from a
    # real appointment (jobs/device_sync.py's calendar_events.generated).
    created = 0
    for block in blocks:
        event_uid = str(uuid.uuid4())
        result = create_or_update_event(
            uid=event_uid,
            summary=block.label,
            start_iso=text_to_utc(block.start.strftime("%Y-%m-%d %H:%M:%S")),
            end_iso=text_to_utc(block.end.strftime("%Y-%m-%d %H:%M:%S")),
            generated=True,
        )
        if not result.get("success"):
            continue
        created += 1

        # One boundary reminder per block, due when it ends, pinned to
        # the configured chime sound (agent/settings.py's
        # chime_alert_sound_id) — the same ad-hoc reminder mechanism
        # set_reminder uses (agent/tools/alerts.py's _create_reminder),
        # just invoked directly with a computed time instead of parsed
        # natural language. event_uid links it to the calendar event it
        # was scheduled for, same as jobs/calendar_sync.py's
        # native-alarm-derived reminders.
        reminder_id = str(uuid.uuid4())
        reminder_message = f"{block.label} ended" if block.kind == "task" else "Break's over"
        reminders_store.create_reminder(
            reminder_id,
            reminder_message,
            int(block.end.astimezone(timezone.utc).timestamp()),
            event_uid,
            settings.chime_alert_sound_id or None,
        )
        scheduler.add_job(
            fire_reminder,
            trigger=DateTrigger(run_date=block.end),
            args=[reminder_id],
            id=f"reminder:{reminder_id}",
            replace_existing=True,
        )

    task_count = sum(1 for b in blocks if b.kind == "task")
    summary = f"Scheduled {task_count} task block(s) with breaks for {date_str}, added {created} calendar event(s)."
    if unscheduled:
        summary += f" Couldn't fit: {', '.join(unscheduled)}."
    summary += _recent_reflections(date_str)
    return summary


def get_tools():
    return [add_planning_task, generate_schedule_blocks]
