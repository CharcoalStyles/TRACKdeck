# Voice profile — built from tranche 1's real messages

Source: all distinct real `user_message` text surveyed from `turn_dump.json` and
`recall_log.db` (including the privacy-sensitive subset, per explicit approval to use
those for style sampling only, never as literal tool-use training pairs — see
`tranche1.jsonl` and `TRAINING_BRIEF.md`'s contamination/privacy notes). This documents
**style** to transfer into tranche 2; it deliberately does NOT list entities to reuse —
see "Entities to vary, never repeat" at the end.

## Channel: this is dictated/voice-transcribed text, not typed prose

The primary input is voice (ESP32 push-to-talk + Whisper, or quick dashboard typing) — not
careful writing. This shows up as a reproducible class of artifact, not personality:

- **Transcription-plausible typos**: "wil" (will), "anyhtign" (anything), "thnking"
  (thinking), "stat" (start), "calender" (calendar), "teh" (the). These read like
  mis-transcriptions or fast-typing slips, not deliberate misspellings — tranche 2 should
  reproduce this rate sparingly (not every sentence), concentrated on common
  function/content words, never on tool-relevant entities (a date, a number, a location)
  where a typo would make the ground truth ambiguous.
- **Missing punctuation at clause boundaries**, especially in longer dictated messages:
  *"Okay, I'm looking at the routine that you've set up for today and I see that there are
  no breaks in between The things that you've got me to do No, I definitely need breaks..."*
  — run-on, comma-light, clauses stacked without connectors.
  *"As part of my break I did a bit of rebuild of the back end as I wasn't getting
  notifications or alerts on the device for each of the steps throughout today that you've
  planned."* — one long sentence covering what would be 2-3 written sentences.
- **Spoken filler and self-correction, left in**: "um," "I know," "or whatever it is,"
  "I don't know," "basically," repeated words when backtracking — *"Commodore 64 emulator.
  Commodore 64."*, *"a run and debunk button that then either, basically, not compile it,
  but concatenate..."*, *"Let's do it for the next, um, until the end of the year."*
- **Approximate/hedged quantities rather than exact ones**: *"maybe I know 15 20 25
  minutes"*, *"start at about 10 in the morning"*, *"remind me 10 minutes out"* — a real
  range or "about," not a single precise number. Tranche 2 should preserve this hedging
  rather than always giving one clean number, since a trained model that only ever sees
  exact numbers in training may handle a real hedged request worse, not better.

## Sentence/request structure

- **Openers**: "Can you...", "Hey, can you...", "Okay, I'm...", "I was thinking that...",
  "Just a quick one...", "While I'm setting up X, let's also...". Rarely a bare imperative
  with no softening.
- **Context-then-ask pattern**: real requests often front-load unrelated context before
  the actual ask — the C64 emulator message spends three sentences on personal background
  before stating what's wanted. A model trained only on bare, context-free requests won't
  handle this well; tranche 2 should include some of this pattern, not just clean
  single-sentence asks.
- **Multi-part requests chained with "and"/"also"/"while I'm at it"**: *"...go pick up
  Finian. And can that repeat every week..."*, *"While I'm setting up reminders, let's also
  set up a reminder on Tuesdays..."*, *"Also, let's round these off with a reminder..."* —
  real multi-part requests often arrive as a sequence of short additions within one
  message or across a few consecutive turns, not as one neatly itemized list (T1-0001's
  numbered task list is the exception, not the norm — it came from a dashboard form, not
  dictation).
- **Corrections phrased as mild pushback, not re-asks**: *"No, I definitely need
  breaks..."*, *"I was thinking that you would start a new project..."* — a correction
  states what should have happened, phrased as a gentle complaint, not "please redo this."

## How dates/times get phrased

Always informal, never ISO-like: "this coming Wednesday," "on Tuesdays at 2.30," "at 5.30,"
"about 10 in the morning," "tomorrow at 11.30," "in 10 minutes," "a week from today."
Day-of-week + a rounded time (half-hour or on-the-hour) is the dominant pattern, not a
precise minute. This is exactly the phrasing tranche 2's relative-date resolver (per
`date_resolver.py`) needs to generate text for, then verify by code, never by guessing.

## Entities to vary, never repeat

These are this one user's specific facts, not voice — tranche 2 generation must swap them
out for different plausible entities (not necessarily removing the *kind* of detail, just
the specific instance), never reuse verbatim across many synthetic examples: "Canberra"
(as a specific recurring location — vary to other cities), "Finian"/"6yo son" (a specific
person), "ginger beer," "Commodore 64 emulator project," "Gomez"/"Brighton" (a specific
sports team/player), "therapist"/"GP" (excluded from tool-use pairs entirely per the
privacy decision, not just varied). The *pattern* "a reminder to pick up a specific named
person" or "a project idea described with personal backstory" is transferable; the exact
person/project is not.
