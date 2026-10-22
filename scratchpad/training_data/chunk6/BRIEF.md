# Chunk 6 brief — round 2, gap-targeted (delta on chunk 4 + chunk 5 briefs)

**Read first, in full:** `scratchpad/training_data/chunk4/BRIEF.md` (schema, date_intents rules, date conventions,
behaviour rules 1–14) and `scratchpad/training_data/chunk5/BRIEF.md` (negatives, modes, notes tools). Everything
there still applies. Repo root `/home/charcoal/docker/trackdeck`. Output `scratchpad/training_data/chunk6/<FILE>.jsonl`,
ids `B6X-0001`…, validate with
`uv run python scratchpad/training_data/validate_full_batch.py scratchpad/training_data/chunk6/<FILE>.jsonl`
(all 7 checks must show 0 issues). Always `learning_mode: true`; `one_shot: true` on ~25%; vary anchors (no two
records in your file share one; real Canberra offsets; never an anchor in a changeover 02:00–03:00 hour).

## Why round 2 exists
The v1 model (trained on chunks 1–4) went 26/45 → 38/45 on the held-out eval. These gap-targeted records fix what v1
still gets wrong. Each file targets one specific gap below — stay on target and make every record unambiguous,
because the trainer machine-checks the labels.

## Rules that matter for this round
- **get_current_datetime rule (matches the SYSTEM_PROMPT):** call `get_current_datetime` ONLY when the user
  explicitly asks what the date/time is right now ("what's today's date", "what time is it", "is it still the 3rd").
  Date ARITHMETIC or relative reasoning ("what day is tomorrow", "how many days until Christmas", "what's the date
  90 days from today", "is 2028 a leap year") is answered from the date line with **no tool** (`no_tool`).
- **Weather tool choice:** `get_current_weather` only for right-now conditions; `get_weather_forecast` for the next
  days (7-day array); `get_range_forecast` for specific dates/ranges ("Saturday and Sunday", "this weekend", "the
  12th to the 14th"). Default location Canberra unless the user names a place.
- **news vs web:** `search_news` = recent events/headlines/"what's happening with X"/"latest on X"/"any news about
  X"; `search_web` = facts, how-tos, businesses/opening hours/addresses/prices/recommendations/reviews, anything not
  primarily "news". Look at `scratchpad/training_data/mcp_tool_schemas.json` and existing records for arg shapes and
  result formats (copy formats; never placeholder results).
- `get_calendar_event(uid)` — the uid is never stated by the user; it comes from `history` (flat OpenAI-style role
  messages ending on a plain assistant message) — see file B6B.
- Never delete/modify a calendar event without an identifiable target. Never call `remember_about_me` for a
  statement about a third party's mood/situation unless the user states a durable fact about THEMSELVES.
- Texts must stay clear of the 45 eval prompts in `scratchpad/eval_prompts.json` (similarity ≥0.85 rejected);
  in particular don't reuse the wording of eval H3 / C15 / S11 prompts.

## Weekend-anchor date semantics (file B6A) — compute with `scratchpad/training_data/date_resolver.py`
- Anchor on a **Saturday**: "this weekend" = today (Sat) through tomorrow (Sun); "this Saturday" = today;
  "this Sunday" = tomorrow; "today and tomorrow" = Sat+Sun. "Next Saturday"/"next Sunday" = use the resolver
  (next <wd> = strictly after today; 1–7 days).
- Anchor on a **Sunday**: "this weekend" = today only (Sun); "this Sunday" = today; "today and tomorrow" = Sun+Mon.
  Don't use "this Saturday" on a Sunday (already past) — use "next Saturday" (= +6 days) if you need that day.
- The failure to teach: the model must NOT slide "this Saturday/this weekend" to the following week when the
  anchor is itself Saturday/Sunday. Whenever a `set_reminder`/`add_calendar_event` time is used, it must be strictly
  after the anchor — if "this Saturday 9am" with a Saturday anchor of 14:00 has already passed, don't use that
  record shape (pick an earlier anchor time or a later time of day). Calendar lookups and range forecasts have no
  such problem (end/start are dates).
- Give a `date_intents` entry for EVERY date arg that comes from user phrasing (e.g. `get_range_forecast.start` and
  `.end` both from "this weekend"), phrase = exact substring of `text`.

## Assignments (counts are targets)
- **B6A (28)**: weekend-anchor date records. Anchors: ~14 Saturdays + ~14 Sundays (vary times 06:10…23:40 and
  months across 2026-11 … 2028-12, incl. a couple of changeover weekends and the 2028-02-26/27 leap-year weekend).
  Mix: `get_calendar_events` ("this weekend", "today and tomorrow", "this Saturday", "this Sunday"),
  `get_range_forecast` for weekend windows, `set_reminder` (e.g. "this Sunday at 6pm"), `add_calendar_event`,
  and ~5 compounds (calendar + forecast in one parallel turn). ≥25% one_shot, ≥4 parallel.
- **B6B (22)**: `get_calendar_event` with a uid from `history`: ~7 where history holds a `get_todays_events`
  list and the user asks about one event ("what time's the dentist one again", "where's that lunch"); ~7 where
  history holds an `add_calendar_event` result ("Event added successfully. UID: …") and the user asks a follow-up
  about that event; ~6 where history holds a `get_calendar_events` range result and the user asks for details of
  one event; ~2 negatives where history holds several events and the ask is ambiguous (non-one_shot: ask which
  one, no tool). The final call must be `get_calendar_event` with the right uid, and the reply must state only what
  the tool result returned (copy the exact result format from existing `get_calendar_event` records in chunks 1–3).
- **B6C (36)**: no-tool traps v1 turns into tool calls: ~7 venting/small talk/"how's it going"/"morning"; ~7
  statements about a third party ("Theo's going through a rough patch", "my sister's been really stressed lately")
  → no `remember_about_me`; ~5 complaints like "that never buzzed" / "my reminder didn't go off" → no
  `read_about_me` (sympathetic reply; offering to check what's pending is fine, but don't call a tool in the
  no_tool record); ~6 look-alike settings-only fields (wake time, bedtime reminder, digest time/email, check-in
  cutoff, push notification server, model choice) → point to the Settings page, never name internals; ~4 "pull
  that one off my calendar"/"cancel that" with nothing identifiable → ask which (non-one_shot); for a one_shot
  version, say you can't tell which event and won't delete a guess — no question mark, no tool; ~4 explicit
  "what's the date/time right now" asks → `get_current_datetime` (category `general`, result format
  `The current date and time is: 9:15 AM on Friday 31 December 2027`); ~3 arithmetic/relative date asks
  ("what day is it tomorrow", "how many days till Easter 2027") → `no_tool`. Total negatives ≈ 29 of 36.
- **B6D (30)**: ~14 `search_news` records (headlines/latest/"any news on"), ~8 `search_web` look-alikes that must NOT
  use search_news (opening hours, recipes, reviews, how-tos, "best X"), and ~8 compounds of a web tool plus
  another tool in one parallel turn (e.g. search_web + `get_range_forecast` for a named day window, search_news +
  `get_todays_events`, search_web + `add_calendar_event`) — pick `get_range_forecast`/`get_weather_forecast`
  rather than `get_current_weather` when the weather question is about a future day. ≥8 parallel in total.
- **B6E (14)**: long planning lists: "Plan my day for YYYY-MM-DD" with 6–8 numbered tasks → one
  `add_planning_task` call per assistant turn (sequential turns, each followed by its tool_result), then a final
  `generate_schedule_blocks` for the date, then the reply. Copy the exact shape of B1C-0027. Keep under ~2,000
  tokens (short task names, short result strings). A few with a `date` that is relative in the text ("for
  tomorrow", "for Friday") need `date_intents` on every `add_planning_task.date` call with the per-tool `call`
  index (0,1,2,…) and one more on `generate_schedule_blocks.date`. Flags: `mode: "day_planning"` on most.
  One or two with 6+ one-line tasks without a date (defaults to today: no date arg, no intents). ≥3 one_shot.

## Report (under 150 words)
File, record count, one_shot / parallel / negative / error counts, any problem hit. Do NOT paste records.
