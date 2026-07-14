from datetime import datetime, time
import os
from zoneinfo import ZoneInfo


def get_todays_datetime():
    LOCAL_TZ = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "Australia/Canberra"))

    now_local = datetime.now(LOCAL_TZ)
    now_utc_string = now_local.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")

    start_of_today_local = datetime.combine(now_local.date(), time.min, tzinfo=LOCAL_TZ)
    end_of_today_local = datetime.combine(now_local.date(), time.max, tzinfo=LOCAL_TZ)

    today_start_utc = start_of_today_local.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    today_end_utc = end_of_today_local.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")

    return today_start_utc, today_end_utc

def text_to_utc(date_str, local_timezone_str="Australia/Canberra"):
    """
    Converts an agent/user friendly ISO or natural string format into Nextcloud UTC format.
    Example: '2026-07-10 15:00:00' -> '20260710T050000Z'
    """
    # Accept standard ISO format from the LLM
    dt = datetime.fromisoformat(date_str.replace(" ", "T"))
    
    # If the LLM didn't provide timezone info, assume the user's local timezone
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(local_timezone_str))
        
    # Convert to UTC and format for CalDAV
    utc_dt = dt.astimezone(ZoneInfo("UTC"))
    return utc_dt.strftime("%Y%m%dT%H%M%SZ")