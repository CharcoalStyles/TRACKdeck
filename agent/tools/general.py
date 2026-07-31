import json
import logging
from typing import Optional
from datetime import datetime

from langchain_core.tools import tool
import requests
import os

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
    try:
        data = call_open_meteo_search(location)
    except requests.exceptions.RequestException as e:
        logger.error("Error connecting to Open-Meteo geocoding: %s", e)
        return f"Couldn't look up '{location}' right now — it can be set later from the Settings page."

    results = data.get("results") or []
    if not results:
        return f"Couldn't resolve '{location}' to a place — ask them to be more specific, or it can be set directly from the Settings page."

    match = results[0]
    resolved_name = ", ".join(
        part for part in [match.get("name"), match.get("admin1"), match.get("country")] if part
    )
    tz_name = match.get("timezone")
    if not tz_name or not is_valid_timezone(tz_name):
        return f"Found '{resolved_name}' but couldn't determine its timezone — ask them to set it manually from the Settings page."

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
# Web Search
# ---------------------------------------------------------------------------

@tool
def web_search(query: str) -> str:
    """Search the web for current information.

    Args:
        query: The search query.
    """

    instance_url = os.environ.get("SEARXNG_URL")

    if not instance_url:
        logger.info("No SearXNG instance URL found. Skipping web search.")
        return f"Web search not yet connected. Query was: '{query}'"
    else:
        logger.info("Searching for: %s", query)


    # SearXNG: self-hosted, fully private
    # Define API parameters
    params = {
        'q': query,
        'format': 'json',  # Requests JSON response format
    }
        
    try:
        response = requests.get(f"{instance_url}/search", params=params, timeout=10)
        response.raise_for_status()
        return json.dumps(response.json())
    except requests.exceptions.RequestException as e:
        logger.error("Error connecting to SearXNG: %s", e)
        return f"Web search failed. Query was: '{query}'"
