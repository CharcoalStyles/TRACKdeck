"""
scratchpad/training_data/draft_tranche2.py
---------------------------------------------
Tranche 2: voice-matched synthetic examples, per voice_profile.md. Either
varies a tranche-1 real example's surface details (new entities/dates, same
intent) or writes a new scenario for a tool tranche 1 didn't cover, in the
same dictated/informal register — never reusing tranche 1's specific real
entities (Canberra, Finian, the C64 project, Gomez/Brighton) verbatim.

Run from the repo root: uv run python scratchpad/training_data/draft_tranche2.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent.graph import SYSTEM_PROMPT, ONE_SHOT_ADDENDUM  # noqa: E402

EXAMPLES = []


def fmt(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p on %A %-d %B %Y")


def add(id_, mode, anchor, user_message, turns, expected_tool, notes, history=None):
    addendum = ONE_SHOT_ADDENDUM if mode == "one_shot" else ""
    system_prompt = SYSTEM_PROMPT + addendum + f"\n\nCURRENT DATE AND TIME: {fmt(anchor)}"
    EXAMPLES.append({
        "id": id_, "source": "voice_synthetic", "source_thread_id": None, "mode": mode,
        "system_prompt": system_prompt, "anchor_datetime": anchor.isoformat(),
        "user_message": user_message, "turns": turns, "expected_tool": expected_tool,
        "notes": notes, "verified_by": "draft-unverified", "history": history,
    })


# ===== Calendar (12) =====
add("T2-0001", "interactive", datetime(2026, 10, 12, 9, 0),
    "what have I got on today",
    [{"role": "assistant", "tool_calls": [{"name": "get_todays_events", "args": {}}]},
     {"role": "tool", "name": "get_todays_events", "content": '[{"uid":"a1","start":"20261012T100000Z","end":"20261012T110000Z","summary":"Team standup","location":null}]'},
     {"role": "assistant", "content": "Just one thing today — Team standup at 10am."}],
    "get_todays_events", "Voice-matched, bare informal ask, no entities from tranche 1 reused.")
add("T2-0002", "interactive", datetime(2026, 10, 13, 14, 0),
    "can you check what's going on this tuesday",
    [{"role": "assistant", "tool_calls": [{"name": "get_calendar_events", "args": {"start": "2026-10-13", "end": "2026-10-13"}}]},
     {"role": "tool", "name": "get_calendar_events", "content": "[]"},
     {"role": "assistant", "content": "Nothing on your calendar for Tuesday — clear day."}],
    "get_calendar_events", "'this tuesday' resolved against the anchor itself (anchor IS a Tuesday).")
add("T2-0003", "interactive", datetime(2026, 10, 14, 11, 0),
    "hey can you pull up my dentist appointment again, need the address",
    [{"role": "assistant", "tool_calls": [{"name": "get_calendar_events", "args": {"start": "2026-10-14", "end": "2026-10-28"}}]},
     {"role": "tool", "name": "get_calendar_events", "content": '[{"uid":"8f3a2e1c","start":"20261020T030000Z","end":"20261020T033000Z","summary":"Dentist","location":"Riverside Dental","description":null}]'},
     {"role": "assistant", "content": "Dentist appointment on October 20th at 2pm (your local time), at Riverside Dental."}],
    "get_calendar_events", "No uid stated by the user (a real person never would) — looked up by searching a reasonable date window and matching the 'Dentist' summary from the returned list, rather than being handed an id out of nowhere.")
add("T2-0004", "one_shot", datetime(2026, 10, 15, 8, 0),
    "add my mates place for drinks this saturday night 8pm at The Local",
    [{"role": "assistant", "tool_calls": [{"name": "add_calendar_event", "args": {"title": "Drinks at The Local", "start": "2026-10-17 20:00:00", "location": "The Local"}}]},
     {"role": "tool", "name": "add_calendar_event", "content": "Event added successfully. UID: c2d9e8a1-4b3f-4a21-9c0e-1d6f8e3a5b2c"},
     {"role": "assistant", "content": "Added — drinks at The Local, this Saturday at 8pm."}],
    "add_calendar_event", "'this saturday' = next_weekday(Thursday 10-15, Saturday) = 10-17. One-shot mode, no clarifying question.")
add("T2-0005", "interactive", datetime(2026, 10, 16, 10, 0),
    "nah scratch the gym session tomorrow, I'm not going",
    [{"role": "assistant", "tool_calls": [{"name": "get_calendar_events", "args": {"start": "2026-10-17", "end": "2026-10-17"}}]},
     {"role": "tool", "name": "get_calendar_events", "content": '[{"uid":"7a9c3e2b-1d4f","start":"20261017T200000Z","end":"20261017T210000Z","summary":"Gym session","location":null}]'},
     {"role": "assistant", "tool_calls": [{"name": "delete_calendar_event", "args": {"uid": "7a9c3e2b-1d4f"}}]},
     {"role": "tool", "name": "delete_calendar_event", "content": "Event deleted successfully."},
     {"role": "assistant", "content": "Done, removed tomorrow's gym session."}],
    "delete_calendar_event", "No uid stated — real users never reference event ids in speech (confirmed by my user directly while reviewing this batch). Looks tomorrow's events up first, matches 'Gym session' from the real returned list, then deletes using that real uid.")
add("T2-0006", "interactive", datetime(2026, 10, 15, 8, 2),
    "actually, can you move that to 9pm instead",
    [{"role": "assistant", "tool_calls": [{"name": "update_calendar_event", "args": {"uid": "c2d9e8a1-4b3f-4a21-9c0e-1d6f8e3a5b2c", "title": "Drinks at The Local", "start": "2026-10-17 21:00:00", "end": "2026-10-17 23:00:00", "location": "The Local"}}]},
     {"role": "tool", "name": "update_calendar_event", "content": "Event updated successfully."},
     {"role": "assistant", "content": "Moved it to 9pm."}],
    "update_calendar_event", "Immediate same-session correction to the event T2-0004 just created — uses history (T2-0004's real exchange) rather than having the user state the uid, which nobody does in real speech.",
    history=[
        {"role": "user", "content": "add my mates place for drinks this saturday night 8pm at The Local"},
        {"role": "assistant", "content": "", "tool_calls": [{"name": "add_calendar_event", "args": {"title": "Drinks at The Local", "start": "2026-10-17 20:00:00", "location": "The Local"}}]},
        {"role": "tool", "content": "Event added successfully. UID: c2d9e8a1-4b3f-4a21-9c0e-1d6f8e3a5b2c"},
        {"role": "assistant", "content": "Added — drinks at The Local, this Saturday at 8pm."},
    ])
add("T2-0007", "interactive", datetime(2026, 10, 13, 9, 0),
    "what's on this week for me",
    [{"role": "assistant", "tool_calls": [{"name": "get_calendar_events", "args": {"start": "2026-10-13", "end": "2026-10-18"}}]},
     {"role": "tool", "name": "get_calendar_events", "content": '[{"uid":"e1","start":"20261014T053000Z","end":"20261014T060000Z","summary":"Call with Jamie","location":null}]'},
     {"role": "assistant", "content": "Just one thing this week — a call with Jamie on Wednesday."}],
    "get_calendar_events", "Voice variant of eval H2's intent — 'this week' = today (Tuesday) through Sunday, not a rolling 7 days forward.")
add("T2-0008", "one_shot", datetime(2026, 10, 19, 7, 30),
    "block out next friday arvo for a haircut, maybe an hour",
    [{"role": "assistant", "tool_calls": [{"name": "add_calendar_event", "args": {"title": "Haircut", "start": "2026-10-23 14:00:00", "end": "2026-10-23 15:00:00"}}]},
     {"role": "tool", "name": "add_calendar_event", "content": "Event added successfully. UID: 9b1d4f2e-6c8a-4e03-8f1b-2a7c9d5e3f4a"},
     {"role": "assistant", "content": "Booked in — haircut this coming Friday at 2pm, an hour long. Let me know if 2pm's wrong for 'arvo' and I'll shift it."}],
    "add_calendar_event", "'arvo' (Australian slang for afternoon) defaulted to a reasonable afternoon slot per the one_shot addendum's assumption-stating rule.")
add("T2-0009", "interactive", datetime(2026, 10, 19, 7, 32),
    "can you grab the details for that again, forgot what time I put it at",
    [{"role": "assistant", "content": "2pm this Friday."}],
    None,
    "Immediate same-session follow-up to T2-0008 — in history already, so answerable without a new tool call at all.",
    history=[
        {"role": "user", "content": "block out next friday arvo for a haircut, maybe an hour"},
        {"role": "assistant", "content": "", "tool_calls": [{"name": "add_calendar_event", "args": {"title": "Haircut", "start": "2026-10-23 14:00:00", "end": "2026-10-23 15:00:00"}}]},
        {"role": "tool", "content": "Event added successfully. UID: 9b1d4f2e-6c8a-4e03-8f1b-2a7c9d5e3f4a"},
        {"role": "assistant", "content": "Booked in — haircut this coming Friday at 2pm, an hour long. Let me know if 2pm's wrong for 'arvo' and I'll shift it."},
    ])
add("T2-0010", "interactive", datetime(2026, 10, 21, 9, 0),
    "can you check if I've got anything on in the next two weeks, trying to plan a trip",
    [{"role": "assistant", "tool_calls": [{"name": "get_calendar_events", "args": {"start": "2026-10-21", "end": "2026-11-04"}}]},
     {"role": "tool", "name": "get_calendar_events", "content": '[{"uid":"f2","start":"20261023T030000Z","end":"20261023T040000Z","summary":"Haircut","location":null}]'},
     {"role": "assistant", "content": "Only the haircut on Friday — rest of the next two weeks is clear, good window for a trip."}],
    "get_calendar_events", "Longer custom range than a bare week, intent stated explicitly ('trying to plan a trip'). The returned uid ('f2') is fabricated tool-result data, not something the user stated — fine per the no-invented-id rule, which only concerns args the model itself fills in.")
add("T2-0011", "interactive", datetime(2026, 10, 19, 7, 35),
    "oh wait can you make that repeat every 6 weeks, keep forgetting to book it",
    [{"role": "assistant", "tool_calls": [{"name": "update_calendar_event", "args": {"uid": "9b1d4f2e-6c8a-4e03-8f1b-2a7c9d5e3f4a", "title": "Haircut", "start": "2026-10-23 14:00:00", "end": "2026-10-23 15:00:00", "recurrence": "FREQ=WEEKLY;INTERVAL=6"}}]},
     {"role": "tool", "name": "update_calendar_event", "content": "Event updated successfully."},
     {"role": "assistant", "content": "Set that haircut to repeat every 6 weeks from now on, so it's one less thing to remember."}],
    "update_calendar_event", "Recurrence retrofitted onto an existing event — correct use of RRULE INTERVAL per add_calendar_event's documented recurrence format. Same-session continuation of T2-0008, uid comes from history, never stated by the user.",
    history=[
        {"role": "user", "content": "block out next friday arvo for a haircut, maybe an hour"},
        {"role": "assistant", "content": "", "tool_calls": [{"name": "add_calendar_event", "args": {"title": "Haircut", "start": "2026-10-23 14:00:00", "end": "2026-10-23 15:00:00"}}]},
        {"role": "tool", "content": "Event added successfully. UID: 9b1d4f2e-6c8a-4e03-8f1b-2a7c9d5e3f4a"},
        {"role": "assistant", "content": "Booked in — haircut this coming Friday at 2pm, an hour long. Let me know if 2pm's wrong for 'arvo' and I'll shift it."},
        {"role": "user", "content": "can you grab the details for that again, forgot what time I put it at"},
        {"role": "assistant", "content": "2pm this Friday."},
    ])
add("T2-0012", "interactive", datetime(2026, 10, 23, 8, 0),
    "what's on the calendar until the end of the month",
    [{"role": "assistant", "tool_calls": [{"name": "get_calendar_events", "args": {"start": "2026-10-23", "end": "2026-10-31"}}]},
     {"role": "tool", "name": "get_calendar_events", "content": "[]"},
     {"role": "assistant", "content": "Nothing else on the calendar through the end of October."}],
    "get_calendar_events", "'until the end of the month' resolved to the literal last day of the anchor's month.")

# ===== Weather (6) =====
add("T2-0013", "interactive", datetime(2026, 10, 24, 7, 0),
    "what's it like outside right now",
    [{"role": "assistant", "tool_calls": [{"name": "get_current_weather", "args": {}}]},
     {"role": "tool", "name": "get_current_weather", "content": "Weather for Canberra: 11.4°C, 60% cloud cover, 0.2mm precipitation."},
     {"role": "assistant", "content": "11.4°C and mostly cloudy, a bit of light rain around."}],
    "get_current_weather", "Bare informal ask, no location given, defaults to settings.default_location per the tool's own behavior.")
add("T2-0014", "one_shot", datetime(2026, 10, 25, 20, 0),
    "whats the weather doing tomorrow, deciding whether to ride to work",
    [{"role": "assistant", "tool_calls": [{"name": "get_weather_forecast", "args": {}}]},
     {"role": "tool", "name": "get_weather_forecast", "content": '[{"time":"2026-10-26","temperature_2m_min":9.1,"temperature_2m_max":19.0,"precipitation_probability_min":0,"precipitation_probability_max":10}]'},
     {"role": "assistant", "content": "Tomorrow's looking mild — 9 to 19°C with only a slight chance of rain, should be a fine ride in."}],
    "get_weather_forecast", "Stated intent ('deciding whether to ride') nudges toward actually using the forecast data in the reply, not just reciting raw numbers.")
add("T2-0015", "interactive", datetime(2026, 10, 26, 9, 0),
    "can you give me the forecast for the next 5 days, thinking about when to do the garden",
    [{"role": "assistant", "tool_calls": [{"name": "get_range_forecast", "args": {"start": "2026-10-26", "end": "2026-10-30"}}]},
     {"role": "tool", "name": "get_range_forecast", "content": '[{"time":"2026-10-26","temperature_2m_min":10.0,"temperature_2m_max":18.5,"precipitation_probability_min":0,"precipitation_probability_max":20},{"time":"2026-10-28","temperature_2m_min":11.0,"temperature_2m_max":21.0,"precipitation_probability_min":0,"precipitation_probability_max":5}]'},
     {"role": "assistant", "content": "Wednesday the 28th looks like your best bet for the garden — dry and the warmest of the bunch at 21°C."}],
    "get_range_forecast", "Explicit date range ('next 5 days') resolved against the anchor, not a bare 7-day get_weather_forecast call.")
add("T2-0016", "interactive", datetime(2026, 10, 27, 6, 45),
    "is it cold out",
    [{"role": "assistant", "tool_calls": [{"name": "get_current_weather", "args": {}}]},
     {"role": "tool", "name": "get_current_weather", "content": "Weather for Canberra: 6.2°C, 10% cloud cover, 0.0mm precipitation."},
     {"role": "assistant", "content": "Yeah, pretty chilly — 6.2°C and clear."}],
    "get_current_weather", "Minimal bare question, still clearly a weather-tool case.")
add("T2-0017", "interactive", datetime(2026, 10, 28, 18, 0),
    "what's the forecast looking like over the weekend, might go camping",
    [{"role": "assistant", "tool_calls": [{"name": "get_range_forecast", "args": {"start": "2026-10-31", "end": "2026-11-01"}}]},
     {"role": "tool", "name": "get_range_forecast", "content": '[{"time":"2026-10-31","temperature_2m_min":12.0,"temperature_2m_max":22.0,"precipitation_probability_min":0,"precipitation_probability_max":15},{"time":"2026-11-01","temperature_2m_min":13.0,"temperature_2m_max":20.0,"precipitation_probability_min":10,"precipitation_probability_max":40}]'},
     {"role": "assistant", "content": "Saturday's the better camping day — warm and dry. Sunday's cooler with a decent chance of rain by afternoon."}],
    "get_range_forecast", "'the weekend' resolved to the anchor's upcoming Sat/Sun, same convention as the date resolver's this_weekend helper.")
add("T2-0018", "one_shot", datetime(2026, 10, 29, 7, 0),
    "will I need an umbrella today",
    [{"role": "assistant", "tool_calls": [{"name": "get_current_weather", "args": {}}]},
     {"role": "tool", "name": "get_current_weather", "content": "Weather for Canberra: 14.0°C, 80% cloud cover, 3.5mm precipitation."},
     {"role": "assistant", "content": "Yeah, grab one — it's already drizzling, 3.5mm so far today."}],
    "get_current_weather", "A yes/no-framed question still correctly maps to a weather tool, not answered from general knowledge.")

# ===== Notes (14) =====
add("T2-0019", "interactive", datetime(2026, 10, 30, 19, 0),
    "can you save a note about the deck resealing — need to sand it back, two coats of oil, let it cure a week between",
    [{"role": "assistant", "tool_calls": [{"name": "save_note", "args": {"title": "Deck resealing", "content": "Sand back first. Two coats of oil. Let it cure a week between coats."}}]},
     {"role": "tool", "name": "save_note", "content": "Note saved: 'Deck resealing' (id: a7c3e901)."},
     {"role": "assistant", "content": "Saved — sand, two coats of oil, a week's cure between coats."}],
    "save_note", "A plain save_note request with dictated, comma-chained content.")
add("T2-0020", "interactive", datetime(2026, 10, 31, 10, 0),
    "did I write anything down about the deck",
    [{"role": "assistant", "tool_calls": [{"name": "search_notes", "args": {"query": "deck resealing"}}]},
     {"role": "tool", "name": "search_notes", "content": "[id: a7c3e901] Deck resealing — Sand back first. Two coats of oil. Let it cure a week between coats."},
     {"role": "assistant", "content": "Yeah — you've got a 'Deck resealing' note: sand it back first, two coats of oil, cure a week between coats."}],
    "search_notes", "Vague recall question correctly triggers a search rather than a guessed answer.")
add("T2-0021", "interactive", datetime(2026, 10, 31, 10, 2),
    "can you read me the full thing",
    [{"role": "assistant", "tool_calls": [{"name": "read_note", "args": {"note_id": "a7c3e901"}}]},
     {"role": "tool", "name": "read_note", "content": "# Deck resealing\n\nSand back first. Two coats of oil. Let it cure a week between coats."},
     {"role": "assistant", "content": "Sand it back first, two coats of oil, and let it cure a week between coats."}],
    "read_note", "Immediate follow-up to T2-0020's search — no id stated by the user, it comes from history's prior search_notes result.",
    history=[
        {"role": "user", "content": "did I write anything down about the deck"},
        {"role": "assistant", "content": "", "tool_calls": [{"name": "search_notes", "args": {"query": "deck resealing"}}]},
        {"role": "tool", "content": "[id: a7c3e901] Deck resealing — Sand back first. Two coats of oil. Let it cure a week between coats."},
        {"role": "assistant", "content": "Yeah — you've got a 'Deck resealing' note: sand it back first, two coats of oil, cure a week between coats."},
    ])
add("T2-0022", "interactive", datetime(2026, 11, 2, 16, 0),
    "add a line to my deck resealing note, the oil I'm using is Cabot's Australian Timber Oil",
    [{"role": "assistant", "tool_calls": [{"name": "search_notes", "args": {"query": "deck resealing"}}]},
     {"role": "tool", "name": "search_notes", "content": "[id: a7c3e901] Deck resealing — Sand back first. Two coats of oil. Let it cure a week between coats."},
     {"role": "assistant", "tool_calls": [{"name": "append_to_note", "args": {"note_id": "a7c3e901", "section": "Deck resealing", "content": "Oil: Cabot's Australian Timber Oil."}}]},
     {"role": "tool", "name": "append_to_note", "content": "Added to 'Deck resealing' in 'Deck resealing'."},
     {"role": "assistant", "content": "Added that in."}],
    "search_notes|append_to_note", "No note_id stated or carried in history — looks the note up by name first (search_notes), then appends using the real id that search returns.")
add("T2-0023", "interactive", datetime(2026, 11, 3, 9, 0),
    "replace the generated schedule section on today's planning note, I already redid it myself",
    [{"role": "assistant", "tool_calls": [{"name": "search_notes", "args": {"query": "Planning — 2026-11-03"}}]},
     {"role": "tool", "name": "search_notes", "content": "[id: c9e1a204] Planning — 2026-11-03 — Tasks and generated schedule for today."},
     {"role": "assistant", "tool_calls": [{"name": "update_note_section", "args": {"note_id": "c9e1a204", "section": "Generated Schedule", "new_content": "(user-edited manually, see note)"}}]},
     {"role": "tool", "name": "update_note_section", "content": "Updated 'Generated Schedule' in 'Planning — 2026-11-03'."},
     {"role": "assistant", "content": "Done, cleared the generated section since you've already handled it yourself."}],
    "search_notes|update_note_section", "No note_id given or known — looks up today's planning note by its real title convention first, then edits using the id that search returns, rather than inventing one.")
add("T2-0024", "interactive", datetime(2026, 11, 4, 20, 0),
    "remember that I'm allergic to penicillin",
    [{"role": "assistant", "tool_calls": [{"name": "remember_about_me", "args": {"section": "Health & Goals", "content": "Allergic to penicillin.", "mode": "append"}}]},
     {"role": "tool", "name": "remember_about_me", "content": "Recorded under 'Health & Goals' in About Me."},
     {"role": "assistant", "content": "Got it, noted."}],
    "remember_about_me", "A durable fact worth recording, append mode (never replace on a multi-entry section) per SYSTEM_PROMPT's LEARNING_ADDENDUM rule.")
add("T2-0025", "interactive", datetime(2026, 11, 5, 11, 0),
    "can you set up a note for my sister, Priya, I want to keep track of birthday ideas",
    [{"role": "assistant", "tool_calls": [{"name": "get_or_create_linked_note", "args": {"topic": "Priya", "category": "People"}}]},
     {"role": "tool", "name": "get_or_create_linked_note", "content": "Created a new note for 'Priya' (id: d8e2f104), linked from About Me's 'People' section. Use read_note/append_to_note/update_note_section with this id."},
     {"role": "assistant", "content": "Created a note for Priya — I'll add birthday ideas there as they come up."}],
    "get_or_create_linked_note", "A specific person getting their own linked note rather than a shared section, per SYSTEM_PROMPT's People-section guidance.")
add("T2-0026", "interactive", datetime(2026, 11, 6, 14, 0),
    "I'm starting a new project, want to build a little weather station with a raspberry pi",
    [{"role": "assistant", "tool_calls": [{"name": "get_or_create_project", "args": {"name": "pi-weather-station"}}]},
     {"role": "tool", "name": "get_or_create_project", "content": "Created a new project folder 'pi-weather-station' with an overview note. Use save_note(title=..., content=..., project=...) to add more notes to it."},
     {"role": "assistant", "content": "Set up a 'pi-weather-station' project for it."}],
    "get_or_create_project", "A different new-project scenario from tranche 1's C64 emulator, same intent pattern.")
add("T2-0027", "interactive", datetime(2026, 11, 7, 9, 0),
    "what projects have I got going at the moment",
    [{"role": "assistant", "tool_calls": [{"name": "list_projects", "args": {}}]},
     {"role": "tool", "name": "list_projects", "content": "pi-weather-station, commodore-64-emulator"},
     {"role": "assistant", "content": "Two on the go — the Pi weather station and the Commodore 64 emulator."}],
    "list_projects", "A plain status-check request.")
add("T2-0028", "interactive", datetime(2026, 11, 8, 10, 0),
    "what's my current job listed as again",
    [{"role": "assistant", "tool_calls": [{"name": "read_about_me", "args": {}}]},
     {"role": "tool", "name": "read_about_me", "content": "## Basics\nName: Aaron\nOccupation: Fullstack Software Engineer\nCurrent Job: Senior Engineer at a logistics startup"},
     {"role": "assistant", "content": "Senior Engineer at a logistics startup."}],
    "read_about_me", "A profile-recall question, matches the real result_preview format already captured for this tool.")
add("T2-0029", "interactive", datetime(2026, 11, 9, 15, 0),
    "oh also note down that I prefer tea over coffee, keep forgetting to mention that",
    [{"role": "assistant", "tool_calls": [{"name": "remember_about_me", "args": {"section": "Preferences", "content": "Prefers tea over coffee.", "mode": "append"}}]},
     {"role": "tool", "name": "remember_about_me", "content": "Recorded under 'Preferences' in About Me."},
     {"role": "assistant", "content": "Noted — tea over coffee."}],
    "remember_about_me", "Another durable-fact capture, casual 'oh also' framing typical of the voice profile's chained-request pattern.")
add("T2-0030", "interactive", datetime(2026, 11, 10, 11, 0),
    "search my notes for anything about the raspberry pi project",
    [{"role": "assistant", "tool_calls": [{"name": "search_notes", "args": {"query": "raspberry pi weather station", "project": "pi-weather-station"}}]},
     {"role": "tool", "name": "search_notes", "content": "[id: b4f1a203] pi-weather-station — Overview — New project folder created."},
     {"role": "assistant", "content": "Just the overview note so far, nothing else saved under it yet."}],
    "search_notes", "Project-scoped search, per SYSTEM_PROMPT's Projects section guidance to pass project= when actively discussing one.")
add("T2-0031", "interactive", datetime(2026, 11, 11, 16, 0),
    "update my sister Priya's note, she mentioned wanting a pottery class for her birthday",
    [{"role": "assistant", "tool_calls": [{"name": "search_notes", "args": {"query": "Priya"}}]},
     {"role": "tool", "name": "search_notes", "content": "[id: d8e2f104] Priya — linked from About Me's 'People' section."},
     {"role": "assistant", "tool_calls": [{"name": "append_to_note", "args": {"note_id": "d8e2f104", "section": "Priya", "content": "Birthday idea: a pottery class."}}]},
     {"role": "tool", "name": "append_to_note", "content": "Added to 'Priya' in 'Priya'."},
     {"role": "assistant", "content": "Added — a pottery class."}],
    "search_notes|append_to_note", "No note_id stated — looks Priya's note up by name first (search_notes), then appends using the real id search returns, rather than assuming it's the same id as a different, earlier scenario (T2-0025).")
add("T2-0032", "interactive", datetime(2026, 11, 12, 9, 0),
    "can you dig up that note about Cabot's oil again, forgot the brand",
    [{"role": "assistant", "tool_calls": [{"name": "search_notes", "args": {"query": "Cabot's timber oil deck"}}]},
     {"role": "tool", "name": "search_notes", "content": "[id: a7c3e901] Deck resealing — Sand back first. Two coats of oil. Oil: Cabot's Australian Timber Oil."},
     {"role": "assistant", "content": "Cabot's Australian Timber Oil."}],
    "search_notes", "Another natural recall case, slightly different phrasing from T2-0020.")

# ===== Reminders (6) =====
add("T2-0033", "one_shot", datetime(2026, 11, 13, 8, 0),
    "set a timer for 12 minutes, eggs are on",
    [{"role": "assistant", "tool_calls": [{"name": "set_timer", "args": {"when": "2026-11-13 08:12:00", "message": "Eggs"}}]},
     {"role": "tool", "name": "set_timer", "content": "Timer set for 12 minutes — I'll let you know when it's up."},
     {"role": "assistant", "content": "Timer's running, 12 minutes for the eggs."}],
    "set_timer", "Simple, unambiguous timer request.")
add("T2-0034", "interactive", datetime(2026, 11, 14, 9, 0),
    "what have I got set to remind me about at the moment",
    [{"role": "assistant", "tool_calls": [{"name": "list_reminders", "args": {}}]},
     {"role": "tool", "name": "list_reminders", "content": "You have no pending reminders."},
     {"role": "assistant", "content": "Nothing pending right now."}],
    "list_reminders", "A plain status check, no args needed, matches the real result_preview captured for this tool.")
add("T2-0035", "interactive", datetime(2026, 11, 15, 10, 0),
    "remind me to call the plumber tomorrow arvo",
    [{"role": "assistant", "tool_calls": [{"name": "set_reminder", "args": {"message": "Call the plumber", "when": "2026-11-16 14:00:00"}}]},
     {"role": "tool", "name": "set_reminder", "content": "Got it — I'll remind you to 'Call the plumber' at Monday, 16 November 2026 2:00 PM."},
     {"role": "assistant", "content": "Done — tomorrow afternoon, 2pm."}],
    "set_reminder", "'tomorrow arvo' defaults to a reasonable early-afternoon time, same assumption-stating pattern as T2-0008.")
add("T2-0036", "interactive", datetime(2026, 11, 16, 15, 0),
    "cancel that plumber reminder, sorted it already",
    [{"role": "assistant", "tool_calls": [{"name": "cancel_reminder", "args": {"message": "Call the plumber"}}]},
     {"role": "tool", "name": "cancel_reminder", "content": "Cancelled 'Call the plumber'."},
     {"role": "assistant", "content": "Cancelled."}],
    "cancel_reminder", "A plain cancellation using the reminder's own message text to identify it.")
add("T2-0037", "interactive", datetime(2026, 10, 23, 11, 0),
    "set a reminder for 30 minutes before my haircut",
    [{"role": "assistant", "tool_calls": [{"name": "get_calendar_events", "args": {"start": "2026-10-23", "end": "2026-10-23"}}]},
     {"role": "tool", "name": "get_calendar_events", "content": '[{"uid":"9b1d4f2e-6c8a-4e03-8f1b-2a7c9d5e3f4a","start":"20261023T030000Z","end":"20261023T040000Z","summary":"Haircut","location":null,"description":null}]'},
     {"role": "assistant", "tool_calls": [{"name": "set_reminder", "args": {"message": "Haircut in 30 minutes", "when": "2026-10-23 13:30:00"}}]},
     {"role": "tool", "name": "set_reminder", "content": "Got it — I'll remind you to 'Haircut in 30 minutes' at Friday, 23 October 2026 1:30 PM."},
     {"role": "assistant", "content": "Set for 1:30pm, 30 minutes before."}],
    "set_reminder", "Calendar-relative reminder, no history/prior mention needed — looks today's events up first (get_calendar_events), finds 'Haircut' in the real returned list, then computes 30 minutes before its actual start. The reminder's own time comes from the looked-up event, not from the anchor directly — no date_intent for it (nothing to recompute from the anchor alone).")
add("T2-0038", "one_shot", datetime(2026, 11, 18, 20, 0),
    "remind me to take the bins out in 10 minutes",
    [{"role": "assistant", "tool_calls": [{"name": "set_reminder", "args": {"message": "Take the bins out", "when": "2026-11-18 20:10:00"}}]},
     {"role": "tool", "name": "set_reminder", "content": "Got it — I'll remind you to 'Take the bins out' at Wednesday, 18 November 2026 8:10 PM."},
     {"role": "assistant", "content": "Done, 10 minutes."}],
    "set_reminder", "Simple relative-minutes reminder, in_days-style arithmetic reduced to a plain timedelta add rather than a day resolution.")

# ===== Checkin (2) =====
add("T2-0039", "interactive", datetime(2026, 11, 19, 15, 0),
    "I need a grounding exercise, feeling pretty wound up",
    [{"role": "assistant", "tool_calls": [{"name": "get_reflection_prompt", "args": {"category": "low"}}]},
     {"role": "tool", "name": "get_reflection_prompt", "content": "Drop your shoulders away from your ears and unclench your jaw. Take one slow breath — what shifted, even slightly?"},
     {"role": "assistant", "content": "Drop your shoulders away from your ears and unclench your jaw. Take one slow breath — what shifted, even slightly?"}],
    "get_reflection_prompt", "Direct on-demand request, matches a real prompt-bank entry (agent/checkin_prompts.py), low effort category given 'wound up' framing.")
add("T2-0040", "interactive", datetime(2026, 11, 20, 18, 0),
    "give me something to reflect on about today, nothing too heavy though",
    [{"role": "assistant", "tool_calls": [{"name": "get_reflection_prompt", "args": {"category": "medium"}}]},
     {"role": "tool", "name": "get_reflection_prompt", "content": "Name one small thing that went better than expected today — what made it work?"},
     {"role": "assistant", "content": "Name one small thing that went better than expected today — what made it work?"}],
    "get_reflection_prompt", "'nothing too heavy' maps to the medium category rather than the deeper 'high' tier.")

# ===== General (4) =====
add("T2-0041", "interactive", datetime(2026, 11, 21, 7, 0),
    "what's the actual date today, lost track",
    [{"role": "assistant", "tool_calls": [{"name": "get_current_datetime", "args": {}}]},
     {"role": "tool", "name": "get_current_datetime", "content": "The current date and time is: 7:00 AM on Saturday 21 November 2026"},
     {"role": "assistant", "content": "Saturday, November 21st."}],
    "get_current_datetime", "Explicit direct ask for the date, the one case where the tool call is still expected despite the live datetime block already being in context, per SYSTEM_PROMPT's own carve-out.")
add("T2-0042", "interactive", datetime(2026, 11, 22, 11, 0),
    "can you pull up that recipe page I was looking at, it's on the Woolworths site, the beef stew one",
    [{"role": "assistant", "content": "I don't have the specific URL you were looking at — could you paste the link and I'll fetch the full content from it?"}],
    None,
    "fetch_webpage needs an actual URL argument — a vague site description isn't enough to call it, correct behavior is asking for the link rather than guessing or fabricating one.")
add("T2-0043", "interactive", datetime(2026, 11, 22, 11, 2),
    "here you go: https://example.com/recipes/beef-stew",
    [{"role": "assistant", "tool_calls": [{"name": "fetch_webpage", "args": {"url": "https://example.com/recipes/beef-stew"}}]},
     {"role": "tool", "name": "fetch_webpage", "content": "Beef Stew — serves 4. Ingredients: 1kg chuck steak, 2 carrots, 3 potatoes, 1 onion, beef stock, bay leaves. Method: brown the meat, add vegetables and stock, simmer 2.5 hours..."},
     {"role": "assistant", "content": "Got it — chuck steak, carrots, potatoes, onion, beef stock and bay leaves, browned then simmered for 2.5 hours."}],
    "fetch_webpage", "Direct follow-up supplying the URL T2-0042 asked for — a 2-turn real-shaped exchange.")
add("T2-0044", "interactive", datetime(2026, 11, 23, 13, 0),
    "just did 45 minutes on the exercise bike, felt pretty good, maybe a 7 out of 10",
    [{"role": "assistant", "tool_calls": [{"name": "log_activity", "args": {"activity_type": "Exercise", "subject": "Exercise bike", "duration": "45 minutes", "mood_energy": 7}}]},
     {"role": "tool", "name": "log_activity", "content": "Logged: Exercise — 45 minutes, mood 7/10 at Monday, 23 November 2026."},
     {"role": "assistant", "content": "Logged — 45 minutes on the bike, mood 7/10."}],
    "log_activity", "Narrating a just-finished activity with duration and mood, exactly the trigger condition in SYSTEM_PROMPT's Activity Logging section.")

# ===== Planning (3 more) =====
add("T2-0045", "interactive", datetime(2026, 11, 24, 20, 0),
    "add a task for tomorrow, need to renew the car rego, say 15 mins",
    [{"role": "assistant", "tool_calls": [{"name": "add_planning_task", "args": {"date": "2026-11-25", "task": "renew car rego", "duration_minutes": 15}}]},
     {"role": "tool", "name": "add_planning_task", "content": "Added 'renew car rego' (15 mins) to the planning note for 2026-11-25."},
     {"role": "assistant", "content": "Added for tomorrow."}],
    "add_planning_task", "A single-task add, not a full-day batch like tranche 1's T1-0001.")
add("T2-0046", "interactive", datetime(2026, 11, 25, 8, 0),
    "go ahead and generate today's schedule, nothing special needed",
    [{"role": "assistant", "tool_calls": [{"name": "generate_schedule_blocks", "args": {"date": "2026-11-25"}}]},
     {"role": "tool", "name": "generate_schedule_blocks", "content": "Scheduled 1 task for 2026-11-25 starting at 09:00, with short breaks between sprints. Total: 15 mins."},
     {"role": "assistant", "content": "Scheduled — just the car rego renewal, starting at 9am."}],
    "generate_schedule_blocks", "The 'already saved, just generate' case per DAY_PLANNING_ADDENDUM's own 'normal case for a start-my-day trigger' rule — no add_planning_task call here.")
add("T2-0047", "interactive", datetime(2026, 11, 26, 19, 0),
    "for tomorrow can you put the gym session after my lunch break, everything else can go wherever",
    [{"role": "assistant", "tool_calls": [{"name": "add_planning_task", "args": {"date": "2026-11-27", "task": "Gym session", "duration_minutes": 60}}]},
     {"role": "tool", "name": "add_planning_task", "content": "Added 'Gym session' (60 mins) to the planning note for 2026-11-27."},
     {"role": "assistant", "tool_calls": [{"name": "generate_schedule_blocks", "args": {"date": "2026-11-27"}}]},
     {"role": "tool", "name": "generate_schedule_blocks", "content": "Scheduled 1 task for 2026-11-27 starting at 09:00. Total: 60 mins."},
     {"role": "assistant", "content": "Added the gym session — but heads up, there's no actual lunch-break task or calendar event for it to land after, so I can't guarantee the ordering you asked for. Want me to add a lunch block too so there's something real to schedule around?"}],
    "add_planning_task|generate_schedule_blocks", "Only the task actually mentioned (gym) gets added — no invented filler task. Matches DAY_PLANNING_ADDENDUM's own documented escape hatch: 'If the guidance can't be satisfied this way... say so plainly in your reply rather than silently ignoring it' — there's no real lunch-break task/event to order against, so ordering guidance genuinely can't be honored, and the correct move is saying that, not fabricating a placeholder task to engineer the requested order.")

print(f"{len(EXAMPLES)} examples defined (full tranche 2)")
if __name__ == "__main__":
    out_path = Path(__file__).parent / "tranche2_partial.jsonl"
    with open(out_path, "w") as f:
        for ex in EXAMPLES:
            f.write(json.dumps(ex) + "\n")
    print(f"wrote {len(EXAMPLES)} examples to {out_path}")
