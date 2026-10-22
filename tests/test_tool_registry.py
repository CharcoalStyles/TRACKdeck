from agent import graph as graph_mod
from agent.tools.all_tools import get_tools

V2_LOCAL_TOOLS = {
    "get_todays_events", "get_calendar_events", "add_calendar_event", "update_calendar_event",
    "move_calendar_event", "delete_calendar_event",
    "set_reminder", "set_timer", "list_reminders", "cancel_reminder",
    "add_planning_task", "generate_schedule_blocks",
    "get_current_weather", "get_weather_forecast", "get_range_forecast",
    "get_reflection_prompt", "jot_note", "fetch_webpage",
}


def test_local_registry_is_exactly_the_v2_tools():
    names = [t.name for t in get_tools()]
    assert len(names) == len(set(names)) == 18
    assert set(names) == V2_LOCAL_TOOLS  # search_web (MCP) makes 19


def test_mode_tool_sets_only_name_registered_tools():
    for names in graph_mod.MODE_TOOL_NAMES.values():
        assert set(names) <= V2_LOCAL_TOOLS
