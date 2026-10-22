# Upcoming

Ideas and follow-ups that came up during other work, not yet scheduled. The v1 backlog (profile
system, vault watcher, digest-era items) was retired with v2; what remains is what still applies.

- **Per-alert-type sound control and a wake-up alert.** The alert-sound library is flat: the device
  picks any sound for any nudge. Wanted: an audio on/off toggle and a curated subset per alert type
  (reminders, bedtime, check-ins), carried in the `/device/sync` payload, plus a wake-up alert on
  `jobs/day_start.py`. The play-from-subset logic is a firmware change, out of scope here.
- **Graceful degradation when LM Studio is unreachable.** Several paths (scheduled messages,
  ordinary chat) throw if the local model is down. The `/voice` background path reports through
  Gotify, but not uniformly; a shared retry and a consistent "LM Studio unreachable" message would
  make failures easier to diagnose.
- **Rate limiting the check-in magic links.** `POST /checkin/{id}/skip`, `/reply` and `/voice` are
  gated only by UUID possession; rate limiting would guard against brute-forcing. `POST /login`
  already has a limiter (`auth.py`'s `check_login_rate_limit`).
- **A backup strategy distinct from Syncthing.** Syncthing keeps devices in sync, which is not a
  backup: a corrupted copy propagates everywhere. A periodic off-site copy of the vault, the event
  log and the Radicale data would close that gap.
- **A privacy pass on what flows through the vault.** Check-in answers are personal; consider
  at-rest protection and confirm Syncthing's transport settings.
