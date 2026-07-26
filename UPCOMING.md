# Upcoming

Ideas and follow-ups that came up during other work, not yet scheduled.

## Discussed, intentionally not built yet

- **Extending linked-note splitting to accumulate real content beyond People** —
  `agent/graph.py`'s addendums now already tell the model to use
  `get_or_create_linked_note` for a specific ongoing project or health matter, not just
  people, so the prompting side is done. What's still open is whether those categories
  have actually accumulated enough content in practice to be worth their own notes, versus
  still living in About Me's shared sections.
- **A real login/auth system.** Found while wiring up the check-in Gotify link: every
  static page's script tag hits `GET /static/js/api.js`, which serves the real
  `API_TOKEN` with no auth check of its own, and the whole `/static` mount has no auth
  dependency either — so once a public domain (e.g. `adhi.xyz`) is actually pointed at
  this app, anyone who reaches it can fetch the master token and get full read/write
  access to everything (notes, calendar, settings, all of it). The check-in link feature
  itself was scoped around this (a magic-link design, authorized only by each check-in's
  own UUID, never the global token), but the underlying exposure is app-wide and predates
  that feature. Don't point a public domain at this app until this is addressed.

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
- **Rate limiting.** Splits into two cases:
  - The unauthenticated GET routes (`/`, `GET /settings`, `/threads`,
    `/threads/{id}/messages`, `/health`) — moot once the login/auth item above lands,
    since they'd presumably sit behind it like everything else.
  - `POST /checkin/{id}/skip` and `POST /checkin/{id}/reply` (added for the magic-link
    check-in feature) — these are *deliberately* scoped by UUID possession rather than
    `API_TOKEN`, by design, so the login/auth fix won't cover them. Rate limiting here
    stands on its own, against UUID brute-forcing/abuse, independent of that fix.

  All mutating/agent-facing routes (`/text`, `/voice`, `/synthesize`, `POST /settings`,
  `/threads/new`, the mutating `/debug/*` routes) are now gated by `API_TOKEN`.
