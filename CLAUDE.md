# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

trackdeck v2 is a self-hosted day-organiser: it keeps your calendar and reminders, catches
passing thoughts, nudges you with short check-ins, and writes you a morning message, an evening
message and weekly and monthly reviews. FastAPI + LangGraph on the backend, local LLMs through
LM Studio, an Obsidian vault (synced with Syncthing) for everything you would want to keep, and a
push-to-talk ESP32-S3 as the primary hardware interface, with a browser dashboard as a full
alternative.

Everything runs on a Mac Mini M2 (16GB shared memory), which shapes the design: prefer cheap
deterministic logic over extra LLM calls, keep dependencies light, and don't make a small model do
more reasoning than a step needs.

v2 was built by subtraction from v1 (tag `v1-final`): the profile / About Me / onboarding /
learning-mode system, Chroma recall, the daily digest, the vault watcher and Inbox, OpenRouter /
Gemini providers and the LoRA tool model are gone. Don't reintroduce them.

```
ESP32-S3 (push-to-talk) ──┐
                           ├──> FastAPI (main.py) ──> LangGraph agent (agent/graph.py)
Browser dashboard ─────────┘         │                        │
                                      │                        ├──> LM Studio: tool model + writer model
                              APScheduler                      ├──> 19 tools (calendar, reminders, planning,
                              (morning, evening, weekly,        │     weather, notes, web)
                               monthly, bedtime, reminders,     └──> Event log (data/logs/*.jsonl)
                               check-ins, calendar sync)
                                      │
                                      ├──> Gotify (push)  └──> SMTP (email copy of the messages)

Obsidian vault (./data/vault) <──sync──> Syncthing <──sync──> your other devices
```

`README.md` has the fuller feature writeup; this file covers what is load-bearing and adds nothing
that contradicts it.

## Models

Local only, through LM Studio's OpenAI-compatible API:

- **Tool model** — stock `liquid/lfm2.5-1.2b` (no LoRA): picks tools, handles one-shot voice turns
  and short confirmations. `settings.lmstudio_chat_model` (seeded from `LMSTUDIO_CHAT_MODEL`).
- **Writer model** — `gemma-4-e4b-it`: writes what the user reads (morning / evening / weekly /
  monthly messages, day-planning summaries, replies after tool errors, long or conversational
  answers). `settings.lmstudio_writer_model` (blank = off; the tool model writes everything).

`agent/writer.py` holds the routing rules (`decide()`) and the hooks `agent/graph.py` calls. Reasons
it logs: empty_draft, tool_error, prose_tool, mode:day_planning, one_shot, conversation,
short_draft (<=240 chars for confirmation-only tools, <=500 otherwise), long_draft. Every decision
goes to `writer_log.db` (`GET /debug/writer-log`). Any writer failure falls back to the tool
model's own text. Don't try to fix LFM's prose by training; tune the handoff. Per-surface model
overrides live in `agent/model_assignments.py` (Settings page, "Models by Mode").

## Commands

Package manager is `uv`. No lint tooling is configured.

```bash
uv run pytest -q                                   # backend suite (tests/)
cd frontend && npx tsc --noEmit -p tsconfig.app.json && npm run build

# Local dev, full hot-reload — two processes. Browse http://localhost:5173, not :8000.
uv run uvicorn main:app --reload
cd frontend && npm run dev

# Regenerate the typed API client after any route/model change (needs uvicorn running):
cd frontend && npm run gen:types

# Bundled services during dev
docker compose --env-file .env.docker up syncthing caldav -d

# Full stack (--env-file is required for the host port mappings)
./setup.sh
docker compose --env-file .env.docker up --build

# Wipe thread checkpoints and raw recordings; vault, settings and logs preserved
./reset_knowledge.sh [--vault] [--dry-run]

uv add <package>
```

`docker-compose.yml` runs three containers: the app, Syncthing and Radicale (CalDAV). LM Studio,
Gotify and the mail provider are external.

Always sandbox `VAULT_PATH`, `EVENT_LOG_DIR` and the working directory before booting `main:app`
for a test: stores resolve `data/<name>` relative to cwd and would otherwise touch live data.

## Where state lives (portability rule)

Deleting a database must lose only transient state, never content.

| Content | Home |
|---|---|
| Captures | `Daily Notes/YYYY-MM-DD.md`, checklist lines `- [ ] HH:MM text ^id` |
| Check-in answers | `Check-ins/YYYY-MM-DD.md`, one file per day (`utils/checkin_log.py`) |
| Reviews | `Reviews/Daily/`, `Reviews/Weekly/`, `Reviews/Monthly/` (`utils/reviews.py`) |
| Planning notes | `planning-YYYY-MM-DD.md` at the vault root (`utils/vault.py`, `agent/tools/planning.py`) |
| What happened and from where | `data/logs/events-YYYY-MM.jsonl` (`utils/event_log.py`) |
| Calendar | CalDAV (Radicale) |

Databases hold transient or configuration state only: `settings.db` (all settings),
`reminders.db`, `task_library.db`, `checkins.db` (scheduling and pending state only),
`alert_sounds.db`, `device_errors.db`, `device_state.db`, `writer_log.db`, `memory.db` (LangGraph
thread checkpoints).

Context for the scheduled messages and reviews is gathered by ordinary code that reads files by
date range (`utils/day_context.py`) and is handed to the writer. Never make that a tool.

## Event log

Append-only, one file per month, `EVENT_LOG_DIR` overrides the default `data/logs`. Kinds:
`interaction` (text, tools called, reply, channel), `capture` (with `source` voice/dashboard and
`via` tool/fallback/form), `artifact` (something created: calendar event, reminder, capture),
`edit` (calendar update/delete, capture update/delete), `convert` (capture turned into an event or
reminder). `log_event`, `events_between`, `origin_of`, `note_artifact`. Logging never raises. It
exists so interactions can be reviewed and scored.

## Threading and keyword addressing

- **Recency** — continue the most recently active thread if used within 5 minutes
  (`SESSION_TIMEOUT_SECONDS` in `agent/runtime.py`); otherwise start a new one.
- **Keyword prefix** — every thread gets a generated two-word phrase (`agent/keywords.py`, e.g.
  "Copper Wolf"). Saying it as a prefix reopens that thread whatever its age. Matching is fuzzy
  (`difflib`) to tolerate Whisper mis-transcriptions and only checks the first two words.

Keyword wins when both apply. Threads are swept nightly by the evening message job
(`jobs/evening.py`), freeing keywords for reuse. That is a deliberate, known trade-off.

## System prompt and modes

`agent/graph.py` builds the system prompt from a base plus one optional addendum chosen per request
through LangGraph's `config` (never persisted into thread state):

| Mode | Trigger | Behaviour |
|---|---|---|
| Default | always | Date/time grounding, multi-part completion, fact-verification rules |
| `one_shot` | `one_shot=True` on `/text` or `/voice` | Never ends on a clarifying question; assume, state the assumption, finish. Simulates the ESP32's no-follow-up constraint |
| `day_planning` | `mode="day_planning"` | Narrowed tool set (`MODE_TOOL_NAMES`); the writer summarises the schedule |

## The 19 tools

Registry: `agent/tools/all_tools.py` (18 local + MCP `search_web`). `tests/test_tool_registry.py`
pins the exact set; changing it means changing that test deliberately.

- Calendar (6): `get_todays_events`, `get_calendar_events`, `add_calendar_event`,
  `update_calendar_event`, `move_calendar_event`, `delete_calendar_event`
- Reminders and timers (4): `set_reminder`, `set_timer`, `list_reminders`, `cancel_reminder`
- Planning (2): `add_planning_task`, `generate_schedule_blocks`
- Weather (3): `get_current_weather`, `get_weather_forecast`, `get_range_forecast`
- Other local (3): `get_reflection_prompt`, `jot_note`, `fetch_webpage`
- MCP (1): `search_web` (SearXNG, via `settings.mcp_servers`)

`jot_note` takes no arguments on purpose: the app saves the user's raw message from the run config,
so a small model cannot paraphrase or invent text.

**Fallback capture.** For a `one_shot` turn or `source == "voice"` with no mode and no tool calls,
`agent/runtime.py` saves the user's words with `save_capture(..., via="fallback")` and replies
"Saved to today's captures." (`FALLBACK_CAPTURE_REPLY`). Spoken words are never lost.

## Calendar and reminder write guards

The 1.2B tool model copies stale dates and invents confirmations, so writes are guarded in code.
Don't loosen these to "let the model decide":

- `add_/move_calendar_event` and `set_reminder` refuse a past start with a corrective error holding
  today's date (`utils/datetime.py`'s `past_start_message`).
- `agent/date_guard.py` fixes a call's date when the user said exactly one of tonight / today /
  tomorrow, and `clean_search_queries` strips dates and weekdays the user never wrote from search
  queries.
- Successful writes get their reply from `writer.template_reply` (`route=template` in
  `writer_log`); a reply claiming a change with no matching tool is replaced by
  `writer.NO_CHANGE_REPLY`; `writer.unbacked_detail_claim` replaces a claim of extra details when
  no location/description was saved; `writer.event_write_notes` flags a guessed start time or a
  missing venue after a search.
- A calendar/reminder/note write in the same tool batch as a search or fetch is held back one step
  (`defer_writes_after_lookup`) so it can use the results. `update_calendar_event` keeps
  location/description the model omits.

## Scheduled jobs

All on the shared APScheduler (`agent/scheduler.py`); times come from settings and reschedule live
when saved. Job ids: `morning_message`, `evening_message`, `weekly_review`, `monthly_review`,
`bedtime_reminder`, `day_start`, `calendar_reminder_sync`, plus per-item `reminder:<id>`,
`checkin:<id>`, `checkin_expire:<id>`.

- **Morning** (`jobs/morning.py`, `wake_time`) — day-ahead: today's calendar and reminders,
  today's and tomorrow's weather, yesterday's unticked captures, a heads-up on tomorrow.
- **Evening** (`jobs/evening.py`, `evening_time`) — not a recap (the assistant can't know what you
  did). Built by code from what you wrote: bedtime, today's check-in prompts and answers verbatim,
  a short grounded reading across recent answers (the only generated part), unticked captures,
  tomorrow. Optionally saved to `Reviews/Daily/` (`daily_commentary`, default on). Also sweeps
  threads, stale thread locks and old recordings, even if the message failed.
- **Weekly review** (`jobs/reviews.py`, Sunday `weekly_review_time`) and **monthly review**
  (`monthly_review_timing` = `last_evening` or `first_morning`) — written by the writer from files
  read by date range, saved under `Reviews/`, pushed shortened and emailed in full.
- **Bedtime** (`jobs/bedtime.py`) — fixed Gotify nudge at `bedtime`.
- **Check-ins** (`jobs/checkin.py`, `jobs/day_start.py`, `agent/tools/checkin.py`) — short
  reflection prompts at randomised times in `[wake_time, latest_checkin_time)`, delivered through
  `/device/sync` and Gotify magic links. A skip gets one lighter retry before the cooldown; an
  unanswered/expired prompt goes straight to cooldown. Prompts come from `agent/checkin_prompts.py`
  (`random.choice`, no personalisation).
- **Reminders** (`jobs/reminders.py`, `agent/tools/alerts.py`) — `set_reminder`/`set_timer` resolve
  relative language to an absolute local time before persisting to `reminders.db` and scheduling a
  one-shot job. Re-hydrated at startup; anything overdue fires immediately. One-off only.
- **Calendar reminder sync** (`jobs/calendar_sync.py`) — CalDAV has no push, so poll every
  `calendar_sync_interval_minutes` plus at startup. The event's own `VALARM` is the opt-in; keyed
  by event UID. Only a UTC (`Z`) `DTSTART` is understood; floating/TZID starts are skipped.
- **Day planning** is ad hoc: `routes/day_planning.py` `POST /day-plans/run` saves the tasks into a
  planning note and runs a `day_planning` agent turn. `utils/planning.py` orders tasks from
  task-library order hints ("before X" / "after Y").

Notifications: `utils/notify.py` (Gotify) and `utils/mailer.py` (SMTP), blocking calls through
`asyncio.to_thread`. Gotify priority 3 for routine pushes, 5 for the morning message, 7 for
reminders and bedtime, 8 for errors.

## Other features worth knowing

- **Voice pipeline** (`voice.py`) — `POST /voice` is fire-and-forget: immediate empty `202`;
  transcription (faster-whisper) and the agent turn run in a background task so the ESP32 can drop
  wifi at once. No spoken reply, no HTTP feedback to the device; outcomes surface through Gotify.
  `sync`/`one_shot` form fields exist only for dashboard testing.
- **Device sync** — `POST /device/sync` (`jobs/device_sync.py`) is a 24h display snapshot called on
  each deep-sleep wake; the device is a display layer, Gotify/APScheduler are the delivery path.
  Optional telemetry lands in `utils/device_state.py`. `POST /device/error` is a separate channel so
  failures are reported even when sync never succeeds (30-minute per-type push cooldown; every
  occurrence is still logged).
- **Alert sounds** (`routes/alert_sounds.py`, `utils/alert_sounds_store.py`) — uploads are
  transcoded to 16kHz/16-bit mono WAV, catalogued by hash, delivered via metadata-diffing in
  `/device/sync`. Dashboard page `/admin/alert-sounds`.
- **Calendar** — plain CalDAV (`utils/caldav_client.py`), Radicale bundled; its collection UI is
  proxied at `/calendar` by `routes/calendar_proxy.py`. `routes/calendar_events.py` lets the
  dashboard create/edit/delete events (logged as artifact/edit events). Weather is Open-Meteo.
- **Dashboard** (`frontend/`) — React + TypeScript SPA (Vite, Tailwind, TanStack Query,
  react-router) served from `dist/` by `main.py`'s `serve_spa` catch-all (registered last). Pages:
  Home (Today pane with day navigation + Captures), Captures, Chat (tiny), Day planning, Reminders,
  Reflection, Settings, and admin: Testing, Models, Check-ins, Alert sounds, Errors, Thread debug.
  `src/api/schema.ts` is generated from the live OpenAPI schema; `static/checkin.html` is the one
  page kept outside the SPA (magic link, no session).

## Project structure

```
main.py                    FastAPI app, routes, lifespan (scheduler, job registration)
auth.py                    require_device_token / require_session_or_token, dashboard login
voice.py                   /voice — fire-and-forget ESP32 ingestion
agent/
  graph.py                 LangGraph build, system prompt + mode addendums
  runtime.py               AppState, thread resolution, run_agent(), fallback capture
  writer.py                Split-model routing, template replies, claim guards
  date_guard.py            Date correction + search-query cleaning
  keywords.py              Wordlist + fuzzy prefix matching
  settings.py              Standing settings (persisted via utils/settings_store.py)
  scheduler.py             Shared APScheduler + cron trigger builders
  model_assignments.py     Per-surface model overrides
  checkin_prompts.py       Reflection prompt bank
  tools/                   calendar, alerts, planning, weather, general, jot, checkin, all_tools
jobs/                      morning, evening, reviews, bedtime, reminders, calendar_sync, checkin,
                           day_start, device_sync, common (deliver/write helpers)
utils/                     vault, daily_notes, checkin_log, reviews, day_context, event_log,
                           planning, caldav_client, datetime, *_store.py (sqlite3), notify, mailer,
                           llm_client, lmstudio_client, transcription, writer_log
routes/                    today, captures, calendar_events, day_planning, task_library,
                           reflection, alert_sounds, calendar_proxy, transcribe, synth
frontend/                  React SPA (src/routes one file per page)
static/                    checkin.html + theme.css + voiceInput.js
tests/                     pytest suite
```

## Configuration

See `.env.example`. Notable:

- **LM Studio** — `LMSTUDIO_OPENAI_URL`; `LMSTUDIO_CHAT_MODEL` and `LMSTUDIO_WRITER_MODEL` are
  first-run seeds only (settings.db owns them afterwards, live-switchable on the Models page);
  nothing embeds anything in v2, so there is no embedding model. `LMSTUDIO_MANAGEMENT_URL` (optional) lets `utils/lmstudio_client.py` read the model's real loaded
  context length for history trimming and list downloaded models.
- **CalDAV** — `CALDAV_URL`, `CALDAV_USERNAME`, `CALDAV_PASSWORD` (bundled Radicale or any server).
- **SearXNG** — `SEARXNG_URL` seeds the `searxng` entry of `settings.mcp_servers` at first run.
- **Gotify / SMTP / email** — `GOTIFY_URL`, `GOTIFY_TOKEN`, `PUBLIC_BASE_URL`, `EMAIL_TO` (alias
  `DIGEST_EMAIL_TO`) are first-run seeds; settings.db owns them afterwards. `GOTIFY_TOKEN` is never
  echoed back (`gotify_token_set`). SMTP is env-only.
- **Paths** — `VAULT_PATH`, `EVENT_LOG_DIR`.
- **Auth** — `API_TOKEN` (hardware and scripts: `/voice`, `/device/*`, `/synthesize`; also accepted
  on every dashboard route), `DASHBOARD_PASSWORD`, `SESSION_SECRET_KEY`, `SESSION_COOKIE_SECURE`,
  `SESSION_MAX_AGE_DAYS`, `SESSION_IDLE_TIMEOUT_DAYS`. Kept separate on purpose so rotating the
  device token doesn't force a dashboard relogin. The app refuses to start with placeholder values.
  Set `SESSION_COOKIE_SECURE=true` only behind HTTPS (a Secure cookie is never sent over plain
  HTTP, so login silently breaks). `static/checkin.html` endpoints are gated by the check-in UUID.
- **Settings (settings.db, live via GET/POST `/settings`)** — `default_location`, `timezone`,
  `wake_time`, `evening_time`, `bedtime`, `latest_checkin_time`, `weekly_review_time`,
  `monthly_review_timing`, `monthly_review_evening_time`, `monthly_review_morning_time`,
  `daily_commentary`, `weather_enabled`, `calendar_sync_interval_minutes`,
  `device_poll_interval_seconds`, `max_history_tokens`, `email_to`, `public_base_url`, `gotify_url`,
  `gotify_token`, `mcp_servers`, `planning_template_note_id`, `chime_alert_sound_id`,
  `lmstudio_chat_model`, `lmstudio_writer_model`. See `agent/settings.py` for bounds and which
  changes reschedule a job. `digest_email_to` survives only as a legacy alias in
  `apply_persisted()` so an upgraded settings.db still loads.

## Known limitations (true today, not proposals — don't "fix" without asking)

- `routes/synth.py` raises at import time if the Piper model files are missing, taking down the
  whole app (mitigated operationally by `setup.sh`, not fixed in code).
- Threads and keyword addressability are swept nightly regardless of origin; dashboard
  conversations have the same one-day lifespan as voice keywords. Deliberate.
- In-memory thread/keyword state isn't covered by `reset_knowledge.sh`; it only clears on restart.
- A floating or TZID-local `DTSTART` is skipped by the calendar reminder sync.
- Most feature code (check-ins, alert sounds, calendar sync, device sync) is covered only at the
  unit/route level; the full voice and hardware path has been verified by hand, not in the suite.
