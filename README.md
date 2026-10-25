# trackdeck

A self-hosted day-organiser. It keeps your calendar and reminders, catches passing thoughts as
you speak them, asks a few short reflective questions across the day, and writes you a morning
message, an evening message and weekly and monthly reviews. Everything runs locally: FastAPI and
LangGraph on a Mac Mini, local models through LM Studio, an Obsidian vault as the notes system,
Radicale as the calendar, and a push-to-talk ESP32-S3 as the primary hardware interface. A browser
dashboard does everything the device does, for anyone without the hardware.

This is v2, built from v1 (tag `v1-final`) by subtraction. The profile and onboarding system,
vector recall, the daily digest, the vault watcher and hosted-model providers are gone.

```
ESP32-S3 (push-to-talk) ──┐
                           ├──> FastAPI (main.py) ──> LangGraph agent (agent/graph.py)
Browser dashboard ─────────┘         │                        │
                                      │                        ├──> LM Studio: tool model + writer model
                              APScheduler                      ├──> 19 tools
                              (morning, evening, weekly,        └──> Event log (data/logs/*.jsonl)
                               monthly, bedtime, reminders,
                               check-ins, calendar sync)
                                      │
                                      ├──> Gotify (push)  └──> SMTP (email copy)

Obsidian vault (./data/vault) <──sync──> Syncthing <──sync──> your other devices
Radicale (CalDAV) <──────────────────────────────────────── your phone / Thunderbird
```

## What it does

- **Captures.** Say or type something to remember. The tool model saves it as a line in today's
  `Daily Notes/` file. If a one-shot or voice turn ends without any tool being chosen, the words are
  saved anyway ("Saved to today's captures."), so nothing spoken is lost. Captures can be ticked
  off, edited, deleted, or converted into a calendar event or reminder from the dashboard.
- **Calendar.** Add, move, update, delete and look up events by voice or text (plain CalDAV; any
  server works, Radicale is bundled). The dashboard's Today pane shows any day and edits events
  directly.
- **Reminders and timers.** "Remind me in 10 minutes", "set a 25 minute timer", "30 minutes before
  my dentist appointment". One-off; a recurring need is a calendar event. Pending reminders survive
  restarts; anything overdue fires immediately.
- **Check-ins.** Short reflective prompts at random times between `checkin_start_time`
  and `latest_checkin_time`, answered on the device, by magic link or in the dashboard. Answers are
  stored in the vault.
- **Day planning.** Give it a list of tasks and the hours you have; it builds schedule blocks
  around your fixed commitments. Ad hoc, run when you want it (the dashboard's Day planning page).
- **Messages.** A morning day-ahead message, an evening message, a Sunday weekly review and a
  monthly review, by Gotify and email.
- **Weather and web.** Open-Meteo forecasts, SearXNG search and page fetching.

### The messages

All context for these is gathered by ordinary code that reads vault files by date range
(`utils/day_context.py`), never by tools; the writer model only ever sees what it is handed.

| Message | When | Contents |
|---|---|---|
| Morning | `morning_time` | Today's calendar and reminders, today's and tomorrow's weather, yesterday's unticked captures, a heads-up on tomorrow |
| Evening | `evening_time` | Bedtime, unticked captures, tomorrow. Built by code with no model call. It deliberately does not recap the day: the assistant cannot know what you did, so it would invent |
| Weekly review | Sunday, `weekly_review_time` | What the week held, what stayed open, a couple of things to decide. A pattern counts only if it shows on 3 or more separate days |
| Monthly review | last evening or first morning (`monthly_review_timing`) | Built from the month's weekly reviews and daily commentary |

The evening message is also the nightly housekeeping run: it sweeps the thread/keyword registry,
stale thread locks and old raw voice recordings, even when the message itself failed. With
`daily_commentary` on (the default) its text is saved to `Reviews/Daily/`. Reviews are saved under
`Reviews/Weekly/` and `Reviews/Monthly/`; Gotify gets a shortened version, email the full text.
`POST /debug/morning`, `/debug/evening`, `/debug/weekly-review`, `/debug/monthly-review` run each on
demand.

## Where your data lives

Deleting a database must lose only transient state, never content.

| What | Where |
|---|---|
| Captures | `Daily Notes/YYYY-MM-DD.md`, lines like `- [ ] 14:32 buy stamps ^a1b2c3d4` |
| Check-in answers | `Check-ins/YYYY-MM-DD.md`, one file per day |
| Daily / weekly / monthly reviews | `Reviews/Daily/`, `Reviews/Weekly/`, `Reviews/Monthly/` |
| Planning notes | `planning-YYYY-MM-DD.md` at the vault root |
| Calendar | CalDAV (Radicale) |
| What happened and where it came from | `data/logs/events-YYYY-MM.jsonl` |
| Settings | `settings.db` |
| Reminders, task library, check-in scheduling | `reminders.db`, `task_library.db`, `checkins.db` |
| Device state, errors, alert sounds | `device_state.db`, `device_errors.db`, `alert_sounds.db` + `alert_sounds/` |
| Thread checkpoints, writer routing log | `memory.db`, `writer_log.db` |

The **event log** is an append-only JSON-lines file per month recording each interaction (what was
said, which tools ran, the reply, the channel), each capture (with where it came from: voice or
dashboard, tool or fallback), each artifact created, each edit and each conversion. It exists so
interactions can be reviewed and scored.

## Models

Local only, via LM Studio's OpenAI-compatible endpoint.

- **Tool model**, stock `liquid/lfm2.5-1.2b` with no fine-tuning, chooses tools and handles one-shot
  voice turns and short confirmations.
- **Writer model**, `gemma-4-e4b-it`, writes what you read: the scheduled messages, day-planning
  summaries, replies after tool errors, long and conversational answers.

`agent/writer.py` decides per turn who writes the final reply. Successful calendar and reminder
writes get a reply built in code from the tool result (`route=template`), so the confirmation
always states the date and time that was actually saved. A reply claiming a change that no tool
made is replaced with "I haven't changed anything". Every routing decision is recorded in
`writer_log.db` (`GET /debug/writer-log`). Set `lmstudio_writer_model` blank to turn the writer off.

### Guards on writes

A 1.2B model copies stale dates and invents confirmations, so writes are checked in code: a start
time in the past is refused with today's date in the error, a date is corrected when the user said
exactly one of tonight/today/tomorrow, search queries lose dates and weekdays the user never said,
and a write in the same batch as a search is held back one step so it can use the results. These
are deliberate; don't loosen them.

## The 19 tools

| Group | Tools |
|---|---|
| Calendar | `get_todays_events`, `get_calendar_events`, `add_calendar_event`, `update_calendar_event`, `move_calendar_event`, `delete_calendar_event` |
| Reminders and timers | `set_reminder`, `set_timer`, `list_reminders`, `cancel_reminder` |
| Planning | `add_planning_task`, `generate_schedule_blocks` |
| Weather | `get_current_weather`, `get_weather_forecast`, `get_range_forecast` |
| Other | `get_reflection_prompt`, `jot_note`, `fetch_webpage` |
| Web search (MCP) | `search_web` |

`jot_note` takes no arguments: the app saves the user's exact words, so the model only has to pick
the tool. `tests/test_tool_registry.py` pins this set.

## Threads and keywords

A request joins the most recently used thread if it was active in the last five minutes, otherwise
it starts a new one. Every thread also gets a two-word keyword ("Copper Wolf"); saying it first
reopens that thread whatever its age. Matching is fuzzy to tolerate mis-transcription. Keywords are
freed each night by the evening job.

## Voice

`POST /voice` takes an audio upload from the ESP32. It returns an empty `202` at once and does the
rest in the background (faster-whisper transcription, then the agent turn), so the device can drop
wifi immediately. There is no spoken reply and no HTTP feedback to the device: success and failure
reach you by Gotify. The `sync` and `one_shot` form fields exist only for dashboard testing.
`checkin_id` ties a recording to an open check-in as its answer.

## Device sync

`POST /device/sync` is called on every deep-sleep wake at a flat interval
(`device_poll_interval_seconds`, default 300, editable without reflashing). The device is a
display layer; Gotify and the scheduler are what actually deliver reminders, check-ins and bedtime.
The response is a stateless 24-hour snapshot:

- `now`, `next_wake_at` (epoch seconds, so the device corrects RTC drift)
- `timezone.iana` and `timezone.posix` (a POSIX TZ string read from the zoneinfo file, so firmware
  renders DST correctly)
- `poll_interval_seconds`, `bedtime`
- `checkins` and `reminders` pending within 24 hours
- `calendar_events`, a raw agenda, and `weather` (current plus today's min/max and sun times); either
  failing degrades to empty rather than failing the sync
- alert-sound metadata, diffed so the device fetches only new or changed files

Optional telemetry in the request body (`battery_mv`, `wake_reason`, `firmware_version`,
`rssi_dbm`, `time_awake_ms`, `reset_reason`) is stored in `device_state.db` and shown on the Testing
page. `POST /device/error` is a separate channel so failures are reported even when sync never
succeeds; each occurrence is logged, and repeat pushes of the same type are suppressed for 30
minutes. `GET /debug/device-sync` and `GET /debug/device-state` show the payload and telemetry.

## Alert sounds

Upload audio on the Alert sounds page (`/admin/alert-sounds`). Files are transcoded to 16 kHz
16-bit mono WAV and catalogued by hash; the device picks one at random when nudging about a
reminder. The chime sound used by day-planning boundary reminders is chosen on the Settings page.

## Calendar

Plain CalDAV through `utils/caldav_client.py`; Radicale is bundled. Radicale's own web UI manages
collections only (no day or week view) and is proxied at `/calendar`. To see and edit events in a
native client (DAVx5, Thunderbird, a phone calendar), publish Radicale's port by uncommenting the
`caldav` service's `ports:` line in `docker-compose.yml`. That port is a separate trust boundary
from the dashboard's auth.

**Calendar reminder sync.** CalDAV has no push, so `jobs/calendar_sync.py` polls every
`calendar_sync_interval_minutes` (default 30) and once at startup. Turning on an event's own
reminder (a `VALARM`) opts it in; each becomes a row in `reminders.db` keyed by event UID, so
re-syncing an unchanged event is a no-op. An event pushed beyond the lookahead is checked directly
before its reminder is cancelled, and a reminder cancelled by hand stays cancelled. Only UTC
(`Z`-suffixed) start times are understood; an event written with a floating or TZID-local start is
skipped. `POST /debug/calendar-sync` runs a pass now.

## Dashboard

A React and TypeScript single-page app, served by FastAPI from its built `dist/`.

- **Home** — a Today pane (any day, with navigation; add, edit and delete events) beside the
  Captures list
- **Captures** — all captures by day, with voice/dashboard badges, tick, edit, delete and convert
- **Chat** — a deliberately small chat page
- **Day planning**, **Reminders**, **Reflection**
- **Settings** — the settings listed below
- **Admin** — Testing (trigger jobs, device payload and telemetry), Check-ins, Alert sounds,
  Errors, Thread debug

`static/checkin.html` is the one page outside the SPA: the magic-link check-in page reached from a
push notification, with no session.

## Settings

All live-editable on the Settings page (`GET/POST /settings`), persisted to `settings.db`, and
loaded at startup. Job times reschedule immediately when saved.

| Group | Settings |
|---|---|
| Day | `default_location`, `timezone`, `wake_time` (default start of a generated day schedule) |
| Times | `morning_time`, `checkin_start_time`, `latest_checkin_time`, `evening_time`, `bedtime`, `weekly_review_time`, `monthly_review_*` (all on one Settings card, grouped by function) |
| Messages | `monthly_review_timing` (`last_evening` or `first_morning`), `daily_commentary`, `weather_enabled`, `email_to` |
| Notifications | `gotify_url`, `gotify_token` (write-only), `public_base_url` |
| Sync | `calendar_sync_interval_minutes`, `device_poll_interval_seconds` |
| Models | `lmstudio_chat_model`, `lmstudio_writer_model`, `max_history_tokens` |
| Other | `mcp_servers` (JSON; seeds a SearXNG server from `SEARXNG_URL`), `planning_template_note_id`, `chime_alert_sound_id` |

Env vars only seed these on first run; once saved, `settings.db` wins.

## Authentication

- `API_TOKEN` is the bearer credential for hardware and scripts (`/voice`, `/device/*`,
  `/synthesize`) and is also accepted on every dashboard route (`curl -H "auth: $API_TOKEN"`).
- `DASHBOARD_PASSWORD` and `SESSION_SECRET_KEY` drive the browser login (`POST /login`, a signed
  session cookie). `SESSION_MAX_AGE_DAYS` is the absolute expiry and `SESSION_IDLE_TIMEOUT_DAYS`
  (default 7) a sliding idle expiry. Rotating `API_TOKEN` does not log the browser out, and vice
  versa. `POST /login` is rate-limited (5 attempts per 15 minutes per IP).
- The app refuses to start if any of these three is still a placeholder.
- `SESSION_COOKIE_SECURE=true` only behind an HTTPS-terminating proxy; a Secure cookie is never
  sent over plain HTTP, so login would silently stop working.
- The check-in magic-link endpoints (`/checkin/{id}/...`) are gated only by possessing that
  check-in's UUID. `GET /health` is open.

## Running it

**First run.** Copy `.env.example` to `.env` (local dev) and/or `.env.docker` (Docker) and fill in
`API_TOKEN`, `DASHBOARD_PASSWORD` and `SESSION_SECRET_KEY` with real random values. Everything else
(CalDAV, Gotify, SMTP, ...) is optional or feature-gated.

Local dev with hot reload runs two processes:

```bash
uv run uvicorn main:app --reload      # terminal 1
cd frontend && npm run dev             # terminal 2; Vite proxies API calls to :8000
```

Browse `http://localhost:5173`, not `:8000`. A bare uvicorn serves only the API unless
`frontend/dist/` already exists from `npm run build`. To reach it from other LAN devices, add
`--host 0.0.0.0`.

Syncthing and Radicale can run on their own during dev:

```bash
docker compose --env-file .env.docker up syncthing caldav -d
VAULT_PATH=./data/vault CALDAV_URL=http://localhost:5232/myuser/personal/ uv run uvicorn main:app --reload
```

Full stack:

```bash
./setup.sh      # once: .env files, Piper model, DB bind-mount files, PUID/PGID
docker compose --env-file .env.docker up --build
```

Two Compose gotchas. `--env-file .env.docker` is required on every command, because `env_file:`
only injects variables into the container and does not feed the `${ASSISTANT_PORT}`,
`${CALDAV_PORT}`, `${SYNCTHING_GUI_*}` substitutions in the compose file. And editing
`.env.docker` contents is not noticed by a plain `up -d`: run `docker compose down` then `up`, or
`up -d --force-recreate <service>`.

Syncthing's device IDs are generated per instance, so pairing with your other devices is a one-time
manual step in its web GUI (`127.0.0.1:8384` by default).

`./reset_knowledge.sh [--vault] [--dry-run]` clears thread checkpoints and raw recordings. It never
touches settings, check-in state, device errors, the calendar or the event log, and only wipes the
vault when you pass `--vault`.

### First-run calendar setup

No manual step: Radicale provisions itself. Set three variables like any other secret:

```bash
CALDAV_URL=http://caldav:5232/myuser/personal/
CALDAV_USERNAME=myuser
CALDAV_PASSWORD=some-password-you-pick
```

The username must match the first path segment of the URL; `personal` can be any collection name.
On startup the `caldav` container rewrites its config and htpasswd file from these values
(idempotent, never touching calendar data) and the app creates the collection with a CalDAV
`MKCALENDAR` call (best effort, so an external server that handles this differently is fine).
To use an external CalDAV server, point `CALDAV_URL` at it.

### Configuration reference

See `.env.example` for the full list with explanations. In short: `LMSTUDIO_OPENAI_URL`,
`LMSTUDIO_CHAT_MODEL`, `LMSTUDIO_WRITER_MODEL` and optionally `LMSTUDIO_MANAGEMENT_URL` (lets the app
read the model's real context length and list downloaded models); `CALDAV_*`; `SEARXNG_URL`;
`GOTIFY_URL`, `GOTIFY_TOKEN`, `PUBLIC_BASE_URL`; `SMTP_*` and `EMAIL_TO`; `VAULT_PATH`;
`EVENT_LOG_DIR`; the auth variables above; `LOG_LEVEL`.

## Tests

```bash
uv run pytest -q
cd frontend && npx tsc --noEmit -p tsconfig.app.json && npm run build
```

After any route or model change, regenerate the typed client with `npm run gen:types` while the
backend is running.

## Known limitations

- `routes/synth.py` raises at import time if the Piper model files are missing, which takes down
  the whole app. `setup.sh` downloads the model first, but the code is not hardened.
- Threads and their keywords are swept nightly regardless of origin, so a dashboard conversation
  has the same one-day lifespan as a voice keyword. Deliberate.
- In-memory thread and keyword state is not covered by `reset_knowledge.sh`; it clears on restart.
- Calendar reminder sync skips events with floating or TZID-local start times.
- The unit and route tests are broad, but the full voice-to-device path has been verified by hand,
  not in the suite.

Open ideas are in [`UPCOMING.md`](UPCOMING.md).
