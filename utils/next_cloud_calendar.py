import os
import xml.etree.ElementTree as ET
import requests
from requests.auth import HTTPBasicAuth

# ==========================================
# CONFIGURATION
# ==========================================
NEXTCLOUD_URL = os.getenv("NEXTCLOUD_URL")
USERNAME = os.getenv("NEXTCLOUD_USERNAME")
APP_PASSWORD = os.getenv("NEXTCLOUD_APP_PASSWORD")
CALENDAR_SLUG = os.getenv("NEXTCLOUD_CALENDAR_SLUG")

BASE_URL = f"{NEXTCLOUD_URL}/remote.php/dav/calendars/{USERNAME}/{CALENDAR_SLUG}/"
AUTH = HTTPBasicAuth(USERNAME, APP_PASSWORD)

# ==========================================
# HELPER UTILITIES
# ==========================================
def parse_ics(ics_text):
    """
    Parses raw iCalendar text into a clean dictionary.
    Perfect for handing structured data directly to an LLM context.
    """
    event_details = {}

    # 1. Unfold lines (iCalendar spec standardizes splitting long lines with CRLF + Space)
    unfolded_text = ics_text.replace("\r\n ", "").replace("\n ", "")
    
    for line in unfolded_text.splitlines():
        if not line or ":" not in line:
            continue
            
        # Split only on the first colon to preserve colons inside descriptions/URLs
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().replace(r"\,", ",").replace(r"\;", ";") # Unescape punctuation
        
        if key == "SUMMARY":
            event_details["summary"] = value
        elif key == "DTSTART":
            event_details["start"] = value
        elif key == "DTEND":
            event_details["end"] = value
        elif key == "DESCRIPTION":
            event_details["description"] = value
        elif key == "UID":
            event_details["uid"] = value
            
    return event_details


# ==========================================
# CALENDAR CRUD & QUERY FUNCTIONS
# ==========================================

def _escape_ics_text(value):
    """Escapes a value for use in an RFC5545 TEXT property (SUMMARY/DESCRIPTION/LOCATION)."""
    return (
        value.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def create_or_update_event(uid, summary, start_iso, end_iso, description="", location=""):
    """
    Creates or updates an event.
    """
    url = f"{BASE_URL}{uid}.ics"

    # Callers may pass explicit None (overriding these defaults) when the
    # user didn't provide a description/location — without this they'd be
    # written into the ICS as the literal string "None".
    description = description or ""
    location = location or ""

    # Base event structure
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Nextcloud Python Agent//NONSGML v1.0//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTART:{start_iso}",
        f"DTEND:{end_iso}",
        f"SUMMARY:{_escape_ics_text(summary)}",
        f"DESCRIPTION:{_escape_ics_text(description)}",
        f"LOCATION:{_escape_ics_text(location)}"
    ]
        
    ics_lines.extend(["END:VEVENT", "END:VCALENDAR"])
    
    ics_body = "\r\n".join(ics_lines)  # iCalendar spec prefers CRLF line endings

    headers = {"Content-Type": "text/calendar; charset=utf-8"}
    response = requests.put(url, data=ics_body, headers=headers, auth=AUTH)
    
    if response.status_code in [201, 204]:
        return {"success": True, "message": "Event saved successfully."}
    return {"success": False, "error": response.text}


def get_event(uid):
    """
    [READ]
    Fetches a single event by its unique ID.
    Returns a parsed dictionary or None if not found.
    """
    url = f"{BASE_URL}{uid}.ics"
    response = requests.get(url, auth=AUTH)
    
    if response.status_code == 200:
        return {"success": True, "event": parse_ics(response.text)}
    elif response.status_code == 404:
        return {"success": False, "message": "Event not found."}
    return {"success": False, "status_code": response.status_code, "error": response.text}


def delete_event(uid):
    """
    [DELETE]
    Removes an event from the calendar using its unique ID.
    """
    url = f"{BASE_URL}{uid}.ics"
    response = requests.delete(url, auth=AUTH)
    
    if response.status_code == 204:  # 204 No Content means successful deletion
        return {"success": True, "message": "Event deleted successfully."}
    elif response.status_code == 404:
        return {"success": False, "message": "Event did not exist."}
    return {"success": False, "status_code": response.status_code, "error": response.text}


def get_events_in_range(start_iso, end_iso):
    """
    [QUERY RANGE]
    Queries the calendar for any events falling within a specific time range.
    Timestamps must be in UTC format: 'YYYYMMDDTHHMMSSZ'
    """
    # WebDAV REPORT XML payload targeting specific time-ranges
    xml_payload = f"""<?xml version="1.0" encoding="utf-8" ?>
    <C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
        <D:prop>
            <D:getetag />
            <C:calendar-data />
        </D:prop>
        <C:filter>
            <C:comp-filter name="VCALENDAR">
                <C:comp-filter name="VEVENT">
                    <C:time-range start="{start_iso}" end="{end_iso}"/>
                </C:comp-filter>
            </C:comp-filter>
        </C:filter>
    </C:calendar-query>"""

    headers = {
        "Content-Type": "application/xml; charset=utf-8",
        "Depth": "1"
    }

    # Custom HTTP verb 'REPORT' is required for CalDAV filtering
    response = requests.request("REPORT", BASE_URL, data=xml_payload, headers=headers, auth=AUTH)
    
    if response.status_code != 207:  # 207 Multi-Status is standard WebDAV success
        return {"success": False, "status_code": response.status_code, "error": response.text}

    # Parse WebDAV multi-status XML response
    root = ET.fromstring(response.content)
    namespaces = {
        'd': 'DAV:',
        'c': 'urn:ietf:params:xml:ns:caldav'
    }
    
    events_list = []
    for response_node in root.findall('d:response', namespaces):
        calendar_data = response_node.find('.//c:calendar-data', namespaces).text
        if calendar_data:
            events_list.append(parse_ics(calendar_data))
            
    return {"success": True, "events": events_list}