"""
jobs/device_sync.py
---------------------
Assembles the payload for main.py's POST /device/sync — everything the
ESP32-S3 needs to render a rolling 24-hour view on wake: pending
check-ins, reminders (ad-hoc + calendar-derived), a raw calendar agenda,
today's weather, and enough timezone/scheduling context to keep its own
clock and polling loop correct.

The device is a preview/display layer, not the delivery mechanism —
Gotify pushes and the APScheduler jobs elsewhere in this codebase are
what actually fire reminders/check-ins/bedtime regardless of whether the
device is online or reachable. This module only decides what to *show*.

Calendar and weather are both external services that can be briefly
unreachable; a failure there degrades to an empty list / None rather
than failing the whole sync (which would also mean losing the far more
important check-in/reminder data), and is logged rather than pushed to
Gotify via notify_error — this runs on every device poll (as often as
every few minutes), so alerting on every transient outage would be pure
noise.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from agent.settings import settings
from agent.tools.weather import fetch_current_conditions
from jobs import checkin as checkin_jobs
from utils import alert_sounds_store, checkins_store, reminders_store
from utils.datetime import posix_tz_string
from utils.caldav_client import get_events_in_range

logger = logging.getLogger(__name__)

_ICS_UTC_FORMAT = "%Y%m%dT%H%M%SZ"


def _parse_utc(value: Optional[str]) -> Optional[datetime]:
    """Same convention as jobs/calendar_sync.py's _earliest_event_start —
    only a UTC 'Z'-suffixed DTSTART/DTEND is understood; anything else
    (floating/TZID-local) is skipped rather than guessed at."""
    if not value or "T" not in value:
        return None
    try:
        return datetime.strptime(value, _ICS_UTC_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _fetch_calendar_events(now_utc: datetime) -> list[dict]:
    try:
        result = get_events_in_range(
            now_utc.strftime(_ICS_UTC_FORMAT),
            (now_utc + timedelta(hours=24)).strftime(_ICS_UTC_FORMAT),
        )
    except Exception as e:
        logger.warning("Device sync: calendar fetch failed: %s", e)
        return []
    if not result.get("success"):
        logger.warning("Device sync: calendar query unsuccessful: %s", result)
        return []

    events = []
    for event in result.get("events", []):
        start = _parse_utc(event.get("start"))
        if start is None:
            continue
        end = _parse_utc(event.get("end"))
        events.append(
            {
                "uid": event.get("uid"),
                "summary": event.get("summary") or "(untitled)",
                "start": int(start.timestamp()),
                "end": int(end.timestamp()) if end else None,
            }
        )
    return events


async def build_sync_payload() -> dict:
    now_epoch = int(time.time())
    now_utc = datetime.now(timezone.utc)

    checkins = await asyncio.to_thread(checkins_store.list_next_24h, now_epoch)
    reminders = await asyncio.to_thread(reminders_store.list_pending_due_within_24h, now_epoch)
    calendar_events = await asyncio.to_thread(_fetch_calendar_events, now_utc)
    weather = await asyncio.to_thread(fetch_current_conditions, settings.default_location)
    alert_sounds = await asyncio.to_thread(alert_sounds_store.list_sounds)
    next_wake_at = await checkin_jobs.next_wake_at()

    return {
        "now": now_epoch,
        "timezone": {
            "iana": settings.timezone,
            "posix": posix_tz_string(settings.timezone),
        },
        "poll_interval_seconds": settings.device_poll_interval_seconds,
        "bedtime": settings.bedtime,
        "next_wake_at": next_wake_at,
        "checkins": [
            {
                "id": c["id"],
                "category": c["category"],
                "prompt_text": c["prompt_text"],
                "scheduled_at": c["scheduled_at"],
                "fired_at": c["fired_at"],
            }
            for c in checkins
        ],
        "reminders": [
            {
                "id": r["id"],
                "message": r["message"],
                "due_at": r["due_at"],
                "event_uid": r["event_uid"],
            }
            for r in reminders
        ],
        "calendar_events": calendar_events,
        "weather": weather,
        # Full current library, not a delta — same "rebuilt from scratch"
        # pattern as everything else in this payload. The device is
        # expected to diff this against what it already has on its SD
        # card: fetch anything new/changed from `url`, delete anything
        # local whose id no longer appears here. Keeps this payload cheap
        # (pure metadata) on every poll and confines the actual audio
        # transfer to GET /device/alert-sounds/{id}, only hit when a file
        # is actually added or changed.
        "alert_sounds": [
            {
                "id": s["id"],
                "sha256": s["sha256"],
                "size_bytes": s["size_bytes"],
                "duration_seconds": s["duration_seconds"],
                "url": f"/device/alert-sounds/{s['id']}",
            }
            for s in alert_sounds
        ],
    }
