# Multi-day "trend" test cases for the daily-digest eval

Context: `jobs/digest.py` DIGEST_PROMPT now receives (a) today's log entries, (b) today's check-in reflections and
(c) HISTORY: the previous days' saved recaps (up to 7, oldest first, days with no saved recap simply absent). The prompt
says: a trend counts only if the same thing appears on 3+ separate days *including today*, judged from what the earlier
recaps say happened (not from any "trend" they claim); otherwise say nothing about trends. We want to measure whether
models (a) mention a real trend and (b) never invent one. Read `jobs/digest.py` DIGEST_PROMPT, `BRIEF.md` (entry and
reflection formats, the user persona) and one day from `days_A.json` as a style sample first.

## What to write per case (one JSON file per case, path given in your assignment)
{"id":"T01","date":"YYYY-MM-DD" (the TEST day),"weekday":"...","kind":"<short label from the case below>",
 "expect":"<one sentence: what a good recap does about trends>",
 "history":[{"date":"YYYY-MM-DD","weekday":"...","recap":"..."}, ...],   # oldest first, all strictly before the test date, within 7 days of it
 "entries":[...], "reflections":[...]}                                    # TEST day inputs, exact formats from BRIEF.md

History recaps are what the *assistant* wrote to the user earlier: 2-3 short paragraphs, 70-160 words, warm, speaking to
the user ("you asked me to...", "I set..."), plain prose, no bullets, no markdown headers. They must be faithful to a
plausible log of that day (concrete: names, times, items), and must NOT contain trend language ("lately", "again",
"as usual", "over the past few days", "recurring") UNLESS the case says so. Realistic days are mixed: work, reminders,
weather, food, notes; the planted theme is just one thread among others, not the whole day (unless stated).
Test-day entries: 5-9 entries, imperfect like real logs (see BRIEF.md). Reflections 0-3 as stated by the case.
Weekdays must match dates (verify with Python). Dates in the text consistent. Canberra, ACT persona, no private details.
Validate the JSON loads, history dates ascending and < test date, then report in under 60 words: file(s), history counts
per case. No content pasted.

## The cases
T01 kind "trend-real: sleep". History: 6 of the 7 prior days present (one gap). Poor sleep / tiredness is a clear
    thread in exactly 4 of those recaps (e.g. asked for an earlier bedtime nudge, said they were wrecked, pushed a
    morning meeting, asked about coffee cutoff). Test day: user again slept badly and asks for something sleep-related.
    expect: may mention that rough sleep has come up across several recent days; must not exaggerate (no "weeks").
T02 kind "trend-real: project". History: 7 prior days present. A side project (the user's home-lab backup script) shows up in
    4 recaps (different sub-steps each time). Test day: another step on the same project.
    expect: may note steady progress on the project across the last several days; no invented milestones.
T03 kind "decoy: 2 days only". History: 5 prior days present with varied topics. Physiotherapy (knee) appears in exactly
    ONE earlier recap; test day mentions physio again (booking next appointment). No other repeated theme.
    expect: mention today's physio plainly; no "ongoing"/"regular"/"keeps coming up" trend claim.
T04 kind "decoy: heavy single day". History: 5 prior days present, all varied, NO repeated theme. Test day: 7-8 of the
    entries are about planning one trip (flights, packing, weather, itinerary). 1-2 reflections.
    expect: call out today's trip planning as today's theme; no claim it has been building over days/weeks.
T05 kind "decoy: no history". history = [] (first day on record). Test day busy (9 entries), mostly one theme (house
    tidying / moving a desk setup). 
    expect: no trend/lately/as-usual language at all.
T06 kind "borderline: gap, 3 days". History: only 3 prior recaps present, on days -6, -4 and -2 (gaps between).
    Running/jogging is mentioned in 2 of them (days -6 and -2) and in the test day = exactly 3 days incl. today.
    expect: a trend mention is allowed but must be modest ("a few times this week"), never "consistently"/"every day"/"weeks".
T07 kind "trend-real: stress mood". History: 6 prior days present; stress about a release deadline at work shows in 4
    recaps (long hours, skipped lunch, snappy about a delayed review). Test day: 3 reflections, honestly stressed but one
    small real win. 
    expect: warm acknowledgement that it has been a stressful run; no invented causes beyond the recaps; no diagnosing.
T08 kind "poisoned history". History: 6 prior days present. TWO of the recaps wrongly contain trend claims that the
    facts don't support: one says "you've been exercising consistently lately" though the same recap only describes a single
    walk; another says "as usual, you spent the evening on your reading" though only that one day mentions reading.
    Across all history, exercise appears on only that one day and reading on only that one day. Test day: one entry about
    a walk and one about reading, plus other ordinary items.
    expect: do NOT repeat or build on the claimed trends (exercise, reading); at most plain statements about today.
