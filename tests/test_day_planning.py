import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from utils import task_library_store, vault
from utils.planning import order_tasks, parse_order_hint

TASKS = [("Dishes", 20), ("Laundry", 30), ("Shower", 10), ("Study", 45)]


def test_parse_order_hint():
    assert parse_order_hint("before Shower") == ("before", "Shower")
    assert parse_order_hint("  After  Clean the kitchen ") == ("after", "Clean the kitchen")
    assert parse_order_hint("") is None and parse_order_hint(None) is None
    assert parse_order_hint("sometime Shower") is None
    assert parse_order_hint("before") is None


def names(tasks):
    return [t[0] for t in tasks]


def test_order_tasks_moves_before_and_after():
    assert names(order_tasks(TASKS, {"study": "before dishes"})) == ["Study", "Dishes", "Laundry", "Shower"]
    assert names(order_tasks(TASKS, {"dishes": "after Shower"})) == ["Laundry", "Shower", "Dishes", "Study"]


def test_order_tasks_ignores_absent_self_and_malformed_references():
    assert order_tasks(TASKS, {"dishes": "before Gardening"}) == TASKS
    assert order_tasks(TASKS, {"dishes": "before Dishes"}) == TASKS
    assert order_tasks(TASKS, {"dishes": "whenever"}) == TASKS
    assert order_tasks(TASKS, {}) == TASKS


def test_order_tasks_contradictory_hints_terminate_and_keep_every_task():
    result = order_tasks(TASKS, {"dishes": "before Laundry", "laundry": "before Dishes"})
    assert sorted(result) == sorted(TASKS)


def test_order_tasks_does_not_mutate_input():
    original = list(TASKS)
    order_tasks(TASKS, {"study": "before dishes"})
    assert TASKS == original


@pytest.fixture
def planning_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setattr(task_library_store, "DB_PATH", str(tmp_path / "task_library.db"))
    task_library_store.init_db()
    return tmp_path


def test_generate_schedule_blocks_honours_library_hints(planning_env, monkeypatch):
    from agent.tools import planning

    monkeypatch.setattr(planning, "get_events_in_range", lambda a, b: {"success": True, "events": []})
    created = []
    monkeypatch.setattr(
        planning, "create_or_update_event", lambda **kw: created.append(kw["summary"]) or {"success": True}
    )
    monkeypatch.setattr(planning.reminders_store, "create_reminder", lambda *a, **k: None)
    monkeypatch.setattr(planning.scheduler, "add_job", lambda *a, **k: None)
    task_library_store.create("t1", "Study", 45, None, "before Dishes")

    date = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")
    planning.save_planning_tasks(date, [("Dishes", 20), ("Study", 45)])
    planning.generate_schedule_blocks.func(date=date, start_time="09:00", end_time="18:00")
    tasks = [s for s in created if s != "Break"]
    assert tasks == ["Study", "Dishes"]


def test_task_library_routes_validate_and_store_order_hint(planning_env, monkeypatch):
    import main

    from routes import task_library

    body = task_library.TaskLibraryInput(label="Tea", default_minutes=5, order_hint=" after Dishes ")
    assert body.order_hint == "after Dishes"
    assert task_library.TaskLibraryInput(label="Tea", default_minutes=5, order_hint="  ").order_hint is None
    with pytest.raises(ValueError):
        task_library.TaskLibraryInput(label="Tea", default_minutes=5, order_hint="at noon")

    created = asyncio.run(task_library.create_task_library_item(body, None))
    assert created["order_hint"] == "after Dishes"
    listed = asyncio.run(task_library.list_task_library(None))
    assert listed[0]["order_hint"] == "after Dishes"


def test_run_now_saves_tasks_then_runs_the_day_planning_turn(planning_env, monkeypatch):
    from routes import day_planning

    calls = []

    class Result:
        reply = "Here is your schedule."

    async def fake_run_agent(text, **kwargs):
        calls.append((text, kwargs))
        return Result()

    monkeypatch.setattr(day_planning, "run_agent", fake_run_agent)
    body = day_planning.DayPlanRun(
        date="2026-10-23",
        tasks=[day_planning.TaskInput(task="Dishes", minutes=20)],
        fixed_blocks=[day_planning.FixedBlockInput(name="Work", start_time="09:00", end_time="17:00")],
        notes="Shopping after lunch",
        start_time="17:00",
        end_time="21:00",
    )
    response = asyncio.run(day_planning.run_day_plan(body, None))
    assert response == {"reply": "Here is your schedule."}
    text, kwargs = calls[0]
    assert "Generate my schedule for 2026-10-23" in text
    assert "Shopping after lunch" in text and "Schedule window: 17:00 to 21:00" in text
    assert kwargs == {"thread_id": "day_planning:2026-10-23", "mode": "day_planning", "source": "dashboard"}
    note = vault.parse_note(vault.planning_note_path("2026-10-23"))
    assert "Dishes — Est: 20 mins" in vault.get_section(note.body, "Tasks")
    assert "Work — 09:00 to 17:00" in vault.get_section(note.body, "Fixed Blocks")


def test_no_scheduled_plan_routes_remain():
    import main

    paths = set(main.app.openapi()["paths"])
    assert "/day-plans/run" in paths
    assert not {"/day-plans", "/day-plans/{plan_id}", "/day-plans/{plan_id}/cancel"} & paths
