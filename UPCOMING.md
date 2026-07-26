# Upcoming

Ideas and follow-ups that came up during other work, not yet scheduled.

## Discussed, intentionally not built yet

- **Extending linked-note splitting to accumulate real content beyond People** —
  `agent/graph.py`'s addendums now already tell the model to use
  `get_or_create_linked_note` for a specific ongoing project or health matter, not just
  people, so the prompting side is done. What's still open is whether those categories
  have actually accumulated enough content in practice to be worth their own notes, versus
  still living in About Me's shared sections.

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
