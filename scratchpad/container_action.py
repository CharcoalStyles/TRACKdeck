"""Runs ONE authenticated HTTP action against the app inside its own
container (so $API_TOKEN never leaves the container's process). Reads a
single JSON object from stdin describing the action, prints a single JSON
object to stdout with the result. Invoked via:

    docker exec -i pa-assistant-learning /app/.venv/bin/python - < payload.json
    (with this file's contents piped in as the script, payload as argv[1] JSON,
     or -- simpler here -- the payload is read from stdin as JSON directly)

Actions: switch_model {model}, post_text {text, thread_id}, get_thread {thread_id},
set_tool_router {enabled}, set_tool_suggestion {enabled}
"""
import json
import os
import sys

import httpx

payload = json.loads(sys.argv[1])
action = payload["action"]
h = {"auth": os.environ.get("API_TOKEN", "")}
base = "http://localhost:8000"
out = {}

try:
    if action == "switch_model":
        r = httpx.post(f"{base}/settings", headers=h, json={"lmstudio_chat_model": payload["model"]}, timeout=30)
        out = {"ok": r.status_code == 200, "status": r.status_code}
    elif action == "post_text":
        r = httpx.post(
            f"{base}/text", headers=h,
            json={"text": payload["text"], "thread_id": payload["thread_id"], "one_shot": True},
            timeout=payload.get("timeout", 120),
        )
        out = {"ok": r.status_code == 200, "status": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:500]}
    elif action == "get_thread":
        r = httpx.get(f"{base}/debug/thread/{payload['thread_id']}", headers=h, timeout=30)
        out = {"ok": r.status_code == 200, "status": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:500]}
    elif action == "set_tool_router":
        r = httpx.post(f"{base}/settings", headers=h, json={"tool_router_enabled": payload["enabled"]}, timeout=30)
        out = {"ok": r.status_code == 200, "status": r.status_code}
    elif action == "set_tool_suggestion":
        r = httpx.post(f"{base}/settings", headers=h, json={"tool_suggestion_enabled": payload["enabled"]}, timeout=30)
        out = {"ok": r.status_code == 200, "status": r.status_code}
    elif action == "list_models":
        r = httpx.get(f"{base}/debug/lmstudio-models", headers=h, timeout=15)
        out = {"ok": r.status_code == 200, "status": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:500]}
    else:
        out = {"ok": False, "error": f"unknown action {action}"}
except Exception as e:
    out = {"ok": False, "error": f"{type(e).__name__}: {e}"}

print(json.dumps(out))
