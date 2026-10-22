from freezegun import freeze_time

from utils.datetime import format_now_human


@freeze_time("2026-09-27 00:15:00")  # UTC instant; Australia/Brisbane is a fixed UTC+10, no DST
def test_format_now_human_matches_frozen_time(monkeypatch):
    from agent.settings import settings

    monkeypatch.setattr(settings, "timezone", "Australia/Brisbane")
    assert format_now_human() == "10:15 AM on Sunday 27 September 2026"


@freeze_time("2026-01-01 12:00:00")
def test_format_now_human_accepts_explicit_tz():
    from zoneinfo import ZoneInfo

    assert format_now_human(ZoneInfo("UTC")) == "12:00 PM on Thursday 1 January 2026"
