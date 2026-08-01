"""
agent/tools.py
--------------
Stub tools for the personal assistant.

Each tool is a plain Python function decorated with @tool.
LangGraph's ToolNode will call whichever one the LLM picks.

"""
from langchain_core.tools import tool

from agent.memory import MemoryStore

from agent.tools.activity_log import log_activity
from agent.tools.alerts import cancel_reminder, list_reminders, set_reminder, set_timer
from agent.tools.calendar import get_tools as get_calendar_tools
from agent.tools.checkin import get_reflection_prompt
from agent.tools.general import (
    get_current_datetime,
    mark_onboarding_complete,
    set_home_location,
    web_search,
)
from agent.tools.notes import make_note_tools
from agent.tools.weather import get_tools as get_weather_tools

# ---------------------------------------------------------------------------
# Tool registry — imported by graph.py
# ---------------------------------------------------------------------------

def get_tools(memory: MemoryStore):

    tools = []

    tools.extend(get_calendar_tools())
    tools.extend(get_weather_tools())
    tools.extend(make_note_tools(memory))
    tools.extend([
        get_current_datetime,
        set_reminder,
        set_timer,
        list_reminders,
        cancel_reminder,
        get_reflection_prompt,
        web_search,
        mark_onboarding_complete,
        set_home_location,
        log_activity,
    ])

    return tools