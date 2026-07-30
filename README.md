# Personal Assistant Backend

A self-hosted, local-first personal assistant: FastAPI + LangGraph on the backend, a local
LLM via LM Studio, an Obsidian vault (synced with Syncthing) as the notes system, and a
push-to-talk ESP32-S3 as the primary hardware interface — with a browser dashboard as a
full alternative for anyone who can't or doesn't want the hardware.

Everything runs on a Mac Mini M2 (16GB shared memory), which shapes a lot of the design
decisions below: prefer cheap deterministic logic over extra LLM calls, keep dependencies
light, and don't make the model do more reasoning than it needs to for a given step.

## Contents

- [Architecture at a glance](#architecture-at-a-glance)
- [Core concepts](#core-concepts)
  - [The three memory systems](#the-three-memory-systems)
  - [Threading and keyword addressing](#threading-and-keyword-addressing)
  - [System prompt modes](#system-prompt-modes)
- [Features](#features)
  - [Voice pipeline (ESP32)](#voice-pipeline-esp32)
  - [Notes vault](#notes-vault)
  - [About Me / profile](#about-me-profile)
  - [Calendar, weather, web search](#calendar-weather-web-search)
  - [Reminders](#reminders)
  - [Calendar reminder sync](#calendar-reminder-sync)
  - [Bedtime reminder](#bedtime-reminder)
  - [Device sync](#device-sync)
  - [Notifications](#notifications)
  - [Daily digest](#daily-digest)
  - [Dashboard](#dashboard)
- [Project structure](#project-structure)
- [Configuration](#configuration)
- [API reference](#api-reference)
- [Running it](#running-it)
  - [First-run calendar setup](#first-run-calendar-setup)
- [Known limitations](#known-limitations)
- [Things we've talked about adding](#things-weve-talked-about-adding)

---

## Architecture at a glance

```
ESP32-S3 (push-to-talk) ──┐
                           ├──> FastAPI (main.py) ──> LangGraph agent (agent/graph.py)
Browser dashboard ─────────┘         │                        │
                                      │                        ├──> LM Studio (local LLM)
                              APScheduler                      ├──> Tools (calendar, weather,
                              (daily digest,                   │     notes, web search, ...)
                               20:45 local)                    └──> Chroma (recall + notes index)
                                      │
                                      ├──> Gotify (push notifications)
                                      └──> SMTP (daily recap email)

Obsidian vault (./data/vault) <──sync──> Syncthing <──sync──> your other devices
```

Three containers in `docker-compose.yml`: the FastAPI app, Syncthing (with a shared volume
between them for the vault), and Radicale (a bundled CalDAV server for the calendar
integration — swap it out for an external CalDAV server if you'd rather, see Configuration
below). LM Studio, Gotify, and your mail provider are external services the app talks to
over HTTP/SMTP — none of them run in this compose file.

## Core concepts

### The three memory systems

Easy to conflate, genuinely separate, each solving a different problem:

1. **LangGraph checkpoint** (`memory.db`, SQLite via `AsyncSqliteSaver`) — short-term,
   thread-scoped. The actual raw message history for one conversation, replayed on every
   turn in that thread. This is what makes a thread "continuable."
2. **Chroma `conversations` collection** — long-term, cross-thread semantic recall. Every
   successful turn gets summarized and embedded (`agent/runtime.py`'s `run_agent`); every
   subsequent call injects the 3 most similar past summaries as "RELEVANT PAST CONTEXT"
   into the system prompt, regardless of which thread they came from.
3. **Chroma `notes` collection** — a search index *over* the Obsidian vault, not a store of
   its own. The vault (markdown files on disk) is the source of truth; Chroma is a
   disposable, rebuildable cache. If it's ever wrong, `/debug/reconcile-vault` rebuilds it
   from the files.

### Threading and keyword addressing

Two ways a request lands in a thread, keyword always wins when both apply:

- **Recency** — continue the most recently active thread if used within 5 minutes
  (`SESSION_TIMEOUT_SECONDS` in `agent/runtime.py`); otherwise start a new one.
- **Keyword prefix** — every thread gets a generated two-word phrase (`agent/keywords.py`,
  e.g. "Copper Wolf") when it's created. Saying/typing that phrase as a prefix
  ("Copper Wolf, actually make that 3pm") reopens that specific thread regardless of how
  long ago it was last used. Matching is fuzzy (stdlib `difflib`, no extra dependency) to
  tolerate Whisper mis-transcriptions, and only ever checks the first two words of an
  utterance.

Threads are unified regardless of where they came from — a conversation started by voice
and one started by typing in the dashboard are handled identically, including expiry.

Threads (and their keywords) are **swept nightly** at digest time
(`jobs/digest.py`), freeing the keywords for reuse and clearing the sidebar. This is a
deliberate, known trade-off — see [Known limitations](#known-limitations).

### System prompt modes

`agent/graph.py` builds the system prompt from a base + one optional addendum, chosen per
request via LangGraph's `config` (not persisted into thread state — it's a per-call
setting, never baked into the conversation history):

| Mode | Trigger | Behavior |
|---|---|---|
| Default | always | Date/time grounding, multi-part request completion, fact-verification rules |
| `one_shot` | `one_shot=True` on `/text` or `/voice` | Never ends on a clarifying question — makes a reasonable assumption, states it, completes the task. Simulates the real ESP32 constraint (no way to hear a follow-up) for testing before the hardware exists |
| Learning mode | `settings.learning_mode` (standing toggle) | Passive — opportunistically records durable facts about the user as they come up naturally, via `remember_about_me` |
| `onboarding` | `mode="onboarding"`, fixed thread `"onboarding"` | Active — drives a getting-to-know-you interview using a checklist as a guide, not a script; records as it goes, not at the end |
| `profile_chat` | `mode="profile_chat"`, fixed thread `"profile_chat"` | Scoped to answering/correcting what's in the profile |

Learning mode and the two active modes are mutually exclusive per turn.

## Features

### Voice pipeline (ESP32)

`voice.py` — `POST /voice` is fire-and-forget by design: the device uploads audio, gets an
immediate `202` with an empty body, and can drop its wifi connection right away. Actual
transcription (faster-whisper, CPU) and the agent turn happen in a background task *after*
the response is sent.

There's deliberately no synthesized voice reply and no HTTP feedback to the device — that
was an explicit call to avoid keeping the ESP32's wifi connection open longer than
necessary. Instead:
- Silence (no speech detected) is discarded quietly.
- Real failures push to Gotify at high priority.
- Successes push to Gotify at low priority (silent on Android once the channel's
  configured — see [Notifications](#notifications)), and get recapped in the nightly digest.

Two form fields exist purely for testing via the dashboard, and should never be set by real
hardware: `sync` (wait for and return the result instead of firing-and-forgetting) and
`one_shot`.

### Notes vault

`utils/vault.py` + `agent/vault_watcher.py`. Plain markdown files with YAML frontmatter
(`id`, `title`, `created`, `updated`, `tags`, `aliases`, `source`, `linked_notes`), synced
across devices via Syncthing, edited by hand in Obsidian or by the agent.

- **Flat vault, no category folders** — tags and `[[links]]` do the organizing.
  `Inbox/` is the one special folder: a landing pad for anything not created through direct
  agent interaction (e.g. a note typed on your phone). Set Obsidian's "default location for
  new notes" to `Inbox` so this happens automatically.
- **Inbox auto-ingestion** — the watcher picks up a raw file, asks the LLM for just a title
  and tags (a narrow, cheap call — not summarization), writes it as a proper note at the
  vault root, indexes it, deletes the Inbox copy, and pushes a Gotify confirmation.
- **Reconciliation is the correctness guarantee, the watcher is a freshness optimization.**
  A full sweep runs at startup and on demand (`POST /debug/reconcile-vault`): indexes
  anything unindexed or changed (by mtime), removes orphaned index entries, catches up any
  Inbox files left over from downtime. The live watcher (`watchfiles`) handles the common
  case in near-real-time, but nothing depends on it being perfectly reliable.
- **Atomic writes** (temp file + `os.replace`) so a concurrent reader — or Syncthing
  mid-sync — never sees a half-written file. `*.sync-conflict-*` files are explicitly
  ignored, never indexed.
- **Section-scoped editing** — `append_to_section`/`replace_section` operate on one `##`
  heading only, provably never touching anything outside it (this is unit-tested logic, not
  just prompted behavior).

### About Me / profile

The two hardest-won lessons from building this, both fixed structurally rather than by
prompting harder:

1. **Deterministic lookup, not search.** The About Me note lives at a fixed path
   (`about-me.md`), found via `get_or_create_about_me()` — never through `search_notes`,
   never by a remembered id. Early on, routing it through the generic
   search-then-remember-the-id flow was exactly the kind of multi-step chain a smaller
   local model didn't reliably get right.
2. **Section blast radius must match what's being corrected.** `remember_about_me`'s
   `replace` mode replaces an entire heading — safe for a section that's one coherent
   topic ("Current Status"), unsafe for a section that's actually a collection ("People"
   holding several different people). Correcting one person's info once wiped everyone
   else's, because the tool did exactly what it was asked, on a section whose shape didn't
   match the request.

   The fix: `get_or_create_linked_note(topic, category)`. About Me's frontmatter holds a
   `linked_notes` registry (topic name → note id) — a plain dict lookup, not search. Each
   distinct person/project/topic gets its own note, found the same reliable way every time,
   with an index line (`- [[Alex]]`) left in the relevant About Me section. Once the model
   has that id, it uses the same `read_note`/`append_to_note`/`update_note_section` tools
   as any other note — no parallel tool surface, no new failure mode.

Manual, precise corrections (fixing a typo, a wrong number) are expected to happen by hand
in Obsidian — the agent's tools are deliberately append/section-scoped, not general
find-and-replace, so it structurally can't mangle prose it wasn't asked to touch.

### Calendar, weather, web search

- **Calendar** (`agent/tools/calendar.py`, `utils/caldav_client.py`) — plain CalDAV,
  protocol-generic. Bundled by default with Radicale (see "First-run calendar setup"
  below), or point at any external CalDAV server (Nextcloud, Baikal, Fastmail, etc.).
  `add_calendar_event`, `get_calendar_events`, `update_calendar_event`,
  `delete_calendar_event`, `get_todays_events`.
- **Weather** (`agent/tools/weather.py`) — Open-Meteo, no API key needed.
- **Web search** (`agent/tools/general.py`) — SearXNG, self-hosted. Falls back to a plain
  "not connected" message if `SEARXNG_URL` isn't set.

### Reminders

`agent/tools/alerts.py`'s `set_reminder`/`set_timer` are real. `when` arrives as an
absolute local date/time — the system prompt's mandatory date/time-grounding rule (see
[System prompt modes](#system-prompt-modes)) already makes the LLM resolve relative
language ("in 10 minutes", "tomorrow at 9am") into an absolute value before calling any
tool, the same convention `add_calendar_event`'s `start` param already relies on. Parsing
is shared: `utils/datetime.py`'s `parse_local_datetime` does the work, and `text_to_utc`
(used by the calendar tools) is now a thin wrapper around it.

A reminder is a row in `reminders.db` (`utils/reminders_store.py`, plain stdlib `sqlite3`
— no new dependency, matches the sync style the tool functions already use) plus a one-shot
APScheduler job (`agent/scheduler.py`'s shared `scheduler`, job id `reminder:<id>`,
`DateTrigger`) that calls `jobs/reminders.py`'s `fire_reminder` at the due time.
`list_reminders`/`cancel_reminder` round out the tool set — cancellation matches by
substring against the reminder's message text.

On startup, `main.py`'s `lifespan` re-hydrates every pending reminder from the DB into the
scheduler (the DB, not the in-memory scheduler, is the source of truth across restarts).
Anything already overdue — the app was down past its fire time — fires immediately instead
of being silently dropped.

Calendar-relative reminders ("remind me 30 minutes before my dentist appointment") also
work **on-demand**: the agent already has `get_todays_events`/`get_calendar_events`, so it
computes the offset itself and calls `set_reminder` with the resulting absolute time — no
calendar involvement needed beyond that single turn. Reminders are **one-off only**, no
recurrence rules; a genuinely recurring need is a calendar event, not a reminder.

`POST /debug/reminders/fire/{reminder_id}` fires a specific pending reminder immediately,
for testing delivery without waiting on the real due time.

### Calendar reminder sync

Events are also often added, moved, or deleted directly in a calendar app — outside any
conversation with the agent — and CalDAV has no push mechanism to notify this app when
that happens. `jobs/calendar_sync.py`'s `sync_calendar_reminders` polls for it instead, on
its own APScheduler `IntervalTrigger` job (`"calendar_reminder_sync"`), plus one immediate
run at startup via `next_run_time`. The poll interval is
`settings.calendar_sync_interval_minutes` (default 30, 1–1440 valid range) —
live-reschedulable via `/settings`, same pattern as `digest_time`/`bedtime`.

The opt-in is the calendar's own native reminder: an event with a `VALARM` (RFC 5545 — the
same "remind me" toggle any calendar app's event editor already exposes — a native CalDAV
client like Thunderbird or your phone's calendar app, not Radicale's own web UI, which has
no event editor at all, see "First-run calendar setup") gets a matching row in
`reminders.db`, keyed by the event's UID
(`upsert_calendar_reminder`) so re-syncing the same unchanged event is a no-op rather than
piling up duplicate reminders. `utils/caldav_client.py`'s `parse_ics` now also
collects each `VALARM`'s `TRIGGER` value; `parse_ics_duration` turns the RFC 5545 duration
string (e.g. `-PT30M`) into a `timedelta`, applied against the event's start time. An event
with more than one alarm uses whichever is closest to the start time — a calendar app's
basic reminder picker only ever sets one, so this is a rare case. Only a UTC (`Z`-suffixed)
`DTSTART` is understood; an event whose calendar app wrote a floating/TZID-local start
instead won't parse and is silently skipped rather than guessed at — worth checking against
whatever client actually creates the event if reminders seem to be missing.

Removal is handled by checking directly rather than assuming: any already-tracked
calendar-linked reminder not seen in the latest range query gets a direct `get_event(uid)`
check before anything happens to it, so an event that was simply pushed further out than
the 14-day lookahead (still real, still has its alarm) doesn't get its reminder cancelled
by mistake — only a genuinely deleted event, or one whose alarm was removed, does.
Once a reminder has fired or been cancelled (including by hand, via `cancel_reminder`), a
later sync pass leaves it alone unless the event's computed due time has actually changed,
so cancelling a calendar-derived reminder sticks rather than being silently recreated on
the next poll.

`POST /debug/calendar-sync` runs a sync pass immediately, for testing.

### Bedtime reminder

`jobs/bedtime.py`, its own APScheduler cron job (`"bedtime_reminder"`) at
`settings.bedtime` (default 21:20, see [Daily digest](#daily-digest) for why 20:45 is
offset 35 minutes earlier). A fixed, simple Gotify push — no calendar cross-referencing,
that would be scope beyond what was asked for. Deliberately a separate mechanism from both
the digest and ad-hoc reminders: same delivery channel, different trigger, different
purpose (the digest recaps the day; this just says it's time to wind down).

### Device sync

`POST /device/sync` (`auth.py`'s `require_device_token`) is what the ESP32-S3 calls on
every deep-sleep wake — a flat polling interval (`settings.device_poll_interval_seconds`,
default 300s, dashboard-editable so the cadence can be retuned without reflashing firmware)
rather than the earlier variable-RTC-wake design, since a battery budget built around a
fixed cadence is simpler to reason about and test. The device is a **preview/display
layer, not the delivery mechanism** — Gotify pushes and the APScheduler jobs elsewhere in
this codebase are what actually fire reminders/check-ins/bedtime regardless of whether the
device is online; this endpoint only decides what to *show* on its eink display.

The device may POST optional telemetry in the request body (`battery_mv`, `wake_reason`,
`firmware_version`, `rssi_dbm`, `time_awake_ms`, `reset_reason` — all nullable, since early
firmware may not send everything yet), recorded into `device_state.db`
(`utils/device_state.py`, a single-row store — one physical device, no fleet concept) and
visible on the dashboard's Testing page. `time_awake_ms` (wifi connect → response received)
is what actually validates the multi-day battery estimate instead of guessing at it;
`reset_reason` is ESP-IDF's `esp_reset_reason()` stringified by firmware (e.g. `"power_on"`,
`"deep_sleep_wake"`, `"brownout"`, `"watchdog"`) — the only visibility into a crash during
the beta without a debugger attached.

The response (`jobs/device_sync.py`'s `build_sync_payload`) is a full 24-hour snapshot,
rebuilt from scratch on every call (no delta/cursor tracking, same stateless pattern
`checkins_store.list_next_24h` already used):
- `now`, `next_wake_at` — epoch seconds, so the device can correct its own RTC drift each
  sync and knows when the next check-in is expected.
- `timezone.iana`/`timezone.posix` — the POSIX TZ string (e.g.
  `AEST-10AEDT,M10.1.0,M4.1.0/3`) is extracted straight from the compiled zoneinfo (TZif)
  file's own v2+ footer (`utils/datetime.py`'s `posix_tz_string`) rather than hand-maintained,
  so firmware (`setenv("TZ", ...)`) renders correct local time across DST changes instead of
  a hardcoded offset that goes stale twice a year.
- `poll_interval_seconds`, `bedtime` — current settings, for the device's own loop/display.
- `checkins`, `reminders` — everything pending and due within 24h, reusing
  `checkins_store.list_next_24h` and the new `reminders_store.list_pending_due_within_24h`.
- `calendar_events` — a raw agenda (even events without their own alarm), via
  `utils/caldav_client.py`'s `get_events_in_range`.
- `weather` — current conditions plus today's min/max temp and sunrise/sunset
  (`agent/tools/weather.py`'s `fetch_current_conditions`, factored out of the
  `get_current_weather` tool so both share one Open-Meteo call — the daily fields ride
  along on the same request via Open-Meteo's `daily` param, not a second call).

Calendar and weather are both external services that can be briefly unreachable; either
failing degrades to `[]`/`null` rather than failing the whole sync (which would also cost
the far more important check-in/reminder data) — logged, not pushed through
`notify_error`, since this runs as often as every few minutes and alerting on every
transient outage would be pure noise.

`GET /debug/device-sync` returns the same payload without recording telemetry, and
`GET /debug/device-state` returns the last-reported telemetry — both on the dashboard's
Testing page, for checking the payload shape and watching the beta device without needing
real hardware or SSH access to the logs.

### Notifications

`utils/notify.py` (Gotify) + `utils/mailer.py` (SMTP), both deliberately simple —
one blocking call each, run via `asyncio.to_thread` from async code.

Gotify priority tiers map to Android notification channels (configured in the Gotify app's
own settings, not in this code): routine per-turn pushes use priority 3 (the low/silent
tier) and include the thread's keyword in the title; reminders and the bedtime push use
priority 7 (should actually alert you); errors use priority 8 (the tier that actually
interrupts you).

### Daily digest

`jobs/digest.py`, scheduled via APScheduler for 20:45 `Australia/Canberra` (35 minutes
before a 21:20 bedtime read). Pulls the day's conversation summaries out of Chroma, asks
the LLM to write a short recap (not a raw log dump), emails it, then sweeps the
keyword-addressable thread registry for the new day. `POST /debug/digest` fires it on
demand for testing.

### Dashboard

`static/`, plain HTML/CSS/JS — no build step, no bundler, no framework. Shared code via
native ES modules (`static/js/api.js`, `static/js/chat.js`) imported directly by
`<script type="module">`. This was a deliberate choice over a React/Vue app in its own
container: the actual problem was one HTML file getting unwieldy, not a need for component
state management, for a tool with exactly one user.

| Page | Purpose |
|---|---|
| `index.html` | Chat — sidebar of addressable threads + main window, default mode |
| `voice.html` | Voice Test — mic recording against the real `/voice` pipeline, `sync`/`one_shot` toggles |
| `onboarding.html` | Guided profile interview |
| `profile.html` | Query & update the profile conversationally |
| `settings.html` | Standing toggles (currently: learning mode) |

`chat.js`'s `ChatWidget` is the one piece of real shared logic — send/receive/loading
state/error handling, plus `setThread()` for the sidebar to switch between conversations
and reload history from `GET /threads/{id}/messages`.

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
  caldav_client.py           CalDAV client, protocol-generic (any CalDAV server)
  datetime.py                 Calendar day-boundary helpers, parse_local_datetime
  reminders_store.py           sqlite3 CRUD for reminders.db
  notify.py, mailer.py        Gotify, SMTP
routes/
  synth.py                    Piper TTS (built, not wired into the production voice flow)
  calendar_proxy.py            Reverse-proxies the bundled Radicale UI at /calendar
static/                       Dashboard (see above)
docker-compose.yml            assistant + syncthing + caldav (Radicale) services, shared vault volume
setup_check.sh                 Verifies/downloads Piper models, fixes DB bind-mount gotchas
reset_knowledge.sh              Wipes memory/index/checkpoints; vault wipe gated behind --vault
```

## Configuration

See `.env.example` for the full list. Grouped by what needs external setup:

- **LM Studio** — `LM_STUDIO_URL`, `CHAT_MODEL`, `EMBEDDING_MODEL`. Local, on the Mac Mini.
- **CalDAV** — `CALDAV_URL`, `CALDAV_USERNAME`, `CALDAV_PASSWORD`. Points at the bundled
  Radicale service by default (see "First-run calendar setup" below), or any external
  CalDAV server (Nextcloud, Baikal, Fastmail, etc.).
- **SearXNG** — `SEARXNG_URL` (optional; web search degrades gracefully without it).
- **Gotify** — `GOTIFY_URL`, `GOTIFY_TOKEN`.
- **SMTP** — `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`,
  `DIGEST_EMAIL_TO`.
- **Vault** — `VAULT_PATH` (defaults to `./data/vault`, matching the Docker layout).
- **`API_TOKEN`** — bearer-token credential for hardware/unattended callers that can't do
  cookies: `/voice`, `/device/sync`, `/device/checkin/{id}/skip`, `/synthesize` (see
  `auth.py`'s `require_device_token`). Also still accepted as a fallback on every
  dashboard-facing route below, so `curl -H "auth: $API_TOKEN"` scripting keeps working.
- **`DASHBOARD_PASSWORD`, `SESSION_SECRET_KEY`, `SESSION_COOKIE_SECURE`,
  `SESSION_MAX_AGE_DAYS`** — the browser dashboard's real login/session system
  (`auth.py`'s `require_session_or_token`, `POST /login`/`POST /logout`, Starlette's
  `SessionMiddleware`). Kept as a separate secret from `API_TOKEN` on purpose — rotating
  the ESP32's device token shouldn't force a dashboard relogin, and vice versa.
  `SESSION_COOKIE_SECURE` should only flip to `true` once this app sits behind an
  HTTPS-terminating reverse proxy/tunnel; see `.env.example`'s comment for why doing it
  earlier silently breaks login.
- **`LEARNING_MODE_DEFAULT`** — startup default; live-changeable after that via `/settings`.

`API_TOKEN`, `DASHBOARD_PASSWORD`, and `SESSION_SECRET_KEY` specifically are checked at
startup (`main.py`) — the app refuses to boot at all if any of them is still the literal
placeholder string from `.env.example` (or, for `SESSION_SECRET_KEY`, unset). Every other
var above is optional/feature-gated — the app starts fine without them, just with that
integration degraded or unavailable.

## API reference

| Route | Method | Auth | Purpose |
|---|---|---|---|
| `/login` | POST | none | Password → session cookie for the dashboard |
| `/logout` | POST | none | Clears the session cookie |
| `/device/token` | GET | session-or-token | Lets an already-logged-in dashboard fetch `API_TOKEN` (only used by the Voice Test page, to call the device-token-only `/voice`) |
| `/text` | POST | session-or-token | Talk to the agent as text. `thread_id`, `one_shot`, `mode` optional |
| `/voice` | POST | `API_TOKEN` | Audio upload. `sync`, `one_shot` form fields for testing |
| `/threads` | GET | session-or-token | Sidebar thread list |
| `/threads/new` | POST | session-or-token | Mint a new thread before any message |
| `/threads/{id}/messages` | GET | session-or-token | Thread history for the sidebar |
| `/settings` | GET | session-or-token | Current standing toggles |
| `/settings` | POST | session-or-token | Update standing toggles |
| `/health` | GET | none | Liveness/readiness check |
| `/debug/digest` | POST | session-or-token | Fire the daily digest on demand |
| `/debug/reminders/fire/{id}` | POST | session-or-token | Fire a specific pending reminder on demand |
| `/debug/calendar-sync` | POST | session-or-token | Run a calendar reminder sync pass on demand |
| `/debug/reconcile-vault` | POST | session-or-token | Force a full vault/index reconciliation |
| `/device/sync` | POST | `API_TOKEN` | ESP32-S3 wake/poll — optional telemetry body, returns the 24h snapshot |
| `/debug/device-sync` | GET | session-or-token | Preview the exact `/device/sync` payload, no telemetry recorded |
| `/debug/device-state` | GET | session-or-token | Last telemetry the device reported |
| `/synthesize` | POST | `API_TOKEN` | Piper TTS — built, unused in the production voice flow |

"session-or-token" (`auth.py`'s `require_session_or_token`) accepts either a valid dashboard
session cookie or the `API_TOKEN` header. `/checkin/{id}/skip`, `/checkin/{id}/reply`, and
`/checkin/{id}/voice` are deliberately excluded from both this table's auth tiers — they're
gated only by possessing that check-in's own UUID, a magic-link trust model unrelated to
login (see `jobs/checkin.py`'s `answer_checkin` docstring).

## Running it

**First-run setup, before any of the commands below**: copy `.env.example` to `.env`
(local dev) and/or `.env.docker` (Docker), and fill in `API_TOKEN`, `DASHBOARD_PASSWORD`,
and `SESSION_SECRET_KEY` with real random values — the app refuses to start at all if any
of these three is left as its placeholder (see Configuration above). Everything else in
that file is optional/feature-gated (fill in what you need — CalDAV, Gotify, SMTP, etc. —
and leave the rest unset).

One gotcha worth knowing up front: editing `.env.docker`'s *contents* doesn't get picked
up by a plain `docker compose up -d` — Compose only recreates a container when it detects
a change to the compose file itself, not to an env file's contents. After editing secrets,
either `docker compose down` then `up` again, or `docker compose up -d --force-recreate
<service>` for just the one that changed.

Local dev, full hot-reload:
```bash
uv run uvicorn main:app --reload
```

Syncthing and the bundled CalDAV server (Radicale) need to run somewhere stable even during
dev — they don't need to be the same process as the app:
```bash
docker compose up syncthing caldav -d
VAULT_PATH=./data/vault CALDAV_URL=http://localhost:5232/myuser/personal/ uv run uvicorn main:app --reload
```

Full stack:
```bash
./setup_check.sh          # once, before first run — Piper model, DB bind-mount files
docker compose up --build
```

Bound to all interfaces, so other devices on the LAN (phone, laptop, the ESP32) can reach
the dashboard/API — the plain `--reload` command above binds to `127.0.0.1` only:
```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
Then hit `http://<mac-mini-lan-ip>:8000` from another device. Keep `SESSION_COOKIE_SECURE`
unset/`false` in `.env` for this — a `Secure` session cookie is never sent over plain HTTP,
so login silently breaks if it's `true` and you're not behind an HTTPS-terminating proxy.

See the Obsidian/Syncthing setup notes (discussed separately) for first-time vault pairing
across devices — that part isn't fully automatable via `docker-compose.yml` alone, since
device IDs are generated per-instance.

### First-run calendar setup

No manual setup step — the bundled Radicale service is fully self-provisioning. Just fill
in three env vars in `.env.docker` like any other secret in that file (`.env.example` has
the full explanation):

```bash
CALDAV_URL=http://caldav:5232/myuser/personal/
CALDAV_USERNAME=myuser
CALDAV_PASSWORD=some-password-you-pick
```

The username must match the first path segment of the URL (Radicale scopes each user to
their own `/<user>/...` path) — `personal` can be any collection name you like. Then:

```bash
docker compose up -d
```

That's it. Two things happen automatically on startup:
- The `caldav` service's entrypoint writes Radicale's config and htpasswd users file from
  `CALDAV_USERNAME`/`CALDAV_PASSWORD` every time it starts (idempotent — never touches the
  actual calendar data, just the auth config).
- The `assistant` service creates the calendar collection itself at startup, via a CalDAV
  `MKCALENDAR` call (`utils/caldav_client.py`'s `ensure_collection_exists`) — best-effort and
  non-fatal, so it also doesn't get in the way if you've pointed `CALDAV_URL` at an external
  server that handles this differently.

Browse to `http://<host>:8000/calendar/` to reach Radicale's own web UI, proxied through
the assistant's single port — no separate Radicale login, just your existing dashboard
session. Worth knowing up front: that UI is for managing *collections* (create/rename/
delete a calendar, see what exists) — it doesn't render a day/week/month view of your
events. Radicale doesn't have one built in.

To actually see and edit events in a browser you'd need a separate calendar-viewing
frontend, and the realistic options there aren't good enough to bundle by default (checked
during development: the classic pairing, CalDAVZAP, hasn't been released since 2015; a
newer option, Bloben, needs its own Postgres+Redis+Node stack and its original repo is
gone). So for actually viewing/editing your calendar day-to-day, use a native CalDAV
client instead — a phone app via DAVx5, Thunderbird, or macOS/Google Calendar's "add CalDAV
account" — pointed at Radicale directly. By default Radicale's own port (5232) isn't
published to the host; uncomment the `caldav` service's `ports: - "5232:5232"` line in
`docker-compose.yml` and use `http://<host>:5232/myuser/personal/` with the same
credentials — a separate trust boundary from the dashboard's session/API_TOKEN auth, same
as Syncthing's GUI port note above.

## Known limitations

Things that are true about the current code, not proposals:

- **`routes/synth.py` raises at import time if the Piper model files are missing**, which
  takes down the whole app, not just TTS, since it's imported at module load. Mitigated
  operationally by `setup_check.sh` downloading the model first, but not fixed at the code
  level.
- **Threads (and their keyword addressability) are swept nightly regardless of origin** —
  a conversation started from the dashboard has the same one-day lifespan as a voice
  command's keyword. This was a deliberate, explicit choice ("threads are threads") rather
  than an oversight, but worth knowing if the dashboard becomes a daily-driver interface
  rather than mostly a testing tool.
- **In-memory thread/keyword state isn't covered by `reset_knowledge.sh`** — it was never
  written to disk in the first place, so it only clears on app restart.
- **Reconciliation and the Inbox pipeline can create duplicate work under real Syncthing
  conditions** (genuine multi-device edit conflicts) that haven't been exercised yet beyond
  the mitigations already built in — sync-conflict file filtering, atomic writes, the
  reconciliation sweep as a catch-all. Worth a real multi-device stress test at some point.

## Things we've talked about adding

Discussed-but-not-yet-built ideas, and Claude's own follow-up suggestions, live in
[`UPCOMING.md`](UPCOMING.md) rather than being duplicated here — check there for the
current list rather than this file, which only records decisions, not a backlog.

One thing was seriously considered and explicitly decided against, worth recording here so
it doesn't get re-litigated from scratch:
- **A React/Vue frontend in its own container** — decided against in favor of the current
  modular-vanilla-JS approach, given the added build/networking complexity for a
  single-user tool. Not off the table forever if the dashboard's needs outgrow this.