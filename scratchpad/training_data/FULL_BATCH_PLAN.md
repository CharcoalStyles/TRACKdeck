# Full-batch generation plan (~1,500-2,000 total, pilot's 98 already sent/approved)

Trainer signed off on the 98-example pilot (97/98 passed). This tracks the full-volume
follow-up, generated via parallel subagents in this session (user's choice), sent to the
trainer in ~200-300 chunks per their request.

## Global targets (across the ~1,700 remaining, not necessarily per-chunk)

- one_shot: ~25%
- negatives (no_tool/traps): ≥20%
- parallel-call turns (independent calls, one assistant turn, multiple tool_calls): ≥10%
- error-recovery (real error strings, honest failure replies): 5-10%
- modes: onboarding / profile_chat / day_planning / project_chat — meaningful share of each
- every tool ≥ a handful, especially gap tools: get_calendar_event, mark_onboarding_complete,
  set_home_location, search_images, search_videos
- fetch_url: NOT used (fetch_webpage is the standardized "user gave a URL" tool)
- groups: tag every augmentation/continuity family
- IDs: never stated by the user — always from history or a lookup result
- size: each record's conversation under ~2,000 tokens

## Chunk tracker

| Chunk | Status | Records | Notes |
|---|---|---|---|
| Pilot | Sent, approved (97/98) | 98 | T1/T2/T3 prefixes, already with trainer |
| 1 | Sent, awaiting trainer validation | 250 | 5 sub-batches (B1A-B1E), sent as 5 separate messages. Validated clean locally (contamination/arg-schema/turn-shape/stated-id/reminder-future/date-intent/anchor-tz all 0 issues after fixing 2 validator bugs + 2 missing `learning_mode` flags + 4 bad date_intents). |
| 2 | Written to files, awaiting trainer validation | 250 | 5 sub-batches (B2A one_shot-heavy/B2B weather/B2C reflection+news/B2D modes+light error/B2E fresh negatives+parallel), written directly to `scratchpad/training_data/chunk2/B2{A..E}.jsonl`. Fixed 1 anchor-offset bug (B2B-0004) before declaring clean. |
| 3 | Written to files, awaiting trainer validation | 265 | 5 sub-batches (B3A one_shot push/B3B modes/B3C general diverse/B3D fresh negatives+parallel/B3E remaining tool top-ups), written directly to `scratchpad/training_data/chunk3/B3{A..E}.jsonl`. Fixed 1 anchor-offset bug (B3E-0027) before declaring clean. **PAUSED HERE per trainer's explicit request — do not start chunk 4 until they've machine-validated chunks 1–3.** |
| 4 | Written (300 records, 7 files B4A–B4G), sent to trainer; awaiting validation | 300 | Date-focused: B4A/B4B reminders+timers, B4C get_calendar_events, B4D add/update/delete, B4E search_web/get_current_datetime/range forecast/log_activity, B4F date-flavored negatives, B4G (5) S11 ordinary-chat location. Brief: chunk4/BRIEF.md. Trainer validated chunks 1–3: 748/765; the 17 rejects were fixed locally (11 per-tool `call` index, B2D-0030 date, B2E-0011 placeholder, B2A-0004/B3D-0031/B3C-0007/B2B-0047 intents) and the validator now checks per-tool call index + weekday/tomorrow/in-N/hour consistency. |
| 5 | Written (230 records, B5A-B5E), validated locally, sent to trainer | 230 | B5A notes tools, B5B about-me/projects/modes, B5C remaining tool coverage + day_planning, B5D negatives A, B5E negatives B (incl. ordinary-chat 'I've moved'). Brief: chunk5/BRIEF.md. Chunk 4 trainer result: 297/300, 3 rejects (B4C-0029, B4D-0009, B4D-0027) fixed locally. Cumulative (1,295 records): no_tool 21.3%, one_shot 25.0%, parallel 14.2%. Training on trainer side starts soon; later data is a second round. |
| 6 | Round 2 (gap-targeted from v1 results 26/45->38/45), written (130 records B6A-B6E), validated locally, sent | 130 | B6A weekend-anchor dates, B6B get_calendar_event from history, B6C no-tool traps + explicit date asks, B6D news vs web + compounds, B6E long planning lists. Also relabelled B4F-0023 (tool), B4F-0033 reworded, B4E-0023/0026/0028/0030 (arithmetic -> no_tool). Brief: chunk6/BRIEF.md. |
| 7 | Round 3 (v3 counter-examples; v2 scored 36/45 vs v1 38 - over-triggering), written (150 records B7A-B7E), validated locally, sent | 150 | B7A pasted event text -> add_calendar_event, B7B answer-from-knowledge vs search, B7C learning-mode restraint, B7D one search then answer, B7E meta chat no_tool. 55 no_tool (37%). Brief: chunk7/BRIEF.md. Trainer also asked to re-copy chunk2 B2A-E, chunk3 B3C-E, chunk4 B4C-F. |

## Chunk 1 review resolution (trainer's feedback)

- Rejections (B1A-0024/0029/0040 "same shape" placeholders, B1A-0040 date-range math, B1B-0032 near-dup of eval S7) — fixed directly in the chunk1_{a,b}.jsonl files.
- Behavioral issues (B1C-0031 confabulation w/o checking calendar, B1C-0030 fake buffer claim, B1C-0017 invented employer continuity, B1A-0032 invented "this month", B1A-0022/0027 UTC/local timestamp mismatch, B1E-0002/0020 app-internals leaks, default-location consistency) — all fixed; non-Canberra default-location weather results (Wagga Wagga/Dubbo/Lismore/Tamworth/Orange/Bathurst) changed to Canberra since these represent the one real user, not different users.
- **set_home_location conflict — resolved by the user: onboarding-only is the correct product behavior.** Training data's existing onboarding-only convention stays as-is. Eval S11 (expects set_home_location from ordinary chat) is the thing that's wrong and should be corrected on the trainer's side — flagged to them.
- Transport switched to files: `scratchpad/training_data/chunk1/B1A.jsonl` through `B1E.jsonl` (the user copies these into the trainer's repo manually). No more pasting record content into cross-session messages — just file names + change summaries from here on.

## Lessons for chunk 2+ subagent briefs

- `history` must use flat OpenAI-style role-tagged messages (role: user/assistant/tool), matching the pilot's own convention (e.g. T1-0013) — NOT the trainer's `turns` block shape ({tool_calls}/{tool_results}/{content}). State this explicitly, a validator bug from assuming otherwise cost a wasted check this round.
- Always double-check `flags` includes `learning_mode: true` even on mode-flagged records (onboarding/profile_chat/day_planning/project_chat) — two B1B records omitted it when `mode` was set.
- `date_intents` phrases must be an exact substring of the CURRENT record's `text`, never a phrase that only appears in `history` — if the date was resolved in a prior turn, omit `date_intents` entirely on the follow-up record.

## Chunk 1 sub-batch assignments

- **B1A (50)**: parallel/multi-part calls — task lists, multi-event adds, weather+calendar
  compounds. ~25% one_shot mix.
- **B1B (50)**: error recovery — bad time strings, mood_energy out of range, ambiguous/no
  cancel_reminder match, note-id-not-found — real error strings, honest retry/failure.
- **B1C (50)**: modes — onboarding (13), profile_chat (13), day_planning (12), project_chat (12).
- **B1D (50)**: coverage-gap tools — get_calendar_event (via history/lookup), search_images,
  search_videos, search_news, get_range_forecast, less-common notes tools, activity_log variety.
- **B1E (50)**: negatives/traps — capability limits, settings-only fields, weather/calendar-ish
  chat, general knowledge, acknowledgements/sign-offs/venting.

Output: `scratchpad/training_data/chunk1_{a,b,c,d,e}.jsonl`, written directly in the trainer's
final schema (id/source/category/anchor/flags/text/turns/date_intents/group/history/notes) —
no intermediate conversion step this time, unlike the pilot's tranche1-3 → convert_for_handoff.py
pipeline, since that doesn't scale to many parallel subagents cleanly.

After all 5 land: merge, run contamination + arg-schema + balance checks (reuse/extend
check_contamination.py, balance_check.py), fix anything flagged, then send to the trainer as
one ~250-record chunk.
