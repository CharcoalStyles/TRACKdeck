"""Phase B step 3: score baseline / embedding-similarity / Laya against the
Phase A labeled turn_dump.json. Standalone script, run with the project's
main venv (for agent.memory) -- Laya calls use a subprocess into the
pydecide scratch venv would be overkill; instead this script imports
`decide` directly by adding the scratch venv's site-packages to sys.path,
since both venvs are pure-Python-importable CPython 3.12 environments.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
from dotenv import dotenv_values

# --- make the pydecide scratch venv's packages importable here too ---
SCRATCH_SITE = Path(__file__).parent / "pydecide_venv" / "lib" / "python3.12" / "site-packages"
sys.path.insert(0, str(SCRATCH_SITE))
sys.path.insert(0, str(Path(__file__).parent.parent))  # project root, for `agent.*`

# --- load LM Studio config from .env.docker (the running container's config) ---
docker_env = dotenv_values(".env.docker")
os.environ["LMSTUDIO_OPENAI_URL"] = docker_env["LMSTUDIO_OPENAI_URL"]
os.environ["EMBEDDING_MODEL"] = docker_env["EMBEDDING_MODEL"]

from agent.memory import make_embedding_function  # noqa: E402
from decide import Choice, Client, Noul  # noqa: E402

TOOL_DESCRIPTIONS = {
    "get_current_datetime": "Get the current date and time for grounding relative time references.",
    "log_activity": "Log a completed activity or exercise with duration, mood, and reflection.",
    "set_reminder": "Schedule a one-off reminder for a specific future date and time.",
    "set_timer": "Start a short countdown timer for a duration from now.",
    "list_reminders": "List all pending reminders.",
    "cancel_reminder": "Cancel a previously scheduled reminder.",
    "get_todays_events": "List today's calendar events.",
    "get_calendar_event": "Get details of a specific calendar event by its ID.",
    "add_calendar_event": "Create a new event on the calendar.",
    "delete_calendar_event": "Delete an existing calendar event by its ID.",
    "get_calendar_events": "List calendar events within a given date range.",
    "update_calendar_event": "Update an existing calendar event's details.",
    "get_reflection_prompt": "Serve a reflective check-in prompt on demand.",
    "get_current_datetime_alt": "unused",
    "mark_onboarding_complete": "Mark the onboarding interview as finished.",
    "set_home_location": "Set the user's home location for weather/default lookups.",
    "fetch_webpage": "Fetch and summarize the content of a specific webpage URL.",
    "append_to_note": "Add text to one section of an existing note in the vault.",
    "update_note_section": "Replace the content of one section of a note.",
    "read_note": "Read the contents of a note from the vault.",
    "save_note": "Create a new note in the vault, optionally from a template.",
    "search_notes": "Search the notes vault for relevant notes.",
    "remember_about_me": "Record a durable fact about the user in their profile.",
    "read_about_me": "Read the user's About Me profile note.",
    "get_or_create_linked_note": "Find or create a linked note about a specific person or topic.",
    "list_projects": "List existing projects.",
    "get_or_create_project": "Find or create a project note.",
    "add_planning_task": "Add a task with an estimated duration to a day's plan.",
    "generate_schedule_blocks": "Generate a day's schedule of fixed and task time blocks.",
    "get_current_weather": "Get the current weather conditions for a location.",
    "get_weather_forecast": "Get the weather forecast for upcoming days.",
    "get_range_forecast": "Get the weather forecast for a specific date range.",
    "search_web": "Search the web for current information not known locally.",
    "search_news": "Search for recent news articles.",
    "no_tool_needed": "General conversation, question already answered, or no capability exists for this — a plain text reply is sufficient.",
}
del TOOL_DESCRIPTIONS["get_current_datetime_alt"]
TOOL_NAMES = list(TOOL_DESCRIPTIONS)


def cosine(a, b):
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def main():
    data = json.load(open("scratchpad/turn_dump.json"))
    degenerate = {"session_1789475541_17eaf9", "session_1789544729_db6d40"}
    clean = [r for r in data if r["thread_id"] not in degenerate]
    print(f"Full dataset: {len(data)}, after excluding 2 degenerate threads: {len(clean)}")

    # --- embedding baseline: precompute tool description embeddings once ---
    embedder = make_embedding_function()
    tool_vecs = {}
    try:
        vecs = embedder.embed_documents(list(TOOL_DESCRIPTIONS.values()))
        tool_vecs = dict(zip(TOOL_NAMES, vecs))
        embedding_reachable = True
    except Exception as exc:
        print("EMBEDDING BASELINE UNAVAILABLE:", type(exc).__name__, str(exc)[:200])
        embedding_reachable = False

    # --- laya client ---
    laya_client = Client.from_env()

    results = []
    emb_agree = laya_agree = total_scored = 0
    for r in clean:
        actual_tools = sorted({tc["tool_name"] for tc in r["tool_calls"]}) or ["no_tool_needed"]
        rec = {"thread_id": r["thread_id"], "user_message": r["user_message"], "label": r["label"], "actual": actual_tools}

        if embedding_reachable:
            try:
                msg_vec = embedder.embed_query(r["user_message"])
                sims = {name: cosine(msg_vec, v) for name, v in tool_vecs.items()}
                emb_choice = max(sims, key=sims.get)
                rec["embedding_choice"] = emb_choice
                rec["embedding_agrees"] = emb_choice in actual_tools
                emb_agree += int(rec["embedding_agrees"])
            except Exception as exc:
                rec["embedding_choice"] = f"ERROR: {exc}"

        try:
            noul = laya_client.decide(
                r["user_message"],
                {"needs_tool": Noul(instructions="Does responding to this message require calling a tool/function?")},
            )["needs_tool"].noul
            if noul < 0.5:
                laya_choice = "no_tool_needed"
            else:
                choice_resp = laya_client.decide(
                    r["user_message"],
                    {"tool": Choice(instructions="Which tool should be called for this request?", criteria={k: v for k, v in TOOL_DESCRIPTIONS.items() if k != "no_tool_needed"})},
                )
                laya_choice = choice_resp["tool"].choice
            rec["laya_choice"] = laya_choice
            rec["laya_agrees"] = laya_choice in actual_tools
            laya_agree += int(rec["laya_agrees"])
        except Exception as exc:
            rec["laya_choice"] = f"ERROR: {exc}"

        total_scored += 1
        results.append(rec)

    print(f"\nAgreement-with-actual-choice across {total_scored} clean (non-degenerate) turns:")
    print(f"  embedding-similarity: {emb_agree}/{total_scored} = {100*emb_agree/total_scored:.1f}%")
    print(f"  laya zero-shot:       {laya_agree}/{total_scored} = {100*laya_agree/total_scored:.1f}%")

    out_path = Path("scratchpad/phase_b_results.json")
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nWrote {len(results)} scored records to {out_path}")


if __name__ == "__main__":
    main()
