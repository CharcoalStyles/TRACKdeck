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
