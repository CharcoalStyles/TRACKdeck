import asyncio
import time
from datetime import datetime, timezone

import pytest

from agent.settings import settings
from jobs import checkin as checkin_jobs
from utils import checkin_log, checkins_store


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setattr(checkins_store, "DB_PATH", str(tmp_path / "c.db"))
    monkeypatch.setattr(settings, "timezone", "UTC")
    checkins_store.init_db()
    return tmp_path


def _fired_checkin(checkin_id="c1", prompt="What went well today?"):
    checkins_store.create_checkin(checkin_id, "low", prompt, int(time.time()))
    checkins_store.mark_fired(checkin_id, int(time.time()))


def test_entries_round_trip_including_multiline_and_hostile_answers(env):
    when = datetime(2026, 10, 22, 9, 41, tzinfo=timezone.utc)
    checkin_log.append_entry("a1", when, "answered", "Name a win?", "Fixed the bug\n## not a heading\n\nand lunch")
    checkin_log.append_entry("a2", when.replace(hour=14), "skipped", "How is your energy?")
    entries = checkin_log.read_entries("2026-10-22")
    assert [e["id"] for e in entries] == ["a1", "a2"]
    assert entries[0]["time"] == "09:41" and entries[0]["status"] == "answered"
    assert entries[0]["answer"] == "Fixed the bug\n## not a heading\n\nand lunch"
    assert entries[1]["status"] == "skipped" and entries[1]["answer"] is None
    assert checkin_log.checkin_file("2026-10-22").read_text().startswith("---\ntype: check-ins")


def test_append_is_idempotent_per_checkin(env):
    when = datetime(2026, 10, 22, 9, 41, tzinfo=timezone.utc)
    checkin_log.append_entry("a1", when, "answered", "p", "x")
    checkin_log.append_entry("a1", when, "answered", "p", "x")
    assert len(checkin_log.read_entries("2026-10-22")) == 1


def test_missing_day_reads_empty(env):
    assert checkin_log.read_entries("2020-01-01") == []


def test_answer_checkin_writes_vault_and_reflections_read_it_back(env, monkeypatch):
    async def no_schedule(*a, **k):
        return None

    monkeypatch.setattr(checkin_jobs, "_schedule_next", no_schedule)
    _fired_checkin()
    assert asyncio.run(checkin_jobs.answer_checkin("c1", "The walk was good")) is True
    assert asyncio.run(checkin_jobs.answer_checkin("c1", "again")) is False  # already resolved
    now = int(time.time())
    records = asyncio.run(checkin_jobs.reflections_between(now - 60, now + 60))
    assert len(records) == 1
    assert records[0]["status"] == "answered" and records[0]["answer"] == "The walk was good"


def test_skip_is_recorded_as_no_answer(env, monkeypatch):
    async def no_schedule(*a, **k):
        return None

    monkeypatch.setattr(checkin_jobs, "_schedule_next", no_schedule)
    _fired_checkin("c2")
    asyncio.run(checkin_jobs.resolve_checkin("c2", outcome="skipped"))
    now = int(time.time())
    (record,) = asyncio.run(checkin_jobs.reflections_between(now - 60, now + 60))
    assert record["status"] == "skipped" and record["answer"] is None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert checkin_log.read_entries(today)[0]["status"] == "skipped"


def test_unfired_checkin_cannot_be_answered(env):
    checkins_store.create_checkin("c3", "low", "p", int(time.time()))
    assert asyncio.run(checkin_jobs.answer_checkin("c3", "hi")) is False
