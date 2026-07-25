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
  - [Notifications](#notifications)
  - [Daily digest](#daily-digest)
  - [Dashboard](#dashboard)
- [Project structure](#project-structure)
- [Configuration](#configuration)
- [API reference](#api-reference)
- [Running it](#running-it)
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

Three containers in `docker-compose.yml`: the FastAPI app, Syncthing, and a shared volume
between them for the vault. LM Studio, Gotify, and your mail provider are external services
the app talks to over HTTP/SMTP — none of them run in this compose file.

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

- **Calendar** (`agent/tools/calendar.py`, `utils/next_cloud_calendar.py`) — Nextcloud
  CalDAV. `add_calendar_event`, `get_calendar_events`, `update_calendar_event`,
  `delete_calendar_event`, `get_todays_events`.
- **Weather** (`agent/tools/weather.py`) — Open-Meteo, no API key needed.
- **Web search** (`agent/tools/general.py`) — SearXNG, self-hosted. Falls back to a plain
  "not connected" message if `SEARXNG_URL` isn't set.
- `set_reminder`/`set_timer` (`agent/tools/alerts.py`) are **stubs** — they print and
  return a canned response, no real scheduling behind them yet.

### Notifications

`utils/notify.py` (Gotify) + `utils/mailer.py` (SMTP), both deliberately simple —
one blocking call each, run via `asyncio.to_thread` from async code.

Gotify priority tiers map to Android notification channels (configured in the Gotify app's
own settings, not in this code): routine per-turn pushes use priority 3 (the low/silent
tier) and include the thread's keyword in the title; errors use priority 8 (the tier that
actually interrupts you).

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
  memory.py                  Chroma wrapper (conversations + notes collections)
  vault_watcher.py            Live watcher, Inbox ingestion, reconciliation
  tools/
    calendar.py, weather.py, general.py, alerts.py, notes.py, all_tools.py
jobs/
  digest.py                 Daily recap + keyword sweep
utils/
  vault.py                  Frontmatter, atomic writes, section editing, About Me/linked notes
  next_cloud_calendar.py     CalDAV client
  datetime.py                 Calendar day-boundary helpers
  notify.py, mailer.py        Gotify, SMTP
routes/
  synth.py                    Piper TTS (built, not wired into the production voice flow)
static/                       Dashboard (see above)
docker-compose.yml            assistant + syncthing services, shared vault volume
setup_check.sh                 Verifies/downloads Piper models, fixes the memory.db bind-mount gotcha
reset_knowledge.sh              Wipes memory/index/checkpoints; vault wipe gated behind --vault
```

## Configuration

See `.env.example` for the full list. Grouped by what needs external setup:

- **LM Studio** — `LM_STUDIO_URL`, `CHAT_MODEL`, `EMBEDDING_MODEL`. Local, on the Mac Mini.
- **Nextcloud** — `NEXTCLOUD_URL`, `NEXTCLOUD_USERNAME`, `NEXTCLOUD_APP_PASSWORD`,
  `NEXTCLOUD_CALENDAR_SLUG`.
- **SearXNG** — `SEARXNG_URL` (optional; web search degrades gracefully without it).
- **Gotify** — `GOTIFY_URL`, `GOTIFY_TOKEN`.
- **SMTP** — `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`,
  `DIGEST_EMAIL_TO`.
- **Vault** — `VAULT_PATH` (defaults to `./data/vault`, matching the Docker layout).
- **`API_TOKEN`** — gates `/voice` and the mutating `/debug/*`/`/settings` routes.
  **`/text` currently has no auth at all** — see [Known limitations](#known-limitations).
- **`LEARNING_MODE_DEFAULT`** — startup default; live-changeable after that via `/settings`.

## API reference

| Route | Method | Auth | Purpose |
|---|---|---|---|
| `/text` | POST | none | Talk to the agent as text. `thread_id`, `one_shot`, `mode` optional |
| `/voice` | POST | `API_TOKEN` | Audio upload. `sync`, `one_shot` form fields for testing |
| `/threads` | GET | none | Sidebar thread list |
| `/threads/new` | POST | none | Mint a new thread before any message |
| `/threads/{id}/messages` | GET | none | Thread history for the sidebar |
| `/settings` | GET | none | Current standing toggles |
| `/settings` | POST | `API_TOKEN` | Update standing toggles |
| `/health` | GET | none | Liveness/readiness check |
| `/debug/digest` | POST | `API_TOKEN` | Fire the daily digest on demand |
| `/debug/reconcile-vault` | POST | `API_TOKEN` | Force a full vault/index reconciliation |
| `/synthesize` | POST | none | Piper TTS — built, unused in the production voice flow |

## Running it

Local dev, full hot-reload:
```bash
uv run uvicorn main:app --reload
```

Syncthing needs to run somewhere stable even during dev — it doesn't need to be the same
process as the app:
```bash
docker compose up syncthing -d
VAULT_PATH=./data/vault uv run uvicorn main:app --reload
```

Full stack:
```bash
./setup_check.sh          # once, before first run — Piper model + memory.db/chroma_db setup
docker compose up --build
```

See the Obsidian/Syncthing setup notes (discussed separately) for first-time vault pairing
across devices — that part isn't fully automatable via `docker-compose.yml` alone, since
device IDs are generated per-instance.

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