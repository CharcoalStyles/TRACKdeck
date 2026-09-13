import utils.reminders_store as reminders_store


def _use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(reminders_store, "DB_PATH", str(tmp_path / "reminders.db"))
    reminders_store.init_db()


def test_list_pending_calendar_linked_excludes_non_alarm_event_links(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    # Simulates agent/tools/planning.py's generate_schedule_blocks: links a
    # reminder to a calendar event for association only, not because it
    # mirrors that event's native alarm.
    reminders_store.create_reminder("block-reminder", "Break's over", 1000, "evt-block")

    # Simulates jobs/calendar_sync.py mirroring a real VALARM.
    reminders_store.upsert_calendar_reminder("evt-alarm", "Upcoming: Dentist", 2000)

    linked = reminders_store.list_pending_calendar_linked()

    assert [r["event_uid"] for r in linked] == ["evt-alarm"]


def test_upsert_calendar_reminder_marks_alarm_derived_on_update(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    reminders_store.upsert_calendar_reminder("evt-alarm", "Upcoming: Dentist", 2000)
    reminders_store.upsert_calendar_reminder("evt-alarm", "Upcoming: Dentist", 3000)

    linked = reminders_store.list_pending_calendar_linked()
    assert len(linked) == 1
    assert linked[0]["due_at"] == 3000
