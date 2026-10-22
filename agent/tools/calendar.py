from typing import Optional
import json
import logging
import uuid

import re
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher

from langchain_core.tools import tool

from utils.datetime import (
    get_todays_datetime, text_to_utc, add_time_to_UTC_text, parse_local_datetime,
    format_span, past_start_message,
)
from utils.caldav_client import (
    get_event, get_events_in_range, create_or_update_event, delete_event, _parse_ics_datetime,
)

logger = logging.getLogger(__name__)

@tool
def get_todays_events() -> str:
    """Retrieves today's calendar events. Use this when the user asks what's
    on their schedule, agenda, or calendar today."""

    start, end = get_todays_datetime()
    logger.info("Retrieving events from %s to %s", start, end)

    response = get_events_in_range(start, end)

    if response.get("success"):
        return json.dumps(response.get("events"))
    else:
        return f"Failed to retrieve today's events. {response.get('error') or response.get('message') or 'Unknown error'}"

@tool
def get_calendar_event(uid: str) -> str:
    """Retrieves a specific event from the calendar.

    Args:
        uid: The event's unique ID.
    """
    logger.info("Retrieving event with UID: %s", uid)
    
    response = get_event(uid)
    
    if response.get("success"):
        return json.dumps(response.get("event"))
    else:
        return f"Failed to retrieve event. {response.get('error') or response.get('message') or 'Unknown error'}"

@tool
def add_calendar_event(title: str, start: str, end: Optional[str] = None, description: Optional[str] = None, location: Optional[str] = None, recurrence: Optional[str] = None) -> str:
    """Add an event to the calendar.

    Args:
        title: The event's title.
        start: The event's start date/time.
        end: The event's end date/time. Defaults to one hour after start.
        description: Optional event description.
        location: Optional event location.
        recurrence: An RFC 5545 RRULE value if this event repeats — e.g.
            "FREQ=DAILY", "FREQ=WEEKLY;BYDAY=MO,WE,FR",
            "FREQ=WEEKLY;INTERVAL=2" (every two weeks), "FREQ=MONTHLY;BYMONTHDAY=15",
            "FREQ=DAILY;COUNT=10" (stop after 10 occurrences), or
            "FREQ=WEEKLY;UNTIL=20261231T000000Z" (stop by a date, always UTC/"Z").
            Leave unset for a one-off event. A single reminder that happens once —
            even a relative one like "30 minutes before my appointment" — should
            use set_reminder instead, not a recurring event.
    """

    start_UTC = text_to_utc(start)

    past = past_start_message(parse_local_datetime(start), "add the event", "add_calendar_event")
    if past:
        return past

    # If no end date is provided, set teh end time to an hour after the start time
    if end is None:
        end_UTC = add_time_to_UTC_text(start_UTC, timedelta(hours=1))
    else:
        end_UTC = text_to_utc(end)

    logger.info("Adding event: %s from %s to %s", title, start_UTC, end_UTC)
    logger.debug("Description: %s", description)
    logger.debug("Location: %s", location)
    logger.debug("Recurrence: %s", recurrence)


    uid = str(uuid.uuid4())

    response = create_or_update_event(
        uid=uid,
        summary=title,
        start_iso=start_UTC,
        end_iso=end_UTC,
        description=description,
        location=location,
        rrule=recurrence,
    )

    if response.get("success"):
        return f"Event added successfully. UID: {uid}. Added '{title}' for {_span_text(start_UTC, end_UTC)}."
    else:
        return f"Failed to add event. {response.get('error') or response.get('message') or 'Unknown error'}"
    
@tool
def delete_calendar_event(uid: str) -> str:
    """Delete an event from the calendar.

    Args:
        uid: The event's unique ID.
    """
    logger.info("Deleting event with UID: %s", uid)

    existing = get_event(uid)
    title = (existing.get("event") or {}).get("summary") if existing.get("success") else None

    response = delete_event(uid)

    if response.get("success"):
        return f"Event deleted successfully. Deleted '{title}'." if title else "Event deleted successfully."
    else:
        return f"Failed to delete event. {response.get('error') or response.get('message') or 'Unknown error'}"
    
def _inclusive_end(end: str) -> str:
    """A bare date as a range end means "through the end of that day", not midnight at its start."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", end.strip()):
        return (date.fromisoformat(end.strip()) + timedelta(days=1)).isoformat()
    return end


@tool
def get_calendar_events(start: str, end: str) -> str:
    """Retrieves calendar events within a specific time range.

    Args:
        start: Start of the range.
        end: End of the range. A date alone (e.g. 2026-10-19) includes that whole day.
    """

    start_UTC = text_to_utc(start)
    end_UTC = text_to_utc(_inclusive_end(end))

    logger.info("Retrieving events from %s to %s", start_UTC, end_UTC)
    
    response = get_events_in_range(start_UTC, end_UTC)
    
    if response.get("success"):
        return json.dumps(response.get("events"))
    else:
        return f"Failed to retrieve events. {response.get('error') or response.get('message') or 'Unknown error'}"

@tool
def update_calendar_event(uid: str, title: str, start: str, end: str, description: Optional[str] = None, location: Optional[str] = None, recurrence: Optional[str] = None) -> str:
    """Update an event in the calendar.

    Args:
        uid: The event's unique ID.
        title: The event's title.
        start: The event's start date/time.
        end: The event's end date/time.
        description: Optional event description. Omit to keep the current one.
        location: Optional event location. Omit to keep the current one.
        recurrence: An RFC 5545 RRULE value, same format as add_calendar_event.
            Replaces the event's recurrence outright — pass the existing value
            again to keep it, or omit to turn a repeating event into a one-off.
    """

    start_UTC = text_to_utc(start)
    end_UTC = text_to_utc(end)

    logger.info("Updating event with UID: %s to %s from %s to %s", uid, title, start_UTC, end_UTC)

    # The save is a full replace, and the tool model often omits fields it
    # isn't changing; carry those over instead of silently blanking them.
    if description is None or location is None:
        current = get_event(uid)
        if current.get("success"):
            existing = current.get("event", {})
            if description is None:
                description = existing.get("description")
            if location is None:
                location = existing.get("location")

    response = create_or_update_event(
        uid=uid,
        summary=title,
        start_iso=start_UTC,
        end_iso=end_UTC,
        description=description,
        location=location,
        rrule=recurrence,
    )

    if response.get("success"):
        return f"Event updated successfully. Updated '{title}' to {_span_text(start_UTC, end_UTC)}."
    else:
        return f"Failed to update event. {response.get('error') or response.get('message') or 'Unknown error'}"


def _span_text(start_utc: str, end_utc: str) -> str:
    return format_span(_parse_ics_datetime(start_utc), _parse_ics_datetime(end_utc))


def _find_event_for_move(ref: str) -> tuple[Optional[dict], Optional[str]]:
    """(event, error). `ref` is a uid or part of a title; searches from 30
    days back to a year ahead and refuses to guess between close matches."""
    ref = ref.strip()
    found = get_event(ref)
    if found.get("success") and found.get("event", {}).get("uid"):
        return found["event"], None

    now = datetime.now(timezone.utc)
    window = get_events_in_range(
        (now - timedelta(days=30)).strftime("%Y%m%dT%H%M%SZ"),
        (now + timedelta(days=365)).strftime("%Y%m%dT%H%M%SZ"),
    )
    if not window.get("success"):
        return None, f"Failed to look up events. {window.get('error') or window.get('message') or 'Unknown error'}"

    needle = ref.lower()
    scored = []
    for ev in window["events"]:
        name = (ev.get("summary") or "").lower()
        if not name or ev.get("generated"):
            continue
        score = 1.0 if needle in name or name in needle else SequenceMatcher(None, needle, name).ratio()
        if score >= 0.6:
            scored.append((score, ev))
    if not scored:
        return None, f"Failed to find an event matching '{ref}'."
    scored.sort(key=lambda x: -x[0])
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.15:
        options = "; ".join(f"'{e['summary']}'" for _, e in scored[:4])
        return None, f"Failed to pick one event: '{ref}' matches several ({options}). Be more specific."
    return scored[0][1], None


@tool
def move_calendar_event(event: str, new_start: str) -> str:
    """Move an existing calendar event to a new start time, keeping its title
    and length. Use this to fix or change when an event happens.

    Args:
        event: The event's title (or part of it), or its UID.
        new_start: The new start date/time, as an absolute local date and time.
    """
    ev, error = _find_event_for_move(event)
    if error:
        return error
    if ev.get("rrule"):
        return "Failed to move event. It repeats; changing a repeating event needs update_calendar_event."

    old_start, old_end = _parse_ics_datetime(ev.get("start", "")), _parse_ics_datetime(ev.get("end", ""))
    if not old_start or not old_end:
        return "Failed to move event. Its times are in a format I can't change safely; edit it in your calendar app."

    new_start_dt = parse_local_datetime(new_start)
    past = past_start_message(new_start_dt, "move the event", "move_calendar_event")
    if past:
        return past

    new_start_utc = text_to_utc(new_start)
    new_end_utc = add_time_to_UTC_text(new_start_utc, old_end - old_start)

    response = create_or_update_event(
        uid=ev["uid"],
        summary=ev.get("summary", ""),
        start_iso=new_start_utc,
        end_iso=new_end_utc,
        description=ev.get("description"),
        location=ev.get("location"),
        rrule=None,
    )
    if response.get("success"):
        return f"Event updated successfully. Moved '{ev.get('summary')}' to {_span_text(new_start_utc, new_end_utc)}."
    return f"Failed to move event. {response.get('error') or response.get('message') or 'Unknown error'}"

def get_tools():
    return [
        get_todays_events,
        get_calendar_event,
        add_calendar_event,
        delete_calendar_event,
        get_calendar_events,
        update_calendar_event,
        move_calendar_event,
    ]