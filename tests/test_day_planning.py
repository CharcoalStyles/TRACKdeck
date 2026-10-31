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
    # Study is split into sprints, but all of them still come before Dishes.
    assert tasks[-1] == "Dishes" and all(t.startswith("Study") for t in tasks[:-1])


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


def _dt(hour, minute=0):
    return datetime(2026, 10, 31, hour, minute, tzinfo=timezone.utc)


def test_long_tasks_are_split_into_sprints_with_varied_breaks():
    import random

    from utils.planning import compute_schedule_blocks

    for seed in range(20):
        blocks, unscheduled = compute_schedule_blocks(
            [("Study", 90), ("Toilet", 10), ("Yard", 45)],
            [], _dt(9), _dt(20),
            chunk_range=(15, 25), break_range=(5, 15), shuffle=True, rng=random.Random(seed),
        )
        assert not unscheduled
        task_blocks = [b for b in blocks if b.kind == "task"]
        minutes = lambda b: (b.end - b.start).seconds // 60
        assert sum(minutes(b) for b in task_blocks if b.label.startswith("Study")) == 90
        assert sum(minutes(b) for b in task_blocks if b.label.startswith("Yard")) == 45
        assert all(15 <= minutes(b) <= 25 for b in task_blocks if not b.label.startswith("Toilet"))
        assert all(5 <= minutes(b) <= 15 for b in blocks if b.kind == "break" and b is not blocks[-1])


def test_after_constraint_survives_shuffling():
    import random

    from utils.planning import compute_schedule_blocks

    tasks = [("Kitchen", 30), ("Bircher", 15), ("Vacuum", 15), ("Study", 90)]
    after = {"bircher": "kitchen", "vacuum": "kitchen"}
    for seed in range(50):
        blocks, _ = compute_schedule_blocks(
            tasks, [], _dt(9), _dt(20), chunk_range=(15, 25), break_range=(5, 15),
            shuffle=True, after=after, rng=random.Random(seed),
        )
        labels = [b.label for b in blocks if b.kind == "task"]
        last_kitchen = max(i for i, l in enumerate(labels) if l.startswith("Kitchen"))
        for dependent in ("Bircher", "Vacuum"):
            assert labels.index(dependent) > last_kitchen


def test_after_suffix_round_trips_through_the_planning_note(planning_env):
    from agent.tools import planning
    from utils.planning import parse_target_tasks, parse_task_dependencies

    planning.save_planning_tasks("2026-11-05", [("Kitchen", 30), ("Bircher", 15, "Kitchen")])
    note = vault.parse_note(vault.planning_note_path("2026-11-05"))
    section = vault.get_section(note.body, "Tasks")
    assert parse_target_tasks(section) == [("Kitchen", 30), ("Bircher", 15)]
    assert parse_task_dependencies(section) == {"bircher": "kitchen"}


def test_window_always_sent_with_defaults_for_a_missing_bound(planning_env):
    from routes import day_planning

    body = day_planning.DayPlanRun(date="2026-10-31", start_time="11:15")
    text = day_planning.build_run_message(body)
    assert "Schedule window: 11:15 to " in text


def test_reminders_fire_at_block_start_not_end(planning_env, monkeypatch):
    from agent.tools import planning

    made = []
    monkeypatch.setattr(planning, "get_events_in_range", lambda *a: {"success": True, "events": []})
    monkeypatch.setattr(planning, "create_or_update_event", lambda **kw: {"success": True})
    monkeypatch.setattr(planning.reminders_store, "create_reminder", lambda rid, msg, due, uid, snd: made.append((msg, due, uid)))
    monkeypatch.setattr(planning.scheduler, "add_job", lambda *a, **k: None)
    date = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")
    planning.save_planning_tasks(date, [("Dishes", 20)])
    planning.generate_schedule_blocks.func(date=date, start_time="09:00", end_time="18:00")
    messages = [m for m, _, _ in made]
    assert messages[0] == "Start: Dishes" and messages[1] == "Break time"
    assert messages[-1] == "All done for the day" and not any("ended" in m for m in messages)


def test_push_text_adds_length_and_end_only_for_generated_blocks(monkeypatch):
    from jobs import reminders

    event = {"start": "20261031T001500Z", "end": "20261031T004000Z", "generated": True}
    monkeypatch.setattr(reminders, "get_event", lambda uid: {"success": True, "event": event})
    text = reminders.push_text({"message": "Start: Study", "event_uid": "u1"})
    assert text.startswith("Start: Study — 25 min, until ")
    event["generated"] = False
    assert reminders.push_text({"message": "Dentist", "event_uid": "u1"}) == "Dentist"
    assert reminders.push_text({"message": "Tea", "event_uid": None}) == "Tea"
    monkeypatch.setattr(reminders, "get_event", lambda uid: (_ for _ in ()).throw(RuntimeError()))
    assert reminders.push_text({"message": "Study", "event_uid": "u1"}) == "Study"
