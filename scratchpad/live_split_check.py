"""Live check of the LFM + Gemma split. Run ONLY after the trainer reports v3 done.

Usage (from anywhere):  .venv/bin/python scratchpad/live_split_check.py [--tool-id ID] [--writer-id ID]

Runs in an isolated scratch cwd/vault so the real ./data is never touched. Builds the real
graph with real LM Studio models, runs a fixed prompt set across modes, and writes
report.json / report.md into the scratch dir (path printed at the end).
"""
import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--tool-id", default="lfm2.5-1.2b-tools-v1")
ap.add_argument("--writer-id", default="gemma-4-e4b-it")
ap.add_argument("--out", default=None)
args = ap.parse_args()

scratch = Path(args.out or tempfile.mkdtemp(prefix="live_split_"))
(scratch / "data").mkdir(parents=True, exist_ok=True)
(scratch / "vault").mkdir(exist_ok=True)
for name in (".models", "static", "frontend"):
    src, dst = REPO / name, scratch / name
    if src.exists() and not dst.exists():
        dst.symlink_to(src)

from dotenv import dotenv_values  # noqa: E402

_docker_env = dotenv_values(REPO / ".env.docker")
for _k in ("LMSTUDIO_OPENAI_URL", "LMSTUDIO_MANAGEMENT_URL", "EMBEDDING_MODEL"):
    if _docker_env.get(_k):
        os.environ[_k] = _docker_env[_k]
os.environ["VAULT_PATH"] = str(scratch / "vault")
os.chdir(scratch)
sys.path.insert(0, str(REPO))

sys.modules.setdefault("faster_whisper", MagicMock())

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from agent import graph as graph_mod  # noqa: E402
from agent.settings import settings  # noqa: E402
from utils import writer_log  # noqa: E402

settings.llm_provider = "lmstudio"
settings.lmstudio_chat_model = args.tool_id
settings.lmstudio_writer_model = args.writer_id
settings.tool_router_enabled = False
settings.tool_suggestion_enabled = False
writer_log.DB_PATH = str(scratch / "data" / "writer_log.db")
writer_log.init_db()

memory = MagicMock()
memory.search_conversations.return_value = []
graph_mod.log_recall = lambda *a, **k: None


try:
    g = graph_mod.build_graph(MemorySaver(), memory)
except TypeError:
    g = graph_mod.build_graph(MemorySaver(), memory, mcp_tools=None)

# (label, thread, mode kwargs, text)
CASES = [
    ("one_shot short confirm", "t-a", {"one_shot": True}, "remind me in 10 minutes to check the oven"),
    ("one_shot plain chat", "t-b", {"one_shot": True}, "hey, how's it going?"),
    ("default chat (no tools)", "t-c", {}, "give me a few ideas for a rainy Sunday with a six year old"),
    ("weather (tool, error path likely or short)", "t-d", {"one_shot": True}, "what's the weather like today"),
    ("calendar add", "t-e", {"one_shot": True}, "put a dentist appointment on next Tuesday at 3pm"),
    ("note save", "t-f", {}, "save a note called garden ideas: plant tomatoes along the south fence, add a compost bin near the shed, and look into drip irrigation for the raised beds before summer"),
    ("learning fact", "t-g", {}, "remember that I don't eat mushrooms"),
    ("onboarding", "onboarding", {"mode": "onboarding"}, "hi, let's get started"),
    ("profile_chat", "profile_chat", {"mode": "profile_chat"}, "what do you know about me so far?"),
    ("day_planning", "t-h", {"mode": "day_planning"}, "plan my day: gym at 7, work 9 to 5, groceries after"),
    ("project_chat", "t-i", {"mode": "project_chat"}, "what's a good way to structure a small garden project?"),
]


async def main():
    rows = []
    for label, thread, kw, text in CASES:
        cfg = {"configurable": {"thread_id": thread, **kw}}
        t0 = time.time()
        err = None
        reply = None
        try:
            res = await asyncio.wait_for(
                g.ainvoke({"messages": [{"role": "user", "content": text}]}, config=cfg), timeout=240
            )
            reply = res["messages"][-1].content
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
        rows.append({
            "label": label, "mode": kw, "prompt": text, "reply": reply,
            "seconds": round(time.time() - t0, 1), "error": err,
            "log": writer_log.get_writer_log(thread_id=thread, limit=10),
        })
        print(f"[{len(rows)}/{len(CASES)}] {label}: {rows[-1]['seconds']}s {'ERR ' + err if err else 'ok'}", flush=True)
    return rows


rows = asyncio.run(main())
(scratch / "report.json").write_text(json.dumps(rows, indent=2, default=str))
lines = ["# Live split check\n"]
for r in rows:
    routes = ", ".join(f"{x['kind']}={x['route']}({x['reason']})" for x in reversed(r["log"])) or "no writer decision logged"
    lines.append(f"## {r['label']}  ({r['seconds']}s)\n- prompt: {r['prompt']}\n- decisions: {routes}\n- error: {r['error']}\n- reply: {r['reply']}\n")
(scratch / "report.md").write_text("\n".join(lines))
n_writer = sum(1 for r in rows for x in r["log"] if x["route"] == "writer")
n_fb = sum(1 for r in rows for x in r["log"] if x["route"] == "fallback")
n_err = sum(1 for r in rows if r["error"])
print(f"DONE cases={len(rows)} writer={n_writer} fallback={n_fb} errors={n_err} report={scratch}/report.md")
