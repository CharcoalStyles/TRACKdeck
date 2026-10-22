"""Builds scratchpad/eval_prompts.json — the 45-prompt multi-model tool-calling
eval set (15 historical replays, 15 styled-synthetic, 15 clean synthetic edge
cases). Anchor date for all date-relative "expected" notes: 2026-09-26 (Sat),
confirmed as the real container clock at build time. Throwaway/one-off."""
import json

ANCHOR = "2026-09-26 (Saturday)"

prompts = []

def add(id_, source, text, tool, notes):
    prompts.append({"id": id_, "source": source, "text": text, "expected": {"tool": tool, "notes": notes}})

# ---- 15 historical replays (verbatim from scratchpad/turn_dump.json, excluding the two degenerate threads) ----
add("H1", "historical", "Can you tell me what the weather wil be this sunday and things I can do with my 6 year old around Canberra?",
    "get_current_weather|get_weather_forecast|get_range_forecast",
    "Any weather tool call with location=Canberra (or default_location) counts; the 'things to do' half has no tool, ignore for scoring.")
add("H2", "historical", "Can you tell me what I have on this week?",
    "get_calendar_events", "start/end should span roughly the current week (today through Sun).")
add("H3", "historical", "just any events that I have on this weekend",
    "get_calendar_events", f"start/end should be the upcoming Sat({ANCHOR} is itself Sat)/Sun.")
add("H4", "historical", "Hey, can you get me the events I have in the calendar until the end of the year?",
    "get_calendar_events", "start=today, end=2026-12-31 (or close to it).")
add("H5", "historical", "Is there anyhtign interesting for my 6yo son and I on sunday in Canberra?",
    "search_web|search_news|null", "A 'what's on locally' question — a web search tool or a reasonable general-knowledge reply are both acceptable; calendar tools would be wrong_tool.")
add("H6", "historical", "Can you generate a blank planning template for tomorrow?",
    "generate_schedule_blocks|save_note|add_planning_task", "Any planning-category tool touching tomorrow's date is acceptable.")
add("H7", "historical", "So I'm making my ginger beer. Is there any way that I can, like, test how much sugar is in it after it's done its second ferment? So when it comes to bottling I know how much to add for good carbonation without it going too far.",
    None, "Pure general-knowledge question — correct behavior is answering directly with no tool call.")
add("H8", "historical", "It seemed your LLM was down. Can you try again?",
    None, "Conversational/meta — no tool call expected.")
add("H9", "historical", "Hey, it seems I might have accidentally set my bedtime reminder to 9 a.m.  I need to set that to 9 p.m.  Can you do that for me?",
    None, "Trap: 'bedtime' is a Settings-page-only field (agent/settings.py's settings.bedtime) with NO agent tool to change it — set_reminder would be wrong_tool. Correct behavior is explaining it can't be changed via chat / pointing at Settings.")
add("H10", "historical", "DFPM presents DUB.SEPT\n\nSaturday 19 September 2026\n21:00\n\nSunday 20 September 2026\n3:00\n\nBlank Cultural Platform, 131 City Walk, Canberra, Australian Capital Territory 2601",
    "add_calendar_event", "title~'DFPM presents DUB.SEPT', start=2026-09-19T21:00, end~2026-09-20T03:00 (spans midnight), location includes 'Blank Cultural Platform'.")
add("H11", "historical", "Here's the info for another thing I'm doing: Canberra - Tuff Nutterz with Tuff\nNutterz\n\nSaturday 26 September 2026\n\n11:00 to 12:45\n\nTuff Nutterz, Queen Elizabeth Terrace, Parkes, Australian Capital Territory 2600",
    "add_calendar_event", "title~'Tuff Nutterz', start=2026-09-26T11:00, end=2026-09-26T12:45 (today's date, since the run happens on 2026-09-26), location includes 'Queen Elizabeth Terrace'.")
add("H12", "historical", "And another one: Khaled Khalafalla show\n\nSaturday 7 November 2026\n\n18:00 to 20:00\n\nThe Street theatre",
    "add_calendar_event", "title~'Khaled Khalafalla show', start=2026-11-07T18:00, end=2026-11-07T20:00, location~'The Street theatre'.")
add("H13", "historical", "Sounds great, catch you tomorrow morning",
    None, "Pure sign-off/closing remark — no tool call expected.")
add("H14", "historical", "Ok, I've updated the backend and the device firmware, as well as updating the template to something closer  to what I expected. Can you confirm from what you can see that everything is in order?",
    None, "Asks the assistant to confirm state it has no tool visibility into — a text reply (possibly declining/clarifying its limits) is correct; any tool call here is likely a hallucinated check, mark as unneeded.")
add("H15", "historical", "Yeah, I think the short sprints with timed breaks would work best for me. So, like 20 min in the kitchen, break, 30 min on the lounge room and laundry, break, 20 min in work study, break, etc.\nWe will need to define the areas and potentially estimated effort.",
    "add_planning_task|generate_schedule_blocks", "Lenient: context-dependent (references an earlier plan that doesn't exist in a fresh thread), so accept either concrete add_planning_task call(s) for kitchen/lounge+laundry/work-study, or a reasonable clarifying-but-still-attempting reply.")

# ---- 15 styled-synthetic (voice matched to the real historical messages above) ----
add("S1", "styled_synthetic", "Just got back from a run, was about 35 mins, felt pretty good actually, maybe a 7 out of 10",
    "log_activity", "type~run/exercise, duration~35 (minutes), mood~7.")
add("S2", "styled_synthetic", "can you remind me to take the bins out tonight around 8",
    "set_reminder", "when resolves to today (2026-09-26) ~20:00; message mentions bins.")
add("S3", "styled_synthetic", "set a timer for 12 minutes, i'm boiling eggs",
    "set_timer", "when~12 minutes; message/context mentions eggs.")
add("S4", "styled_synthetic", "what reminders do i have set at the moment",
    "list_reminders", "No args needed.")
add("S5", "styled_synthetic", "actually cancel that bin reminder i just set",
    "cancel_reminder|list_reminders", "Lenient: fresh thread has no prior reminder, so either an attempt to cancel_reminder(message~bin) or a check via list_reminders first is acceptable; a plain hallucinated 'done, cancelled' with no tool call is not_called.")
add("S6", "styled_synthetic", "hey quick one, what do you actually know about me so far?",
    "read_about_me", "No args needed.")
add("S7", "styled_synthetic", "did i ever write anything down about my knitting patterns?",
    "search_notes", "query should mention knitting.")
add("S8", "styled_synthetic", "can you jot down a note that I want to try making sourdough this month",
    "save_note", "content/title should mention sourdough.")
add("S9", "styled_synthetic", "whats the weather looking like over the next few days, thinking of going for a bike ride",
    "get_weather_forecast|get_range_forecast", "A multi-day forecast call, location defaulted if not given.")
add("S10", "styled_synthetic", "can i get one of those reflection prompts, feeling a bit scattered today",
    "get_reflection_prompt", "category may or may not be set; call itself is what matters.")
add("S11", "styled_synthetic", "just so you know, i've moved, i'm in Queanbeyan now not Canberra",
    "set_home_location", "location should become Queanbeyan (not Canberra).")
add("S12", "styled_synthetic", "can you grab the details off this page for me https://example.com/event-details",
    "fetch_webpage", "url should be exactly the given URL.")
add("S13", "styled_synthetic", "what were the details on that tuff nutterz event again",
    "get_calendar_events|search_web|null", "Lenient/hard: no UID known in a fresh thread, so any reasonable attempt (searching calendar events, or admitting it can't find it without more info) is acceptable; a hallucinated made-up answer with no tool call is not_called.")
add("S14", "styled_synthetic", "worked on the 3d printer project for like 2 hours, kind of frustrating tbh, 4/10 mood",
    "log_activity", "type~3d printing/project, duration~120 (minutes), mood=4.")
add("S15", "styled_synthetic", "add 'water the garden' to today's list, shouldn't take more than 10 mins",
    "add_planning_task", "task~'water the garden', duration_minutes~10, date=today (2026-09-26).")

# ---- 15 clean synthetic edge cases ----
# (a) date-relative phrasing (6) — highest priority given today's found bug
add("C1", "clean_synthetic", "remind me to submit my timesheet next Tuesday morning",
    "set_reminder", "when should resolve to 2026-09-29 (next Tuesday), morning (~08:00-10:00). THIS IS THE EXACT FAILURE CLASS FOUND TODAY (qwen2.5 resolved 'next Tuesday' to 2023-11-14) — score strictly on year/month/day correctness.")
add("C2", "clean_synthetic", "can you set a reminder for in 3 days to check the mail redirect",
    "set_reminder", "when should resolve to 2026-09-29 (today+3 days).")
add("C3", "clean_synthetic", "block out an hour this Friday afternoon for admin stuff",
    "add_planning_task|add_calendar_event", "Date should resolve to 2026-10-02 (this Friday), afternoon (~13:00-17:00), duration~60 min.")
add("C4", "clean_synthetic", "a week from today I've got a dentist check-up, can you pop that in the calendar for 10am",
    "add_calendar_event", "start should resolve to 2026-10-03 (today+7 days) at 10:00.")
add("C5", "clean_synthetic", "remind me tomorrow morning to call the vet",
    "set_reminder", "when should resolve to 2026-09-27 (tomorrow), morning.")
add("C6", "clean_synthetic", "can you check what's on my calendar for next month",
    "get_calendar_events", "start/end should span October 2026 (2026-10-01 to 2026-10-31).")
# (b) no-tool-needed conversational (3)
add("C7", "clean_synthetic", "how's it going?", None, "Small talk — no tool call.")
add("C8", "clean_synthetic", "what's the capital of France?", None, "General knowledge — no tool call.")
add("C9", "clean_synthetic", "thanks, that's really helpful", None, "Acknowledgement — no tool call.")
# (c) ambiguous-but-answerable, reasonable default expected (one_shot rule) (3)
add("C10", "clean_synthetic", "add an event for lunch with Sam",
    "add_calendar_event", "No date/time given — per the one_shot system-prompt rule the model should assume a concrete date/time (e.g. today or tomorrow, ~12:00) rather than asking a clarifying question. title~'Lunch with Sam'.")
add("C11", "clean_synthetic", "remind me about the thing later",
    "set_reminder", "Very vague — correct behavior per one_shot is still to set a reminder with a reasonable assumed time (e.g. a few hours out) and a generic message, not to refuse or ask for clarification.")
add("C12", "clean_synthetic", "log my workout",
    "log_activity", "No duration/mood given — should still call log_activity with reasonable defaults/omissions rather than refusing.")
# (d) more coverage / compound requests (3)
add("C13", "clean_synthetic", "what's the date next Wednesday, and can you also tell me the forecast for then",
    "get_current_datetime|get_weather_forecast|get_range_forecast", "Compound request: next Wednesday = 2026-09-30. Accept either/both tools; the datetime part should resolve to 2026-09-30 specifically if get_current_datetime or an equivalent date computation is surfaced in the reply.")
add("C14", "clean_synthetic", "remind me the day after tomorrow to renew my passport",
    "set_reminder", "when should resolve to 2026-09-28 (today+2 days).")
add("C15", "clean_synthetic", "can you tell me if I'm free this Saturday afternoon",
    "get_calendar_events", "Trap: today (2026-09-26) IS already a Saturday — 'this Saturday' most naturally means TODAY, not next Saturday. Check whether the model resolves to 2026-09-26 (correct) vs. incorrectly jumping to 2026-10-03 (bad_args).")

with open("scratchpad/eval_prompts.json", "w") as f:
    json.dump(prompts, f, indent=2)

print(f"Wrote {len(prompts)} prompts to scratchpad/eval_prompts.json")
from collections import Counter
print(Counter(p["source"] for p in prompts))
