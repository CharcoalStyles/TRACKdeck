import os
import time

os.environ.setdefault("API_TOKEN", "test-token")
os.environ.setdefault("DASHBOARD_PASSWORD", "test-password")

import pytest
from fastapi import HTTPException

import auth


class _FakeRequest:
    def __init__(self, session: dict):
        self.session = session


def test_active_session_passes_and_refreshes_last_seen(monkeypatch):
    monkeypatch.setattr(auth, "_SESSION_IDLE_TIMEOUT_SECONDS", 7 * 24 * 60 * 60)
    now = 1_700_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    request = _FakeRequest({"authenticated": True, "last_seen": now - 60})

    auth.require_session_or_token(request, auth=None)

    assert request.session["last_seen"] == now


def test_idle_session_beyond_timeout_is_rejected_and_cleared(monkeypatch):
    monkeypatch.setattr(auth, "_SESSION_IDLE_TIMEOUT_SECONDS", 7 * 24 * 60 * 60)
    now = 1_700_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    stale_last_seen = now - (7 * 24 * 60 * 60) - 1
    request = _FakeRequest({"authenticated": True, "last_seen": stale_last_seen})

    with pytest.raises(HTTPException) as exc_info:
        auth.require_session_or_token(request, auth=None)

    assert exc_info.value.status_code == 401
    assert request.session == {}


def test_session_with_no_last_seen_yet_is_treated_as_fresh(monkeypatch):
    # A session predating this feature, or one from POST /login (which sets
    # last_seen itself) — either way, no last_seen recorded yet must not be
    # misread as "infinitely stale".
    monkeypatch.setattr(auth, "_SESSION_IDLE_TIMEOUT_SECONDS", 7 * 24 * 60 * 60)
    now = 1_700_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    request = _FakeRequest({"authenticated": True})

    auth.require_session_or_token(request, auth=None)

    assert request.session["last_seen"] == now


def test_device_token_bypasses_session_entirely(monkeypatch):
    request = _FakeRequest({})
    auth.require_session_or_token(request, auth="test-token")
    assert "last_seen" not in request.session
