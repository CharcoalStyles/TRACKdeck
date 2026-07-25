import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from agent.settings import settings

_AM_PM_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[ T](?P<time>\d{1,2}:\d{2}(?P<seconds>:\d{2})?)\s*(?P<meridiem>[AaPp][Mm])$"
)

def get_todays_datetime():
    LOCAL_TZ = settings.zoneinfo()

    now_local = datetime.now(LOCAL_TZ)
    now_utc_string = now_local.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")

    start_of_today_local = datetime.combine(now_local.date(), time.min, tzinfo=LOCAL_TZ)
    end_of_today_local = datetime.combine(now_local.date(), time.max, tzinfo=LOCAL_TZ)

    today_start_utc = start_of_today_local.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    today_end_utc = end_of_today_local.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")

    return today_start_utc, today_end_utc

def parse_local_datetime(date_str: str, local_timezone_str: str | None = None) -> datetime:
    """
    Parses an agent/user friendly ISO or 12-hour string into a tz-aware datetime.
    Example: '2026-07-10 15:00:00' or '2026-07-10 3:00 PM'.
    """
    local_timezone_str = local_timezone_str or settings.timezone

    date_str = date_str.strip()

    # fromisoformat has no AM/PM support, so a 12-hour string (e.g. "2026-07-10
    # 3:00 PM") needs an explicit %I/%p parse rather than just stripping the
    # marker, which discarded the PM offset entirely.
    am_pm_match = _AM_PM_PATTERN.match(date_str)
    if am_pm_match:
        fmt = "%Y-%m-%d %I:%M:%S %p" if am_pm_match.group("seconds") else "%Y-%m-%d %I:%M %p"
        dt = datetime.strptime(
            f"{am_pm_match.group('date')} {am_pm_match.group('time')} {am_pm_match.group('meridiem').upper()}",
            fmt,
        )
    else:
        # Accept standard ISO format from the LLM
        dt = datetime.fromisoformat(date_str.replace(" ", "T"))

    # If the LLM didn't provide timezone info, assume the user's local timezone
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(local_timezone_str))

    return dt


def text_to_utc(date_str, local_timezone_str=None):
    """
    Converts an agent/user friendly ISO or natural string format into Nextcloud UTC format.
    Example: '2026-07-10 15:00:00' -> '20260710T050000Z'
    """
    dt = parse_local_datetime(date_str, local_timezone_str)
    utc_dt = dt.astimezone(ZoneInfo("UTC"))
    return utc_dt.strftime("%Y%m%dT%H%M%SZ")

def add_time_to_UTC_text(utc: str, timedelta: timedelta) -> str:
    """
    Adds a timespan to a UTC string
    """
    # Convert to UTC and format for CalDAV
    utc_dt = datetime.fromisoformat(utc)
    utc_dt = utc_dt + timedelta
    return utc_dt.strftime("%Y%m%dT%H%M%SZ")