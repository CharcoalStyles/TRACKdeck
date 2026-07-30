import json
import logging
from typing import Optional
from datetime import datetime

from langchain_core.tools import tool
import requests
import os

from agent.settings import settings
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
