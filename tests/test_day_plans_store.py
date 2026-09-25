import utils.day_plans_store as day_plans_store


def _use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(day_plans_store, "DB_PATH", str(tmp_path / "day_plans.db"))
    day_plans_store.init_db()


def test_create_and_get_round_trips(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    day_plans_store.create("p1", "2026-09-20", "09:00", "12:00", "morning only")
    plan = day_plans_store.get("p1")

    assert plan["date"] == "2026-09-20"
    assert plan["start_time"] == "09:00"
    assert plan["end_time"] == "12:00"
    assert plan["notes"] == "morning only"
    assert plan["status"] == "scheduled"
    assert plan["reply"] is None


def test_list_upcoming_excludes_past_dates_and_non_scheduled(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    day_plans_store.create("past", "2026-09-01", "09:00", None, None)
    day_plans_store.create("future", "2026-09-25", "09:00", None, None)
    day_plans_store.create("cancelled", "2026-09-26", "09:00", None, None)
    day_plans_store.cancel("cancelled")

    upcoming = day_plans_store.list_upcoming("2026-09-18")

    assert [p["id"] for p in upcoming] == ["future"]


def test_update_changes_fields_without_touching_status(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    day_plans_store.create("p1", "2026-09-20", "09:00", None, None)
    updated = day_plans_store.update("p1", "10:00", "11:00", "revised")

    assert updated["start_time"] == "10:00"
    assert updated["end_time"] == "11:00"
    assert updated["notes"] == "revised"
    assert updated["status"] == "scheduled"


def test_mark_generated_sets_status_and_reply(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    day_plans_store.create("p1", "2026-09-20", "09:00", None, None)
    day_plans_store.mark_generated("p1", "Scheduled 3 tasks.")

    plan = day_plans_store.get("p1")
    assert plan["status"] == "generated"
    assert plan["reply"] == "Scheduled 3 tasks."
    assert plan["generated_at"] is not None
    assert day_plans_store.list_upcoming("2026-09-01") == []


def test_cancel_removes_from_scheduled_listings(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    day_plans_store.create("p1", "2026-09-20", "09:00", None, None)
    day_plans_store.cancel("p1")

    assert day_plans_store.get("p1")["status"] == "cancelled"
    assert day_plans_store.list_scheduled() == []
    assert day_plans_store.list_upcoming("2026-09-01") == []
