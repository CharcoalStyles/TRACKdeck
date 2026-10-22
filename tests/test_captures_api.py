import asyncio
from datetime import datetime

import pytest
from fastapi import HTTPException

from agent.settings import settings
from utils import daily_notes, event_log


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("EVENT_LOG_DIR", str(tmp_path / "logs"))
    return tmp_path


def run(coro):
    return asyncio.run(coro)


def events(kind):
    now = datetime.now(settings.zoneinfo())
    return [e for e in event_log.read_events(f"{now:%Y-%m}") if e["kind"] == kind]


def test_update_capture_edits_text_and_tick_in_place(env):
    dt = datetime(2026, 10, 22, 9, 5, tzinfo=settings.zoneinfo())
    a = daily_notes.append_capture(dt, "buy milk")
    b = daily_notes.append_capture(dt, "call mum")
    updated = daily_notes.update_capture("2026-10-22", a, text="  buy oat\nmilk ", done=True)
    assert updated == {"id": a, "time": "09:05", "text": "buy oat milk", "done": True}
    assert daily_notes.read_captures("2026-10-22") == [
        {"id": a, "time": "09:05", "text": "buy oat milk", "done": True},
        {"id": b, "time": "09:05", "text": "call mum", "done": False},
    ]
    assert daily_notes.update_capture("2026-10-22", a, done=False)["text"] == "buy oat milk"
    assert daily_notes.update_capture("2026-10-22", "nope", done=True) is None
    assert daily_notes.update_capture("2026-01-01", a, done=True) is None
    with pytest.raises(ValueError):
        daily_notes.update_capture("2026-10-22", a, text="   ")


def test_add_list_edit_flow_logs_edit_with_origin(env):
    from routes import captures

    created = run(captures.add_capture(captures.CaptureCreate(text="book dentist"), None))
    today = f"{datetime.now(settings.zoneinfo()):%Y-%m-%d}"
    listing = run(captures.list_captures(None, days=3))
    assert listing["unticked"] == 1 and listing["days"][0]["date"] == today
    assert listing["days"][0]["captures"][0]["text"] == "book dentist"
    cap = events("capture")[0]
    assert cap["source"] == "dashboard" and cap["capture_id"] == created["id"]

    out = run(captures.edit_capture(today, created["id"], captures.CaptureEdit(done=True), None))
    assert out["done"] is True
    edit = events("edit")[0]
    assert edit["capture_id"] == created["id"] and edit["fields"] == ["done"]
    assert edit["before"] == {"done": False} and edit["after"] == {"done": True}
    assert run(captures.list_captures(None, days=3))["unticked"] == 0

    run(captures.edit_capture(today, created["id"], captures.CaptureEdit(done=True), None))
    assert len(events("edit")) == 1  # no-op edits are not logged


def test_capture_routes_validate_input(env):
    from routes import captures

    with pytest.raises(HTTPException) as e:
        run(captures.add_capture(captures.CaptureCreate(text="  "), None))
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        run(captures.edit_capture("../../etc/passwd", "x", captures.CaptureEdit(done=True), None))
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        run(captures.edit_capture("2026-10-22", "missing", captures.CaptureEdit(done=True), None))
    assert e.value.status_code == 404


def test_convert_to_reminder_ticks_capture_and_logs_convert(env, monkeypatch):
    from agent.tools import alerts
    from routes import captures

    created = run(captures.add_capture(captures.CaptureCreate(text="water plants"), None))
    today = f"{datetime.now(settings.zoneinfo()):%Y-%m-%d}"
    seen = []
    monkeypatch.setattr(alerts, "_create_reminder", lambda msg, when: seen.append((msg, when)) or "Got it — x")
    body = captures.CaptureConvert(to="reminder", when="2099-01-01 10:00")
    out = run(captures.convert_capture(today, created["id"], body, None))
    assert seen == [("water plants", "2099-01-01 10:00")] and out["done"] is True
    conv = events("convert")[0]
    assert conv["to"] == "reminder" and conv["capture_id"] == created["id"]


def test_convert_failure_leaves_capture_open(env, monkeypatch):
    from agent.tools import alerts
    from routes import captures

    created = run(captures.add_capture(captures.CaptureCreate(text="water plants"), None))
    today = f"{datetime.now(settings.zoneinfo()):%Y-%m-%d}"
    monkeypatch.setattr(alerts, "_create_reminder", lambda msg, when: "I couldn't understand the time 'soon'.")
    with pytest.raises(HTTPException) as e:
        run(captures.convert_capture(today, created["id"], captures.CaptureConvert(to="reminder", when="soon"), None))
    assert e.value.status_code == 400 and "couldn't understand" in e.value.detail
    with pytest.raises(HTTPException) as e:
        run(captures.convert_capture(today, created["id"], captures.CaptureConvert(to="event"), None))
    assert e.value.status_code == 422
    assert daily_notes.read_captures(today)[0]["done"] is False
    assert events("convert") == []


def test_convert_to_task_saves_a_planning_task(env, monkeypatch):
    from routes import captures

    saved = []
    monkeypatch.setattr(captures, "save_planning_tasks", lambda d, t: saved.append((d, t)))
    created = run(captures.add_capture(captures.CaptureCreate(text="tidy desk"), None))
    today = f"{datetime.now(settings.zoneinfo()):%Y-%m-%d}"
    run(captures.convert_capture(today, created["id"], captures.CaptureConvert(to="task", minutes=15), None))
    assert saved == [(today, [("tidy desk", 15)])]


def test_today_and_capture_routes_are_in_the_schema():
    import main

    paths = set(main.app.openapi()["paths"])
    assert {"/today", "/captures", "/captures/{date_str}/{capture_id}",
            "/captures/{date_str}/{capture_id}/convert"} <= paths


def test_today_collects_events_reminders_and_answered_checkins(env, monkeypatch):
    from routes import today

    monkeypatch.setattr(today, "get_events_in_range", lambda a, b: {"success": True, "events": [
        {"summary": "Later", "start": "20991231T150000Z", "end": "20991231T160000Z"},
        {"summary": "Bad", "start": "x"},
    ]})
    monkeypatch.setattr(today.reminders_store, "list_pending", lambda: [])
    out = run(today.today(None))
    assert [e["title"] for e in out["events"]] == ["Later"]
    assert out["reminders"] == [] and out["checkins"] == []
    assert out["date"] == f"{datetime.now(settings.zoneinfo()):%Y-%m-%d}"
