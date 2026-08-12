# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A self-hosted, local-first personal assistant: FastAPI + LangGraph on the backend, a local
LLM via LM Studio, an Obsidian vault (synced with Syncthing) as the notes system, and a
push-to-talk ESP32-S3 as the primary hardware interface — with a browser dashboard as a
full alternative for anyone who can't or doesn't want the hardware.

Everything runs on a Mac Mini M2 (16GB shared memory), which shapes a lot of the design
decisions: prefer cheap deterministic logic over extra LLM calls, keep dependencies light,
and don't make the model do more reasoning than it needs to for a given step.

```
ESP32-S3 (push-to-talk) ──┐
                           ├──> FastAPI (main.py) ──> LangGraph agent (agent/graph.py)
Browser dashboard ─────────┘         │                        │
                                      │                        ├──> LM Studio (local LLM)
                              APScheduler                      ├──> Tools (calendar, weather,
                              (daily digest, bedtime,           │     notes, reminders, ...)
                               ad-hoc reminders)                └──> Chroma (recall + notes index)
                                      │
                                      ├──> Gotify (push notifications)
                                      └──> SMTP (daily recap email)

Obsidian vault (./data/vault) <──sync──> Syncthing <──sync──> your other devices
```

There is a full architecture/feature writeup in `README.md` — read it before making
non-trivial changes. This file summarizes what's most load-bearing and adds nothing that
contradicts it.

## Commands

Package manager is `uv`. A small pytest suite exists (`tests/`, run via `uv run pytest`)
covering thread resolution, keyword matching, datetime parsing, and vault section editing —
no lint tooling (ruff etc.) is configured, and most feature/integration code is still
untested.

```bash
# Local dev, full hot-reload — two processes: backend (terminal 1) +
# frontend dev server (terminal 2). Browse http://localhost:5173, not
# :8000 — Vite proxies API calls to the backend (frontend/vite.config.ts).
uv run uvicorn main:app --reload
cd frontend && npm run dev

# Regenerate the frontend's typed API client from the backend's live
# OpenAPI schema whenever a route/model changes (needs uvicorn running):
cd frontend && npm run gen:types

# Syncthing and the bundled CalDAV server (Radicale) need to run somewhere
# stable even during dev (separate process from the app)
docker compose up syncthing caldav -d
VAULT_PATH=./data/vault CALDAV_URL=http://localhost:5232/myuser/personal/ uv run uvicorn main:app --reload

# Full stack — CALDAV_USERNAME/PASSWORD/URL need to be set in .env.docker
# first (see .env.example), same as any other secret; the caldav service
# is otherwise fully self-provisioning, no setup.sh step needed for it.
# --env-file is required: it's how ASSISTANT_PORT/CALDAV_PORT/SYNCTHING_GUI_*
# in .env.docker reach docker-compose.yml's port mappings (see that file's
# header comment for why env_file: alone isn't enough).
./setup.sh                # once, before first run — .env files, Piper model, SQLite DBs/chroma_db, PUID/PGID
docker compose --env-file .env.docker up --build

# Wipe accumulated memory (Chroma + thread checkpoints), vault preserved unless --vault passed
./reset_knowledge.sh [--vault] [--dry-run]

# Add a dependency
uv add <package>
```

`docker-compose.yml` runs three containers: the FastAPI app, Syncthing (with a shared
volume between them for the vault), and Radicale (a bundled CalDAV server for the calendar
integration — swappable for an external CalDAV server instead, see Configuration below).
LM Studio, Gotify, and the mail provider are external services reached over HTTP/SMTP —
none of them run in compose.

## Core concepts

### The three memory systems

Easy to conflate, genuinely separate, each solving a different problem:

1. **LangGraph checkpoint** (`memory.db`, SQLite via `AsyncSqliteSaver`) — short-term,
   thread-scoped. The raw message history for one conversation, replayed every turn. Makes
   a thread "continuable."
2. **Chroma `conversations` collection** — long-term, cross-thread semantic recall. Every
   successful turn is summarized and embedded (`agent/runtime.py`'s `run_agent`); every
   subsequent call queries it for the 3 most similar past summaries and injects them as
   "RELEVANT PAST CONTEXT" into the system prompt (`agent/graph.py`'s `call_llm`,
   `agent/memory.py`'s `search_conversations`). Bounded three ways so this doesn't leak
   sensitive or stale content across unrelated threads: a cosine-distance cutoff
   (`settings.recall_max_distance`), a recency window (`settings.recall_recency_days`), and
   exclusion of the `onboarding`/`profile_chat` threads plus the current thread itself as
   sources. What actually got recalled on each turn is logged (`recall_log.db`,
   `utils/recall_log_store.py`) and viewable per-thread on the dashboard's Thread Debug page
   (`/admin/thread-debug`, `GET /debug/thread/{thread_id}`) — use it to tune the two
   settings from real distances rather than guessing.
3. **Chroma `notes` collection** — a search index *over* the Obsidian vault, not a store of
   its own. The vault (markdown files on disk) is the source of truth; Chroma is
   disposable/rebuildable. `POST /debug/reconcile-vault` rebuilds it from the files.

### Threading and keyword addressing

Two ways a request lands in a thread, keyword always wins when both apply:

- **Recency** — continue the most recently active thread if used within 5 minutes
  (`SESSION_TIMEOUT_SECONDS` in `agent/runtime.py`); otherwise start a new one.
- **Keyword prefix** — every thread gets a generated two-word phrase (`agent/keywords.py`,
  e.g. "Copper Wolf") at creation. Saying/typing that phrase as a prefix reopens that
  specific thread regardless of how long ago it was last used. Matching is fuzzy (stdlib
  `difflib`) to tolerate Whisper mis-transcriptions, and only checks the first two words of
  an utterance.

Threads are unified regardless of origin (voice vs dashboard) and are **swept nightly** at
digest time (`jobs/digest.py`), freeing keywords for reuse — a deliberate, known trade-off.

### System prompt modes

`agent/graph.py` builds the system prompt from a base + one optional addendum, chosen per
request via LangGraph's `config` (never persisted into thread state — a per-call setting):

| Mode | Trigger | Behavior |
|---|---|---|
| Default | always | Date/time grounding, multi-part request completion, fact-verification rules |
| `one_shot` | `one_shot=True` on `/text` or `/voice` | Never ends on a clarifying question — makes a reasonable assumption, states it, completes the task. Simulates the ESP32's no-follow-up constraint |
| Learning mode | `settings.learning_mode` (standing toggle) | Passive — opportunistically records durable facts about the user via `remember_about_me` |
| `onboarding` | `mode="onboarding"`, fixed thread `"onboarding"` | Active — checklist-guided getting-to-know-you interview; records as it goes |
| `profile_chat` | `mode="profile_chat"`, fixed thread `"profile_chat"` | Scoped to answering/correcting what's in the profile |

Learning mode and the two active modes are mutually exclusive per turn.

## Feature notes worth knowing before touching the code

- **Voice pipeline** (`voice.py`) — `POST /voice` is fire-and-forget: immediate `202` with
  empty body, transcription (faster-whisper) and the agent turn happen in a background task
  *after* the response is sent, so the ESP32 can drop wifi right away. No synthesized voice
  reply, no HTTP feedback to the device by design — failures/successes surface via Gotify
  instead. `sync`/`one_shot` form fields exist only for dashboard testing, never sent by
  real hardware.
- **Notes vault** (`utils/vault.py`, `agent/vault_watcher.py`) — flat vault, no category
  folders; tags and `[[links]]` do the organizing. `Inbox/` is the one special folder for
  anything not created through direct agent interaction. Atomic writes (temp file +
  `os.replace`); `*.sync-conflict-*` files are ignored. Reconciliation (startup + on
  demand) is the correctness guarantee; the live watcher is just a freshness optimization —
  nothing depends on it being perfectly reliable. `append_to_section`/`replace_section`
  operate on one `##` heading only, provably scoped.
- **About Me / profile** — lives at a fixed path (`about-me.md`) via
  `get_or_create_about_me()`, never through generic search — deliberate, since routing it
  through search-then-remember-the-id was unreliable for a smaller local model. Distinct
  people/topics get their own linked note via `get_or_create_linked_note(topic, category)`,
  tracked in About Me's frontmatter `linked_notes` registry (topic → note id), because a
  section-`replace` on a collective section (e.g. "People") would wipe every entry in it,
  not just the one being corrected.
- **Calendar/weather/search** — Calendar is plain CalDAV (`agent/tools/calendar.py`,
  `utils/caldav_client.py`), protocol-generic — `docker-compose.yml` bundles Radicale as the
  default backend, with its collection-management UI (create/rename/delete a calendar —
  Radicale has no event-viewing UI at all) reverse-proxied through `routes/calendar_proxy.py`
  at `/calendar`. Actually viewing/editing events needs a native CalDAV client (Thunderbird,
  a phone app, etc.) pointed at Radicale directly — see README's "First-run calendar setup".
  Point `CALDAV_URL` at any external CalDAV server (Nextcloud, Baikal, Fastmail, etc.)
  instead if you'd rather. Weather is Open-Meteo, no key. Web search is SearXNG,
  self-hosted, degrades gracefully if `SEARXNG_URL` unset.
- **Reminders** (`agent/tools/alerts.py`) — `set_reminder`/`set_timer` resolve relative
  language ("in 10 minutes") to an absolute local date/time (the system prompt's date/time-
  grounding rule) before persisting to `reminders.db` and scheduling a one-shot APScheduler
  job that fires it (`jobs/reminders.py`). Pending reminders are re-hydrated into the
  scheduler on startup; anything overdue while the app was down fires immediately instead of
  being dropped. Calendar-relative reminders ("30 min before my dentist appointment") also
  work on-demand — the LLM combines a calendar tool with `set_reminder` itself. One-off
  only, no recurrence — a recurring need is a calendar event, not a reminder.
- **Calendar reminder sync** (`jobs/calendar_sync.py`) — CalDAV has no push mechanism to
  notice an event manually added/moved/deleted outside the agent, so this polls on an
  interval (`settings.calendar_sync_interval_minutes`, default 30) plus once at startup.
  Opt-in is the event's own native reminder toggle (a `VALARM`, RFC 5545), not a custom tag
  scheme; syncing is keyed by event UID so re-syncing an unchanged event is a no-op. Only a
  UTC (`Z`-suffixed) `DTSTART` is understood — a floating/TZID-local event start is silently
  skipped.
- **Notifications** — `utils/notify.py` (Gotify) + `utils/mailer.py` (SMTP), single
  blocking call each via `asyncio.to_thread`. Gotify priority 3 (silent) for routine
  per-turn pushes (title includes the thread keyword), priority 7 for reminders/bedtime
  (should actually alert), priority 8 for errors.
- **Check-ins** (`jobs/checkin.py`, `agent/tools/checkin.py`, `utils/checkins_store.py`) —
  short reflective prompts delivered at randomized times within
  `[wake_time, latest_checkin_time)`, primarily via `/device/sync` +
  `POST /device/checkin/{id}/skip`. A skip gets one lighter fallback retry before the full
  cooldown; an unanswered/expired prompt skips straight to cooldown instead, since silence
  more likely means offline than overwhelmed. `get_reflection_prompt` lets the assistant
  also serve a prompt on-demand mid-chat, bypassing this state machine entirely.
- **Activity logging** (`jobs/activity_log.py`, `agent/tools/activity_log.py`,
  `utils/activity_log_store.py`) — structured entries (type, duration, mood 1–10,
  reflection) captured only via the `log_activity` tool, charted on the dashboard. Duration
  is stored as free text and parsed into minutes at read time, not write time —
  unparseable durations are silently excluded from the chart rather than guessed.
- **Alert sounds** (`routes/alert_sounds.py`, `utils/alert_sounds_store.py`) — dashboard
  audio uploads are transcoded to 16kHz/16-bit mono WAV and catalogued by hash; the
  ESP32-S3 randomly picks one to play when nudging about a reminder. A separate,
  device-audio-only channel from Reminders/Notifications above — this only supplies which
  sound plays, delivered via metadata-diffing in `/device/sync` so only new/changed files
  get fetched.
- **Device error reporting** (`utils/device_errors_store.py`, `POST /device/error`) —
  standalone channel independent of `/device/sync`, so ESP32-S3 failures (WiFi, SD-card)
  are still reported even when sync itself never succeeds. Every occurrence is logged
  regardless of whether it triggered a Gotify push (a 30-minute per-error-type cooldown
  suppresses repeat alerts, not repeat logging).
- **Daily digest** — `jobs/digest.py`, APScheduler at 20:45 `Australia/Canberra`. Pulls the
  day's Chroma conversation summaries, has the LLM write a recap, emails it, sweeps the
  thread/keyword registry. `POST /debug/digest` fires it on demand.
- **Bedtime reminder** — `jobs/bedtime.py`, its own APScheduler cron job
  (`"bedtime_reminder"`) at `settings.bedtime` (default 21:20) — a fixed, simple Gotify
  push, deliberately separate from the digest (different trigger, different purpose: the
  digest recaps the day, this just says it's time to wind down).
- **Dashboard** (`frontend/`) — a React + TypeScript SPA (Vite, Tailwind, TanStack Query,
  react-router), served by FastAPI from its built `dist/` output (`main.py`'s `serve_spa`
  catch-all, registered last). Replaced an earlier plain-HTML/vanilla-JS dashboard once the
  Projects page's markdown/gallery/chat/polling composition outgrew hand-rolled DOM
  manipulation. `frontend/src/api/schema.ts` is generated from the backend's live OpenAPI
  schema (`npm run gen:types`), typing every API call via `openapi-fetch`
  (`frontend/src/api/client.ts`). `frontend/src/hooks/useChat.ts` + `components/chat/
  ChatWidget.tsx` are the shared send/receive/optimistic-bubble logic every chat-bearing
  page reuses. `static/checkin.html` is the one page deliberately kept outside the SPA
  (magic-link, zero-session, reached from a bare push notification) — still served via a
  narrow `StaticFiles` mount at its original URL so already-delivered links never break.
- **Device sync** — `POST /device/sync` (`jobs/device_sync.py`'s `build_sync_payload`) is
  what the ESP32-S3 calls on every deep-sleep wake, on a flat interval
  (`settings.device_poll_interval_seconds`, dashboard-editable). Returns a full 24h
  snapshot (checkins, reminders, a raw calendar agenda, weather, a POSIX TZ string via
  `utils/datetime.py`'s `posix_tz_string` for DST-correct local time in firmware) — the
  device is a preview/display layer only, Gotify/APScheduler remain the actual delivery
  mechanism regardless of whether it's online. Optional telemetry in the request body
  (`battery_mv`, `wake_reason`, etc.) is recorded into `utils/device_state.py`'s single-row
  store and visible on the dashboard's Testing page alongside a raw payload preview
  (`GET /debug/device-sync`, `GET /debug/device-state`).

## Project structure

```
main.py                    FastAPI app, routes, lifespan (scheduler, watcher, reconciliation)
auth.py                     require_device_token/require_session_or_token, dashboard login
voice.py                   /voice — fire-and-forget ESP32 ingestion
agent/
  graph.py                 LangGraph build, system prompt + mode addendums
  runtime.py                AppState, thread resolution, run_agent()
  keywords.py               Wordlist + fuzzy prefix matching
  settings.py                Standing app-level toggles (persisted via utils/settings_store.py)
  scheduler.py                Shared APScheduler instance + cron trigger builders
  memory.py                  Chroma wrapper (conversations + notes collections)
  vault_watcher.py            Live watcher, Inbox ingestion, reconciliation
  checkin_prompts.py            Reflection prompt bank for check-ins
  tools/
    calendar.py, weather.py, general.py, alerts.py, notes.py, checkin.py,
    activity_log.py, all_tools.py
jobs/
  digest.py                 Daily recap + keyword sweep
  bedtime.py                 Fixed nightly wind-down nudge
  reminders.py                Fires a single ad-hoc reminder
  calendar_sync.py             Polls for manually added/changed/removed calendar events
  checkin.py                    Check-in scheduling/firing state machine
  activity_log.py                Duration parsing for activity-log charts
  device_sync.py                  Builds the /device/sync response payload
  day_start.py                     Beginning-of-day setup (today's check-in target, etc.)
utils/
  vault.py                  Frontmatter, atomic writes, section editing, About Me/linked notes
  caldav_client.py           CalDAV client, protocol-generic (any CalDAV server)
  datetime.py                 Calendar day-boundary helpers, parse_local_datetime
  reminders_store.py           sqlite3 CRUD for reminders.db
  settings_store.py            sqlite3 key/value store for settings.db
  recall_log_store.py           sqlite3 log of each turn's cross-thread recall matches
  checkins_store.py             sqlite3 CRUD for check-in state
  activity_log_store.py          sqlite3 CRUD for activity-log entries
  alert_sounds_store.py           sqlite3 catalogue of transcoded alert-sound files
  device_errors_store.py           sqlite3 log of ESP32-S3 error reports
  device_state.py                   Single-row store for latest device telemetry
  notify.py, mailer.py        Gotify, SMTP
routes/
  synth.py                    Piper TTS (built, not wired into the production voice flow)
  calendar_proxy.py            Reverse-proxies the bundled Radicale UI at /calendar
  alert_sounds.py                Upload/transcode/serve the alert-sound library
  transcribe.py                   Dashboard-only speech-to-text for chat input (no agent turn)
frontend/                     React SPA dashboard (see above) — src/routes/ one file per page,
                                src/components/ shared pieces (ChatWidget, ObsidianMarkdown,
                                RequireAuth, activity-log charts), src/api/ generated OpenAPI
                                types + typed client
static/                       checkin.html only — magic-link check-in page, deliberately
                                outside the SPA, plus the two assets it depends on
                                (css/theme.css, js/voiceInput.js)
tests/                        pytest suite — thread resolution, keywords, datetime, vault sections
docker-compose.yml            assistant + syncthing + caldav (Radicale) services, shared vault volume
setup.sh                        Bootstrap + prerequisite checks: .env files, Piper model, DB
                                  bind-mount gotchas, PUID/PGID — idempotent, safe to re-run
reset_knowledge.sh              Wipes memory/index/checkpoints, then re-runs setup.sh; vault
                                  wipe gated behind --vault
```

## Configuration

See `.env.example` for the full list. Notable ones:

- **LM Studio** — `LMSTUDIO_OPENAI_URL` (OpenAI-compatible endpoint, used for chat/embeddings),
  `CHAT_MODEL`, `EMBEDDING_MODEL`. `LMSTUDIO_MANAGEMENT_URL` is a separate, optional endpoint
  (LM Studio's own REST API, not OpenAI-compatible) — when set, `utils/lmstudio_client.py`
  live-fetches `CHAT_MODEL`'s actual loaded context length from it, so history trimming
  (`agent/graph.py`'s `call_llm`) always matches what's configured in LM Studio's model loader
  instead of a guessed setting; unset, it falls back to the dashboard-editable
  `max_history_tokens` setting.
- **CalDAV** — `CALDAV_URL`, `CALDAV_USERNAME`, `CALDAV_PASSWORD`. Points at the bundled
  Radicale service (`docker-compose.yml`'s `caldav`) by default, or any external CalDAV
  server.
- **SearXNG** — `SEARXNG_URL` (optional).
- **Gotify** — `GOTIFY_URL`, `GOTIFY_TOKEN`. Only used as the first-run default for
  `agent/settings.py`'s `gotify_url`/`gotify_token` — live-editable from there after that
  (Settings page's Notifications card), see the settings bullet below.
- **SMTP** — `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`.
  `DIGEST_EMAIL_TO` is likewise only a first-run default — see below.
- **Vault** — `VAULT_PATH` (defaults to `./data/vault`).
- **`API_TOKEN`** — bearer-token credential for hardware/unattended callers that can't do
  cookies: `/voice`, `/device/sync`, `/device/checkin/{id}/skip`, `/synthesize`
  (`auth.py`'s `require_device_token`). Also accepted as a fallback on every dashboard-facing
  route, so `curl -H "auth: $API_TOKEN"` scripting keeps working alongside a logged-in
  browser.
- **`DASHBOARD_PASSWORD`, `SESSION_SECRET_KEY`, `SESSION_COOKIE_SECURE`,
  `SESSION_MAX_AGE_DAYS`, `SESSION_IDLE_TIMEOUT_DAYS`** — the browser dashboard's real login
  system. `POST /login` checks `DASHBOARD_PASSWORD` and sets a signed session cookie
  (Starlette's `SessionMiddleware`, `SESSION_SECRET_KEY`, `same_site="strict"`); `auth.py`'s
  `require_session_or_token` gates every dashboard-facing route on either that cookie or
  `API_TOKEN`. Kept as a separate secret from `API_TOKEN` on purpose — rotating the ESP32's
  device token shouldn't force a dashboard relogin, and vice versa. `SESSION_MAX_AGE_DAYS`
  is the cookie's absolute expiry from login; `SESSION_IDLE_TIMEOUT_DAYS` (default 7) is a
  sliding idle expiry layered on top — `require_session_or_token` re-stamps a `last_seen`
  timestamp in the session on every authenticated request, so a session in regular use never
  hits it even though it's much shorter than the absolute max age. The frontend's
  `RequireAuth` (`frontend/src/components/RequireAuth.tsx`) is the single client-side gate
  every route uses, probing `GET /settings` the same way the old dashboard's per-page
  `requireSession()` did. `static/checkin.html` is the one page with no session dependency
  at all (magic-link, UUID-gated only). `SESSION_COOKIE_SECURE` should only flip to `true`
  once this app sits behind an HTTPS-terminating reverse proxy/tunnel — see
  `.env.example`'s comment for why doing it earlier silently breaks login (a `Secure` cookie
  is never sent over plain HTTP).
- **`LEARNING_MODE_DEFAULT`** — startup default for `agent/settings.py`'s `learning_mode`;
  live-changeable via `/settings`.
- **Standing settings in `agent/settings.py`** — all live-editable via GET/POST `/settings`
  (the dashboard's Settings page) and persisted to `settings.db`
  (`utils/settings_store.py`) so edits survive a restart: `main.py`'s lifespan loads them
  into the `Settings` singleton via `apply_persisted()` before any setting is read. Two
  flavors — see `agent/settings.py` itself for exact bounds and which changes
  live-reschedule an APScheduler job:
  - *No env var at all* — `default_location`, `timezone`, `wake_time`, `bedtime`,
    `latest_checkin_time`, `digest_time`, `calendar_sync_interval_minutes`,
    `device_poll_interval_seconds`, `recall_max_distance`, `recall_recency_days` — meant to
    be set only from the frontend (the onboarding "Basics" form, or the Settings page), so
    `.env` was never a second source of truth for these.
  - *Env-seeded, so an existing deployment keeps working unchanged after upgrading* —
    `digest_email_to`, `public_base_url`, `gotify_url`, `gotify_token`, `mcp_servers` (from
    `DIGEST_EMAIL_TO`/`PUBLIC_BASE_URL`/`GOTIFY_URL`/`GOTIFY_TOKEN`/`SEARXNG_URL`
    respectively). Once saved once via `/settings`, `settings.db` — not `.env` — is the
    source of truth. `gotify_token` is the one exception to "GET /settings echoes the
    current value back": it's a real credential, so the response only reports
    `gotify_token_set` (bool); the Settings page treats its input as write-only/blank-to-keep.

## Known limitations (true today, not proposals — don't "fix" without asking)

- `routes/synth.py` raises at import time if Piper model files are missing, taking down the
  whole app since it's imported at module load (mitigated operationally by
  `setup.sh`, not fixed in code).
- Threads (and keyword addressability) are swept nightly regardless of origin — dashboard
  conversations have the same one-day lifespan as voice-command keywords. Deliberate
  ("threads are threads"), not an oversight.
- In-memory thread/keyword state isn't covered by `reset_knowledge.sh` — only clears on
  app restart.
- The pytest suite covers `resolve_thread`'s recency/keyword interplay, keyword
  fuzzy-matching, datetime parsing, and section-scoped vault editing — reconciliation's
  orphan detection and most feature/integration code (check-ins, activity log, alert
  sounds, calendar sync, etc.) remain only manually verified.
