import asyncio

import pytest

from agent.settings import apply_persisted, settings
from utils import settings_store


@pytest.fixture
def settings_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "DB_PATH", str(tmp_path / "settings.db"))
    settings_store.init_db()
    for name in (
        "weekly_review_time", "monthly_review_timing", "monthly_review_evening_time",
        "monthly_review_morning_time", "daily_commentary", "weather_enabled",
        "calendar_sync_interval_minutes", "device_poll_interval_seconds", "email_to",
    ):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    return tmp_path


def test_response_model_exposes_the_v2_fields():
    import main

    fields = set(main.SettingsResponse.model_fields)
    assert {
        "weekly_review_time", "monthly_review_timing", "monthly_review_evening_time",
        "monthly_review_morning_time", "daily_commentary", "weather_enabled", "email_to",
        "calendar_sync_interval_minutes", "device_poll_interval_seconds",
    } <= fields
    assert set(main._current_settings()) == fields


def test_update_validates_the_new_fields():
    import main

    with pytest.raises(ValueError):
        main.SettingsUpdate(monthly_review_timing="whenever")
    with pytest.raises(ValueError):
        main.SettingsUpdate(weekly_review_time="25:00")
    with pytest.raises(ValueError):
        main.SettingsUpdate(calendar_sync_interval_minutes=0)
    with pytest.raises(ValueError):
        main.SettingsUpdate(device_poll_interval_seconds=5)


def test_update_applies_persists_and_reschedules(settings_env, monkeypatch):
    import main

    rescheduled = []
    monkeypatch.setattr(main, "reschedule_time_jobs", lambda *ids: rescheduled.append(ids))
    sync_calls = []
    monkeypatch.setattr(main.scheduler, "reschedule_job", lambda *a, **k: sync_calls.append(a))

    update = main.SettingsUpdate(
        weekly_review_time="18:30",
        monthly_review_timing="first_morning",
        daily_commentary=False,
        weather_enabled=False,
        calendar_sync_interval_minutes=15,
        device_poll_interval_seconds=600,
        email_to=" me@example.com ",
    )
    asyncio.run(main._apply_settings_update(update))

    assert settings.weekly_review_time == "18:30"
    assert settings.daily_commentary is False and settings.weather_enabled is False
    assert settings.email_to == "me@example.com"
    assert set(rescheduled[0]) == {"weekly_review", "monthly_review"}
    assert sync_calls and sync_calls[0][0] == "calendar_reminder_sync"

    stored = settings_store.load_all()
    assert stored["weekly_review_time"] == "18:30"
    assert stored["daily_commentary"] == "0"
    assert stored["monthly_review_timing"] == "first_morning"

    settings.daily_commentary = True
    settings.weekly_review_time = "00:00"
    apply_persisted(stored)
    assert settings.weekly_review_time == "18:30"
    assert settings.daily_commentary is False


def test_morning_checkin_start_and_wake_time_are_independent(settings_env, monkeypatch):
    import main

    for name in ("wake_time", "morning_time", "checkin_start_time"):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    rescheduled = []
    monkeypatch.setattr(main, "reschedule_time_jobs", lambda *ids: rescheduled.append(set(ids)))

    asyncio.run(main._apply_settings_update(main.SettingsUpdate(checkin_start_time="09:30")))
    assert rescheduled == [{"day_start"}]
    assert settings.morning_time != "09:30"

    asyncio.run(main._apply_settings_update(main.SettingsUpdate(morning_time="06:45", wake_time="06:00")))
    assert rescheduled[1] == {"morning_message", "morning_podcast"}
    assert (settings.morning_time, settings.checkin_start_time, settings.wake_time) == ("06:45", "09:30", "06:00")

    with pytest.raises(ValueError):
        main.SettingsUpdate(checkin_start_time="25:00")


def test_split_times_inherit_wake_time_until_saved(monkeypatch):
    for name in ("wake_time", "morning_time", "checkin_start_time"):
        monkeypatch.setattr(settings, name, getattr(settings, name))

    apply_persisted({"wake_time": "06:15"})
    assert (settings.morning_time, settings.checkin_start_time) == ("06:15", "06:15")

    apply_persisted({"wake_time": "06:15", "morning_time": "07:30", "checkin_start_time": "10:00"})
    assert (settings.morning_time, settings.checkin_start_time) == ("07:30", "10:00")
