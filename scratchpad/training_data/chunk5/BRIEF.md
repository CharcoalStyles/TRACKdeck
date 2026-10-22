# Chunk 5 brief — negatives, modes, notes/projects/about-me tools (delta on chunk 4)

**First read `scratchpad/training_data/chunk4/BRIEF.md` in full** — record schema, `date_intents` rules, date
conventions, arg formats, behaviour rules 1–14, mix targets and workflow all still apply, with the changes below.
Repo root: `/home/charcoal/docker/trackdeck`. Write to `scratchpad/training_data/chunk5/<YOURFILE>.jsonl`,
ids `B5X-0001`…, validate with
`uv run python scratchpad/training_data/validate_full_batch.py scratchpad/training_data/chunk5/<YOURFILE>.jsonl`
(all 7 checks must show 0 issues).

## What is different from chunk 4
- Chunk 4 was date-dense; chunk 5 is NOT. Most records need no `date_intents` (omit the key). When a date *is* used
  (planning dates, reminders, calendar lookups) it must still be exactly right — compute with Python, and use
  `date_intents` for any date arg that comes from user phrasing.
- Cumulative `no_tool` is at 17.5% and must reach ≥20% overall, so chunk 5 carries many negatives (files D/E are
  nearly all negatives; A–C each include a few look-alike negatives).
- Rule 7 changes: `set_home_location` is allowed **only** with `flags.mode: "onboarding"`. In ordinary chat a
  location/timezone change request is a negative (see below).
- Anchors: still vary widely 2026-03 … 2028-12, no two records in your file share an anchor, real Canberra offsets
  (+11:00 Oct–Apr, +10:00 Apr–Oct; changeover Sundays 2026-10-04, 2027-04-04, 2028-04-02, 2028-10-01 — never an
  anchor in the 02:00–03:00 hour). The 35% boundary-anchor requirement is dropped.

## Negative (`no_tool`) records
- `category: "no_tool"`, `turns` = a single `{"content": "<reply>"}` block, no `date_intents`.
- A negative is a message where the correct behaviour is NO tool call. Types (spread across them in D/E):
  1. **Capability limits** — no tool exists: music/media, smart-home/lights, printing, QR/OCR/image reading,
     sending email/texts, phone calls, ordering food/shopping, maps/directions/traffic, booking travel, banking,
     controlling the device volume, setting alarms *as a device feature* (reminders exist — an "alarm" request that
     is really "remind me at 6" is a tool case, not a negative). Reply: short plain decline + what the assistant CAN
     do if natural. Never claim to have done it.
  2. **Settings-only fields** — wake time, bedtime reminder time, latest check-in time, daily digest time/email,
     timezone, default location, calendar sync interval, device poll interval, notification (push) server, which
     AI model/provider is used, alert/chime sound, recall settings. No agent tool changes these. Reply: say it's
     changed from the Settings page; never name internals ("settings.db", "agent/settings.py", "APScheduler").
  3. **Ordinary-chat "I've moved"/location/timezone changes** (eval S11 family): user says they've moved or are
     travelling and wants the assistant to use the new place. `set_home_location` is onboarding-only, so reply
     is: congratulate/acknowledge briefly and point to the Settings page for the home location. No tool call.
     Include a few with `one_shot: true` (still never end on a question).
  4. **Look-alike traps** — messages that sound like a tool call but are not: venting about a busy calendar,
     "remind me every Monday" (reminders are one-off; offer a recurring calendar event — but this is a *question
     back*, so non one_shot only; for one_shot the right move is to create the recurring calendar event, which is a
     TOOL record, not a negative — don't mislabel), "what's the capital of …"/general knowledge, "how do I make a
     note" (how-to question about the app), discussing past events without asking for a lookup, hypotheticals
     ("what would I do if it rained Saturday"), commentary on the weather ("ugh it's freezing") with no request,
     "thanks"/"cheers"/sign-offs, greetings, jokes, opinions, small talk, a request that needs info the user did not
     give and cannot be defaulted (ask a clarifying question — NOT one_shot).
  5. **Mode-scoped negatives** — off-topic question in `profile_chat` (stay scoped), small talk during `onboarding`
     or `day_planning`, a project_chat question that is general knowledge. Keep the flags (`mode`, `project`).
- A one_shot negative never ends on a question: decline/answer and stop. A non-one_shot negative may ask one short
  clarifying question when truly needed.
- Replies: 1–3 sentences, plain, same voice as chunks 1–4. No emojis. No app-internal names.
- Do not make the capability-limit reply preachy; one short sentence, optionally one helpful alternative that the
  assistant genuinely can do (e.g. "I can set a reminder for it").

## Mode records (flags.mode ∈ onboarding | profile_chat | day_planning | project_chat)
Copy shapes from chunk1 B1C (`scratchpad/training_data/chunk1/B1C.jsonl`) and chunk2/3 B2D/B3B. Always
`learning_mode: true` as well.
- **onboarding**: interview style; `remember_about_me` as facts arrive (one call per distinct fact, correct
  `section`), `set_home_location` when a place is stated (real string on failure:
  `Couldn't resolve '{x}' to a place — ask them to be more specific, or it can be set directly from the Settings page.`),
  `mark_onboarding_complete` only when the user clearly says they're done/finished the checklist.
- **profile_chat**: `read_about_me` first before stating what is recorded; `remember_about_me` with
  `mode: "replace"` / `"append"` exactly as in chunk 1–3 examples for corrections; off-topic → negative.
- **day_planning**: user message is a "Plan my day for YYYY-MM-DD" task list → one `add_planning_task` per task,
  then `generate_schedule_blocks` for the date (see B1C-0027); single-task follow-ups also appear.
- **project_chat**: `flags.project` = project name; `save_note`/`search_notes` carry `project=<name>` where the
  tool has that arg; `get_or_create_project` / `list_projects` appear when the user names/asks about projects.

## Notes / projects / about-me tools
`read_note`, `append_to_note`, `update_note_section` need a `note_id`: the user NEVER states it. It comes from a
prior `search_notes` result in `turns` (lookup-first) or from `history` (flat role messages) — never invented.
`append_to_note`/`update_note_section` need an existing `section` heading — take it from a `read_note` result
in `turns`/`history`, not invented. `get_or_create_linked_note(topic, category)` is for distinct people/topics.
Tool-result strings must match the real formats — copy from existing chunk 1–3 records of the same tool and
`scratchpad/training_data/tool_result_references.json`. Search results: realistic ids (8 hex chars), titles,
snippets; never placeholder text.

## Remaining tool coverage (assigned in file C)
`cancel_reminder` (real error `No pending reminder matching '{message}'.`), `list_reminders`, `get_todays_events`,
`get_reflection_prompt` (optional `category`), `search_news`, `search_images`, `search_videos`, `get_calendar_event`
(uid from history/lookup), `generate_schedule_blocks` (date/start_time/end_time), `fetch_webpage` (user pastes a
URL; the URL convention is `fetch_webpage`, never `fetch_url`). MCP web tools: see `scratchpad/training_data/
mcp_tool_schemas.json` for arg shapes and copy result formats from existing records.

## Mix targets (per file unless the assignment says otherwise)
- `one_shot: true` on ~25%; ≥10% parallel (multi-entry `tool_calls`, independent calls only) in A–C; ~5–8% error
  recovery in A–C (real error strings, honest retry); negatives per the assignment.
- Everything else from chunk 4 brief: no near-copies of the 45 eval prompts in `scratchpad/eval_prompts.json`
  (≥0.85 similarity rejected — be well clear; e.g. don't reuse the eval's S11 wording), vary entities heavily,
  casual dictated voice, ≤~2,000 tokens/record, no placeholder tool results, never claim an unverified action.

## Assignments
- **B5A (46)**: notes tools — save_note (incl. project-scoped), search_notes, read_note, append_to_note,
  update_note_section, get_or_create_linked_note; lookup-first chains; ~5 look-alike negatives (e.g. "how do I
  make a note", chatting about a note's topic).
- **B5B (46)**: about-me and projects — read_about_me, remember_about_me (append/replace), get_or_create_project,
  list_projects, mark_onboarding_complete, set_home_location (onboarding only); modes onboarding (~14),
  profile_chat (~12), project_chat (~10); ~5 mode-scoped negatives.
- **B5C (46)**: remaining coverage — cancel_reminder, list_reminders, get_todays_events, get_reflection_prompt,
  search_news, search_images, search_videos, get_calendar_event, generate_schedule_blocks/day_planning (~8),
  fetch_webpage, get_current_weather; ~5 look-alike negatives.
- **B5D (46)**: NEGATIVES A — ~38 capability-limit + settings-only + look-alike traps (spread all five types
  above); the other ~8 are matching positive controls where the near-identical ask DOES need a tool (e.g. "set a
  reminder to turn the heating off" vs "turn the heating off"). Include some modes.
- **B5E (46)**: NEGATIVES B — ~40 ordinary-chat negatives: ordinary-chat "I've moved/I'm in X now" (≥10, varied
  towns/cities/countries, a few one_shot), acknowledgements/sign-offs/greetings/small talk, venting, general
  knowledge, hypotheticals, clarify-first (non-one_shot) asks, mode-scoped negatives; the other ~6 are positive
  controls with a tool.

## Report (under 150 words)
File, record count, one_shot / parallel / negative / error-recovery counts, any problem hit. Do NOT paste records.
