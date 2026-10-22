import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from agent import writer
from agent.settings import settings
from utils import writer_log


def run(coro):
    return asyncio.run(coro)


def info_for(*calls, errors=()):
    info = writer.TurnInfo(user_message="hi")
    for name in calls:
        info.tool_calls.append((name, {}))
        info.results.append((name, "ok", name in errors))
    return info


def d(draft="Done.", *, mode=None, one_shot=False, agent_run=False, info=None):
    return writer.decide(mode=mode, one_shot=one_shot, agent_run=agent_run, info=info or info_for(), draft=draft)


# --- Rule A ----------------------------------------------------------------

def test_empty_draft_goes_to_writer_even_in_one_shot():
    assert d("  ", one_shot=True, info=info_for("set_reminder")) == (True, "empty_draft")


def test_unresolved_error_goes_to_writer():
    assert d(info=info_for("add_calendar_event", errors={"add_calendar_event"}), one_shot=True) == (True, "tool_error")


def test_error_later_resolved_by_retry_does_not_count():
    info = writer.TurnInfo()
    info.tool_calls = [("add_calendar_event", {}), ("add_calendar_event", {})]
    info.results = [("add_calendar_event", "Failed to add event.", True), ("add_calendar_event", "ok", False)]
    assert d(info=info) == (False, "short_draft")


@pytest.mark.parametrize("tool_name", ["generate_schedule_blocks", "get_reflection_prompt", "fetch_webpage"])
def test_prose_tools_go_to_writer(tool_name):
    assert d(info=info_for(tool_name), one_shot=True) == (True, "prose_tool")


@pytest.mark.parametrize("mode", ["onboarding", "profile_chat", "day_planning", "project_chat"])
def test_always_writer_modes(mode):
    assert d("Got it.", mode=mode, info=info_for("remember_about_me")) == (True, f"mode:{mode}")


def test_agent_run_goes_to_writer():
    assert d(mode="project_chat", agent_run=True) == (True, "mode:agent_run")


def test_one_shot_keeps_draft():
    assert d("Set.", one_shot=True, info=info_for("set_reminder")) == (False, "one_shot")
    assert d("A" * 900, one_shot=True) == (False, "one_shot")


def test_plain_conversation_goes_to_writer():
    assert d("Sure, here's what I think...") == (True, "conversation")


def test_short_confirmation_kept_long_one_rewritten():
    info = info_for("set_reminder")
    assert d("Reminder set for 3pm.", info=info) == (False, "short_draft")
    assert d("x" * 300, info=info) == (True, "long_draft")


def test_data_tool_has_larger_limit():
    info = info_for("get_todays_events")
    assert d("x" * 400, info=info) == (False, "short_draft")
    assert d("x" * 600, info=info) == (True, "long_draft")


def test_remember_about_me_next_to_a_real_answer_is_long_draft():
    assert d("x" * 600, info=info_for("remember_about_me", "get_current_weather"))[0] is True


# --- helpers ----------------------------------------------------------------

def test_is_error_result():
    assert writer.is_error_result(ToolMessage(content="Failed to add event. nope", tool_call_id="1"))
    assert writer.is_error_result(ToolMessage(content="No note found with id 'x'.", tool_call_id="1"))
    assert writer.is_error_result(ToolMessage(content="boom", tool_call_id="1", status="error"))
    assert not writer.is_error_result(ToolMessage(content="No matching notes found.", tool_call_id="1"))
    assert not writer.is_error_result(ToolMessage(content="Event added successfully.", tool_call_id="1"))


def test_current_turn_collects_calls_and_results():
    msgs = [
        HumanMessage(content="old"),
        AIMessage(content="old reply"),
        HumanMessage(content="remind me"),
        AIMessage(content="", tool_calls=[{"name": "set_reminder", "args": {"m": "x"}, "id": "c1"}]),
        ToolMessage(content="Failed to set", tool_call_id="c1"),
    ]
    info = writer.current_turn(msgs)
    assert info.user_message == "remind me"
    assert info.tool_names == ["set_reminder"]
    assert info.unresolved_errors == ["set_reminder"]


def test_shorten_and_tool_model_view():
    long = "First sentence here. " + "More words. " * 60
    short = writer.shorten_for_tool_model(long)
    assert len(short) <= writer.TOOL_VIEW_MAX_CHARS + 3 and short.endswith("…")
    assert writer.shorten_for_tool_model("tiny") == "tiny"
    flagged = AIMessage(content=long, additional_kwargs={writer.WRITER_FLAG: True})
    plain = AIMessage(content=long)
    out = writer.tool_model_view([flagged, plain])
    assert out[0].content == short
    assert out[1].content == long
    assert flagged.content == long  # original untouched


def test_valid_rewrite_tidy_keeps_anchors():
    orig = "Meeting 3:30 on 12/10 at https://x.example/a with [[Bob]]. " * 8
    assert writer.valid_rewrite(orig, orig.replace("Meeting", "Mtg"), compose=False)
    assert not writer.valid_rewrite(orig, orig.replace("3:30", "4:30"), compose=False)
    assert not writer.valid_rewrite(orig, orig.replace("[[Bob]]", "Bob"), compose=False)
    assert not writer.valid_rewrite(orig, "short", compose=False)
    assert not writer.valid_rewrite(orig, "", compose=False)


def test_valid_rewrite_compose_must_not_shrink_or_drop_urls():
    orig = "Outline see https://a.example/x"
    assert writer.valid_rewrite(orig, "A full note. https://a.example/x and a lot more detail here", compose=True)
    assert not writer.valid_rewrite(orig, "A full note with no link and plenty of words in it", compose=True)


# --- finalize_reply / rewrite_tool_calls (writer model mocked) --------------

@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "llm_provider", "lmstudio")
    monkeypatch.setattr(settings, "lmstudio_writer_model", "gemma-test")
    monkeypatch.setattr(writer_log, "DB_PATH", str(tmp_path / "w.db"))
    writer_log.init_db()
    calls = []

    async def fake_invoke(messages, temperature, timeout, surface=None):
        calls.append(messages)
        return fake_invoke.reply

    fake_invoke.reply = "Writer text."
    monkeypatch.setattr(writer, "_invoke", fake_invoke)
    return calls, fake_invoke


def finalize(msgs, draft, **kw):
    kw.setdefault("mode", None)
    kw.setdefault("one_shot", False)
    kw.setdefault("agent_run", False)
    return run(writer.finalize_reply(msgs, draft=draft, thread_id="t1", **kw))


def test_finalize_disabled_without_writer_model(monkeypatch):
    monkeypatch.setattr(settings, "lmstudio_writer_model", "")
    assert finalize([HumanMessage(content="hi")], "hello") is None


def test_finalize_disabled_on_other_provider(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    monkeypatch.setattr(settings, "lmstudio_writer_model", "gemma-test")
    assert finalize([HumanMessage(content="hi")], "hello") is None


def test_finalize_uses_writer_and_logs(enabled):
    calls, _ = enabled
    assert finalize([HumanMessage(content="chat with me")], "meh draft") == "Writer text."
    prompt = calls[0][-1].content
    assert "chat with me" in prompt and "meh draft" in prompt
    row = writer_log.get_writer_log("t1")[0]
    assert (row["route"], row["reason"], row["final"], row["draft"]) == ("writer", "conversation", "Writer text.", "meh draft")


def test_finalize_keeps_draft_when_rule_says_so(enabled):
    msgs = [HumanMessage(content="jot this"), AIMessage(content="", tool_calls=[{"name": "save_note", "args": {}, "id": "c"}]),
            ToolMessage(content="Note saved", tool_call_id="c")]
    assert finalize(msgs, "Saved.") is None
    assert writer_log.get_writer_log("t1")[0]["route"] == "tool_model"


def test_finalize_falls_back_on_writer_error(enabled, monkeypatch):
    async def boom(*a, **k):
        raise TimeoutError("slow")

    monkeypatch.setattr(writer, "_invoke", boom)
    assert finalize([HumanMessage(content="chat")], "draft") is None
    row = writer_log.get_writer_log("t1")[0]
    assert row["route"] == "fallback" and "TimeoutError" in row["error"] and row["final"] == "draft"


def test_finalize_rejects_toolcall_looking_output(enabled):
    _, fake = enabled
    fake.reply = '{"name": "set_reminder", "arguments": {}}'
    assert finalize([HumanMessage(content="chat")], "draft") is None
    assert writer_log.get_writer_log("t1")[0]["route"] == "fallback"


def test_writer_prompt_tells_it_about_errors_and_voice(enabled):
    calls, _ = enabled
    msgs = [HumanMessage(content="add dentist"),
            AIMessage(content="", tool_calls=[{"name": "add_calendar_event", "args": {"title": "Dentist"}, "id": "c"}]),
            ToolMessage(content="Failed to add event. Unknown", tool_call_id="c")]
    finalize(msgs, "Done, added!", one_shot=True)
    system, final = calls[0][0].content, calls[0][-1].content
    assert "plain text only" in system
    assert "Result (ERROR): Failed to add event" in final


LONG = ("Service notes: oil changed at 120000 km on 2026-03-01 by [[Bob]] see https://x.example/a. " * 6)


def tool_call_msgs(name, args, user="u"):
    return [HumanMessage(content=user), AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "c1"}])]


def test_rewrite_tool_calls_tidy(enabled):
    _, fake = enabled
    fake.reply = LONG.replace("Service notes", "Service log")
    msgs = tool_call_msgs("save_note", {"content": LONG, "title": "Car"})
    new = run(writer.rewrite_tool_calls(msgs, thread_id="t1", mode=None, agent_run=False))
    assert new[0]["args"]["content"] == fake.reply and new[0]["args"]["title"] == "Car"
    assert msgs[-1].tool_calls[0]["args"]["content"] == LONG  # original untouched
    assert writer_log.get_writer_log("t1")[0]["kind"] == "arg:save_note.content"


def test_rewrite_tool_calls_skips_short_content(enabled):
    msgs = tool_call_msgs("save_note", {"content": "buy milk"})
    assert run(writer.rewrite_tool_calls(msgs, thread_id="t1", mode=None, agent_run=False)) is None


def test_rewrite_tool_calls_skips_other_tools(enabled):
    msgs = tool_call_msgs("remember_about_me", {"section": "x", "content": LONG})
    assert run(writer.rewrite_tool_calls(msgs, thread_id="t1", mode=None, agent_run=False)) is None


def test_rewrite_tool_calls_invalid_rewrite_keeps_original(enabled):
    _, fake = enabled
    fake.reply = "Totally different and drops every anchor but is long enough to pass the length check. " * 5
    msgs = tool_call_msgs("save_note", {"content": LONG})
    assert run(writer.rewrite_tool_calls(msgs, thread_id="t1", mode=None, agent_run=False)) is None
    row = writer_log.get_writer_log("t1")[0]
    assert row["route"] == "fallback" and row["error"] == "validation_failed"


def test_rewrite_tool_calls_compose_runs_even_for_short_drafts(enabled):
    _, fake = enabled
    fake.reply = "A full written note. https://a.example/x and plenty more detail than the outline had."
    msgs = tool_call_msgs("save_note", {"content": "outline https://a.example/x"}, user="research X")
    new = run(writer.rewrite_tool_calls(msgs, thread_id="project_demo", mode="project_chat", agent_run=True))
    assert new[0]["args"]["content"] == fake.reply
