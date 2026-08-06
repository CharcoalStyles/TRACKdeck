import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from agent.runtime import (
    _last_digest_boundary,
    app_state,
    rehydrate_threads_from_checkpoints,
)
from agent.settings import settings


@pytest.fixture(autouse=True)
def clean_app_state(monkeypatch):
    monkeypatch.setattr(settings, "timezone", "UTC")
    monkeypatch.setattr(settings, "digest_time", "20:45")
    app_state.threads = {}
    app_state.keywords = {}
    app_state.default_thread_id = None
    app_state.default_last_activity = 0.0
    yield
    app_state.threads = {}
    app_state.keywords = {}
    app_state.default_thread_id = None
    app_state.default_last_activity = 0.0


def _utc_ts(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp()


def test_last_digest_boundary_uses_yesterday_before_todays_digest_time():
    now = _utc_ts(2026, 8, 6, 10, 0)  # before 20:45 today
    boundary = _last_digest_boundary(now)
    assert boundary == _utc_ts(2026, 8, 5, 20, 45)


def test_last_digest_boundary_uses_today_after_todays_digest_time():
    now = _utc_ts(2026, 8, 6, 21, 0)  # after 20:45 today
    boundary = _last_digest_boundary(now)
    assert boundary == _utc_ts(2026, 8, 6, 20, 45)


def test_rehydrate_keeps_only_threads_created_after_the_last_sweep(monkeypatch):
    now = _utc_ts(2026, 8, 6, 21, 0)
    monkeypatch.setattr("agent.runtime.time.time", lambda: now)

    boundary = _last_digest_boundary(now)
    old_thread = f"session_{int(boundary - 3600)}_aaaaaa"
    new_thread = f"session_{int(boundary + 3600)}_bbbbbb"

    async def fake_list_checkpoint_thread_ids():
        return [
            {"thread_id": old_thread, "latest_checkpoint_id": "x"},
            {"thread_id": new_thread, "latest_checkpoint_id": "y"},
            {"thread_id": "onboarding", "latest_checkpoint_id": "z"},
        ]

    monkeypatch.setattr("agent.runtime.list_checkpoint_thread_ids", fake_list_checkpoint_thread_ids)

    restored = asyncio.run(rehydrate_threads_from_checkpoints())

    assert restored == 1
    assert new_thread in app_state.threads
    assert old_thread not in app_state.threads
    assert "onboarding" not in app_state.threads
    assert app_state.default_thread_id == new_thread
    keyword = app_state.threads[new_thread].keyword
    assert app_state.keywords[keyword] == new_thread
