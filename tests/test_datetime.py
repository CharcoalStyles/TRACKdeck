from utils.datetime import text_to_utc


def test_text_to_utc_iso_format():
    assert text_to_utc("2026-07-10 15:00:00", "Australia/Canberra") == "20260710T050000Z"


def test_text_to_utc_iso_with_t_separator():
    assert text_to_utc("2026-07-10T15:00:00", "Australia/Canberra") == "20260710T050000Z"


def test_text_to_utc_12_hour_pm_matches_equivalent_24_hour():
    # Regression test: stripping " PM" without adjusting the hour used to
    # silently produce a time 12 hours off (3:00 PM parsed as 03:00).
    assert text_to_utc("2026-07-10 3:00 PM", "Australia/Canberra") == text_to_utc(
        "2026-07-10 15:00:00", "Australia/Canberra"
    )


def test_text_to_utc_12_hour_am_matches_equivalent_24_hour():
    assert text_to_utc("2026-07-10 3:00 AM", "Australia/Canberra") == text_to_utc(
        "2026-07-10 03:00:00", "Australia/Canberra"
    )


def test_text_to_utc_12_hour_with_seconds():
    assert text_to_utc("2026-07-10 3:00:05 PM", "Australia/Canberra") == "20260710T050005Z"


def test_text_to_utc_falls_back_to_settings_timezone(monkeypatch):
    from agent.settings import settings

    monkeypatch.setattr(settings, "timezone", "Australia/Canberra")
    assert text_to_utc("2026-07-10 15:00:00") == "20260710T050000Z"
