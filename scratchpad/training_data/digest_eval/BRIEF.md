# Synthetic "days" for the daily-digest text-quality eval

Purpose: the daily recap (`jobs/digest.py`, `DIGEST_PROMPT`) is a single free-text LLM call. Its input is (a) a list
of the day's conversation summaries ("entries") and (b) the day's answered check-in reflections. We need ~24 realistic
synthetic days to feed that prompt to several models and have the user rate the outputs. This is EVAL data, not
training data: it needs to look like what the app really produces, mess included.

Read `jobs/digest.py` (DIGEST_PROMPT, `_todays_checkin_reflections`) and `agent/checkin_prompts.py` (PROMPTS) first.

## Entry format (real, from the app's long-term memory)
One string per turn: `"User: <what the user said, dictated voice, casual, run-ons, occasional typos>\nAssistant: <what the
assistant replied AFTER any tools ran>"`. Assistant replies are 1–6 sentences, often with markdown (**bold** dates/times,
short "- " lists), sometimes ending with an offer ("Want me to set a reminder too?"). Real logs are imperfect: include
~1 in 8 entries where the assistant reply is mildly unhelpful, repeats the question, asks a clarifying question, or
reports a failed lookup. Do NOT write them as clean highlight reels. Entries are in time order.

## Reflection format
`Prompt (<low|medium|high>): "<a prompt copied verbatim from agent/checkin_prompts.py PROMPTS[category]>"\nReply: <the user's
spoken answer, 1–3 casual sentences, transcription-style>`. 0–4 per day. A day may have none.

## The user (loosely; don't copy private details, invent plausible ones)
Adult living in Canberra, ACT, works full-time as a software engineer (hybrid), vegetarian, tries to build routines,
Saturday house-tidying/walk routine, uses the assistant for reminders, calendar, notes, project ideas, weather,
web lookups, planning their day. Weekday-appropriate content (work days vs weekends). Dates in the text consistent
with the day's date and weekday (compute with Python).

## Mix across the 24 days (each file has 8 days; spread these kinds across files)
- busy mixed day, 10–14 entries (x6 total)
- moderate day, 5–8 entries (x6)
- quiet day, 1–3 entries (x4)
- completely empty day: `entries: []` and no reflections (x1) — the digest should say it was quiet
- check-ins only: `entries: []`, 2–4 reflections (x1)
- rough-mood day: entries show stress/low energy, reflections show it honestly (x3)
- good-mood/productive day with gratitude reflections (x2)
- repeat-topic day: the same theme (e.g. a trip, a project, house tidying) keeps coming up, tempting a model to
  invent "trends over the past weeks" it has no data for (x2, may overlap with the above)
- Include a few days with plain failures (reminder couldn't be set, search found nothing) and one with a
  health-adjacent item (meds, appointment) handled matter-of-factly.

## Output
Write ONE JSON file (path given in your assignment): a list of objects
`{"id":"D01","date":"YYYY-MM-DD","weekday":"Tuesday","kind":"<one of the kinds above>","entries":[...],"reflections":[...]}`.
Dates spread across 2026-09 … 2026-12, weekday must match (verify with Python). Don't write recaps — only inputs.
Validate the JSON loads and counts match. Report in under 80 words: file, day count, kinds covered. No records pasted.
