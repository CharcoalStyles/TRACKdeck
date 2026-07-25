# Upcoming

Ideas and follow-ups that came up during other work, not yet scheduled.

<!-- Previous entries here (default location, digest time, and location/timezone as
     onboarding-collected settings) landed — see agent/settings.py, main.py's /settings,
     static/settings.html, static/onboarding.html.

     Also landed: digest-into-vault (jobs/digest.py's _write_recap_to_vault,
     alongside the email), the Syncthing conflict-file Gotify alert
     (agent/vault_watcher.py's _alert_new_conflict_files), and structured
     logging over print() (utils/logging.py). -->

## Discussed, intentionally not built yet

- **Bedtime / proactive reminders.** A push-based nudge (Gotify, or the ESP32's eInk)
  around a set time, separate from the passive digest — this is presumably where
  `set_reminder`/`set_timer` (`agent/tools/alerts.py`) stop being stubs and start doing
  real work. Discussed as a distinct mechanism from the digest, timed close to it but not
  the same trigger.
- **Gratitude/mood/wins prompting as part of the digest.** Explicitly deferred — "get the
  basics out of the way first" — but was the original motivation for wanting a daily
  digest at all.
- **Extending linked-note splitting beyond People** — Career/Health/Routine/Interests
  becoming their own linked notes the same way, once About Me's sections have enough
  content to justify it. The mechanism (`get_or_create_linked_note`) is already general
  enough to do this; it just hasn't been specifically prompted for or exercised beyond
  People yet.
- **Dialing learning mode**, not just toggling it — some notion of intensity/selectivity
  beyond on/off, once there's a real sense of what "too aggressive" looks like in practice.

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
- **Rate limiting on the unauthenticated GET routes** (`/`, `GET /settings`, `/threads`,
  `/threads/{id}/messages`, `/health`), if this is ever reachable outside your home
  network. All mutating/agent-facing routes (`/text`, `/voice`, `/synthesize`,
  `POST /settings`, `/threads/new`, the mutating `/debug/*` routes) are now gated by
  `API_TOKEN`.
