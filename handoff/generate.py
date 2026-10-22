"""Regenerates handoff/*.json and *.txt from the live code. Run from the repo root:
    API_TOKEN=t DASHBOARD_PASSWORD=p SESSION_SECRET_KEY=s VAULT_PATH=<tmp> EVENT_LOG_DIR=<tmp> \
    LMSTUDIO_OPENAI_URL=http://x/v1 LMSTUDIO_CHAT_MODEL=x .venv/bin/python handoff/generate.py
Needs a stub faster_whisper if it is not installed. search_web comes from the MCP server, so
its schema is read from handoff/search_web.mcp.json (captured once from searxng-mcp-server)."""
import json
import sys
from pathlib import Path

from langchain_core.utils.function_calling import convert_to_openai_tool

sys.path.insert(0, ".")
from agent import graph
from agent.settings import settings
from agent.tools.all_tools import get_tools

out = Path("handoff")
mcp = json.loads((out / "search_web.mcp.json").read_text())
search_web = {
    "type": "function",
    "function": {"name": mcp["name"], "description": mcp["description"], "parameters": mcp["inputSchema"]},
}
tools = [convert_to_openai_tool(t) for t in get_tools()] + [search_web]
assert len(tools) == 19

(out / "system_prompt.txt").write_text(graph.SYSTEM_PROMPT)
(out / "addendum_one_shot.txt").write_text(graph.ONE_SHOT_ADDENDUM)
(out / "addendum_day_planning.txt").write_text(graph.DAY_PLANNING_ADDENDUM)
(out / "tools.json").write_text(json.dumps(tools, indent=2) + "\n")
(out / "mode_tools.json").write_text(json.dumps(graph.MODE_TOOL_NAMES, indent=2) + "\n")

import main  # noqa: E402

(out / "settings.defaults.json").write_text(json.dumps(main._current_settings(), indent=2) + "\n")
(out / "settings.schema.json").write_text(json.dumps(main.SettingsResponse.model_json_schema(), indent=2) + "\n")
print("ok", len(tools), "tools")
