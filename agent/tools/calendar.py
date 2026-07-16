from typing import Optional
import json
import uuid

from datetime import timedelta

from langchain_core.tools import tool

from utils.datetime import get_todays_datetime, text_to_utc, add_time_to_UTC_text
from utils.next_cloud_calendar import get_event, get_events_in_range, create_or_update_event, delete_event

@tool
def get_todays_events() -> str:
    """Retrieves today's calendar events. Use this when the user asks what's
    on their schedule, agenda, or calendar today."""

    start, end = get_todays_datetime()
    print(f"Retrieving events from {start} to {end}")
    
    return get_events_in_range(start, end)

@tool
def get_calendar_event(uid: str) -> str:
    """Retrieves a specific event from the calendar.

    Args:
        uid (str): The unique ID of the event to retrieve.
    """ 
    print(f"Retrieving event with UID: {uid}")
    
    response = get_event(uid)
    
    if response.get("success"):
        return json.dumps(response.get("event"))
    else:
        return "Failed to retrieve event." + response.get("error")

@tool
def add_calendar_event(title: str, start: str, end: Optional[str] = None, description: Optional[str] = None, location: Optional[str] = None) -> str:
    """Add an event to the calendar.

    Args:
        title (str): The title of the event.
        start (str): The start date and time of the event
        end (Optional[str], optional): The end date and time of the event. Defaults to one hour after the start time.
        description (Optional[str], optional): A description of the event. Defaults to None.
        location (Optional[str], optional): The location of the event. Defaults to None.
    """ 

    start_UTC = text_to_utc(start)
    
    # If no end date is provided, set teh end time to an hour after the start time
    if end is None:
        end_UTC = add_time_to_UTC_text(start_UTC, timedelta(hours=1))
    else:
        end_UTC = text_to_utc(end)

    print(f"Adding event: {title} from {start_UTC} to {end_UTC}")
    print(f"Description: {description}")
    print(f"Location: {location}")
    

    uid = str(uuid.uuid4())

    response = create_or_update_event(
        uid=uid,
        summary=title,
        start_iso=start_UTC,
        end_iso=end_UTC,
        description=description,
        location=location,
    )

    if response.get("success"):
        return f"Event added successfully. UID: {uid}"
    else:
        return "Failed to add event." + response.get("error")
    
@tool
def delete_calendar_event(uid: str) -> str:
    """Delete an event from the calendar.

    Args:
        uid (str): The unique ID of the event to delete.
    """ 
    print(f"Deleting event with UID: {uid}")
    
    response = delete_event(uid)
    
    if response.get("success"):
        return "Event deleted successfully."
    else:
        return "Failed to delete event." + response.get("error")
    
@tool
def get_calendar_events(start: str, end: str) -> str:
    """Retrieves calendar events within a specific time range.

    Args:
        start (str): The start date and time of the event
        end (str): The end date and time of the event
    """ 

    start_UTC = text_to_utc(start)
    end_UTC = text_to_utc(end)

    print(f"Retrieving events from {start_UTC} to {end_UTC}")
    
    response = get_events_in_range(start_UTC, end_UTC)
    
    if response.get("success"):
        return json.dumps(response.get("events"))
    else:
        return "Failed to retrieve events." + response.get("error")

@tool
def update_calendar_event(uid: str, title: str, start: str, end: str, description: Optional[str] = None, location: Optional[str] = None) -> str:
    """Update an event in the calendar.

    Args:
        uid (str): The unique ID of the event to update.
        title (str): The title of the event.
        start (str): The start date and time of the event
        end (str): The end date and time of the event
        description (Optional[str], optional): A description of the event. Defaults to None.
        location (Optional[str], optional): The location of the event. Defaults to None.
    """ 

    start_UTC = text_to_utc(start)
    end_UTC = text_to_utc(end)

    print(f"Updating event with UID: {uid} to {title} from {start_UTC} to {end_UTC}")


    response = create_or_update_event(
        uid=uid,
        summary=title,
        start_iso=start_UTC,
        end_iso=end_UTC,
        description=description,
        location=location,
    )

    if response.get("success"):
        return "Event updated successfully."
    else:
        return "Failed to update event." + response.get("error")  

def get_tools():
    return [
        get_todays_events,
        get_calendar_event,
        add_calendar_event,
        delete_calendar_event,
        get_calendar_events,
        update_calendar_event,
    ]