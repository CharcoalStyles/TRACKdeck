import logging
from typing import Optional
from datetime import datetime

from langchain_core.tools import tool
import requests
import trafilatura

from agent.scheduler import scheduler, bedtime_trigger, digest_trigger, wake_trigger
from agent.settings import is_valid_timezone, settings
from agent.tools.weather import call_open_meteo_search
from utils import onboarding_state

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Time & Date
# ---------------------------------------------------------------------------

@tool
def get_current_datetime() -> str:
    """Returns the current date and time. Use this whenever you need to know the current time or date. It can help with finding the nearest specific day"""

    now = datetime.now(settings.zoneinfo())
    now_string = now.strftime("%-I:%M %p on %A %-d %B %Y")
    logger.info("Current date and time: %s", now_string)
    return f"The current date and time is: {now_string}"

# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

def resolve_location(location: str) -> tuple[str, str] | None:
    """Geocode a free-text place name to a canonical name + IANA timezone via
    Open-Meteo. Returns None if it couldn't be resolved. Shared by the
    set_home_location tool and the onboarding basics form endpoint so both
    go through the same geocoding logic."""
    try:
        data = call_open_meteo_search(location)
    except requests.exceptions.RequestException as e:
        logger.error("Error connecting to Open-Meteo geocoding: %s", e)
        return None

    results = data.get("results") or []
    if not results:
        return None

    match = results[0]
    resolved_name = ", ".join(
        part for part in [match.get("name"), match.get("admin1"), match.get("country")] if part
    )
    tz_name = match.get("timezone")
    if not tz_name or not is_valid_timezone(tz_name):
        return None

    return resolved_name, tz_name


@tool
def mark_onboarding_complete() -> str:
    """Call this once the guided onboarding interview's main areas (preferences, people,
    routine, interests) feel reasonably covered — only when the onboarding mode addendum's
    guidance applies, not during ordinary chat or profile Q&A. Marks onboarding complete so
    the dashboard defaults to the profile Q&A view instead of the interview. Safe to call
    more than once; the user can still switch back to the interview manually afterward."""
    onboarding_state.mark_onboarding_complete()
    logger.info("Onboarding marked complete.")
    return "Onboarding marked complete."


@tool
def set_home_location(location: str) -> str:
    """Call this during guided onboarding as soon as the user answers where they live —
    only in onboarding mode, never during ordinary chat or profile Q&A. Resolves the
    free-text place name to a canonical location and its IANA timezone via geocoding
    (rather than guessing the timezone yourself), then saves both as the app's standing
    default_location/timezone settings — used by weather lookups, calendar day
    boundaries, and the daily digest/bedtime schedule. This is separate from the About
    Me profile — do not also record it with remember_about_me. If it resolves to the
    wrong place (e.g. an ambiguous town name), the user can always correct it afterward
    from the dashboard's Settings page.

    Args:
        location: The place the user said they live, as close to their own words as
            possible (e.g. "Melbourne, Australia").

    Returns:
        Confirmation of what was set, or an explanation if the location couldn't be
        resolved.
    """
    resolved = resolve_location(location)
    if resolved is None:
        return f"Couldn't resolve '{location}' to a place — ask them to be more specific, or it can be set directly from the Settings page."
    resolved_name, tz_name = resolved

    settings.default_location = resolved_name
    settings.timezone = tz_name
    # Same rescheduling main.py's POST /settings does on a timezone change —
    # these three jobs are registered as fixed cron triggers, not read fresh.
    scheduler.reschedule_job("daily_digest", trigger=digest_trigger())
    scheduler.reschedule_job("bedtime_reminder", trigger=bedtime_trigger())
    scheduler.reschedule_job("day_start", trigger=wake_trigger())

    logger.info("Onboarding set default_location=%s timezone=%s", resolved_name, tz_name)
    return f"Set default location to '{resolved_name}' and timezone to '{tz_name}'."

# ---------------------------------------------------------------------------
# Web Page Fetching
# ---------------------------------------------------------------------------

# Kept in step with all_tools.py's _MCP_TOOL_RESULT_CHAR_LIMIT — same
# reasoning (bound a single tool result to what the local model's context
# can absorb), just a separate constant since this module doesn't import
# from all_tools.py (all_tools.py already imports from here).
_FETCH_WEBPAGE_CHAR_LIMIT = 12000


@tool
def fetch_webpage(url: str) -> str:
    """Fetch a specific webpage and extract its actual main content (not
    navigation, ads, or sidebar chrome) as clean text via boilerplate
    removal, not just an HTML-to-markdown dump. Use this after search_web
    when a result's snippet is only a pointer to what you need — a blurb
    saying a page has a full timeline/list/figures — rather than the detail
    itself, so you can read the real content instead of just relaying a
    link back to the user.

    Args:
        url: The exact URL to fetch, usually taken from a search_web result.
    """
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error("Error fetching %s: %s", url, e)
        return f"Couldn't fetch '{url}': {e}"

    extracted = trafilatura.extract(response.text, output_format="markdown", include_links=False)
    if not extracted:
        return (
            f"Couldn't extract readable article content from '{url}' — it may not be a "
            "plain content page (e.g. requires JavaScript, or is a non-article format)."
        )

    if len(extracted) > _FETCH_WEBPAGE_CHAR_LIMIT:
        total = len(extracted)
        extracted = extracted[:_FETCH_WEBPAGE_CHAR_LIMIT] + f"\n\n[...truncated, {total} chars total]"

    return extracted
