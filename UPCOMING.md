# Upcoming

Ideas and follow-ups that came up during other work, not yet scheduled.

## Discussed, intentionally not built yet

- **Extending linked-note splitting to accumulate real content beyond People** —
  `agent/graph.py`'s addendums now already tell the model to use
  `get_or_create_linked_note` for a specific ongoing project or health matter, not just
  people, so the prompting side is done. What's still open is whether those categories
  have actually accumulated enough content in practice to be worth their own notes, versus
  still living in About Me's shared sections.

- **Per-alert-type sound control, plus a new wake-up alert.** Today's alert-sound system
  (`routes/alert_sounds.py`, `utils/alert_sounds_store.py`, `static/alert-sounds.html`) is a
  single flat, undifferentiated WAV library — every `POST /device/sync`
  (`jobs/device_sync.py`) folds the *entire* library into the payload, and per
  `routes/alert_sounds.py`'s own docstring, the ESP32-S3 firmware just picks a random file
  from that whole library for any nudge. No per-alert-type distinction or enable/disable
  exists anywhere. Wanted: for reminders/timers (`jobs/reminders.py`, Gotify priority 7),
  bedtime (`jobs/bedtime.py`, priority 7), and check-in prompts (`jobs/checkin.py`, priority
  3), an on/off toggle controlling *audio only* (not the underlying Gotify push), plus a
  curated subset ("playlist") of the shared library per alert type — when enabled, the
  device should randomly pick from just that alert's assigned subset, not the whole library.
  Also wanted: a **new** wake-up alert, mirroring bedtime — `jobs/day_start.py` already runs
  on a cron rescheduled via `settings.wake_time`, but today only sets up the day's check-in
  window and sends no push at all, so the natural home for this is a Gotify push added
  inside that existing job, gated by its own new enabled toggle, rather than a whole new
  cron job. Backend work this implies: new `Settings`/`settings_store` boolean fields per
  alert (following the `learning_mode` pattern); a new mapping table (likely extending
  `utils/alert_sounds_store.py`) for `alert_type -> [sound_id, ...]`, since a playlist isn't
  a scalar setting; new `/settings` fields and `static/settings.html` controls referencing
  the sound catalog for the playlist picker; and extending `jobs/device_sync.py`'s payload
  to carry each alert type's `{enabled, sound_ids}`. The actual "only play from the assigned
  subset, respect the enabled flag" logic is a **firmware change**, out of scope for this
  backend repo.

- **Cross-thread recall leak (root-caused) + a per-thread debug page.** A check-in
  surfaced content from the previous night's onboarding conversation, on a different
  thread. Root cause, pinned exactly: `agent/graph.py`'s `call_llm` (~lines 209-236) calls
  `memory.search_conversations` (`agent/memory.py`, ~lines 90-99) on *every* turn — a pure
  vector-similarity query over the entire Chroma `conversations` collection, with no `where`
  filter on `thread_id`, no recency window, and no distance/similarity threshold. The top 3
  nearest neighbors are always injected into the system prompt as "RELEVANT PAST CONTEXT"
  (lines 220-222, 235) regardless of source thread or age — contrast with
  `get_conversations_between`/`get_conversation_by_thread` (lines 101-146), which *do*
  filter by thread. This is the intended cross-thread-recall mechanism (`CLAUDE.md`'s memory
  system #2) working exactly as built, just with wider reach than expected — and it persists
  indefinitely, since the nightly sweep (`jobs/digest.py` ~lines 199-211) only clears the
  in-memory thread/keyword registry, never the Chroma `conversations` collection or the
  `memory.db` checkpoint. A fix
  (distance/similarity threshold, a recency window, and/or excluding special threads like
  onboarding/check-in from cross-pollinating) is deliberately deferred until there's a way
  to see the actual behavior first — hence the second half of this item: a debug page that,
  for a given thread, shows the opening message, which tools were called, and what they
  returned. Most of that needs no new instrumentation — `agent/runtime.py`'s `run_agent`
  already logs (but never persists) `tool_calls`/tool output per turn, and the LangGraph
  `memory.db` checkpoint already retains full per-thread message history including tool-call
  requests/results, readable via `graph.aget_state()` (see `get_thread_messages`, ~lines
  135-162, which already does this but filters tool messages out for chat rendering). What's
  genuinely missing is a distinct "thought process"/reasoning trace — the model (`ChatOpenAI`
  via LM Studio, plain `.bind_tools`, no reasoning param) never emits reasoning separate from
  tool calls or its final reply, so that part may not be satisfiable without a
  reasoning-capable model swap. Also worth surfacing: what `search_conversations` actually
  returned/injected for a given turn, which ties directly into the leak above. New work
  needed: a debug endpoint following the existing `/debug/*` pattern in `main.py`, plus a
  dashboard page following `static/testing.html`'s pattern — working off raw thread_ids
  (enumerable from `memory.db` directly) rather than keyword lookup, since keywords stop
  resolving after the nightly sweep even though the checkpoint itself is never pruned.

## Additional suggestions (Claude's own ideas, not discussed)

- **A privacy pass on what's now flowing through the vault.** The profile system is working
  as intended, which means it now holds real, sensitive information — health/diagnosis
  details about you and your family. Worth a deliberate think about at-rest protection
  (vault encryption, or at least confirming Syncthing's transport security settings) given
  that data now syncs across every paired device by default.
- **A backup strategy distinct from Syncthing sync.** Syncthing keeps devices in sync, and
  file versioning gives you an undo button — neither is a backup in the sense of surviving
  a lost/corrupted primary copy propagating everywhere. A periodic off-site copy of the
  vault would close that gap.
- **Graceful degradation when LM Studio is unreachable.** Several paths (digest generation,
  Inbox title/tag generation, ordinary chat) will currently just throw if the local model
  is down or restarting. Some of this is already caught (the `/voice` background path
  reports via Gotify), but not uniformly — a shared retry/backoff or a consistent
  "LM Studio unreachable" user-facing message would make failures easier to diagnose.
- **A read-only "browse the vault" dashboard page.** Chat/Voice/Onboarding/Profile/Settings
  cover creating and updating; there's no page for just looking through what's accumulated
  without opening Obsidian.
- **Rate limiting.** The real login system (`auth.py`, `POST /login`, session cookies) has
  now closed the plain-unauthenticated-GET case — `/`, `GET /settings`, `/threads`,
  `/threads/{id}/messages` all require a session or `API_TOKEN` now, and `GET /health`
  stays open on purpose (standard liveness-check convention, no sensitive data). What's
  left is `POST /checkin/{id}/skip`, `POST /checkin/{id}/reply`, and
  `POST /checkin/{id}/voice` (the magic-link check-in feature) — these are *deliberately*
  scoped by UUID possession rather than login/`API_TOKEN`, by design, so they sit outside
  the new system entirely. Rate limiting there is still a standalone concern, against UUID
  brute-forcing/abuse. `POST /login` itself already has a small in-memory rate limiter
  (`auth.py`'s `check_login_rate_limit`, 5 attempts / 15 min per IP) — that one's covered.
