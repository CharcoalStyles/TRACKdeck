"""
agent/tools/all_tools.py
------------------------
The v2 tool registry: 18 local tools (6 calendar, 4 reminder/timer, 2 planning,
3 weather, get_reflection_prompt, jot_note, fetch_webpage) plus search_web from
the MCP server (get_mcp_tools) = 19. tests/test_tool_registry.py pins the names.
"""
import logging

from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.types import CallToolResult, TextContent

from agent.settings import settings

from agent.tools.alerts import cancel_reminder, list_reminders, set_reminder, set_timer
from agent.tools.calendar import get_tools as get_calendar_tools
from agent.tools.checkin import get_reflection_prompt
from agent.tools.jot import jot_note
from agent.tools.general import fetch_webpage
from agent.tools.planning import get_tools as get_planning_tools
from agent.tools.weather import get_tools as get_weather_tools

logger = logging.getLogger(__name__)

# Roughly ~3000 tokens — generous for one tool result, but small enough that
# a handful of them plus conversation history still fit the local model's
# context. Needed because MCP servers are semi-trusted third-party code that
# doesn't bound its own output — e.g. a "fetch this page" tool returning an
# entire Wikipedia article (500KB+) verbatim would blow the context budget
# in a single tool call.
_MCP_TOOL_RESULT_CHAR_LIMIT = 12000


async def _truncate_large_mcp_results(request, handler):
    """MultiServerMCPClient tool_interceptor — caps any MCP tool's text
    output, applied to every configured server (not just one), since any
    of them could return an unbounded amount of text."""
    result = await handler(request)
    if isinstance(result, CallToolResult):
        for block in result.content:
            if isinstance(block, TextContent) and len(block.text) > _MCP_TOOL_RESULT_CHAR_LIMIT:
                total = len(block.text)
                block.text = block.text[:_MCP_TOOL_RESULT_CHAR_LIMIT] + f"\n\n[...truncated, {total} chars total]"
    return result

# ---------------------------------------------------------------------------
# Tool registry — imported by graph.py
# ---------------------------------------------------------------------------

def get_tools():

    tools = []

    tools.extend(get_calendar_tools())
    tools.extend(get_weather_tools())
    tools.extend(get_planning_tools())
    tools.extend([
        set_reminder,
        set_timer,
        list_reminders,
        cancel_reminder,
        get_reflection_prompt,
        jot_note,
        fetch_webpage,
    ])

    return tools


# searxng-mcp-server also exposes search_images/videos/news and fetch_url; v2 binds only search_web.
MCP_TOOL_ALLOWLIST = {"search_web"}


def filter_mcp_tools(tools: list) -> list:
    return [t for t in tools if t.name in MCP_TOOL_ALLOWLIST]


async def get_mcp_tools() -> list:
    """Fetches tools from every enabled server in settings.mcp_servers
    (see agent/settings.py). Each server is loaded independently — one
    misconfigured/unreachable server (bad command, server down, etc.)
    only drops that server's tools and logs a warning, rather than
    failing startup the way MultiServerMCPClient.get_tools() would if
    called for all servers in one batched call (any one exception fails
    every task in that gather)."""
    configs = settings.mcp_server_configs()
    if not configs:
        return []

    client = MultiServerMCPClient(configs, tool_interceptors=[_truncate_large_mcp_results])
    tools = []
    for name in configs:
        try:
            loaded = await client.get_tools(server_name=name)
            tools.extend(filter_mcp_tools(loaded))
        except Exception:
            logger.exception("Could not load tools from MCP server '%s' — skipping it.", name)
    return tools
