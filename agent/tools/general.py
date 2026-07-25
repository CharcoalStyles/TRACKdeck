import json
from typing import Optional
from datetime import datetime

from langchain_core.tools import tool
import requests
import os

from agent.settings import settings


# ---------------------------------------------------------------------------
# Time & Date
# ---------------------------------------------------------------------------

@tool
def get_current_datetime() -> str:
    """Returns the current date and time. Use this whenever you need to know the current time or date. It can help with finding the nearest specific day"""

    now = datetime.now(settings.zoneinfo())
    now_string = now.strftime("%-I:%M %p on %A %-d %B %Y")
    print(f"Current date and time: {now_string}")
    return f"The current date and time is: {now_string}"

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
        print("No SearXNG instance URL found. Skipping web search.")
        return "Web search not yet connected. Query was: '{query}'"
    else:
        print(f"Searching for: {query}")
        
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
        print(f"Error connecting to SearXNG: {e}")
        return f"Web search failed. Query was: '{query}'"
