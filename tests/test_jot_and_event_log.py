import asyncio
from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from agent import runtime, writer
from agent.settings import settings
from agent.tools import jot
from agent.tools.all_tools import get_tools
from utils import daily_notes, event_log


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("EVENT_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(settings, "timezone", "UTC")
    return tmp_path


WHEN = datetime(2026, 10, 22, 14, 32, tzinfo=timezone.utc)


def test_captures_append_in_order_and_round_trip(env):
    a = daily_notes.append_capture(WHEN, "buy oat milk")
    b = daily_notes.append_capture(WHEN.replace(hour=15), "## ask Sam\nabout the\n- [ ] fake item ^zzz")
    caps = daily_notes.read_captures("2026-10-22")
    assert [c["id"] for c in caps] == [a, b]
    assert caps[0] == {"id": a, "time": "14:32", "text": "buy oat milk", "done": False}
    assert caps[1]["text"] == "## ask Sam about the - [ ] fake item ^zzz"
    text = daily_notes.daily_notes_file("2026-10-22").read_text()
    assert text.startswith("---\ntype: daily-notes\ndate: 2026-10-22\n---")
    body = [line for line in text.splitlines() if line.startswith("- [")]
    assert len(body) == 2 and f"^{a}" in body[0]


def test_empty_capture_refused(env):
    with pytest.raises(ValueError):
        daily_notes.append_capture(WHEN, "  \n ")


def test_event_log_appends_monthly_jsonl(env):
    event_log.log_event("interaction", source="text", user_text="héllo")
    event_log.log_event("edit", capture_id="x")
    month = datetime.now(settings.zoneinfo()).strftime("%Y-%m")
    events = event_log.read_events(month)
    assert [e["kind"] for e in events] == ["interaction", "edit"]
    assert events[0]["user_text"] == "héllo" and events[0]["ts"]


def test_event_log_never_raises(env, monkeypatch):
    monkeypatch.setenv("EVENT_LOG_DIR", "/proc/definitely/not/writable")
    event_log.log_event("interaction", source="text")


def test_jot_note_saves_the_raw_text_and_logs_provenance(env):
    out = jot.jot_note.invoke({}, config={"configurable": {"user_text": "call the dentist", "source": "voice"}})
    assert out == "Saved to today's captures."
    day = datetime.now(settings.zoneinfo()).strftime("%Y-%m-%d")
    assert daily_notes.read_captures(day)[0]["text"] == "call the dentist"
    ev = [e for e in event_log.read_events(day[:7]) if e["kind"] == "capture"][0]
    assert ev["source"] == "voice" and ev["via"] == "tool" and ev["capture_id"]


def test_jot_note_without_text_is_an_error(env):
    out = jot.jot_note.invoke({}, config={"configurable": {}})
    assert out.startswith("Error")


def test_jot_note_is_registered_with_no_arguments():
    tool = next(t for t in get_tools() if t.name == "jot_note")
    assert convert_to_openai_tool(tool)["function"]["parameters"].get("properties") == {}


def test_jot_note_reply_is_templated():
    info = writer.TurnInfo(
        user_message="note that the car needs a service",
        tool_calls=[("jot_note", {})],
        results=[("jot_note", "Saved to today's captures.", False)],
    )
    assert writer.template_reply(mode=None, info=info) == "Saved to today's captures."


class _FakeGraph:
    def __init__(self, messages):
        self.messages = messages
        self.config = None

    async def ainvoke(self, _input, config=None):
        self.config = config
        return {"messages": self.messages}


@pytest.fixture
def agent_env(env, monkeypatch):
    class _Mem:
        def save_conversation_summary(self, *a, **k):
            pass

    monkeypatch.setattr(runtime.app_state, "memory", _Mem())
    monkeypatch.setattr(runtime, "send_gotify", lambda *a, **k: None)
    return env


def _run(text, graph, **kw):
    runtime.app_state.graph = graph
    try:
        return asyncio.run(runtime.run_agent(text, thread_id="t1", **kw))
    finally:
        runtime.app_state.graph = None


def _day_month():
    day = datetime.now(settings.zoneinfo()).strftime("%Y-%m-%d")
    return day, day[:7]


def test_voice_turn_with_no_tool_is_captured(agent_env):
    graph = _FakeGraph([HumanMessage(content="remember the blue folder"), AIMessage(content="Sure, I'll remember that!")])
    result = _run("remember the blue folder", graph, source="voice")
    day, month = _day_month()
    assert result.reply == runtime.FALLBACK_CAPTURE_REPLY
    assert daily_notes.read_captures(day)[0]["text"] == "remember the blue folder"
    assert graph.config["configurable"]["user_text"] == "remember the blue folder"
    ev = [e for e in event_log.read_events(month) if e["kind"] == "interaction"][0]
    assert ev["source"] == "voice" and ev["fallback_capture"] is True and ev["tools"] == []


def test_typed_turn_with_no_tool_is_a_normal_chat_reply(agent_env):
    graph = _FakeGraph([HumanMessage(content="hi"), AIMessage(content="Hello!")])
    result = _run("hi", graph, source="text")
    day, month = _day_month()
    assert result.reply == "Hello!" and daily_notes.read_captures(day) == []
    ev = [e for e in event_log.read_events(month) if e["kind"] == "interaction"][0]
    assert ev["fallback_capture"] is False


def test_voice_turn_with_a_tool_is_not_captured(agent_env):
    call = {"name": "list_reminders", "args": {}, "id": "c1"}
    graph = _FakeGraph([
        HumanMessage(content="what reminders do I have"),
        AIMessage(content="", tool_calls=[call]),
        ToolMessage(content="None.", tool_call_id="c1", name="list_reminders"),
        AIMessage(content="You have none."),
    ])
    result = _run("what reminders do I have", graph, source="voice")
    day, month = _day_month()
    assert result.reply == "You have none." and daily_notes.read_captures(day) == []
    ev = [e for e in event_log.read_events(month) if e["kind"] == "interaction"][0]
    assert ev["tools"] == [{"name": "list_reminders", "args": {}, "result": "None.", "error": False}]


def test_ulid_is_26_chars_sortable_and_unique():
    a, b = event_log.new_ulid(), event_log.new_ulid()
    assert len(a) == 26 and set(a) <= set(event_log._CROCKFORD) and a != b
    time_before = event_log.new_ulid()
    import time as _t
    _t.sleep(0.01)
    assert event_log.new_ulid() > time_before


class _ToolishGraph(_FakeGraph):
    """Stands in for the graph: runs a body (as a tool would) mid-turn."""
    def __init__(self, messages, body=None, route=None):
        super().__init__(messages)
        self.body, self.route = body, route

    async def ainvoke(self, _input, config=None):
        if self.body:
            self.body()
        if self.route:
            event_log.note_reply_route(self.route)
        return await super().ainvoke(_input, config)


def test_interaction_carries_id_results_models_route_and_artifacts(agent_env, monkeypatch):
    monkeypatch.setattr(settings, "lmstudio_chat_model", "lfm-x")
    monkeypatch.setattr(settings, "lmstudio_writer_model", "gemma-y")
    call = {"name": "set_reminder", "args": {"message": "tea", "when": "2026-10-22 16:00"}, "id": "c1"}
    messages = [
        HumanMessage(content="remind me about tea at 4"),
        AIMessage(content="", tool_calls=[call]),
        ToolMessage(content="Got it — I'll remind you.", tool_call_id="c1", name="set_reminder"),
        AIMessage(content="Got it — I'll remind you."),
    ]
    body = lambda: event_log.note_artifact("reminder", "rem-1", "create", message="tea")
    result = _run("remind me about tea at 4", _ToolishGraph(messages, body, route="template"), source="text")
    day, month = _day_month()
    events = event_log.read_events(month)
    ix = [e for e in events if e["kind"] == "interaction"][0]
    art = [e for e in events if e["kind"] == "artifact"][0]
    assert len(ix["interaction_id"]) == 26 and art["origin_interaction_id"] == ix["interaction_id"]
    assert ix["artifacts"] == [{"type": "reminder", "id": "rem-1", "op": "create", "message": "tea"}]
    assert ix["tools"][0]["result"] == "Got it — I'll remind you." and ix["tools"][0]["error"] is False
    assert ix["models"] == {"tool": "lfm-x", "writer": "gemma-y"}
    assert ix["reply_by"] == "template" and ix["timezone"] == "UTC" and ix["ts"].endswith("+00:00")
    assert "prompt_version" in ix
    assert event_log.origin_of("reminder", "rem-1") == ix["interaction_id"]
    assert event_log.origin_of("reminder", "nope") is None
    assert event_log.current_interaction_id() is None


def test_reply_by_maps_routes(agent_env):
    for route, expected in [("tool_model", "lfm"), ("writer", "gemma"), ("fallback", "lfm"), (None, "lfm")]:
        _run("hi", _ToolishGraph([HumanMessage(content="hi"), AIMessage(content="Hello!")], route=route))
    by = [e["reply_by"] for e in event_log.read_events(_day_month()[1]) if e["kind"] == "interaction"]
    assert by == ["lfm", "gemma", "lfm", "lfm"]


def test_fallback_capture_origin_and_reply_by(agent_env):
    graph = _FakeGraph([HumanMessage(content="blue folder"), AIMessage(content="ok")])
    _run("blue folder", graph, source="voice")
    month = _day_month()[1]
    events = event_log.read_events(month)
    ix = [e for e in events if e["kind"] == "interaction"][0]
    cap = [e for e in events if e["kind"] == "capture"][0]
    assert ix["reply_by"] == "fallback"
    assert cap["origin_interaction_id"] == ix["interaction_id"]
    assert ix["artifacts"][0]["type"] == "capture" and ix["artifacts"][0]["id"] == cap["capture_id"]
    assert event_log.origin_of("capture", cap["capture_id"]) == ix["interaction_id"]


def test_add_calendar_event_notes_its_artifact(env, monkeypatch):
    from agent.tools import calendar
    monkeypatch.setattr(calendar, "create_or_update_event", lambda **kw: {"success": True})
    monkeypatch.setattr(calendar, "past_start_message", lambda *a, **k: None)
    ix = event_log.begin_interaction()
    try:
        out = calendar.add_calendar_event.invoke({"title": "Dentist", "start": "2099-01-05 10:00"})
    finally:
        event_log.end_interaction()
    uid = out.split("UID: ")[1].split(".")[0]
    assert ix.artifacts[0]["type"] == "calendar_event" and ix.artifacts[0]["id"] == uid
    assert event_log.origin_of("calendar_event", uid) == ix.id
