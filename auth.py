"""
auth.py
-------
Two auth tiers, both keyed off env-var secrets:

  require_device_token     — pure bearer-token gate for hardware/unattended
    callers that can't do cookies: POST /voice, GET /device/sync,
    POST /device/checkin/{id}/skip, POST /synthesize. Header-only, no
    session fallback.

  require_session_or_token — dashboard-facing routes. Accepts EITHER a
    valid signed session cookie (set by POST /login, main.py's
    SessionMiddleware) or the raw API_TOKEN header, so existing
    `curl -H "auth: $TOKEN"` scripts keep working alongside a logged-in
    browser.

Check-in magic-link routes (POST /checkin/{id}/skip, /reply, /voice) are
deliberately NOT covered by either tier here — they authorize via
possessing that check-in's own UUID, see jobs/checkin.py's
answer_checkin docstring for why that's a separate, unrelated trust
model.

DASHBOARD_PASSWORD is kept separate from API_TOKEN on purpose: the
former is now typed into a public login form (browser autofill/password
managers, brute-force target once on a public domain), the latter lives
in ESP32 firmware and is never touched by a browser after login. Rotating
one shouldn't force the other to change.
"""
from __future__ import annotations

import os
import secrets
import time
from typing import Annotated

from fastapi import Header, HTTPException, Request

_LOGIN_WINDOW_SECONDS = 900  # 15 min
_LOGIN_MAX_ATTEMPTS = 5

# Sliding idle expiry layered on top of SessionMiddleware's own absolute
# max_age (SESSION_MAX_AGE_DAYS, default 30 — main.py). A signed cookie
# alone is only ever absolute: a stolen/leaked one stays valid for the
# full 30 days regardless of activity. This makes an inactive session
# expire much sooner than that without needing separate refresh-token
# infrastructure — every authenticated request just re-stamps last_seen,
# so an actively-used session never hits this even though it's short.
_SESSION_IDLE_TIMEOUT_SECONDS = int(os.environ.get("SESSION_IDLE_TIMEOUT_DAYS", "7")) * 24 * 60 * 60

# Process-memory only — resets on restart, which is fine for a
# single-instance personal deployment; not worth a DB table or a new
# dependency for this.
_login_attempts: dict[str, list[float]] = {}


def _token_matches(auth: str | None) -> bool:
    return auth is not None and secrets.compare_digest(auth, os.environ["API_TOKEN"])


def verify_password(password: str) -> bool:
    return secrets.compare_digest(password, os.environ["DASHBOARD_PASSWORD"])


def require_device_token(auth: Annotated[str | None, Header()] = None) -> None:
    if not _token_matches(auth):
        raise HTTPException(status_code=401, detail="Unauthorized request source")


def require_session_or_token(
    request: Request, auth: Annotated[str | None, Header()] = None
) -> None:
    if _token_matches(auth):
        return
    if request.session.get("authenticated") is True:
        now = time.time()
        last_seen = request.session.get("last_seen")
        if last_seen is not None and now - last_seen > _SESSION_IDLE_TIMEOUT_SECONDS:
            request.session.clear()
            raise HTTPException(status_code=401, detail="Session expired from inactivity")
        request.session["last_seen"] = now
        return
    raise HTTPException(status_code=401, detail="Unauthorized request source")


def check_login_rate_limit(client_ip: str) -> None:
    now = time.time()
    attempts = [t for t in _login_attempts.get(client_ip, []) if now - t < _LOGIN_WINDOW_SECONDS]
    _login_attempts[client_ip] = attempts
    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many login attempts — try again later")


def record_failed_login(client_ip: str) -> None:
    _login_attempts.setdefault(client_ip, []).append(time.time())
