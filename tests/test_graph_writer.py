"""build_graph + a scripted fake tool model + a mocked writer model."""
import asyncio
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver

from agent import graph as graph_mod
from agent import writer
from agent.settings import settings
from utils import writer_log


class FakeToolModel:
    def __init__(self, replies):
        self.replies = list(replies)
        self.bound_tool_names = []
        self.bound_models = []
        self.seen = []

    def bind_tools(self, tools):
        clone = FakeToolModel([])
        clone.parent = self
        clone.names = [t.name for t in tools]
        return clone

    def bind(self, **kw):
        root = getattr(self, "parent", self)
        root.bound_models.append(kw.get("model"))
        return self

    async def ainvoke(self, messages):
        root = getattr(self, "parent", self)
        root.bound_tool_names.append(self.names)
        root.seen.append(messages)
        return root.replies.pop(0)


@tool
def echo_note(content: str) -> str:
    """Pretend to save a note."""
    return f"saved: {content}"


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "llm_provider", "lmstudio")
    monkeypatch.setattr(settings, "lmstudio_chat_model", "lfm-test")
    monkeypatch.setattr(settings, "lmstudio_writer_model", "gemma-test")
    monkeypatch.setattr(settings, "tool_router_enabled", False)
    monkeypatch.setattr(settings, "tool_suggestion_enabled", False)
    monkeypatch.setattr(writer_log, "DB_PATH", str(tmp_path / "w.db"))
    writer_log.init_db()

    async def budget(model=None):
        return 16000

    monkeypatch.setattr(graph_mod, "get_history_budget_tokens", budget)
    monkeypatch.setattr(graph_mod, "log_recall", lambda *a, **k: None)
    memory = MagicMock()
    memory.search_conversations.return_value = []

    state = {"writer_calls": [], "writer_reply": "Gemma says hello, at some length.", "memory": memory}

    async def fake_writer(messages, temperature, timeout, surface=None):
        state["writer_calls"].append(messages)
        return state["writer_reply"]

    monkeypatch.setattr(writer, "_invoke", fake_writer)

    def make(replies, mcp_tools=None):
        fake = FakeToolModel(replies)
        monkeypatch.setattr(graph_mod, "get_chat_llm", lambda temperature=0.7, provider=None: fake)
        return fake, graph_mod.build_graph(MemorySaver(), memory, mcp_tools=mcp_tools)

    return make, state


def invoke(g, text, thread="t1", **cfg):
    config = {"configurable": {"thread_id": thread, **cfg}}
    return asyncio.run(g.ainvoke({"messages": [{"role": "user", "content": text}]}, config=config))


def test_profile_chat_reply_comes_from_writer_and_tools_are_narrowed(env):
    make, state = env
    fake, g = make([AIMessage(content="ok")])
    result = invoke(g, "what do you know about me", mode="profile_chat")
    last = result["messages"][-1]
    assert last.content == state["writer_reply"]
    assert last.additional_kwargs[writer.WRITER_FLAG] is True
    assert len([m for m in result["messages"] if m.type == "ai"]) == 1
    names = set(fake.bound_tool_names[0])
    assert "read_about_me" in names and "remember_about_me" in names
    assert "set_reminder" not in names and "get_current_weather" not in names


def test_default_mode_keeps_full_tool_list(env):
    make, _ = env
    fake, g = make([AIMessage(content="ok")])
    invoke(g, "hello", one_shot=True)
    assert "set_reminder" in fake.bound_tool_names[0]


def test_one_shot_plain_reply_not_rewritten(env):
    make, state = env
    _, g = make([AIMessage(content="Hi there.")])
    result = invoke(g, "hello", one_shot=True)
    assert result["messages"][-1].content == "Hi there."
    assert state["writer_calls"] == []


def test_writer_off_leaves_everything_alone(env, monkeypatch):
    make, state = env
    monkeypatch.setattr(settings, "lmstudio_writer_model", "")
    _, g = make([AIMessage(content="ok")])
    result = invoke(g, "what do you know about me", mode="profile_chat")
    assert result["messages"][-1].content == "ok"
    assert state["writer_calls"] == []


def test_tool_model_sees_shortened_writer_history(env):
    make, state = env
    state["writer_reply"] = "First sentence. " + "Lots more prose here. " * 40
    fake, g = make([AIMessage(content="a"), AIMessage(content="b")])
    invoke(g, "first question", mode="profile_chat")
    invoke(g, "second question", mode="profile_chat")
    second_call_msgs = fake.seen[1]
    prior_ai = [m for m in second_call_msgs if m.type == "ai"]
    assert prior_ai and len(prior_ai[0].content) <= writer.TOOL_VIEW_MAX_CHARS + 3
    # the writer itself still gets the full stored text
    writer_history = [m for m in state["writer_calls"][1] if m.type == "ai"]
    assert len(writer_history[0].content) > writer.TOOL_VIEW_MAX_CHARS * 2


def test_note_argument_rewrite_is_execution_only(env, monkeypatch):
    make, state = env
    monkeypatch.setitem(writer.NOTE_CONTENT_FIELDS, "echo_note", "content")
    original = "Oil changed at 120000 km on 2026-03-01 by [[Bob]]. " * 12
    tidied = original.replace("Oil changed", "Oil change done")
    state["writer_reply"] = tidied
    call = AIMessage(content="", tool_calls=[{"name": "echo_note", "args": {"content": original}, "id": "c1"}])
    _, g = make([call, AIMessage(content="Saved it.")], mcp_tools=[echo_note])
    result = invoke(g, "save this note", one_shot=True)
    tool_msg = next(m for m in result["messages"] if m.type == "tool")
    assert tool_msg.content == f"saved: {tidied}"
    stored_call = next(m for m in result["messages"] if m.type == "ai" and m.tool_calls)
    assert stored_call.tool_calls[0]["args"]["content"] == original
    assert result["messages"][-1].content == "Saved it."  # one_shot confirmation kept


def test_per_mode_models_are_used(env, monkeypatch):
    import json

    make, state = env
    monkeypatch.setattr(settings, "model_assignments", json.dumps(
        {"profile_chat": {"tool": "tool-override"}, "onboarding": {"writer": "@tool"}}))
    fake, g = make([AIMessage(content="ok")])
    invoke(g, "what do you know about me", mode="profile_chat")
    assert fake.bound_models == ["tool-override"]
    assert len(state["writer_calls"]) == 1

    fake, g = make([AIMessage(content="Hello, what's your name?")])
    result = invoke(g, "hi", thread="onboarding", mode="onboarding")
    assert fake.bound_models == ["lfm-test"]
    assert result["messages"][-1].content == "Hello, what's your name?"
    assert len(state["writer_calls"]) == 1  # no new writer call for onboarding


def test_mode_tool_names_exist():
    from agent.tools.all_tools import get_tools

    known = {t.name for t in get_tools(MagicMock())}
    mcp_only = {"search_web"}  # comes from the MCP search server, not get_tools()
    for mode_key, names in graph_mod.MODE_TOOL_NAMES.items():
        missing = set(names) - known - mcp_only
        assert not missing, f"{mode_key}: unknown tools {missing}"


def test_tonight_event_skips_recall_fixes_copied_date_and_replies_from_the_result(env, monkeypatch):
    import freezegun
    from agent.tools import calendar as cal

    make, state = env
    monkeypatch.setattr(settings, "timezone", "Australia/Sydney")
    puts = []
    monkeypatch.setattr(cal, "create_or_update_event", lambda **kw: puts.append(kw) or {"success": True})
    bad_call = AIMessage(content="", tool_calls=[{
        "name": "add_calendar_event", "id": "c1",
        "args": {"title": "Landed at the courtyard studio", "start": "2026-10-19 20:15:00"},
    }])
    _, g = make([bad_call, AIMessage(content="Added, tonight at 9pm")])
    with freezegun.freeze_time("2026-10-15 07:41:00"):
        result = invoke(g, "landed at the courtyard studio tonight at 8.15", one_shot=True)
    assert state["memory"].search_conversations.call_count == 0
    assert puts[0]["start_iso"] == "20261015T091500Z"
    assert result["messages"][-1].content == "Added 'Landed at the courtyard studio' for today, Thursday 15 October, 8:15 PM to 9:15 PM."
    assert state["writer_calls"] == []


def test_write_in_same_batch_as_a_lookup_is_held_back_until_the_next_step(env, monkeypatch):
    from agent.tools import calendar as cal

    make, _ = env
    monkeypatch.setattr(settings, "timezone", "Australia/Sydney")
    monkeypatch.setattr(cal, "get_event", lambda uid: {"success": True, "event": {"location": "Questacon"}})
    puts = []
    monkeypatch.setattr(cal, "create_or_update_event", lambda **kw: puts.append(kw) or {"success": True})

    @tool
    def search_web(query: str) -> str:
        """Pretend web search."""
        assert not puts, "the search must run before any write"
        return '{"results": [{"title": "Questacon After Dark"}]}'

    update_args = {
        "uid": "u1", "title": "Questacon After Dark",
        "start": "2099-10-16 18:30:00", "end": "2099-10-16 21:00:00",
    }
    batch = AIMessage(content="", tool_calls=[
        {"name": "search_web", "id": "s1", "args": {"query": "Questacon event"}},
        {"name": "update_calendar_event", "id": "u1", "args": update_args},
    ])
    retry = AIMessage(content="", tool_calls=[{"name": "update_calendar_event", "id": "u2", "args": update_args}])
    fake, g = make([batch, retry, AIMessage(content="Updated.")], mcp_tools=[search_web])

    result = invoke(g, "search the web for details and update the event", one_shot=True)

    tool_msgs = [m for m in result["messages"] if m.type == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == ["s1", "u1", "u2"]
    assert tool_msgs[0].content.startswith('{"results"')
    assert tool_msgs[1].content.startswith("Failed to run update_calendar_event yet")
    assert tool_msgs[2].content.startswith("Event updated successfully")
    assert len(puts) == 1 and puts[0]["location"] == "Questacon"


def test_defer_writes_after_lookup_only_when_both_are_present():
    calls = lambda *names: [{"name": n, "id": n, "args": {}} for n in names]
    run, held = graph_mod.defer_writes_after_lookup(calls("search_web", "get_calendar_event", "update_calendar_event", "save_note"))
    assert [c["name"] for c in run] == ["search_web", "get_calendar_event"]
    assert [c["name"] for c in held] == ["update_calendar_event", "save_note"]
    run, held = graph_mod.defer_writes_after_lookup(calls("add_calendar_event", "set_reminder"))
    assert len(run) == 2 and held == []
    run, held = graph_mod.defer_writes_after_lookup(calls("fetch_webpage", "get_current_datetime"))
    assert len(run) == 2 and held == []
