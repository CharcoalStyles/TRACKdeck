from agent.tools.calendar import _inclusive_end


def test_bare_date_end_covers_whole_day():
    assert _inclusive_end("2026-10-19") == "2026-10-20"
    assert _inclusive_end(" 2026-12-31 ") == "2027-01-01"


def test_timed_end_is_untouched():
    assert _inclusive_end("2026-10-19 17:00:00") == "2026-10-19 17:00:00"
