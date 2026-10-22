"""
agent/tools/jot.py
--------------------
jot_note: save what the user just said as a line in today's Daily Notes
capture list. Takes no arguments on purpose — the app stores the user's raw
message (handed over through the run config), so a small tool model can't
paraphrase, truncate or invent the text; its only job is to choose this tool.
"""
from __future__ import annotations

from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from agent.settings import settings
from utils import daily_notes, event_log


def save_capture(text: str, source: str, via: str) -> str:
    """Append `text` to today's captures and log its provenance. `via` says
    how it got there: "tool" (the model chose jot_note) or "fallback" (a
    one-shot turn where no tool was chosen)."""
    capture_id = daily_notes.append_capture(datetime.now(settings.zoneinfo()), text)
    event_log.log_event("capture", capture_id=capture_id, source=source, via=via, text=" ".join(text.split()))
    return capture_id


@tool
def jot_note(config: RunnableConfig) -> str:
    """Save the user's message as a quick note on today's capture list.
    Use it when they want something remembered or written down — a thought,
    an idea, something to do later, "note that...", "remember to..." — and it
    is not a calendar event, a timed reminder or a timer. Takes no arguments:
    the app saves their exact words."""
    cfg = (config or {}).get("configurable", {})
    text = str(cfg.get("user_text") or "").strip()
    if not text:
        return "Error: there was no message to save."
    try:
        save_capture(text, source=str(cfg.get("source") or "unknown"), via="tool")
    except OSError as e:
        return f"Error: could not save the note ({e})."
    return "Saved to today's captures."
