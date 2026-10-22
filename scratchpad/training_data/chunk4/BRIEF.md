# Chunk 4 brief — date-heavy tool-calling scenarios (LoRA data for trackdeck's small local LLM)

You are writing synthetic training scenarios, as JSONL (one record per line), straight into the
trainer's final schema. Chunks 1–3 (765 records) already exist in `scratchpad/training_data/chunk{1,2,3}/B*.jsonl`
— **read 3–4 records of the relevant tool types from them first and copy their exact shapes** (tool_calls arg
formats, tool_result strings, reply tone). Repo root: `/home/charcoal/docker/trackdeck`.

## Why chunk 4 exists
The stock model's weakest skill is **date/time arithmetic** (2/24 on the eval). The trainer machine-parses every
phrase in `date_intents` against the anchor and compares to the arg value, so every date must be exactly right.
Chunk 4 is built around dates: relative phrasing resolved against a per-record anchor.

## Record schema (final)
```
{"id":"B4X-0001","source":"synthetic","category":<CATEGORY of the FIRST tool call, or "no_tool">,
 "anchor":"2026-11-14T18:20:00+11:00",           # ISO8601 + real Australia/Canberra offset for that local time
 "flags":{"learning_mode":true, "one_shot":true?, "mode":..?, "project":..?},   # learning_mode ALWAYS true
 "text":"<the user's message>",
 "turns":[ {"tool_calls":[{"name":..,"args":{..}}],"content":""},   # multiple entries in tool_calls = parallel calls
           {"tool_results":["<one string per call, same order>"]},
           ... (more call/result pairs if needed) ...
           {"content":"<final assistant reply, no tool_calls>"} ],
 "date_intents":[{"phrase":"<exact substring of THIS record's text>","arg":"tool.field","call":<int, optional>}],
 "group":..?, "history":[flat role-tagged msgs]..?, "notes":"<one line>"}
```
- category = the CATEGORY_MAP value of the first tool called (`agent/tool_router.py`): calendar, weather, notes, planning,
  reminders, checkin, general, activity_log, web… ; `"no_tool"` for negatives.
- `history` (rare here) is flat OpenAI-style `{role: user|assistant|tool, content, tool_calls?}` messages ending on a plain assistant message — NOT the `turns` block shape.
- Anchor = the "current local time" the assistant is told. The weekday of the anchor date must be what you intend.

## date_intents rules (the trainer enforces these — violations get the record rejected)
- One intent per **date argument whose value comes from a phrase in the user's text** (set_reminder.when, set_timer.when,
  get_calendar_events.start/.end, add/update_calendar_event.start/.end, add_planning_task.date, log_activity.when,
  get_range_forecast.start/.end). If start and end both come from one phrase ("this weekend"), give an intent for each arg with the same phrase.
  Defaulted values (e.g. end = start+1h with no stated duration) get no intent.
- `phrase` must be an **exact substring of `text`** and must be a genuine date/time expression ("next Thursday at 2pm", "in 20 minutes",
  "the end of the month"). Not a whole clause ("the weekend's shaping up" is wrong → "the weekend"). No typos inside the phrase.
  Don't use event-relative phrasing as an intent ("30 minutes before the dentist" → no intent for that arg).
- `call` = 0-based index among calls **of that same tool** (NOT overall position). If a tool is called once, omit `call`.
  E.g. add_calendar_event then set_reminder → the set_reminder intent has no `call` (or `call: 0`), never `call: 1`.
- Never put an intent on a phrase that appears only in `history`.
- Avoid "long weekend" / public-holiday language unless the text itself names the holiday and dates.

## Date conventions (compute with Python — `datetime`, `calendar`, `zoneinfo.ZoneInfo("Australia/Canberra")` — never in your head)
- `scratchpad/training_data/date_resolver.py` implements: **"next <weekday>"** = next occurrence strictly after today (1–7 days ahead; on a Thursday, "next Thursday" = +7);
  **"this <weekday>"** = occurrence in the current week, today if it's that weekday — only use "this <wd>" for today or an upcoming day in the same Mon–Sun week, never a weekday already past.
  "this weekend" = the coming Sat–Sun (today through Sunday if today is Sat/Sun). Bare weekday ("Friday 9am") = the next upcoming such day (today if today and the time is still ahead).
  "end of the month"/"end of next month" = last calendar day; "the first of the month" = 1st of the coming month; "the day after tomorrow" = +2d; "a week from today" = +7d; "in N days/weeks" exact.
- Bare hours without am/pm are fine when context fixes them ("at 4 this afternoon", "9 tonight"); otherwise use am/pm or 24h in args.
- Arg formats (copy chunk 1–3): `set_reminder.when`/`set_timer.when` = `"YYYY-MM-DD HH:MM:SS"` (local, must be strictly after the anchor); `add_calendar_event.start/end` = `"YYYY-MM-DD HH:MM:SS"` local;
  `get_calendar_events.start/end` = `"YYYY-MM-DD"` (end inclusive date); `add_planning_task.date` = `"YYYY-MM-DD"`.
- Calendar JSON in tool results: `start`/`end` are **UTC** (`20261107T070000Z`). UTC = local − offset (+11:00 Oct–Apr AEDT, +10:00 Apr–Oct AEST). Convert with zoneinfo; the reply then states LOCAL times.
  DST: starts first Sunday of October 02:00 (→03:00), ends first Sunday of April 03:00 (→02:00). 2026-10-04 and 2027-04-04 and 2028-04-02, 2028-10-01 are changeover Sundays. Never use an anchor in the nonexistent/ambiguous 02:00–03:00 hour on those days.
  An event on a changeover day, or a window spanning a changeover, must have correctly-offset UTC values.
- Weekday names in your reply must match the date (check with Python). Replies state the resolved date in plain words so it is checkable.

## Anchor distribution (important — vary hard)
Anchors range across 2026-03 … 2028-12 (include 2028-02-28/29 leap-year cases and at least a couple of 2027-12 / 2028-01 year-crossing ones).
At least **35% of your anchors** must be "boundary" anchors: Saturday or Sunday (incl. Sunday evening), the last 3 days of a month, Dec 26–Jan 3, Friday late evening, and changeover weekends
(Sat 2026-10-03, Sun 2026-10-04 after 03:00 → +11:00, Sat 2027-04-03, Sun 2027-04-04 after 03:00 → +10:00, etc.). Anchor times also vary (06:10 … 23:40), and no two records share an anchor.

## Behaviour rules (hard-won — each cost a rejection earlier)
1. Never write shorthand/placeholder text inside a tool result ("(7 days total, same shape)"); results must be the full real output. `get_range_forecast` returns one entry per day inclusive; `get_weather_forecast` a full 7-entry array.
2. Never claim a state/action that no tool call in `turns` verified. If the reply says "nothing on", a get_calendar_events call must precede it. Don't claim an action a tool can't perform (no buffers/travel time etc. unless a tool arg does it).
3. Don't carry stale facts as confirmed; ask or drop.
4. Default weather location is Canberra (one consistent user) unless the user names a city. The user lives in Canberra, kids' names etc. may recur sparsely — vary entities heavily.
5. IDs: the user never states a uid/note_id. update/delete calendar events need a uid from a prior lookup in `turns` (lookup-first) or from `history`. Never invent optional args the user didn't give (no invented mood_energy, location, etc.).
6. Never describe app internals in replies (no "the scheduler", "APScheduler", "settings.db"). Capability limits are stated generically.
7. `set_home_location` only in onboarding mode (don't use it here).
8. Error results must begin with a recognised prefix: `Error`, `{"error`, `I couldn't understand`, `Failed to`, `No note found`, `Couldn't resolve`, `Couldn't fetch`. Real strings: set_reminder/set_timer bad time → `I couldn't understand the time '{when}'. Try an absolute date and time.`; calendar → `Failed to {action}. {detail}`; cancel_reminder → `No pending reminder matching '{message}'.`. An error followed by a later call to the same tool = a "retry" scenario (the trainer excludes the wrong first attempt from training) — the retry must fix the cause, the reply honest. Include error-recovery in ~5% of records, **never** fabricate a success.
9. Reminders are one-off (no recurrence). A recurring need = a calendar event with `recurrence` or an explanation; "remind me every Monday" is a trap (see negatives).
10. Don't copy the 45 held-out eval prompts (`scratchpad/eval_prompts.json`): rephrase well away (the validator rejects ≥0.85 similarity; aim for clearly different wording and different entities).
11. Reminder `when` must be strictly after the anchor. "Tonight at 9" when the anchor is already 22:00 is a trap → resolve to tomorrow only if the user would plausibly mean it, otherwise no_tool/ask (non-one_shot) or state the assumption (one_shot).
12. Final reply states what was done + the resolved day/time + any assumption made, in 1–3 sentences. one_shot replies never end on a question.
13. Phrasing diversity: the user's messages are dictated voice text — casual, sometimes run-on, hedged ("about", "maybe"), occasional context-then-ask. Typos allowed only in non-date words, sparingly. Do not reuse a template; vary openers, verbs, sentence shapes. No two texts within ~0.7 similarity.
14. Under ~2,000 tokens per record. Each record is a different scenario (different entities, anchors, phrasing).

## Mix targets inside every file (unless your assignment says otherwise)
- `flags.one_shot: true` on ~25% of records (these simulate the no-follow-up ESP32: make a reasonable assumption, state it, finish; never end on a question). The rest omit the key.
- ≥12% of records are parallel (a multi-entry `tool_calls` list in one assistant turn: independent calls only).
- ~5% error-recovery (see rule 8).
- Spread phrasing types across relative forms: next/this weekday, "in N minutes/hours/days/weeks", tomorrow morning/arvo/night, "the day after tomorrow", "end of the month/week", "first thing Monday", times with and without am/pm, "half nine", "quarter past 3", "noon", "around 10ish", across month and year boundaries.

## Workflow
1. Read this brief + 3–4 chunk 1–3 example records for each tool in your assignment.
2. For every record, pick the anchor, compute every date/time with Python (write a small helper in your scratchpad dir if useful; use `zoneinfo`), then write the record.
3. Write to `scratchpad/training_data/chunk4/<YOURFILE>.jsonl` (ids `B4X-0001`…). Validate:
   `cd /home/charcoal/docker/trackdeck && uv run python scratchpad/training_data/validate_full_batch.py scratchpad/training_data/chunk4/<YOURFILE>.jsonl`
   Every check (CONTAMINATION, ARG SCHEMA, TURN SHAPE, STATED-ID, REMINDER-FUTURE, DATE-INTENT, ANCHOR TZ) must show 0 issues. The DATE-INTENT check verifies per-tool `call` indexes and weekday / tomorrow / "in N units" / am-pm hour consistency against the anchor. Fix and rerun until clean.
4. Self-audit with Python before you finish: for each record, print anchor weekday, phrase, resolved arg value + its weekday, and eyeball every one; verify UTC conversions in calendar results; check weekday names in replies.
5. Report in under 150 words: file, record count, one_shot/parallel/negative/error counts, any problem you hit. Do NOT paste records in your report.
