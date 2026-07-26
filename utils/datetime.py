import re
import zoneinfo as _zoneinfo_module
from datetime import datetime, time, timedelta
from pathlib import Path
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


def _read_tzif_bytes(iana_name: str) -> bytes | None:
    for base in _zoneinfo_module.TZPATH:
        candidate = Path(base) / iana_name
        if candidate.is_file():
            return candidate.read_bytes()
    try:
        from importlib.resources import files

        resource = files("tzdata.zoneinfo").joinpath(*iana_name.split("/"))
        if resource.is_file():
            return resource.read_bytes()
    except (ImportError, ModuleNotFoundError, FileNotFoundError):
        pass
    return None


def posix_tz_string(iana_name: str) -> str | None:
    """Extracts the POSIX TZ string embedded in the compiled zoneinfo
    (TZif) file for `iana_name`. Every TZif v2+ file ends with a
    '\\n<POSIX TZ string>\\n' footer used for extrapolating transitions
    beyond the explicit table — exactly the DST-aware string firmware
    needs (e.g. ESP-IDF/lwip's setenv("TZ", ...)) to render correct local
    time without hardcoding a fixed UTC offset that goes stale twice a
    year. Returns None if the zone can't be located or lacks a v2+
    footer — callers must handle that gracefully (device sync payload's
    timezone.posix is nullable)."""
    data = _read_tzif_bytes(iana_name)
    if data is None or not data.startswith(b"TZif") or data[4:5] not in (b"2", b"3"):
        return None
    footer = data.rstrip(b"\n").rsplit(b"\n", 1)[-1]
    try:
        return footer.decode("ascii")
    except UnicodeDecodeError:
        return None