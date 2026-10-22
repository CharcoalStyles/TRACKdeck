import asyncio
from datetime import datetime

import pytest
from fastapi import HTTPException

from agent.settings import settings
from utils import event_log


@pytest.fixture
def cal(tmp_path, monkeypatch):
    from routes import calendar_events

    monkeypatch.setenv("EVENT_LOG_DIR", str(tmp_path / "logs"))
    store = {}

    def create(uid, summary, start_iso, end_iso, description="", location="", rrule=None, generated=False):
        store[uid] = {"uid": uid, "summary": summary, "start": start_iso, "end": end_iso,
                      "description": description, "location": location, "rrule": rrule}
        return {"success": True}

    monkeypatch.setattr(calendar_events, "create_or_update_event", create)
    monkeypatch.setattr(calendar_events, "get_event", lambda uid: (
        {"success": True, "event": store[uid]} if uid in store else {"success": False, "message": "nf"}))
    monkeypatch.setattr(calendar_events, "delete_event", lambda uid: (store.pop(uid), {"success": True})[1])
    return calendar_events, store


def run(coro):
    return asyncio.run(coro)


def events(kind):
    now = datetime.now(settings.zoneinfo())
    return [e for e in event_log.read_events(f"{now:%Y-%m}") if e["kind"] == kind]


def test_add_defaults_to_one_hour_and_logs_a_dashboard_create(cal):
    mod, store = cal
    out = run(mod.add_event(mod.CalendarEventCreate(title=" Dentist ", start="2099-03-04 14:00"), None))
    saved = store[out["uid"]]
    assert saved["summary"] == "Dentist" and int(saved["end"][9:11]) == int(saved["start"][9:11]) + 1
    ev = events("artifact")[0]
    assert (ev["type"], ev["op"], ev["id"], ev["source"]) == ("calendar_event", "create", out["uid"], "dashboard")


def test_add_validates_title_time_and_order(cal):
    mod, _ = cal
    for body in (mod.CalendarEventCreate(title=" ", start="2099-03-04 14:00"),
                 mod.CalendarEventCreate(title="x", start="gibberish"),
                 mod.CalendarEventCreate(title="x", start="2099-03-04 14:00", end="2099-03-04 13:00")):
        with pytest.raises(HTTPException) as e:
            run(mod.add_event(body, None))
        assert e.value.status_code == 422


def test_edit_logs_before_after_and_origin_of_the_model_made_event(cal):
    mod, store = cal
    event_log.note_artifact("calendar_event", "u1", "create")
    mod.create_or_update_event("u1", "Lunch", "20990304T020000Z", "20990304T030000Z")
    out = run(mod.edit_event("u1", mod.CalendarEventEdit(title="Lunch with Sam", start="2099-03-04 14:00"), None))
    assert out == {"uid": "u1"}
    assert store["u1"]["summary"] == "Lunch with Sam"
    edit = events("edit")[0]
    assert edit["artifact_type"] == "calendar_event" and edit["action"] == "update"
    assert set(edit["fields"]) == {"title", "start", "end"}  # moving the start keeps the duration
    assert edit["after"]["end"] == "20990304T040000Z"
    assert edit["before"]["title"] == "Lunch" and edit["after"]["title"] == "Lunch with Sam"
    assert edit["before"]["start"] == "20990304T020000Z" and edit["after"]["start"] != edit["before"]["start"]
    assert edit["source"] == "dashboard" and "origin_interaction_id" in edit


def test_edit_noop_is_not_logged_and_repeating_events_are_refused(cal):
    mod, store = cal
    mod.create_or_update_event("u1", "Lunch", "20990304T020000Z", "20990304T030000Z")
    run(mod.edit_event("u1", mod.CalendarEventEdit(title="Lunch"), None))
    assert events("edit") == []
    mod.create_or_update_event("u2", "Gym", "20990304T020000Z", "20990304T030000Z", rrule="FREQ=WEEKLY")
    with pytest.raises(HTTPException) as e:
        run(mod.edit_event("u2", mod.CalendarEventEdit(title="Gym 2"), None))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        run(mod.edit_event("missing", mod.CalendarEventEdit(title="x"), None))
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        run(mod.edit_event("../x", mod.CalendarEventEdit(title="x"), None))
    assert e.value.status_code == 422


def test_delete_logs_a_delete_edit_with_the_event_as_it_was(cal):
    mod, store = cal
    mod.create_or_update_event("u1", "Lunch", "20990304T020000Z", "20990304T030000Z", location="Cafe")
    assert run(mod.remove_event("u1", None)) == {"uid": "u1"}
    assert "u1" not in store
    edit = events("edit")[0]
    assert edit["action"] == "delete" and edit["after"] is None
    assert edit["before"]["title"] == "Lunch" and edit["before"]["location"] == "Cafe"
    with pytest.raises(HTTPException) as e:
        run(mod.remove_event("u1", None))
    assert e.value.status_code == 404


def test_today_takes_a_date_and_exposes_event_details(cal, tmp_path, monkeypatch):
    from routes import today

    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    seen = {}
    monkeypatch.setattr(today, "get_events_in_range", lambda a, b: seen.update(a=a, b=b) or {"success": True, "events": [
        {"uid": "u9", "summary": "Trip", "start": "20991231T150000Z", "end": "20991231T160000Z",
         "location": "Airport", "rrule": "FREQ=YEARLY"}]})
    monkeypatch.setattr(today.reminders_store, "list_pending", lambda: [])
    out = run(today.today(None, date="2099-12-31"))
    assert out["date"] == "2099-12-31" and out["is_today"] is False and out["weekday"] == "Thursday"
    assert out["events"][0]["uid"] == "u9" and out["events"][0]["repeats"] is True
    assert out["events"][0]["location"] == "Airport"
    assert run(today.today(None))["is_today"] is True
    with pytest.raises(HTTPException) as e:
        run(today.today(None, date="2099-02-31"))
    assert e.value.status_code == 422


def test_calendar_event_routes_are_in_the_schema():
    import main

    paths = main.app.openapi()["paths"]
    assert {"post"} <= set(paths["/calendar-events"]) and {"patch", "delete"} <= set(paths["/calendar-events/{uid}"])
    assert "/captures/{date_str}/{capture_id}" in paths and "delete" in paths["/captures/{date_str}/{capture_id}"]
