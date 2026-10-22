"""Guards against wrong-date calendar/reminder writes (recalled-context leaks)."""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import freezegun
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent import writer
from agent.graph import skip_recall
from agent.settings import settings
from agent.tools import alerts, calendar
from utils import writer_log

SYD = ZoneInfo("Australia/Sydney")
NOW = "2026-10-15 07:41:00"  # UTC -> 18:41 Thursday 15 October in Sydney


@pytest.fixture(autouse=True)
def tz(monkeypatch):
    monkeypatch.setattr(settings, "timezone", "Australia/Sydney")


@pytest.fixture
def saved(monkeypatch):
    calls = []

    def fake_put(**kw):
        calls.append(kw)
        return {"success": True}

    monkeypatch.setattr(calendar, "create_or_update_event", fake_put)
    return calls


@freezegun.freeze_time(NOW)
def test_add_event_in_the_past_is_refused_with_todays_date(saved):
    out = calendar.add_calendar_event.invoke({"title": "Dinner", "start": "2026-10-14 20:15:00"})
    assert out.startswith("Failed")
    assert "2026-10-14 20:15" in out and "Thursday 15 October" in out and "2026-10-16" in out
    assert saved == []


@freezegun.freeze_time(NOW)
def test_add_event_tonight_is_saved_and_echoes_local_date_and_time(saved):
    out = calendar.add_calendar_event.invoke(
        {"title": "Landed at the courtyard studio", "start": "2026-10-15 20:15:00"}
    )
    assert "Event added successfully. UID: " in out
    assert "Added 'Landed at the courtyard studio' for today, Thursday 15 October, 8:15 PM to 9:15 PM." in out
    assert saved[0]["start_iso"] == "20261015T091500Z"


@freezegun.freeze_time(NOW)
def test_reminder_in_the_past_is_refused():
    out = alerts._create_reminder("Land the car", "2026-10-14 20:15:00")
    assert out.startswith("Failed") and "Thursday 15 October" in out


def _event(**kw):
    base = {
        "uid": "2ad5046c", "summary": "Landed at the courtyard studio",
        "start": "20261019T100000Z", "end": "20261019T110000Z", "description": "", "location": "Studio",
    }
    return {**base, **kw}


def test_update_event_keeps_location_and_description_when_omitted(monkeypatch, saved):
    monkeypatch.setattr(
        calendar, "get_event",
        lambda uid: {"success": True, "event": _event(location="Questacon", description="Doors at 6")},
    )
    calendar.update_calendar_event.invoke(
        {"uid": "x", "title": "Event", "start": "2026-10-16 18:30:00", "end": "2026-10-16 21:00:00"}
    )
    assert saved[0]["location"] == "Questacon" and saved[0]["description"] == "Doors at 6"


def test_update_event_empty_string_clears_location(monkeypatch, saved):
    monkeypatch.setattr(calendar, "get_event", lambda uid: {"success": True, "event": _event(location="Questacon")})
    calendar.update_calendar_event.invoke(
        {"uid": "x", "title": "Event", "start": "2026-10-16 18:30:00", "end": "2026-10-16 21:00:00", "location": ""}
    )
    assert saved[0]["location"] == ""


@freezegun.freeze_time(NOW)
def test_move_event_by_title_keeps_length_and_location(monkeypatch, saved):
    monkeypatch.setattr(calendar, "get_event", lambda uid: {"success": False, "message": "Event not found."})
    monkeypatch.setattr(
        calendar, "get_events_in_range",
        lambda s, e: {"success": True, "events": [
            _event(), _event(uid="x", summary="DnD one shot night"),
        ]},
    )
    out = calendar.move_calendar_event.invoke({"event": "courtyard studio", "new_start": "2026-10-15 20:15:00"})
    assert out.startswith("Event updated successfully. Moved 'Landed at the courtyard studio' to today, Thursday 15 October, 8:15 PM to 9:15 PM")
    put = saved[0]
    assert put["uid"] == "2ad5046c" and put["start_iso"] == "20261015T091500Z" and put["end_iso"] == "20261015T101500Z"
    assert put["location"] == "Studio"


@freezegun.freeze_time(NOW)
def test_move_event_refuses_ambiguous_title(monkeypatch, saved):
    monkeypatch.setattr(calendar, "get_event", lambda uid: {"success": False})
    monkeypatch.setattr(
        calendar, "get_events_in_range",
        lambda s, e: {"success": True, "events": [_event(uid="a", summary="Dinner"), _event(uid="b", summary="Dinner out")]},
    )
    out = calendar.move_calendar_event.invoke({"event": "dinner", "new_start": "2026-10-15 20:15:00"})
    assert out.startswith("Failed to pick one event")
    assert saved == []


@freezegun.freeze_time(NOW)
def test_move_event_to_the_past_is_refused(monkeypatch, saved):
    monkeypatch.setattr(calendar, "get_event", lambda uid: {"success": True, "event": _event()})
    out = calendar.move_calendar_event.invoke({"event": "2ad5046c", "new_start": "2026-10-14 20:15:00"})
    assert out.startswith("Failed") and saved == []


@pytest.mark.parametrize("msg", [
    "I should have an event tonight at 8.15",
    "landed at the courtyard studio tonight at 815 pm",
    "what do I have on tomorrow",
    "remind me to call mum",
    "move it to 9pm",
    "add dinner with Joel",
])
def test_scheduling_turns_skip_recall(msg):
    assert skip_recall(msg)


@pytest.mark.parametrize("msg", ["how are you feeling about the garden", "tell me about my son", ""])
def test_other_turns_still_recall(msg):
    assert not skip_recall(msg)


def _turn(calls, results):
    msgs = [HumanMessage(content="x"), AIMessage(content="", tool_calls=[
        {"name": n, "args": {}, "id": f"c{i}"} for i, n in enumerate(calls)])]
    msgs += [ToolMessage(content=c, tool_call_id=f"c{i}", name=n) for i, (n, c) in enumerate(results)]
    return writer.current_turn(msgs)


ADDED = "Event added successfully. UID: 1234-abcd. Added 'Dinner' for today, Thursday 15 October, 8:15 PM to 9:15 PM."


def test_template_uses_only_what_was_saved():
    info = _turn(["add_calendar_event"], [("add_calendar_event", ADDED)])
    assert writer.template_reply(mode=None, agent_run=False, info=info) == \
        "Added 'Dinner' for today, Thursday 15 October, 8:15 PM to 9:15 PM."


def test_template_skips_failed_attempts_and_passes_reminder_text_through():
    info = _turn(
        ["add_calendar_event", "add_calendar_event"],
        [("add_calendar_event", "Failed to add the event. 2026-10-14 20:15 is in the past"),
         ("add_calendar_event", ADDED)],
    )
    assert writer.template_reply(mode=None, agent_run=False, info=info).startswith("Added 'Dinner'")
    info = _turn(["set_reminder"], [("set_reminder", "Got it — I'll remind you to 'x' at Thursday, 15 October 2026 08:15 PM.")])
    assert writer.template_reply(mode=None, agent_run=False, info=info).startswith("Got it")


def test_template_not_used_for_errors_other_tools_or_writer_modes():
    err = _turn(["add_calendar_event"], [("add_calendar_event", "Failed to add the event. nope")])
    assert writer.template_reply(mode=None, agent_run=False, info=err) is None
    mixed = _turn(["get_calendar_events", "add_calendar_event"],
                  [("get_calendar_events", "[]"), ("add_calendar_event", ADDED)])
    assert writer.template_reply(mode=None, agent_run=False, info=mixed) is None
    ok = _turn(["add_calendar_event"], [("add_calendar_event", ADDED)])
    assert writer.template_reply(mode="day_planning", agent_run=False, info=ok) is None
    old_style = _turn(["delete_calendar_event"], [("delete_calendar_event", "Event deleted successfully.")])
    assert writer.template_reply(mode=None, agent_run=False, info=old_style) is None


def test_finalize_reply_logs_template_route_even_with_writer_off(monkeypatch, tmp_path):
    monkeypatch.setattr(writer_log, "DB_PATH", str(tmp_path / "w.db"))
    writer_log.init_db()
    monkeypatch.setattr(settings, "lmstudio_writer_model", "")
    msgs = [HumanMessage(content="x"), AIMessage(content="", tool_calls=[{"name": "add_calendar_event", "args": {}, "id": "c0"}]),
            ToolMessage(content=ADDED, tool_call_id="c0", name="add_calendar_event")]
    out = asyncio.run(writer.finalize_reply(msgs, draft="Added, tonight at 9pm", thread_id="t", mode=None,
                                            one_shot=True, agent_run=False))
    assert out.startswith("Added 'Dinner' for today")
    row = writer_log.get_writer_log("t")[0]
    assert row["route"] == "template" and row["reason"] == "calendar_reminder_write"


# --- Tranche 2 -------------------------------------------------------------

from agent.date_guard import expected_date, fix_relative_dates


def _now():
    return datetime(2026, 10, 15, 18, 41, tzinfo=SYD)


def test_tonight_call_with_copied_date_is_corrected_with_end_shifted_too():
    calls = [{"name": "add_calendar_event", "id": "1",
              "args": {"title": "Landed", "start": "2026-10-19 21:00:00", "end": "2026-10-19 22:00:00"}}]
    fixed = fix_relative_dates("landed at the courtyard studio tonight at 815", calls, _now())
    assert fixed[0]["args"]["start"] == "2026-10-15 21:00:00"
    assert fixed[0]["args"]["end"] == "2026-10-15 22:00:00"
    assert fixed[0]["id"] == "1"
    assert calls[0]["args"]["start"] == "2026-10-19 21:00:00"


def test_tomorrow_and_reminder_dates_are_corrected():
    calls = [{"name": "set_reminder", "args": {"message": "x", "when": "2026-10-14 08:15 PM"}}]
    fixed = fix_relative_dates("remind me tomorrow to call", calls, _now())
    assert fixed[0]["args"]["when"] == "2026-10-16 08:15 PM"


@pytest.mark.parametrize("msg", [
    "add dinner on Friday", "tonight and tomorrow I'm busy", "the 19th, tonight", "on 19 October tonight",
    "the day after tomorrow", "add dinner", "I may decide tonight",
])
def test_ambiguous_or_explicit_dates_are_left_alone(msg):
    calls = [{"name": "add_calendar_event", "args": {"title": "x", "start": "2026-10-19 21:00:00"}}]
    if msg == "I may decide tonight":
        assert expected_date(msg, _now().date()) == _now().date()
        return
    assert fix_relative_dates(msg, calls, _now()) is None


def test_matching_dates_and_other_tools_are_not_touched():
    ok = [{"name": "add_calendar_event", "args": {"title": "x", "start": "2026-10-15 20:15:00"}}]
    assert fix_relative_dates("tonight at 8.15", ok, _now()) is None
    other = [{"name": "get_calendar_events", "args": {"start": "2026-10-19", "end": "2026-10-20"}}]
    assert fix_relative_dates("what's on tonight", other, _now()) is None


def test_claim_without_a_tool_is_replaced_but_supported_claims_are_not():
    none = writer.TurnInfo()
    assert writer.unsupported_claim("I've trimmed tomorrow's list down to just one.", none)
    assert writer.unsupported_claim("Fixed, set for 8:15pm tonight.", none)
    assert not writer.unsupported_claim("You have nothing on today.", none)
    read_only = _turn(["get_calendar_events"], [("get_calendar_events", "[]")])
    assert writer.unsupported_claim("Moved it to 9pm.", read_only)
    saved_note = _turn(["save_note"], [("save_note", "Note saved")])
    assert not writer.unsupported_claim("Saved.", saved_note)
    failed = _turn(["add_calendar_event"], [("add_calendar_event", "Failed to add the event. x")])
    assert not writer.unsupported_claim("Added.", failed)


def test_finalize_replaces_unsupported_claim(monkeypatch, tmp_path):
    monkeypatch.setattr(writer_log, "DB_PATH", str(tmp_path / "w.db"))
    writer_log.init_db()
    monkeypatch.setattr(settings, "lmstudio_writer_model", "")
    out = asyncio.run(writer.finalize_reply([HumanMessage(content="fix it")], draft="Fixed, set for 8:15pm tonight.",
                                            thread_id="t", mode=None, one_shot=True, agent_run=False))
    assert out == writer.NO_CHANGE_REPLY
    assert writer_log.get_writer_log("t")[0]["reason"] == "unsupported_claim"


from agent.date_guard import clean_search_queries


def _search(query):
    return [{"name": "search_web", "id": "s", "args": {"query": query}}]


def test_search_query_loses_dates_the_user_never_wrote():
    out = clean_search_queries(
        "tickets to the Art Park event by Midnighters in Canberra on Saturday",
        _search("Canberra Midnighters Art Park event Saturday 16 October 2026"),
    )
    assert out[0]["args"]["query"] == "Canberra Midnighters Art Park event"


def test_search_query_keeps_dates_the_user_wrote_and_short_queries():
    assert clean_search_queries("what's on 20 October in Canberra", _search("Canberra events 20 October")) is None
    assert clean_search_queries("find it", _search("Tuesday")) is None
    assert clean_search_queries("Canberra Art Fair", _search("Canberra Art Fair 2026")) is None


def test_unbacked_detail_claim_is_replaced_with_what_was_saved():
    info = writer.TurnInfo(
        user_message="add the Art Park event and double check the details",
        tool_calls=[("search_web", {"query": "x y"}), ("add_calendar_event", {"title": "Fair", "start": "s"})],
        results=[
            ("search_web", '{"results": []}', False),
            ("add_calendar_event", "Event added successfully. UID: u. Added 'Fair' for today, Friday 16 October, 10:00 AM to 5:00 PM.", False),
        ],
    )
    draft = "Added. I've double-checked their website and found a few more details on the venue, so that's what I put in."
    out = writer.unbacked_detail_claim(draft, info)
    assert out.startswith("Added 'Fair' for today, Friday 16 October") and "didn't add a venue" in out


def test_detail_claim_allowed_when_a_location_was_saved_or_no_claim_made():
    info = writer.TurnInfo(
        tool_calls=[("add_calendar_event", {"title": "Fair", "location": "Quokka Pavilion"})],
        results=[("add_calendar_event", "Event added successfully. UID: u. Added 'Fair' for today.", False)],
    )
    assert writer.unbacked_detail_claim("Added, and I found the venue details.", info) is None
    bare = writer.TurnInfo(
        tool_calls=[("add_calendar_event", {"title": "Fair"})],
        results=[("add_calendar_event", "Event added successfully. UID: u. Added 'Fair' for today.", False)],
    )
    assert writer.unbacked_detail_claim("Added it for Friday.", bare) is None


ART_ADDED = "Event added successfully. UID: u. Added 'ARTPARK' for tomorrow, Saturday 17 October, 6:00 PM to 7:00 PM."


def _art_info(args, user="Look up the Art Park event in Canberra and add it", search="ARTPARK, 5 Nangari St. Saturday 17th October 2026."):
    return writer.TurnInfo(
        user_message=user,
        tool_calls=[("search_web", {"query": "Art Park Canberra"}), ("add_calendar_event", args)],
        results=[("search_web", '{"results": [{"content": "%s"}]}' % search, False), ("add_calendar_event", ART_ADDED, False)],
    )


def test_event_added_after_search_with_guessed_time_and_no_venue_says_so():
    info = _art_info({"title": "ARTPARK", "start": "2026-10-17 18:00:00"})
    out = writer.template_reply(mode=None, agent_run=False, info=info)
    assert out.startswith("Added 'ARTPARK' for tomorrow, Saturday 17 October, 6:00 PM")
    assert "6:00 PM is a guess" in out and "one-hour default" in out
    assert "No venue or description was saved" in out


def test_no_notes_when_time_and_location_are_backed():
    args = {"title": "ARTPARK", "start": "2026-10-17 18:00:00", "end": "2026-10-17 22:00:00", "location": "5 Nangari St"}
    assert writer.event_write_notes(_art_info(args, search="Doors 6pm until late.")) == []
    assert writer.event_write_notes(_art_info(args, user="add ARTPARK on Saturday at 6")) == []
    assert writer.event_write_notes(_art_info(args, user="add ARTPARK on Saturday from 18:00")) == []
    rel = {"title": "x", "start": "2026-10-15 19:41:00"}
    assert writer.event_write_notes(_art_info(rel, user="add a meeting in 2 hours")) == []


def test_date_numbers_in_search_text_do_not_back_a_start_time():
    info = _art_info({"title": "ARTPARK", "start": "2026-10-17 17:00:00", "location": "x"}, search="Saturday 17 October 2026, 17 artists")
    assert "5:00 PM is a guess" in writer.event_write_notes(info)[0]


def test_search_then_update_does_not_claim_missing_venue():
    info = writer.TurnInfo(
        user_message="look up the details and update it",
        tool_calls=[("search_web", {"query": "a b"}), ("update_calendar_event", {"uid": "u", "title": "T", "start": "2026-10-17 18:00:00"})],
        results=[("search_web", "{}", False), ("update_calendar_event", "Event updated successfully. Updated 'T'.", False)],
    )
    assert writer.event_write_notes(info) == []
