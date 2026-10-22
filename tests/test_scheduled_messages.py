import asyncio
import json
from datetime import date, datetime

import pytest
from freezegun import freeze_time

from agent import scheduler
from agent.settings import settings
from jobs import common, evening, morning
from jobs import reviews as review_jobs
from utils import checkin_log, daily_notes, day_context, event_log, reviews


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("EVENT_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(settings, "timezone", "UTC")
    monkeypatch.setattr(settings, "weather_enabled", True)
    monkeypatch.setattr(settings, "daily_commentary", False)
    return tmp_path


DAY = date(2026, 10, 22)  # a Thursday


def _at(hour, minute=0, day=DAY):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=settings.zoneinfo())


def _stub_context(monkeypatch):
    monkeypatch.setattr(day_context, "render_calendar", lambda a, b: f"CAL {a}..{b}")
    monkeypatch.setattr(day_context, "render_reminders", lambda a, b: f"REM {a}..{b}")
    monkeypatch.setattr(day_context, "render_forecast", lambda a, b: f"FC {a}..{b}")


# ---- utils/reviews ---------------------------------------------------------


def test_period_keys():
    assert reviews.period_key("daily", DAY) == "2026-10-22"
    assert reviews.period_key("weekly", DAY) == "2026-W43"
    assert reviews.period_key("monthly", DAY) == "2026-10"
    # ISO year differs from the calendar year at the boundary.
    assert reviews.period_key("weekly", date(2027, 1, 1)) == "2026-W53"
    with pytest.raises(ValueError):
        reviews.period_key("yearly", DAY)


def test_review_round_trip_and_overwrite(env):
    path = reviews.write_review("weekly", "2026-W43", "Weekly review", "First draft.")
    assert path == env / "vault" / "Reviews" / "Weekly" / "2026-W43.md"
    text = path.read_text()
    assert text.startswith("---\ntype: review-weekly\nperiod: 2026-W43\n")
    assert reviews.read_review_body("weekly", "2026-W43") == "First draft."
    reviews.write_review("weekly", "2026-W43", "Weekly review", "Second draft.")
    assert reviews.read_review_body("weekly", "2026-W43") == "Second draft."
    assert reviews.read_review_body("weekly", "2026-W44") is None


# ---- utils/day_context -----------------------------------------------------


def test_render_day_combines_captures_checkins_and_interactions(env):
    daily_notes.append_capture(_at(9, 5), "buy oat milk")
    daily_notes.append_capture(_at(11, 0), "call the dentist")
    checkin_log.append_entry("c1", _at(10), "answered", "What went well?", "Finished the draft")
    checkin_log.append_entry("c2", _at(15), "skipped", "How is your energy?")
    with freeze_time("2026-10-22 12:30:00"):
        event_log.log_event(
            "interaction",
            user_text="what is on tomorrow",
            tools=[{"name": "get_calendar_events"}],
            reply="Nothing much.",
        )
        event_log.log_event("interaction", user_text="call the dentist", fallback_capture=True)

    text = day_context.render_day(DAY, with_replies=True)
    assert "- [ ] 09:05 buy oat milk" in text
    assert "Finished the draft" in text
    assert "How is your energy?" not in text  # unanswered check-ins are left out
    assert "12:30 what is on tomorrow [tools: get_calendar_events]" in text
    assert "Assistant: Nothing much." in text
    # The fallback capture appears once, under Captures only.
    assert text.count("call the dentist") == 1
    assert "Assistant:" not in day_context.render_day(DAY)


def test_render_day_empty_and_clipped(env):
    assert day_context.render_day(DAY) == ""
    daily_notes.append_capture(_at(9), "x" * 500)
    assert len(day_context.render_day(DAY, max_chars=100)) <= 100


def test_render_days_skips_quiet_days_and_clips_total(env):
    daily_notes.append_capture(_at(9), "monday thing", )
    daily_notes.append_capture(_at(9, day=date(2026, 10, 24)), "saturday thing")
    text = day_context.render_days(date(2026, 10, 19), date(2026, 10, 25))
    assert "[Saturday 24 October 2026]" in text and "[Thursday 22 October 2026]" in text
    assert "Friday" not in text
    assert text.index("Thursday") < text.index("Saturday")
    assert len(day_context.render_days(date(2026, 10, 19), date(2026, 10, 25), total_chars=60)) <= 60


def test_leftover_captures_exclude_ticked(env):
    first = daily_notes.append_capture(_at(9), "done already")
    daily_notes.append_capture(_at(10), "still open")
    path = daily_notes.daily_notes_file(DAY.isoformat())
    path.write_text(path.read_text().replace(f"- [ ] 09:00 done already ^{first}", f"- [x] 09:00 done already ^{first}"))
    assert day_context.render_leftover_captures(DAY).splitlines() == ["- 10:00 still open"]


def test_render_reviews_reads_bodies_and_skips_missing(env):
    reviews.write_review("weekly", "2026-W42", "t", "Quiet week.")
    text = day_context.render_reviews("weekly", ["2026-W41", "2026-W42"])
    assert text == "[2026-W42]\nQuiet week."


def test_render_calendar_formats_local_sorted_events(env, monkeypatch):
    monkeypatch.setattr(settings, "timezone", "Australia/Canberra")
    seen = {}

    def fake_events(start, end):
        seen["range"] = (start, end)
        return {
            "success": True,
            "events": [
                {"uid": "b", "summary": "Later", "start": "20261022T080000Z", "end": "20261022T090000Z"},
                {"uid": "a", "summary": "Earlier", "start": "20261022T010000Z", "end": "20261022T020000Z"},
                {"uid": "c", "summary": "Bad", "start": "garbage"},
            ],
        }

    monkeypatch.setattr("utils.caldav_client.get_events_in_range", fake_events)
    lines = day_context.render_calendar(DAY, DAY).splitlines()
    # Canberra is UTC+11 in late October.
    assert lines == ["- Thu 22 Oct 12:00-13:00 Earlier", "- Thu 22 Oct 19:00-20:00 Later"]
    assert seen["range"] == ("20261021T130000Z", "20261022T130000Z")


def test_render_calendar_degrades_to_empty(env, monkeypatch):
    def boom(start, end):
        raise RuntimeError("down")

    monkeypatch.setattr("utils.caldav_client.get_events_in_range", boom)
    assert day_context.render_calendar(DAY, DAY) == ""
    monkeypatch.setattr("utils.caldav_client.get_events_in_range", lambda s, e: {"success": False})
    assert day_context.render_calendar(DAY, DAY) == ""


def test_render_reminders_filters_by_range(env, monkeypatch):
    inside = _at(9).timestamp()
    outside = _at(9, day=date(2026, 10, 25)).timestamp()
    monkeypatch.setattr(
        "utils.reminders_store.list_pending",
        lambda: [{"due_at": inside, "message": "stretch"}, {"due_at": outside, "message": "later"}],
    )
    assert day_context.render_reminders(DAY, DAY) == "- Thu 22 Oct 09:00 stretch"


def test_render_forecast_and_weather_switch(env, monkeypatch):
    payload = json.dumps(
        [
            {
                "time": "2026-10-22",
                "temperature_2m_min": 8,
                "temperature_2m_max": 19,
                "precipitation_probability_min": 0,
                "precipitation_probability_max": 40,
            },
            {"time": "bad"},
        ]
    )

    class FakeTool:
        def invoke(self, args):
            assert args == {"start": "2026-10-22", "end": "2026-10-23"}
            return payload

    monkeypatch.setattr("agent.tools.weather.get_range_forecast", FakeTool())
    out = day_context.render_forecast(DAY, date(2026, 10, 23))
    assert out == "- Thursday 22 October: 8-19 C, rain chance up to 40%"
    monkeypatch.setattr(settings, "weather_enabled", False)
    assert day_context.render_forecast(DAY, date(2026, 10, 23)) == ""


# ---- prompt builders and compose functions ---------------------------------


def test_morning_prompt_carries_today_tomorrow_and_leftovers(env, monkeypatch):
    _stub_context(monkeypatch)
    daily_notes.append_capture(_at(9, day=date(2026, 10, 21)), "renew the permit")
    prompt = morning.build_prompt(DAY)
    assert "Today is Thursday 22 October 2026" in prompt
    assert "CAL 2026-10-22..2026-10-22" in prompt and "CAL 2026-10-23..2026-10-23" in prompt
    assert "FC 2026-10-22..2026-10-23" in prompt
    assert "renew the permit" in prompt


def test_morning_prompt_marks_empty_sections_none(env, monkeypatch):
    monkeypatch.setattr(day_context, "render_calendar", lambda a, b: "")
    monkeypatch.setattr(day_context, "render_reminders", lambda a, b: "")
    monkeypatch.setattr(day_context, "render_forecast", lambda a, b: "")
    prompt = morning.build_prompt(DAY)
    assert prompt.count(":\n(none)\n") == 5


def test_compose_morning_uses_writer(env, monkeypatch):
    _stub_context(monkeypatch)
    prompts = []
    monkeypatch.setattr(morning, "write", lambda p, **k: prompts.append(p) or "Good morning text")
    assert morning.compose_morning_message(DAY) == "Good morning text"
    assert "Thursday 22 October 2026" in prompts[0]


def test_evening_prompt_has_record_leftovers_and_tomorrow(env, monkeypatch):
    _stub_context(monkeypatch)
    daily_notes.append_capture(_at(9), "write report")
    prompt = evening.build_prompt(DAY)
    assert "write report" in prompt
    assert "CAL 2026-10-23..2026-10-23" in prompt


def test_weekly_prompt_covers_the_iso_week(env, monkeypatch):
    monkeypatch.setattr(day_context, "render_calendar", lambda a, b: f"CAL {a}..{b}")
    daily_notes.append_capture(_at(9), "midweek thing")
    reviews.write_review("weekly", "2026-W42", "t", "Last week was calm.")
    key, prompt = review_jobs.build_weekly_prompt(date(2026, 10, 25))  # the Sunday
    assert key == "2026-W43"
    assert "CAL 2026-10-19..2026-10-25" in prompt
    assert "midweek thing" in prompt and "Last week was calm." in prompt


def test_monthly_prompt_covers_previous_month(env):
    reviews.write_review("weekly", "2026-W40", "t", "Early October summary.")
    reviews.write_review("daily", "2026-09-30", "t", "Last day commentary.")
    reviews.write_review("weekly", "2026-W43", "t", "Not in September.")
    key, prompt = review_jobs.build_monthly_prompt(date(2026, 10, 1))
    assert key == "2026-09"
    assert "September 2026" in prompt
    assert "Last day commentary." in prompt
    assert "Not in September." not in prompt


def test_month_and_week_bounds():
    assert review_jobs.previous_month_bounds(date(2026, 1, 5)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert review_jobs.week_bounds(date(2026, 10, 25)) == (date(2026, 10, 19), date(2026, 10, 25))


def test_compose_weekly_and_monthly_write_files(env, monkeypatch):
    monkeypatch.setattr(day_context, "render_calendar", lambda a, b: "")
    monkeypatch.setattr(review_jobs, "write", lambda p, **k: "Review text.")
    path, text = review_jobs.compose_weekly_review(date(2026, 10, 25))
    assert text == "Review text." and path.name == "2026-W43.md"
    assert reviews.read_review_body("weekly", "2026-W43") == "Review text."
    path, _ = review_jobs.compose_monthly_review(date(2026, 11, 1))
    assert path == env / "vault" / "Reviews" / "Monthly" / "2026-10.md"


def test_writer_empty_reply_raises(monkeypatch):
    class Resp:
        content = "   "

    class LLM:
        def invoke(self, prompt):
            return Resp()

    monkeypatch.setattr(common, "get_writer_llm", lambda temperature: LLM())
    with pytest.raises(RuntimeError):
        common.write("hi")


# ---- send functions --------------------------------------------------------


@pytest.fixture
def sent(monkeypatch):
    calls = {"gotify": [], "errors": [], "sweeps": 0}
    monkeypatch.setattr(evening, "send_gotify", lambda *a, **k: calls["gotify"].append(a))
    monkeypatch.setattr(evening, "notify_error", lambda *a, **k: calls["errors"].append(a))

    async def fake_sweep():
        calls["sweeps"] += 1

    monkeypatch.setattr(evening, "sweep_threads", fake_sweep)
    return calls


def test_evening_sends_saves_commentary_only_when_enabled(env, monkeypatch, sent):
    _stub_context(monkeypatch)
    monkeypatch.setattr(evening, "write", lambda p, **k: "Evening text")
    with freeze_time("2026-10-22 20:45:00"):
        asyncio.run(evening.send_evening_message())
        assert sent["gotify"] == [("Evening", "Evening text", evening.EVENING_PRIORITY)]
        assert reviews.read_review_body("daily", "2026-10-22") is None
        monkeypatch.setattr(settings, "daily_commentary", True)
        asyncio.run(evening.send_evening_message())
    assert reviews.read_review_body("daily", "2026-10-22") == "Evening text"
    assert sent["sweeps"] == 2 and not sent["errors"]


def test_evening_failure_reports_error_but_still_sweeps(env, monkeypatch, sent):
    _stub_context(monkeypatch)

    def boom(p, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr(evening, "write", boom)
    asyncio.run(evening.send_evening_message())
    assert sent["gotify"] == [] and len(sent["errors"]) == 1
    assert sent["sweeps"] == 1


def test_sweep_clears_thread_registry(env):
    from agent.runtime import app_state

    app_state.threads["t1"] = object()
    app_state.keywords["copper wolf"] = "t1"
    app_state.default_thread_id = "t1"
    asyncio.run(evening.sweep_threads())
    assert not app_state.threads and not app_state.keywords and app_state.default_thread_id is None


def test_weekly_push_is_clipped(env, monkeypatch):
    sent = []
    monkeypatch.setattr(review_jobs, "send_gotify", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(day_context, "render_calendar", lambda a, b: "")
    monkeypatch.setattr(review_jobs, "write", lambda p, **k: "word " * 400)
    asyncio.run(review_jobs.send_weekly_review())
    assert sent[0][0] == "Weekly review" and len(sent[0][1]) <= review_jobs.PUSH_CHARS


def test_morning_failure_notifies(env, monkeypatch):
    errors = []
    monkeypatch.setattr(morning, "notify_error", lambda *a, **k: errors.append(a))

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(morning, "compose_morning_message", boom)
    asyncio.run(morning.send_morning_message())
    assert len(errors) == 1


# ---- settings and triggers -------------------------------------------------


def test_settings_validators():
    assert settings_mod().is_valid_clock_time("18:00")
    assert not settings_mod().is_valid_clock_time("25:00")
    assert not settings_mod().is_valid_clock_time("nope")
    assert settings_mod().is_valid_monthly_review_day(1)
    assert settings_mod().is_valid_monthly_review_day(28)
    assert not settings_mod().is_valid_monthly_review_day(29)
    assert not settings_mod().is_valid_monthly_review_day(0)


def settings_mod():
    import agent.settings as mod

    return mod


def test_apply_persisted_parses_new_fields(monkeypatch):
    for name in ("evening_time", "weekly_review_time", "monthly_review_day", "daily_commentary", "weather_enabled"):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    settings_mod().apply_persisted(
        {
            "evening_time": "21:10",
            "weekly_review_time": "17:30",
            "monthly_review_day": "3",
            "daily_commentary": "1",
            "weather_enabled": "0",
        }
    )
    assert settings.evening_time == "21:10"
    assert settings.weekly_review_time == "17:30"
    assert settings.monthly_review_day == 3
    assert settings.daily_commentary is True
    assert settings.weather_enabled is False


def test_triggers_follow_settings(monkeypatch):
    monkeypatch.setattr(settings, "timezone", "UTC")
    monkeypatch.setattr(settings, "evening_time", "21:10")
    monkeypatch.setattr(settings, "weekly_review_time", "17:30")
    monkeypatch.setattr(settings, "monthly_review_day", 3)
    assert "hour='21'" in str(scheduler.evening_trigger()) and "minute='10'" in str(scheduler.evening_trigger())
    weekly = str(scheduler.weekly_trigger())
    assert "day_of_week='sun'" in weekly and "hour='17'" in weekly
    monthly = str(scheduler.monthly_trigger())
    assert "day='3'" in monthly and "minute='30'" in monthly


def test_reschedule_time_jobs_only_touches_registered_jobs(monkeypatch):
    class FakeScheduler:
        def __init__(self):
            self.jobs = {"evening_message"}
            self.rescheduled = []

        def get_job(self, job_id):
            return object() if job_id in self.jobs else None

        def reschedule_job(self, job_id, trigger):
            self.rescheduled.append(job_id)

    fake = FakeScheduler()
    monkeypatch.setattr(scheduler, "scheduler", fake)
    scheduler.reschedule_time_jobs()
    scheduler.reschedule_time_jobs("evening_message", "weekly_review")
    assert fake.rescheduled == ["evening_message", "evening_message"]
