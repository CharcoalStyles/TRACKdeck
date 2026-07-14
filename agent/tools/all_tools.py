"""
agent/tools.py
--------------
Stub tools for the personal assistant.

Each tool is a plain Python function decorated with @tool.
LangGraph's ToolNode will call whichever one the LLM picks.

"""
from langchain_core.tools import tool

from agent.memory import MemoryStore

from agent.tools.alerts import set_reminder, set_timer
from agent.tools.calendar import get_tools as get_calendar_tools
from agent.tools.general import get_current_datetime, web_search
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
        web_search,
    ])

    return tools