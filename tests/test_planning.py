import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from utils.planning import (
    compute_schedule_blocks,
    format_reflection_digest,
    format_reflection_section,
    parse_reflection_section,
    parse_target_tasks,
    reflection_is_filled,
)

TZ = ZoneInfo("Australia/Canberra")


def _dt(hour, minute=0):
    return datetime(2026, 9, 13, hour, minute, tzinfo=TZ)


def test_parse_target_tasks_skips_checked_and_unparseable_lines():
    section = """
- [ ] Kitchen dishes — Est: 25 mins
- [x] Already done — Est: 10 mins
- [ ] No estimate here
- [ ] Task 2: Fold laundry — Est: 30 mins
"""
    assert parse_target_tasks(section) == [("Kitchen dishes", 25), ("Fold laundry", 30)]


def test_compute_schedule_blocks_fits_tasks_around_a_calendar_event():
    tasks = [("Kitchen", 25), ("Laundry", 30)]
    occupied = [(_dt(12), _dt(13))]  # lunch, already on the calendar

    blocks, unscheduled = compute_schedule_blocks(tasks, occupied, _dt(7), _dt(21))

    assert unscheduled == []
    task_blocks = [b for b in blocks if b.kind == "task"]
    assert [b.label for b in task_blocks] == ["Kitchen", "Laundry"]
    for block in blocks:
        assert not (block.start < _dt(13) and block.end > _dt(12))


def test_compute_schedule_blocks_reports_unscheduled_when_no_room():
    tasks = [("Too big for the window", 600)]
    blocks, unscheduled = compute_schedule_blocks(tasks, [], _dt(7), _dt(8))
    assert blocks == []
    assert unscheduled == ["Too big for the window"]


def test_reflection_section_round_trips():
    values = {
        "energy_rating": "7",
        "what_worked_well": "Kitchen sprint",
        "what_had_friction": None,
        "adjustments": "Shorter breaks",
    }
    text = format_reflection_section(values)
    assert parse_reflection_section(text) == values


def test_reflection_is_filled():
    empty = {"energy_rating": None, "what_worked_well": None, "what_had_friction": None, "adjustments": None}
    assert reflection_is_filled(empty) is False
    assert reflection_is_filled({**empty, "energy_rating": "7"}) is True


def test_format_reflection_digest_empty():
    assert format_reflection_digest([]) == ""


def test_add_planning_task_concurrent_calls_dont_crash_or_lose_tasks(tmp_path, monkeypatch):
    """Regression test for the day-planning form's actual failure: LangGraph
    runs same-turn tool calls concurrently (once per task, by design — see
    add_planning_task's docstring), which used to crash write_note_atomic
    (pid-only temp names collided across threads) and, even once that's
    fixed, could silently drop a task to a read-modify-write race without
    _planning_note_lock serializing it."""
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    from agent.tools.planning import add_planning_task
    from utils import vault

    date_str = "2026-09-19"
    task_names = [f"Task {i}" for i in range(8)]

    threads = [
        threading.Thread(target=add_planning_task.func, args=(name, 10, date_str))
        for name in task_names
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    note = vault.parse_note(vault.planning_note_path(date_str))
    assert note is not None
    tasks_section = vault.get_section(note.body, "Tasks") or ""
    for name in task_names:
        assert name in tasks_section


def test_format_reflection_digest_formats_filled_fields_only():
    entries = [
        (
            "2026-09-11",
            {
                "energy_rating": "6",
                "what_worked_well": None,
                "what_had_friction": "Too many context switches",
                "adjustments": None,
            },
        ),
    ]
    digest = format_reflection_digest(entries)
    assert "Recent reflections to consider:" in digest
    assert "2026-09-11" in digest
    assert "Too many context switches" in digest
    assert "What worked well" not in digest
