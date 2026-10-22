"""
Host-side orchestrator for the multi-model tool-calling eval. Every
authenticated call happens inside the pa-assistant-learning container (via
`docker exec ... python -c ...`, argv-list subprocess -- never shell=True,
so arbitrary prompt text with quotes/newlines is safe) using
scratchpad/container_action.py, so $API_TOKEN never leaves the container's
own process / never appears in this script's output.

Checkpoints scratchpad/eval_results.json after every single (model, prompt)
result -- safe to re-run; it skips any (model, prompt) pair already present
in the existing results file, so a crash/interrupt loses at most one
in-flight call.

Pass --router anywhere in argv to flip agent/settings.py's tool_router_enabled
on before the sweep and off again after -- results go to a separate file
(scratchpad/eval_results_router.json) since its (model, prompt_id) dedup
would otherwise collide with the already-saved router-off baseline. Pass
--suggest likewise for tool_suggestion_enabled, writing to
scratchpad/eval_results_suggestion.json -- the two flags are mutually
exclusive (each is its own independent A/B condition against the
router/suggestion-off baseline, not meant to be combined for a first pass).

Usage: .venv/bin/python scratchpad/run_eval_sweep.py <model_id> [<model_id> ...] [--router|--suggest]
"""
import json
import subprocess
import sys
import time
import uuid

CONTAINER = "pa-assistant-learning"
ACTION_SCRIPT = open("scratchpad/container_action.py").read()
PROMPTS_PATH = "scratchpad/eval_prompts.json"


def call(payload: dict, timeout=200) -> dict:
    proc = subprocess.run(
        ["docker", "exec", CONTAINER, "/app/.venv/bin/python", "-c", ACTION_SCRIPT, json.dumps(payload)],
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        return {"ok": False, "error": f"docker exec exit {proc.returncode}: {proc.stderr[-500:]}"}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"ok": False, "error": f"bad output: {e}: {proc.stdout[-300:]}"}


def load_results(results_path):
    try:
        return json.load(open(results_path))
    except FileNotFoundError:
        return []


def save_results(results, results_path):
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)


def main():
    args = sys.argv[1:]
    router = "--router" in args
    suggest = "--suggest" in args
    if router and suggest:
        print("--router and --suggest are mutually exclusive")
        sys.exit(1)
    models = [a for a in args if a not in ("--router", "--suggest")]
    if not models:
        print("Usage: run_eval_sweep.py <model_id> [<model_id> ...] [--router|--suggest]")
        sys.exit(1)

    if router:
        results_path = "scratchpad/eval_results_router.json"
    elif suggest:
        results_path = "scratchpad/eval_results_suggestion.json"
    else:
        results_path = "scratchpad/eval_results.json"

    if router:
        r = call({"action": "set_tool_router", "enabled": True}, timeout=30)
        print(f"tool_router_enabled=True: {r}", flush=True)
    if suggest:
        r = call({"action": "set_tool_suggestion", "enabled": True}, timeout=30)
        print(f"tool_suggestion_enabled=True: {r}", flush=True)

    prompts = json.load(open(PROMPTS_PATH))
    results = load_results(results_path)
    done = {(r["model"], r["prompt_id"]) for r in results}

    for model in models:
        print(f"=== switching to {model} ===", flush=True)
        t0 = time.monotonic()
        sw = call({"action": "switch_model", "model": model}, timeout=30)
        print(f"switch result: {sw}", flush=True)

        for p in prompts:
            key = (model, p["id"])
            if key in done:
                continue
            thread_id = f"eval-{abs(hash(model))%100000}-{p['id']}-{uuid.uuid4().hex[:8]}"
            t1 = time.monotonic()
            # generous timeout on the first call per model (JIT load), shorter after
            first_for_model = not any(r["model"] == model for r in results)
            text_resp = call(
                {"action": "post_text", "text": p["text"], "thread_id": thread_id,
                 "timeout": 180 if first_for_model else 90},
                timeout=200,
            )
            record = {
                "model": model, "prompt_id": p["id"], "thread_id": thread_id,
                "elapsed_s": round(time.monotonic() - t1, 1),
                "text_ok": text_resp.get("ok"),
            }
            if text_resp.get("ok"):
                thread_resp = call({"action": "get_thread", "thread_id": thread_id}, timeout=40)
                if thread_resp.get("ok"):
                    turns = thread_resp["body"]["turns"]
                    tool_calls = []
                    router_decisions = []
                    suggestion_decisions = []
                    for t in turns:
                        if t["type"] == "ai" and t.get("tool_calls"):
                            tool_calls.extend(t["tool_calls"])
                        if t["type"] == "ai" and "router_reason" in t:
                            router_decisions.append({
                                "categories": t.get("router_categories"),
                                "probabilities": t.get("router_probabilities"),
                                "reason": t.get("router_reason"),
                            })
                        if t["type"] == "ai" and "suggestion_reason" in t:
                            suggestion_decisions.append({
                                "suggested": t.get("suggested_tools"),
                                "probabilities": t.get("suggestion_probabilities"),
                                "reason": t.get("suggestion_reason"),
                            })
                    record["reply"] = text_resp["body"].get("reply")
                    record["tool_calls"] = tool_calls
                    if router:
                        record["router_decisions"] = router_decisions
                    if suggest:
                        record["suggestion_decisions"] = suggestion_decisions
                else:
                    record["error"] = f"get_thread failed: {thread_resp}"
            else:
                record["error"] = f"post_text failed: {text_resp}"

            results.append(record)
            save_results(results, results_path)
            status = "OK" if text_resp.get("ok") else "FAIL"
            n_tools = len(record.get("tool_calls", []))
            print(f"  [{model}] {p['id']} {status} ({record['elapsed_s']}s, {n_tools} tool call(s))", flush=True)

        print(f"=== {model} done in {round(time.monotonic()-t0, 1)}s ===", flush=True)

    if router:
        r = call({"action": "set_tool_router", "enabled": False}, timeout=30)
        print(f"tool_router_enabled=False: {r}", flush=True)
    if suggest:
        r = call({"action": "set_tool_suggestion", "enabled": False}, timeout=30)
        print(f"tool_suggestion_enabled=False: {r}", flush=True)


if __name__ == "__main__":
    main()
