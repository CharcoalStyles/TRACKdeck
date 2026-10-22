# Chunk 7 brief — v3 counter-examples (delta on chunk 4 + 5 + 6 briefs)

**Read first, in full:** `scratchpad/training_data/chunk4/BRIEF.md` (schema, date_intents rules, date conventions,
behaviour rules), `chunk5/BRIEF.md` (negatives, modes), `chunk6/BRIEF.md` (get_current_datetime rule, news-vs-web).
Everything there still applies. Repo root `/home/charcoal/docker/trackdeck`. Output
`scratchpad/training_data/chunk7/<FILE>.jsonl`, ids `B7X-0001`…, validate with
`uv run python scratchpad/training_data/validate_full_batch.py scratchpad/training_data/chunk7/<FILE>.jsonl`
(all 7 checks must show 0 issues). `learning_mode: true` always; `one_shot: true` on ~25%; vary anchors (no two
records in your file share one; real Canberra offsets; never in a 02:00–03:00 changeover hour).

## Why chunk 7 exists
The v2 model (chunks 1–6) did NOT beat v1 on the held-out eval (36 vs 38) because it OVER-TRIGGERS tools it saw
positive examples of. Observed failures, which these records must counter:
- Pasted event details → v2 searches the web / fetches pages instead of adding the calendar event; also calls
  read_about_me/remember_about_me.
- A plain general-knowledge question → v2 loops search_web → fetch_webpage for ten rounds.
- "It seemed your LLM was down, can you try again?" → v2 calls read_about_me.
- Ordinary statements trigger remember_about_me/read_about_me (learning-mode over-use).
Every record in this chunk is a **counter-example**: the clean, restrained behaviour. Keep each pair-contrast
unambiguous because the trainer machine-checks labels. Do NOT copy the wording or entities of any of the 45 eval
prompts in `scratchpad/eval_prompts.json` (similarity ≥0.85 is rejected; in particular H11 "Tuff Nutterz" /
H12 "Khaled Khalafalla" / Street theatre / Parkes, and S11 "Queanbeyan", and the ginger-beer sugar question are
off-limits — invent clearly different events, venues, topics).

## Global rules for this chunk
- Final replies are short and plain (1–3 sentences), same voice as earlier chunks. No emojis, no app internals.
- `no_tool` records: `category:"no_tool"`, `turns` = single `{"content": ...}` block, no `date_intents`.
  A one_shot negative never ends on a question.
- At most **one** `search_web`/`search_news` call per scenario unless the assignment says otherwise; **never** more
  than one `fetch_webpage`; never a loop. After the tool result(s) the next block is the final plain-text answer.
- Search result formats: copy from existing records (`scratchpad/training_data/mcp_tool_schemas.json`, grep
  `search_web` in chunk1–6 files). Results must be full, realistic, never placeholders. The final answer states only
  what the results support; never claim to have verified something that was not returned.
- Only call `remember_about_me`/`read_about_me` when the assignment says so.
- No `fetch_url`. `set_home_location` stays onboarding-only.

## Assignments
- **B7A (40) — pasted/forwarded event text → `add_calendar_event`, never web search.** The user message IS the
  event details (title, date, time, venue), pasted in MANY styles: multi-line ticketing-site copy-paste (title /
  blank line / "Saturday 14 November 2026" / "19:30 to 22:00" / venue + address), a forwarded email snippet
  ("Hi all, reminder our quiz night is on Thursday 3 December at 7pm at the Hellenic Club"), a one-line text from a
  mate, a flyer transcription, a school newsletter line, a booking confirmation, "doors 7 show 8", start-only with
  no end time, start+end, all-day style, a framing sentence before ("here's another one I'm going to:") or none.
  Behaviour: `add_calendar_event` with `title`, `start`, `end` (end = stated end; if only a start is given, end =
  start + 1 hour with NO date_intent for end — copy how chunk1–4 records default it), `location` if a venue is
  given (copy arg names from the real schema). Absolute dates ("Saturday 14 November 2026") are fine date_intents:
  phrase = exact substring of `text` covering the day + time words the trainer must parse; for end give an intent
  whose phrase carries the day words too (chunk4 brief: end phrase needs the day). The date must be in the future
  of the anchor, the weekday in the pasted text must match the real calendar date (verify with Python). Vary
  anchors widely (2026-10 … 2028-12). ~6 parallel (two events pasted together → two `add_calendar_event` calls in
  one turn, per-tool `call` indexes 0,1), ~6 with an honest error + retry ("Failed to add event. …") using real
  strings, ~10 one_shot (state any assumption in the reply, e.g. "no end time was given so I made it an hour").
  Also ~4 hard cases where the pasted text has no year (resolve to the next occurrence after the anchor, state
  the year in the reply) and ~2 where the text has an ambiguous/missing time → non-one_shot: ask the time (no
  tool); one_shot: state the assumption explicitly (e.g. 9am) and add it.
- **B7B (30) — answer from knowledge, don't search.** ~22 `no_tool` records: cooking (why does bread need
  resting, substitute for buttermilk, how long to boil an egg), DIY/home (how to unblock a drain, what's a stud
  finder), how-things-work (how does a heat pump work, why is the sky dark at night), general health (is it OK to
  take paracetamol with food — keep it safe and general, suggest a pharmacist/doctor for anything specific),
  history, geography, language, units/conversions, quick maths. Give the real, correct, concise answer (2–3
  sentences). Then ~8 PAIR-CONTRAST records that genuinely need `search_web` (one call, then a plain answer):
  current prices, "what's on in town this weekend", live scores/results, opening hours for a named business,
  "is X open today". Make each contrast pair obvious from the wording (knowledge vs current/local info). Mix in
  ~7 one_shot. Do not reuse the ginger-beer/sugar-testing topic.
- **B7C (35) — learning-mode restraint.** Learning mode is on, but the model must NOT call `remember_about_me` /
  `read_about_me` unless the user states a durable fact about THEMSELVES. ~28 records where the correct answer is no
  profile tool: one-off tasks/errands ("I need to pick up the dry cleaning", "got to ring the plumber tomorrow" —
  if it's a clear reminder ask, use `set_reminder`; if just narration, `no_tool`), other people's news ("my mate
  Dave got a new job"), opinions ("that film was rubbish"), weather chat, passing moods, plans for today, jokes,
  questions the assistant can answer. Of these ~28: ~16 `no_tool`, ~12 where the correct tool is something OTHER
  than the profile tools (set_reminder, add_calendar_event, save_note, get_todays_events, add_planning_task,
  get_current_weather…), still with zero about-me calls. Then ~7 contrast records where a durable fact IS stated
  ("I'm vegetarian", "I work nights at the hospital", "my daughter's name is Maya and she's six", "I'm allergic to
  penicillin") → `remember_about_me` with the correct `section`/mode copied from chunk1/3/5 shapes, single call,
  short acknowledgement. Make the contrasts clear. ~9 one_shot.
- **B7D (30) — after one search, answer.** ~20 `search_web` scenarios: one call, one realistic result block, then a
  plain-text answer drawn from the results (no second search, no fetch). ~10 where ONE `fetch_webpage` is
  justified: either the user pasted a URL (call `fetch_webpage` directly, answer from the page), or search_web
  results include one clearly-relevant page whose snippet is not enough and the user asked for specifics (search →
  single fetch → answer). Exactly one fetch max, no loops. Include 4 `search_news` single-call answers. ~8
  one_shot. Cover varied topics (local businesses, recent product releases, event info, recipes needing a source,
  sports results, travel times that need current info). Replies summarise only what the results say.
- **B7E (15) — meta/chat about the assistant itself → `no_tool`.** "try again", "it seemed your LLM was down, can
  you try again?" (no previous context needed: reply that it's happy to, and ask what they'd like it to do / or
  ask them to repeat the request — non one_shot may ask; one_shot says it's ready and they can repeat the request,
  no question mark), "you got that wrong", "that's not what I asked", "are you there?", "can you hear me?", "did
  that go through?" (with no tool context: say it can't see a previous request in this chat), "what can you do?",
  "who are you?", "thanks, that was useful", "you're slow today", "never mind". Use `history` on ~5 of them
  (flat role messages ending on a plain assistant message) so "you got that wrong" has something to refer to; the
  honest reply acknowledges and offers to redo it WITHOUT calling a tool in this record. ~4 one_shot.

## Report (under 150 words)
File, record count, one_shot / parallel / negative / error counts, any problem hit. Do NOT paste records.
