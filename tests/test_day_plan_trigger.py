import asyncio

import jobs.day_plan_trigger as day_plan_trigger


def test_fire_day_plan_is_a_noop_for_a_cancelled_plan(monkeypatch):
    """A plan can be cancelled between being scheduled and its T-15
    trigger firing (routes/day_plans.py's cancel endpoint removes the
    scheduler job, but a race is still possible) — fire_day_plan must
    re-check status and skip rather than generating a schedule the user
    already cancelled."""
    monkeypatch.setattr(
        day_plan_trigger.day_plans_store,
        "get",
        lambda plan_id: {"id": plan_id, "status": "cancelled", "date": "2026-09-20",
                          "start_time": None, "end_time": None, "notes": None},
    )

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("run_agent should not be called for a cancelled plan")

    monkeypatch.setattr(day_plan_trigger, "run_agent", _fail_if_called)

    result = asyncio.run(day_plan_trigger.fire_day_plan("p1"))
    assert result is None


def test_fire_day_plan_is_a_noop_for_a_missing_plan(monkeypatch):
    monkeypatch.setattr(day_plan_trigger.day_plans_store, "get", lambda plan_id: None)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("run_agent should not be called for a missing plan")

    monkeypatch.setattr(day_plan_trigger, "run_agent", _fail_if_called)

    result = asyncio.run(day_plan_trigger.fire_day_plan("p1"))
    assert result is None
