"""
scratchpad/training_data/convert_for_handoff.py
---------------------------------------------------
Converts our tranche{1,2,3}.jsonl (id/source/source_thread_id/mode/
system_prompt/anchor_datetime/user_message/turns/expected_tool/notes/
verified_by) into the LoRA training repo's exact schema (id/source/group/
category/anchor/flags/history/text/turns/date_intents/notes), per
docs/HANDOFF_REQUESTS.md.

date_intents are hand-authored separately (DATE_INTENTS dict below) since
they require knowing which phrase in the original user_message produced
which resolved value -- not mechanically derivable from the stored data
alone.

Run from the repo root: uv run python scratchpad/training_data/convert_for_handoff.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agent.tool_router import CATEGORY_MAP  # noqa: E402

TZ = ZoneInfo("Australia/Canberra")

SOURCE_MAP = {
    "historical": "real",
    "voice_synthetic": "synthetic",
    "generic_synthetic": "synthetic",
}

# Continuity groups: examples that share entities/UIDs across turns, so
# paraphrase-style augmentation of any one of them should land in the same
# split as the others. Keyed by our id -> group tag.
GROUPS = {
    "T2-0004": "drinks-saturday", "T2-0006": "drinks-saturday",
    "T2-0008": "haircut-event", "T2-0009": "haircut-event", "T2-0011": "haircut-event", "T2-0037": "haircut-event",
    "T2-0019": "deck-note", "T2-0020": "deck-note", "T2-0021": "deck-note", "T2-0022": "deck-note", "T2-0032": "deck-note",
    "T2-0025": "priya-note", "T2-0031": "priya-note",
    "T2-0026": "pi-weather-project", "T2-0027": "pi-weather-project", "T2-0030": "pi-weather-project",
    "T1-0012": "c64-project", "T1-0013": "c64-project", "T1-0014": "c64-project",
    "T1-0005": "finian-reminders", "T1-0006": "finian-reminders", "T1-0007": "finian-reminders",
    "T1-0008": "brighton-chat", "T1-0009": "brighton-chat",
    "T1-0010": "gomez-chat", "T1-0011": "gomez-chat",
    "T3-0042": "umbrella-weather", "T3-0043": "umbrella-weather",  # placeholders, no-op if absent
}

# Hand-authored: id -> list of {"phrase": ..., "arg": "tool.field", "call": N (optional)}
DATE_INTENTS = {
    "T1-0005": [],  # no tool call -- clarifying question, no date resolved
    "T1-0006": [{"phrase": "this coming wednesday at 5:30 pm", "arg": "set_reminder.when"}],
    "T1-0007": [{"phrase": "on sunday", "arg": "add_calendar_event.start"}],
    "T2-0002": [{"phrase": "this tuesday", "arg": "get_calendar_events.start"}, {"phrase": "this tuesday", "arg": "get_calendar_events.end"}],
    "T2-0004": [{"phrase": "this saturday night 8pm", "arg": "add_calendar_event.start"}],
    "T2-0005": [{"phrase": "tomorrow", "arg": "get_calendar_events.start"}, {"phrase": "tomorrow", "arg": "get_calendar_events.end"}],
    "T2-0006": [{"phrase": "9pm instead", "arg": "update_calendar_event.start"}],
    "T2-0007": [{"phrase": "this week", "arg": "get_calendar_events.start"}, {"phrase": "this week", "arg": "get_calendar_events.end"}],
    "T2-0008": [{"phrase": "next friday afternoon, about an hour", "arg": "add_calendar_event.start"}],
    "T2-0012": [{"phrase": "until the end of the month", "arg": "get_calendar_events.end"}],
    "T2-0014": [],  # get_weather_forecast has no date argument at all (always "next 7 days from now") -- "tomorrow" isn't passed anywhere, nothing to validate
    "T1-0002": [{"phrase": "today", "arg": "generate_schedule_blocks.date"}],
    "T1-0003": [{"phrase": "today", "arg": "generate_schedule_blocks.date"}],
    "T1-0004": [{"phrase": "the saturday routine (today)", "arg": "generate_schedule_blocks.date"}],
    "T2-0015": [{"phrase": "next 5 days", "arg": "get_range_forecast.start"}, {"phrase": "next 5 days", "arg": "get_range_forecast.end"}],
    "T2-0017": [{"phrase": "the weekend", "arg": "get_range_forecast.start"}, {"phrase": "the weekend", "arg": "get_range_forecast.end"}],
    "T2-0035": [{"phrase": "tomorrow arvo", "arg": "set_reminder.when"}],
    # T2-0037: deliberately no date_intent -- the reminder time is computed
    # from the looked-up event's own start time, not resolved from the
    # anchor via a stated phrase, per the trainer's explicit instruction.
    "T2-0038": [{"phrase": "in 10 minutes", "arg": "set_reminder.when"}],
    "T2-0045": [{"phrase": "tomorrow", "arg": "add_planning_task.date"}],
    "T2-0046": [{"phrase": "today", "arg": "generate_schedule_blocks.date"}],
    "T2-0047": [{"phrase": "tomorrow", "arg": "add_planning_task.date"}, {"phrase": "tomorrow", "arg": "generate_schedule_blocks.date"}],
    "T3-0002": [{"phrase": "this saturday", "arg": "get_calendar_events.start"}, {"phrase": "this saturday", "arg": "get_calendar_events.end"}],
    "T3-0004": [],  # clarifying question, no date resolved
    "T3-0008": [{"phrase": "later", "arg": "set_reminder.when"}],
    "T3-0009": [],
    "T3-0010": [{"phrase": "in an hour", "arg": "set_reminder.when"}],
    "T3-0011": [
        {"phrase": "wednesday 2pm", "arg": "add_calendar_event.start", "call": 0},
        {"phrase": "friday 10am", "arg": "add_calendar_event.start", "call": 1},
        {"phrase": "saturday 1pm", "arg": "add_calendar_event.start", "call": 2},
    ],
    "T3-0013": [{"phrase": "today", "arg": "set_reminder.when"}],
    "T3-0014": [{"phrase": "tomorrow", "arg": "get_calendar_events.start"}, {"phrase": "tomorrow", "arg": "get_calendar_events.end"}, {"phrase": "tomorrow", "arg": "add_planning_task.date"}],
    "T3-0016": [{"phrase": "next tuesday", "arg": "get_calendar_events.start"}, {"phrase": "next tuesday", "arg": "get_calendar_events.end"}],
    "T3-0029": [],  # "rest of the week" -> plain get_weather_forecast, no explicit date arg on this tool
    "T3-0033": [{"phrase": "tomorrow", "arg": "get_calendar_events.start"}, {"phrase": "tomorrow", "arg": "get_calendar_events.end"}],
    "T3-0035": [{"phrase": "3pm", "arg": "set_reminder.when"}],
}


def to_category(record: dict) -> str:
    for turn in record["turns"]:
        for tc in turn.get("tool_calls", []):
            cat = CATEGORY_MAP.get(tc["name"])
            if cat:
                return cat
    return "no_tool"


def to_anchor(anchor_iso: str) -> str:
    naive = datetime.fromisoformat(anchor_iso)
    aware = naive.replace(tzinfo=TZ)
    return aware.isoformat()


def to_flags(record: dict) -> dict:
    flags = {"learning_mode": True}
    if record["mode"] == "one_shot":
        flags["one_shot"] = True
    elif record["mode"] == "day_planning":
        flags["mode"] = "day_planning"
    return flags


def to_turns(record: dict) -> list:
    out = []
    pending_calls = None
    pending_results = []
    for t in record["turns"]:
        if t["role"] == "assistant" and t.get("tool_calls"):
            if pending_calls is not None:
                out.append({"tool_calls": pending_calls, "content": ""})
                out.append({"tool_results": pending_results})
            pending_calls = t["tool_calls"]
            pending_results = []
        elif t["role"] == "tool":
            pending_results.append(t["content"])
        elif t["role"] == "assistant":
            if pending_calls is not None:
                out.append({"tool_calls": pending_calls, "content": ""})
                out.append({"tool_results": pending_results})
                pending_calls = None
                pending_results = []
            out.append({"content": t["content"]})
    return out


def convert(record: dict) -> dict:
    out = {
        "id": record["id"],
        "source": SOURCE_MAP[record["source"]],
        "category": to_category(record),
        "anchor": to_anchor(record["anchor_datetime"]),
        "flags": to_flags(record),
        "text": record["user_message"],
        "turns": to_turns(record),
        "notes": record["notes"],
    }
    if record["id"] in GROUPS:
        out["group"] = GROUPS[record["id"]]
    intents = DATE_INTENTS.get(record["id"])
    if intents:
        out["date_intents"] = intents
    if record.get("history"):
        out["history"] = record["history"]
    return out


def main():
    out_records = []
    for path in ["tranche1.jsonl", "tranche2.jsonl", "tranche3.jsonl"]:
        for line in open(Path(__file__).parent / path):
            if line.strip():
                out_records.append(convert(json.loads(line)))

    out_path = Path(__file__).parent / "handoff_batch.jsonl"
    with open(out_path, "w") as f:
        for r in out_records:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(out_records)} converted records to {out_path}")


if __name__ == "__main__":
    main()
