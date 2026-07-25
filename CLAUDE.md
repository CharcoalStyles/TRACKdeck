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

Package manager is `uv`. No lint or test tooling is configured in this repo yet (no ruff,
no pytest, no test files exist) — don't assume commands for either.

```bash
# Local dev, full hot-reload
uv run uvicorn main:app --reload

# Syncthing needs to run somewhere stable even during dev (separate process from the app)
docker compose up syncthing -d
VAULT_PATH=./data/vault uv run uvicorn main:app --reload

# Full stack
./setup_check.sh          # once, before first run — Piper model + memory.db/reminders.db/chroma_db setup
docker compose up --build

# Wipe accumulated memory (Chroma + thread checkpoints), vault preserved unless --vault passed
./reset_knowledge.sh [--vault] [--dry-run]

# Add a dependency
uv add <package>
```

`docker-compose.yml` runs three containers: the FastAPI app, Syncthing, and a shared volume
between them for the vault. LM Studio, Gotify, and the mail provider are external services
reached over HTTP/SMTP — none of them run in compose.

## Core concepts

### The three memory systems

Easy to conflate, genuinely separate, each solving a different problem:

1. **LangGraph checkpoint** (`memory.db`, SQLite via `AsyncSqliteSaver`) — short-term,
   thread-scoped. The raw message history for one conversation, replayed every turn. Makes
   a thread "continuable."
2. **Chroma `conversations` collection** — long-term, cross-thread semantic recall. Every
   successful turn is summarized and embedded (`agent/runtime.py`'s `run_agent`); every
   subsequent call injects the 3 most similar past summaries as "RELEVANT PAST CONTEXT"
   into the system prompt, regardless of thread.
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
- **Calendar/weather/search** — Calendar is Nextcloud CalDAV
  (`agent/tools/calendar.py`, `utils/next_cloud_calendar.py`). Weather is Open-Meteo, no
  key. Web search is SearXNG, self-hosted, degrades gracefully if `SEARXNG_URL` unset.
- **Reminders** — `agent/tools/alerts.py`'s `set_reminder`/`set_timer` are real: `when`
  arrives as an absolute local date/time (the system prompt's date/time-grounding rule
  makes the LLM resolve relative language like "in 10 minutes" before calling the tool,
  parsed via `utils/datetime.py`'s `parse_local_datetime`), persisted in `reminders.db`
  (`utils/reminders_store.py`) and scheduled as a one-shot APScheduler job
  (`agent/scheduler.py`'s shared `scheduler`, job id `reminder:<id>`) that calls
  `jobs/reminders.py`'s `fire_reminder`. `list_reminders`/`cancel_reminder` round out the
  set. Pending reminders are re-hydrated into the scheduler on startup from the DB;
  anything overdue while the app was down fires immediately instead of being dropped.
  Calendar-relative reminders ("30 min before my dentist appointment") also work
  on-demand — the LLM combines `get_calendar_events`/`get_todays_events` with
  `set_reminder` itself, no calendar involvement beyond that one turn. One-off only, no
  recurrence — a recurring need is a calendar event, not a reminder.
- **Calendar reminder sync** — `jobs/calendar_sync.py`'s `sync_calendar_reminders`, since
  CalDAV has no push mechanism to notice an event manually added/moved/deleted outside the
  agent. APScheduler `IntervalTrigger` job (`"calendar_reminder_sync"`, every
  `settings.calendar_sync_interval_minutes` — default 30, live-reschedulable via
  `/settings` like `digest_time`/`bedtime` — plus once at startup). Opt-in is the event's own
  native reminder — a `VALARM` (RFC 5545, the same "remind me" toggle any calendar app's
  editor exposes) — not a custom tag scheme; `utils/next_cloud_calendar.py`'s `parse_ics`
  collects each `VALARM`'s `TRIGGER`, `parse_ics_duration` turns it into a `timedelta`
  applied against the event start. Keyed by event UID
  (`reminders_store.upsert_calendar_reminder`) so re-syncing an unchanged event is a no-op.
  Only a UTC (`Z`-suffixed) `DTSTART` is understood — a floating/TZID-local start is
  silently skipped. Removal is a direct `get_event(uid)` check for any tracked reminder not
  seen in the latest range query, so an event merely pushed beyond the 14-day lookahead
  isn't mistaken for a deletion; a fired/cancelled reminder is only revived if the event's
  computed due time actually changed since.
- **Notifications** — `utils/notify.py` (Gotify) + `utils/mailer.py` (SMTP), single
  blocking call each via `asyncio.to_thread`. Gotify priority 3 (silent) for routine
  per-turn pushes (title includes the thread keyword), priority 7 for reminders/bedtime
  (should actually alert), priority 8 for errors.
- **Daily digest** — `jobs/digest.py`, APScheduler at 20:45 `Australia/Canberra`. Pulls the
  day's Chroma conversation summaries, has the LLM write a recap, emails it, sweeps the
  thread/keyword registry. `POST /debug/digest` fires it on demand.
- **Bedtime reminder** — `jobs/bedtime.py`, its own APScheduler cron job
  (`"bedtime_reminder"`) at `settings.bedtime` (default 21:20) — a fixed, simple Gotify
  push, deliberately separate from the digest (different trigger, different purpose: the
  digest recaps the day, this just says it's time to wind down).
- **Dashboard** (`static/`) — plain HTML/CSS/JS, no build step, no framework, native ES
  modules (`static/js/api.js`, `static/js/chat.js`). Deliberate choice over a React/Vue app
  given the added complexity for a single-user tool. `chat.js`'s `ChatWidget` is the shared
  send/receive/loading/error logic plus `setThread()`.

## Project structure

```
main.py                    FastAPI app, routes, lifespan (scheduler, watcher, reconciliation)
voice.py                   /voice — fire-and-forget ESP32 ingestion
agent/
  graph.py                 LangGraph build, system prompt + mode addendums
  runtime.py                AppState, thread resolution, run_agent()
  keywords.py               Wordlist + fuzzy prefix matching
  settings.py                Standing app-level toggles
  scheduler.py                Shared APScheduler instance + cron trigger builders
  memory.py                  Chroma wrapper (conversations + notes collections)
  vault_watcher.py            Live watcher, Inbox ingestion, reconciliation
  tools/
    calendar.py, weather.py, general.py, alerts.py, notes.py, all_tools.py
jobs/
  digest.py                 Daily recap + keyword sweep
  bedtime.py                 Fixed nightly wind-down nudge
  reminders.py                Fires a single ad-hoc reminder
  calendar_sync.py             Polls for manually added/changed/removed calendar events
utils/
  vault.py                  Frontmatter, atomic writes, section editing, About Me/linked notes
  next_cloud_calendar.py     CalDAV client
  datetime.py                 Calendar day-boundary helpers, parse_local_datetime
  reminders_store.py           sqlite3 CRUD for reminders.db
  notify.py, mailer.py        Gotify, SMTP
routes/
  synth.py                    Piper TTS (built, not wired into the production voice flow)
static/                       Dashboard (index/voice/onboarding/profile/settings .html)
docker-compose.yml            assistant + syncthing services, shared vault volume
setup_check.sh                 Verifies/downloads Piper models, fixes the memory.db/reminders.db bind-mount gotcha
reset_knowledge.sh              Wipes memory/index/checkpoints; vault wipe gated behind --vault
```

## Configuration

See `.env.example` for the full list. Notable ones:

- **LM Studio** — `LM_STUDIO_URL`, `CHAT_MODEL`, `EMBEDDING_MODEL`.
- **Nextcloud** — `NEXTCLOUD_URL`, `NEXTCLOUD_USERNAME`, `NEXTCLOUD_APP_PASSWORD`,
  `NEXTCLOUD_CALENDAR_SLUG`.
- **SearXNG** — `SEARXNG_URL` (optional).
- **Gotify** — `GOTIFY_URL`, `GOTIFY_TOKEN`.
- **SMTP** — `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`,
  `DIGEST_EMAIL_TO`.
- **Vault** — `VAULT_PATH` (defaults to `./data/vault`).
- **`API_TOKEN`** — gates `/voice` and mutating `/debug/*`/`/settings` routes. **`/text` has
  no auth at all** — known gap, see below.
- **`LEARNING_MODE_DEFAULT`** — startup default for `agent/settings.py`'s `learning_mode`;
  live-changeable via `/settings`.
- **`default_location`, `timezone`, `digest_time`, `bedtime`,
  `calendar_sync_interval_minutes`** — standing settings in `agent/settings.py`,
  deliberately *not* env-backed (unlike `learning_mode`) — they're meant to be set from the
  frontend (the onboarding "Basics" form, or the Settings page), so .env isn't a second
  source of truth for them. `timezone` (IANA name) drives date/time grounding
  (`agent/tools/general.py`, `utils/datetime.py`), calendar day boundaries, and the cron
  jobs below; `digest_time` (`HH:MM`) is when the daily digest fires, `bedtime` (`HH:MM`)
  is when the bedtime reminder fires, `calendar_sync_interval_minutes` (int, 1–1440) is how
  often the calendar reminder sync polls. All four changes live-reschedule their respective
  APScheduler jobs (`daily_digest`/`bedtime_reminder`/`calendar_reminder_sync`) via
  `/settings`.

## Known limitations (true today, not proposals — don't "fix" without asking)

- `web_search`'s "not connected" fallback string in `agent/tools/general.py` is missing its
  `f`-prefix — prints literal `'{query}'` instead of the actual query.
- `get_todays_events` doesn't check `.get("success")` like its sibling calendar tools do.
- `routes/synth.py` raises at import time if Piper model files are missing, taking down the
  whole app since it's imported at module load (mitigated operationally by
  `setup_check.sh`, not fixed in code).
- `/text` has no authentication; the dashboard's `AUTH_TOKEN` in `static/js/api.js` is a
  hardcoded placeholder that needs manually swapping before deployment.
- Threads (and keyword addressability) are swept nightly regardless of origin — dashboard
  conversations have the same one-day lifespan as voice-command keywords. Deliberate
  ("threads are threads"), not an oversight.
- In-memory thread/keyword state isn't covered by `reset_knowledge.sh` — only clears on
  app restart.
- No automated test suite exists yet — a fair amount of subtle logic (`resolve_thread`'s
  recency/keyword interplay, section-scoped editing boundaries, keyword fuzzy-matching,
  reconciliation's orphan detection) has only been manually verified.
