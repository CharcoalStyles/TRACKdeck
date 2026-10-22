from datetime import date

from jobs import digest
from utils import vault


def _daily(tmp_path, day: str, body: str, tags=None):
    note = vault.Note(
        id=f"d-{day}",
        title=f"Daily Digest {day}",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
        tags=[vault.DAILY_NOTE_TAG] if tags is None else tags,
        body=body,
    )
    vault.write_note_atomic(tmp_path / f"daily-{day}.md", vault.serialize_note(note))


def test_previous_recaps_oldest_first_skipping_gaps_and_today(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _daily(tmp_path, "2026-10-04", "Went for a walk.")
    _daily(tmp_path, "2026-10-06", "Worked on the router.")
    _daily(tmp_path, "2026-10-07", "TODAY must not appear.")

    recaps = digest._load_previous_recaps(date(2026, 10, 7))

    assert len(recaps) == 2
    assert recaps[0].startswith("[Sunday 04 October 2026]") and "Went for a walk." in recaps[0]
    assert recaps[1].startswith("[Tuesday 06 October 2026]")
    assert not any("TODAY" in r for r in recaps)


def test_previous_recaps_ignores_non_digest_notes_and_old_days(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _daily(tmp_path, "2026-10-06", "Not a digest.", tags=["other"])
    _daily(tmp_path, "2026-09-01", "Too old.")

    assert digest._load_previous_recaps(date(2026, 10, 7)) == []


def test_previous_recaps_truncates_long_bodies(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _daily(tmp_path, "2026-10-06", "x" * 5000)

    (recap,) = digest._load_previous_recaps(date(2026, 10, 7))

    assert len(recap) < digest.HISTORY_MAX_CHARS_PER_DAY + 60 and recap.endswith("...")


def test_prompt_formats_with_all_slots():
    out = digest.DIGEST_PROMPT.format(entries="e", history="h", reflections="r")
    assert "{" not in out
