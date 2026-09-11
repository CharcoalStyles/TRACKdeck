from datetime import datetime
from zoneinfo import ZoneInfo

from utils.planning import (
    compute_schedule_blocks,
    format_reflection_section,
    parse_reflection_section,
    parse_target_tasks,
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
