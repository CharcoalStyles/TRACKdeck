"""
Run one synthetic prompt against a running instance (the learning stack by
default) and show exactly what tool(s) got called, if any -- the same
two-step flow the eventual full harness will use: POST /text, then GET
/debug/thread/{thread_id} for the unfiltered tool-call trace.

Run inside the target container so it can use the container's own
API_TOKEN without that secret ever passing through the host shell:

    docker exec -i pa-assistant-learning /app/.venv/bin/python - <<'EOF'
    <paste this file's contents, or `docker exec -i ... < scratchpad/run_single_test.py`>
    EOF

Or, simpler, since this file is on disk:
    docker exec -i pa-assistant-learning /app/.venv/bin/python - "your test message" < scratchpad/run_single_test.py
"""
import os
import sys

import httpx

TEST_MESSAGE = sys.argv[1] if len(sys.argv) > 1 else "Add a dentist appointment next Tuesday at 2pm"

h = {"auth": os.environ.get("API_TOKEN", "")}
base = "http://localhost:8000"

resp = httpx.post(f"{base}/text", headers=h, json={"text": TEST_MESSAGE, "one_shot": True}, timeout=60)
resp.raise_for_status()
data = resp.json()
thread_id = data["thread_id"]

print(f"USER:   {TEST_MESSAGE}")
print(f"REPLY:  {data['reply']}")
print(f"THREAD: {thread_id} (keyword: {data['keyword']})")
print()

debug = httpx.get(f"{base}/debug/thread/{thread_id}", headers=h, timeout=30).json()
called_any = False
for turn in debug["turns"]:
    if turn["type"] == "ai" and turn.get("tool_calls"):
        called_any = True
        for tc in turn["tool_calls"]:
            print(f"TOOL CALLED: {tc['name']}({tc['args']})")
    elif turn["type"] == "tool":
        content = (turn.get("content") or "")[:200]
        print(f"  -> result: {content}")

if not called_any:
    print("NO TOOL CALLED -- plain text reply only.")
