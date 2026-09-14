from typing import Optional
import json
import logging
import uuid

from datetime import timedelta

from langchain_core.tools import tool

from utils.datetime import get_todays_datetime, text_to_utc, add_time_to_UTC_text
from utils.caldav_client import get_event, get_events_in_range, create_or_update_event, delete_event

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
        return f"Event added successfully. UID: {uid}"
    else:
        return f"Failed to add event. {response.get('error') or response.get('message') or 'Unknown error'}"
    
@tool
def delete_calendar_event(uid: str) -> str:
    """Delete an event from the calendar.

    Args:
        uid: The event's unique ID.
    """
    logger.info("Deleting event with UID: %s", uid)
    
    response = delete_event(uid)
    
    if response.get("success"):
        return "Event deleted successfully."
    else:
        return f"Failed to delete event. {response.get('error') or response.get('message') or 'Unknown error'}"
    
@tool
def get_calendar_events(start: str, end: str) -> str:
    """Retrieves calendar events within a specific time range.

    Args:
        start: Start of the range.
        end: End of the range.
    """

    start_UTC = text_to_utc(start)
    end_UTC = text_to_utc(end)

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
        description: Optional event description.
        location: Optional event location.
        recurrence: An RFC 5545 RRULE value, same format as add_calendar_event.
            Replaces the event's recurrence outright — pass the existing value
            again to keep it, or omit to turn a repeating event into a one-off.
    """

    start_UTC = text_to_utc(start)
    end_UTC = text_to_utc(end)

    logger.info("Updating event with UID: %s to %s from %s to %s", uid, title, start_UTC, end_UTC)


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
        return "Event updated successfully."
    else:
        return f"Failed to update event. {response.get('error') or response.get('message') or 'Unknown error'}"

def get_tools():
    return [
        get_todays_events,
        get_calendar_event,
        add_calendar_event,
        delete_calendar_event,
        get_calendar_events,
        update_calendar_event,
    ]