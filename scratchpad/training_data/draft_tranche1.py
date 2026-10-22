"""
scratchpad/training_data/draft_tranche1.py
---------------------------------------------
Hand-authored tranche-1 (real-voice) pilot examples. Each EXAMPLES entry is
authored directly (not generated), using the REAL user_message captured in
turn_dump.json/recall_log.db (see scratchpad/training_data/ for the
selection work), paired with a freshly-verified tool call + reply — never
the historical model's own (often-wrong) output.

Run from the repo root: uv run python scratchpad/training_data/draft_tranche1.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # repo root, for agent.graph

from date_resolver import next_weekday, this_weekday, in_days, a_week_from  # noqa: E402

from agent.graph import SYSTEM_PROMPT, ONE_SHOT_ADDENDUM, DAY_PLANNING_ADDENDUM  # noqa: E402
from utils.datetime import format_now_human  # noqa: E402


def render_system(anchor: datetime, addendum: str = "") -> str:
    """Mirrors agent/graph.py's call_llm system-message assembly (addendum +
    datetime_block; memory_block is per-turn recall, not reproducible/
    relevant for an isolated training example, so omitted)."""
    datetime_block = f"\n\nCURRENT DATE AND TIME: {format_now_human_for(anchor)}"
    return SYSTEM_PROMPT + addendum + datetime_block


def format_now_human_for(dt: datetime) -> str:
    """Same format as utils/datetime.py's format_now_human, but for an
    arbitrary anchor instead of the real current time."""
    return dt.strftime("%-I:%M %p on %A %-d %B %Y")


EXAMPLES = []


def add(id_, thread_id, mode, anchor, user_message, turns, expected_tool, notes, history=None):
    addendum = ONE_SHOT_ADDENDUM if mode == "one_shot" else (DAY_PLANNING_ADDENDUM if mode == "day_planning" else "")
    EXAMPLES.append({
        "id": id_,
        "source": "historical",
        "source_thread_id": thread_id,
        "mode": mode,
        "system_prompt": render_system(anchor, addendum),
        "anchor_datetime": anchor.isoformat(),
        "user_message": user_message,
        "turns": turns,
        "expected_tool": expected_tool,
        "notes": notes,
        "verified_by": "draft-unverified",
        "history": history,
    })


# ---- T1-0001: day planning, absolute dates already in the message (no resolver needed) ----
add(
    "T1-0001", "day_planning:2026-09-19", "day_planning", datetime(2026, 9, 19, 7, 0),
    "Plan my day for 2026-09-19. Tasks:\n1. clean kitchen — 25 mins\n2. clean lounge — 20 mins\n"
    "3. clean outside — 60 mins\n4. shop for meal prep — 60 mins\n5. meal prep — 90 mins\n\n"
    "Add each of these tasks to the planning note for 2026-09-19, then generate my schedule for that day.",
    [
        {"role": "assistant", "tool_calls": [{"name": "add_planning_task", "args": {"date": "2026-09-19", "task": "clean kitchen", "duration_minutes": 25}}]},
        {"role": "tool", "name": "add_planning_task", "content": "Added 'clean kitchen' (25 mins) to the planning note for 2026-09-19."},
        {"role": "assistant", "tool_calls": [{"name": "add_planning_task", "args": {"date": "2026-09-19", "task": "clean lounge", "duration_minutes": 20}}]},
        {"role": "tool", "name": "add_planning_task", "content": "Added 'clean lounge' (20 mins) to the planning note for 2026-09-19."},
        {"role": "assistant", "tool_calls": [{"name": "add_planning_task", "args": {"date": "2026-09-19", "task": "clean outside", "duration_minutes": 60}}]},
        {"role": "tool", "name": "add_planning_task", "content": "Added 'clean outside' (60 mins) to the planning note for 2026-09-19."},
        {"role": "assistant", "tool_calls": [{"name": "add_planning_task", "args": {"date": "2026-09-19", "task": "shop for meal prep", "duration_minutes": 60}}]},
        {"role": "tool", "name": "add_planning_task", "content": "Added 'shop for meal prep' (60 mins) to the planning note for 2026-09-19."},
        {"role": "assistant", "tool_calls": [{"name": "add_planning_task", "args": {"date": "2026-09-19", "task": "meal prep", "duration_minutes": 90}}]},
        {"role": "tool", "name": "add_planning_task", "content": "Added 'meal prep' (90 mins) to the planning note for 2026-09-19."},
        {"role": "assistant", "tool_calls": [{"name": "generate_schedule_blocks", "args": {"date": "2026-09-19"}}]},
        {"role": "tool", "name": "generate_schedule_blocks", "content": "Scheduled 5 tasks for 2026-09-19 starting at 09:00, with short breaks between sprints. Total: 255 mins."},
        {"role": "assistant", "content": "Added all 5 tasks to your 2026-09-19 planning note and generated the schedule — kitchen, lounge, and outside cleaning, then shopping and meal prep, starting at 9am with breaks between each."},
    ],
    "add_planning_task|generate_schedule_blocks",
    "Real message, dates already absolute in the text — no relative-date resolution needed. 5x add_planning_task then one generate_schedule_blocks call is the exact multi-part pattern the SYSTEM_PROMPT's 'MANDATORY: Multi-Part Requests' section asks for.",
)

# ---- T1-0002: regenerate today's remaining schedule, "today" = the anchor itself ----
add(
    "T1-0002", "session_1789176034_3c0af4", "interactive", datetime(2026, 10, 6, 11, 0),
    "As part of my break I did a bit of rebuild of the back end as I wasn't getting notifications "
    "or alerts on the device for each of the steps throughout today that you've planned. What I'll "
    "need you to do is from the clean up work study through to the end of the plans for today, "
    "delete them and rebuild them as they were, you should now have an option to actually allow it "
    "to send alerts and that is something that I need for this process to work.",
    [
        {"role": "assistant", "tool_calls": [{"name": "generate_schedule_blocks", "args": {"date": "2026-10-06"}}]},
        {"role": "tool", "name": "generate_schedule_blocks", "content": "Scheduled 4 tasks for 2026-10-06 starting at 11:00, with short breaks between sprints. Total: 180 mins."},
        {"role": "assistant", "content": "Rebuilt today's remaining schedule from 'clean up work study' onward — let me know if a notification doesn't come through on one of the steps and we can look into it further."},
    ],
    "generate_schedule_blocks",
    "Real message — the 'allow it to send alerts' ask can't actually be verified or explained by the model (no tool surfaces that detail), so the correct reply stays within what the tool result supports rather than asserting internal app behavior (alert-sound defaults) it has no way to know from its prompt or tools.",
)

# ---- T1-0003: regenerate with different break lengths, 'today' = anchor ----
add(
    "T1-0003", "session_1789169716_d38449", "interactive", datetime(2026, 10, 7, 9, 0),
    "Okay, I'm looking at the routine that you've set up for today and I see that there are no "
    "breaks in between The things that you've got me to do No, I definitely need breaks about "
    "every maybe I know 15 20 25 minutes Can you delete what you've done and try again? Thanks",
    [
        {"role": "assistant", "tool_calls": [{"name": "generate_schedule_blocks", "args": {"date": "2026-10-07"}}]},
        {"role": "tool", "name": "generate_schedule_blocks", "content": "Scheduled 4 tasks for 2026-10-07 starting at 09:00, with short breaks between sprints. Total: 180 mins."},
        {"role": "assistant", "content": "Regenerated today's schedule — one thing to flag though: break length between sprints isn't something I can actually configure, it's fixed on my end. I can space the tasks out differently if that'd help instead."},
    ],
    "generate_schedule_blocks",
    "Real message — 'maybe I know 15 20 25 minutes' sounds like a configurable request, but generate_schedule_blocks only takes date/start_time/end_time; break length is fixed internally (agent/tools/planning.py has no break-duration parameter at all). Correct behavior is being honest about that limit, not fabricating a break_minutes arg that doesn't exist on the real tool.",
)

# ---- T1-0004: Saturday routine starting at a specific time, 'Saturday' = anchor ----
add(
    "T1-0004", "session_1789169064_1e99d9", "interactive", datetime(2026, 10, 10, 9, 30),
    "Okay I'm up and had a shower just about to get breakfast ready. Can you organize the Saturday "
    "routine and have it start at about 10 in the morning? Would be great.",
    [
        {"role": "assistant", "tool_calls": [{"name": "generate_schedule_blocks", "args": {"date": "2026-10-10", "start_time": "10:00"}}]},
        {"role": "tool", "name": "generate_schedule_blocks", "content": "Scheduled 3 tasks for 2026-10-10 starting at 10:00, with short breaks between sprints. Total: 150 mins."},
        {"role": "assistant", "content": "Set up today's Saturday routine starting at 10am — enjoy breakfast first."},
    ],
    "generate_schedule_blocks",
    "Real message — 'the Saturday routine' refers to today (anchor IS the Saturday being discussed), start_time passed through exactly as given per DAY_PLANNING_ADDENDUM's own rule.",
)

# ---- T1-0005: recurring-reminder trap, missing end-date — correct behavior is to ASK, not guess or silently fabricate a tool call ----
add(
    "T1-0005", "session_1787484299_4a2441", "interactive", datetime(2026, 10, 5, 13, 0),
    "While I'm setting up reminders, let's set up a reminder on Tuesdays at 2.30 to go pick up Finian. "
    "And can that repeat every week until the end of the current school term in the ACT?",
    [
        {"role": "assistant", "content": "Reminders are one-off only — something that repeats every week is really a calendar event, not a reminder, so I'll add it as a recurring calendar event instead. What date does the current ACT school term actually end? Once I have that I can set it to repeat weekly on Tuesdays at 2:30pm until then."},
    ],
    None,
    "TRAP, same shape as eval prompt H9's bedtime-field trap: set_reminder has no recurrence (CLAUDE.md: 'One-off only, no recurrence — a recurring need is a calendar event, not a reminder'), so the naive wrong answer is calling set_reminder anyway. The CORRECT behavior isn't just redirecting to add_calendar_event either — the term end date is genuinely unknown and shouldn't be guessed (interactive mode, not one_shot, so asking is appropriate here unlike a one_shot turn). expected_tool=None because no tool call should happen until that date is given.",
)

# ---- T1-0006: simple one-off reminder, same thread, no trap ----
add(
    "T1-0006", "session_1787484299_4a2441", "interactive", datetime(2026, 10, 5, 13, 1),
    "And this coming Wednesday, I'm out to Funtime Pony for a comedy club event. Um, remind me at 5.30.",
    [
        {"role": "assistant", "tool_calls": [{"name": "set_reminder", "args": {"message": "Funtime Pony comedy club event", "when": "2026-10-07 17:30:00"}}]},
        {"role": "tool", "name": "set_reminder", "content": "Got it — I'll remind you to 'Funtime Pony comedy club event' at Wednesday, 7 October 2026 5:30 PM."},
        {"role": "assistant", "content": "Done — I'll remind you at 5:30pm this Wednesday about Funtime Pony."},
    ],
    "set_reminder",
    "Real message in the same thread as T1-0005/T1-0007 — 'this coming Wednesday' resolved via next_weekday(Monday 2026-10-05, Wednesday) = 2026-10-07. A genuine one-off reminder, no recurrence requested, so no trap here — contrasts directly with the two recurring-reminder traps either side of it in the same real conversation.",
)

# ---- T1-0007: recurring-reminder trap #2, end date IS resolvable this time ----
add(
    "T1-0007", "session_1787484299_4a2441", "interactive", datetime(2026, 10, 5, 13, 2),
    "Also, let's round these off with a reminder at 10 o'clock on Sunday to go pick up Finian, and "
    "that is a repeating one. Let's do it for the next, um, until the end of the year.",
    [
        {"role": "assistant", "tool_calls": [{"name": "add_calendar_event", "args": {"title": "Pick up Finian", "start": "2026-10-11 10:00:00", "recurrence": "FREQ=WEEKLY;UNTIL=20261231T000000Z"}}]},
        {"role": "tool", "name": "add_calendar_event", "content": "Event added successfully. UID: 7e2a1c9b-3f4d-4e21-9a0c-1b6d8f3e5a2c"},
        {"role": "assistant", "content": "Set that up as a recurring calendar event instead of a reminder, since reminders can't repeat — picking up Finian, every Sunday at 10am, through the end of this year."},
    ],
    "add_calendar_event",
    "Same recurring-reminder trap as T1-0005, but here the end condition ('until the end of the year') IS concretely resolvable (2026-12-31) — so unlike T1-0005, no clarifying question is needed, straight to add_calendar_event with an RRULE. 'on Sunday' resolved via this_weekday(Monday 2026-10-05, Sunday) = 2026-10-11, consistent with this_weekday's semantics (current week's occurrence, matching the eval's own C15 trap convention).",
)

# ---- T1-0008 & T1-0009: same real thread, search then casual no-tool follow-up ----
add(
    "T1-0008", "session_1788784819_40adc0", "interactive", datetime(2026, 10, 8, 19, 0),
    "Hey, just a quick one. We've had trouble with the search engine integration, so can you just "
    "search what was the latest Brighton game score and tell me what it is. Thanks.",
    [
        {"role": "assistant", "tool_calls": [{"name": "search_web", "args": {"query": "Brighton latest match score result"}}]},
        {"role": "tool", "name": "search_web", "content": '{"query":"Brighton latest match score result","total_results":4,"results":[{"title":"Brighton 2-1 Fulham: match report","url":"https://example.com/brighton-fulham","snippet":"Brighton secured a narrow win at home..."}]}'},
        {"role": "assistant", "content": "Brighton won their last match 2-1 against Fulham."},
    ],
    "search_web",
    "Real message — explicit distrust ('we've had trouble with the search engine integration') is a nudge to actually call the tool rather than answer from memory, directly countering the confabulated-success failure pattern documented from baseline testing.",
)
add(
    "T1-0009", "session_1788784819_40adc0", "interactive", datetime(2026, 10, 8, 19, 5),
    "perfect that seemed to work properly although you know I didn't actually watch the game but the "
    "highlights were well we need to do some more training on actually kicking goals don't we so many "
    "that are wide and Gomez oh my god after last week in this game he must be a bit of a slump I "
    "really feel for him",
    [
        {"role": "assistant", "content": "Sounds like a rough one for him in front of goal — hopefully he finds his form again soon."},
    ],
    None,
    "Real message, pure casual chat following up on T1-0008's search result — no tool call expected, a negative example in the same thread/topic as a real tool-use example right before it.",
)

# ---- T1-0010 & T1-0011: casual sports chat, no tool, different thread ----
add(
    "T1-0010", "session_recall_gomez", "interactive", datetime(2026, 10, 9, 20, 0),
    "Yeah, Gomez is like one of the ones that I've kind of latched onto. I only really started following him this season.",
    [
        {"role": "assistant", "content": "Makes sense — easy to get attached to a player when you're watching someone come into form in real time."},
    ],
    None,
    "Real message, pure casual chat — no tool call expected.",
)
add(
    "T1-0011", "session_recall_gomez", "interactive", datetime(2026, 10, 9, 20, 2),
    "That is 100% true with Gomez. It's like the last day when I saw him what he did like three what should have been goals.",
    [
        {"role": "assistant", "content": "That's brutal when it's three in one game — hopefully the next match turns around for him."},
    ],
    None,
    "Real message, continuation of T1-0010's casual chat — no tool call expected.",
)

# ---- T1-0012/0013/0014: same real thread, a new project idea captured, then a correction, then a follow-up search ----
add(
    "T1-0012", "session_1790508449_1e9ffe", "interactive", datetime(2026, 10, 11, 15, 0),
    "I've had an idea for a new project. For context, I, when growing up, had a combo 64 and learned "
    "the very basics of programming with, well, basic on it. I would like to create a web app that "
    "uses a JS or web ASM or whatever it is. Commodore 64 emulator. Commodore 64. To then also "
    "basically have a bit of a UI around it that allows the user to chunk up logical segments of, I "
    "don't know, for loops and stuff like that in, essentially, text areas. And then, like, have it "
    "kind of have a run and debunk button that then either, basically, not compile it, but "
    "concatenate all of them with correct line numbers and then run it. There was not really more "
    "context, but I just wanted to get inside the idea now.",
    [
        {"role": "assistant", "tool_calls": [{"name": "get_or_create_project", "args": {"name": "commodore-64-emulator"}}]},
        {"role": "tool", "name": "get_or_create_project", "content": "Created a new project folder 'commodore-64-emulator' with an overview note. Use save_note(title=..., content=..., project=...) to add more notes to it."},
        {"role": "assistant", "tool_calls": [{"name": "save_note", "args": {"title": "Concept", "content": "A JS/WASM-based Commodore 64 emulator with a web UI: users chunk code into logical segments (e.g. for-loops) in separate text areas, then a 'run' button concatenates them with corrected line numbers and executes the combined program. Inspired by learning BASIC on a real C64 growing up.", "project": "commodore-64-emulator"}}]},
        {"role": "tool", "name": "save_note", "content": "Note saved: 'Concept' (id: f3a8c0e1)."},
        {"role": "assistant", "content": "Created a new 'commodore-64-emulator' project and saved the concept down — a web-based C64 emulator where you write code in chunked text areas and run them concatenated with corrected line numbers. Let me know when you want to add more to it."},
    ],
    "get_or_create_project|save_note",
    "Real message — a new, ongoing project idea per SYSTEM_PROMPT's 'Projects' section ('check list_projects (or just try get_or_create_project)... Use save_note... to file its notes together there').",
)
add(
    "T1-0013", "session_1790508449_1e9ffe", "interactive", datetime(2026, 10, 11, 15, 3),
    "I was thnking that you would stat a new project in my notes to keep track of the ideas",
    [
        {"role": "assistant", "content": "Already done — I created a 'commodore-64-emulator' project folder and saved the concept note in it just now, so new ideas for this one have somewhere to go."},
    ],
    None,
    "Real message — a correction/follow-up checking the previous turn actually happened. Since T1-0012 already created the project, the correct behavior here is confirming that, not re-calling get_or_create_project (which would be a harmless no-op per its own idempotent design, but confirming existing state is the more useful reply than a redundant tool call). Needs T1-0012 in history — otherwise 'already done' is unverifiable from this turn alone.",
    history=[
        {"role": "user", "content": "I've had an idea for a new project. For context, I, when growing up, had a combo 64 and learned the very basics of programming with, well, basic on it. I would like to create a web app that uses a JS or web ASM or whatever it is. Commodore 64 emulator."},
        {"role": "assistant", "content": "", "tool_calls": [{"name": "get_or_create_project", "args": {"name": "commodore-64-emulator"}}]},
        {"role": "tool", "content": "Created a new project folder 'commodore-64-emulator' with an overview note. Use save_note(title=..., content=..., project=...) to add more notes to it."},
        {"role": "assistant", "content": "Created a new 'commodore-64-emulator' project and saved the concept down — a web-based C64 emulator where you write code in chunked text areas and run them concatenated with corrected line numbers. Let me know when you want to add more to it."},
    ],
)
add(
    "T1-0014", "session_1790508449_1e9ffe", "interactive", datetime(2026, 10, 11, 15, 10),
    "Can you do a deeper search for any Javascript or WASM based commodore64 emulators?",
    [
        {"role": "assistant", "tool_calls": [{"name": "search_web", "args": {"query": "JavaScript WASM Commodore 64 emulator open source"}}]},
        {"role": "tool", "name": "search_web", "content": '{"query":"JavaScript WASM Commodore 64 emulator open source","total_results":6,"results":[{"title":"vMac64 - WASM C64 emulator","url":"https://example.com/vmac64","snippet":"An open-source Commodore 64 emulator compiled to WebAssembly..."},{"title":"c64js","url":"https://example.com/c64js","snippet":"A pure-JavaScript 6502/C64 emulator running in the browser..."}]}'},
        {"role": "assistant", "content": "Found a couple of existing projects worth looking at: vMac64 (a WASM-compiled C64 emulator) and c64js (a pure-JavaScript 6502/C64 emulator). Want me to save these as references in the project notes?"},
    ],
    "search_web",
    "Real message — same project thread as T1-0012/0013, a concrete research request with a clear search_web call.",
)

print(f"{len(EXAMPLES)} example(s) defined so far (script still being built)")
if __name__ == "__main__":
    out_path = Path(__file__).parent / "tranche1_partial.jsonl"
    with open(out_path, "w") as f:
        for ex in EXAMPLES:
            f.write(json.dumps(ex) + "\n")
    print(f"wrote {len(EXAMPLES)} examples to {out_path}")
