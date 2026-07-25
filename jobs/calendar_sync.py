"""
jobs/calendar_sync.py
----------------------
Nextcloud/CalDAV has no push mechanism this app can subscribe to, so an
event added, moved, or removed directly in a calendar app (outside the
agent) is otherwise invisible to it. This job polls periodically and
keeps a reminders.db row in sync with any event that has its own native
reminder set (a VALARM, RFC 5545) — the same "remind me" toggle any
calendar app's UI already offers. That's the opt-in: events without an
alarm are none of this job's business, exactly like before.

Runs on an APScheduler IntervalTrigger — agent/scheduler.py's
calendar_sync_trigger(), interval controlled by
settings.calendar_sync_interval_minutes (live-reschedulable via
/settings, same as digest_time/bedtime), not tied to a fixed time of day
the way the digest/bedtime jobs are.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.date import DateTrigger

from agent.scheduler import scheduler
from jobs.reminders import fire_reminder
from utils import reminders_store
from utils.next_cloud_calendar import get_event, get_events_in_range, parse_ics_duration
from utils.notify import notify_error

logger = logging.getLogger(__name__)

# How far ahead to look for events with an alarm on each pass. Generous on
# purpose: an event further out than this simply won't be (re)synced until
# it falls inside the window on a later pass, or until _sweep_removed's
# per-UID fallback check catches a change to an already-tracked one.
LOOKAHEAD = timedelta(days=14)

_ICS_UTC_FORMAT = "%Y%m%dT%H%M%SZ"


def _earliest_event_start(start_raw: Optional[str]) -> Optional[datetime]:
    """Parses a DTSTART value already known to look like a timed (not
    all-day) event. Only the UTC 'Z'-suffixed form this codebase writes
    itself is understood — an event created through a calendar app that
    stores a floating/TZID-local DTSTART instead won't parse and is
    skipped rather than guessed at."""
    if not start_raw or "T" not in start_raw:
        return None
    try:
        return datetime.strptime(start_raw, _ICS_UTC_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _alarm_offset(alarms: list[str]) -> Optional[timedelta]:
    """An event can carry more than one alarm; a calendar app's basic
    reminder picker only ever sets one, so this is a rare case. Picks the
    one closest to the event start (least advance notice) as the single
    thing worth mirroring into a Gotify push."""
    offsets = [o for o in (parse_ics_duration(a) for a in alarms) if o is not None]
    return max(offsets) if offsets else None


async def _apply(event_uid: str, summary: str, due_at_dt: datetime) -> None:
    due_epoch = int(due_at_dt.timestamp())
    message = f"Upcoming: {summary}"
    reminder_id, changed = await asyncio.to_thread(
        reminders_store.upsert_calendar_reminder, event_uid, message, due_epoch
    )
    if not changed:
        return

    if due_at_dt <= datetime.now(timezone.utc):
        await fire_reminder(reminder_id)
    else:
        scheduler.add_job(
            fire_reminder,
            trigger=DateTrigger(run_date=due_at_dt),
            args=[reminder_id],
            id=f"reminder:{reminder_id}",
            replace_existing=True,
        )


async def _cancel_linked(reminder_id: str) -> None:
    await asyncio.to_thread(reminders_store.mark_status, reminder_id, "cancelled")
    try:
        scheduler.remove_job(f"reminder:{reminder_id}")
    except JobLookupError:
        pass


async def _sweep_removed(seen_uids: set[str]) -> None:
    """For every calendar-linked pending reminder not seen in this pass'
    range query — either the event was deleted, its alarm was removed, or
    it just moved beyond LOOKAHEAD — check directly rather than assuming
    deletion, so a rescheduled-further-out event doesn't lose its
    reminder."""
    linked = await asyncio.to_thread(reminders_store.list_pending_calendar_linked)
    for reminder in linked:
        uid = reminder["event_uid"]
        if uid in seen_uids:
            continue

        response = await asyncio.to_thread(get_event, uid)
        if not response.get("success"):
            await _cancel_linked(reminder["id"])
            continue

        event = response["event"]
        offset = _alarm_offset(event.get("alarms", []))
        event_start = _earliest_event_start(event.get("start"))
        if offset is None or event_start is None:
            # Alarm removed (or event became all-day/unparseable) — honor that.
            await _cancel_linked(reminder["id"])
            continue

        await _apply(uid, event.get("summary") or "Calendar event", event_start + offset)


async def sync_calendar_reminders() -> None:
    try:
        now = datetime.now(timezone.utc)
        response = await asyncio.to_thread(
            get_events_in_range,
            now.strftime(_ICS_UTC_FORMAT),
            (now + LOOKAHEAD).strftime(_ICS_UTC_FORMAT),
        )
        if not response.get("success"):
            logger.warning(
                "Calendar sync: failed to fetch events: %s",
                response.get("error") or response.get("message"),
            )
            return

        seen_uids: set[str] = set()
        for event in response.get("events", []):
            uid = event.get("uid")
            event_start = _earliest_event_start(event.get("start"))
            offset = _alarm_offset(event.get("alarms", []))
            if not uid or event_start is None or offset is None:
                continue  # all-day/unparseable, or no native alarm set — not our business

            seen_uids.add(uid)
            await _apply(uid, event.get("summary") or "Calendar event", event_start + offset)

        await _sweep_removed(seen_uids)
    except Exception as e:
        logger.error("Calendar reminder sync failed: %s", e)
        notify_error("Calendar reminder sync failed", e)
