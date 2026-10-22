import asyncio
from dataclasses import dataclass

import agent.tool_suggestion as tool_suggestion
from agent.tool_suggestion import build_suggestion_text, build_tool_candidates, suggest_tools
from utils.laya_client import LayaNotInstalled


@dataclass
class FakeTool:
    name: str
    description: str = "Does a thing.\nMore detail on a second line."


def _tools():
    return [
        FakeTool("get_current_weather", "Gets the current weather for a location."),
        FakeTool("set_reminder", "Sets a reminder for a given time."),
        FakeTool("no_description_tool", ""),
    ]


def test_build_tool_candidates_uses_first_line_truncated():
    candidates = build_tool_candidates(_tools())

    assert candidates["get_current_weather"] == "Gets the current weather for a location."
    assert candidates["set_reminder"] == "Sets a reminder for a given time."
    # Falls back to the tool's own name when there's no description.
    assert candidates["no_description_tool"] == "no_description_tool"


def test_build_suggestion_text_empty_when_nothing_suggested():
    assert build_suggestion_text([]) == ""


def test_build_suggestion_text_lists_tool_names():
    text = build_suggestion_text(["get_current_weather", "set_reminder"])
    assert text == "\n\nI think these tools will help you complete what's needed: get_current_weather, set_reminder."


def test_suggest_tools_disabled_never_calls_laya(monkeypatch):
    monkeypatch.setattr(tool_suggestion.settings, "tool_suggestion_enabled", False)

    def fail(*args, **kwargs):
        raise AssertionError("ask_choose_multiple should not be called when disabled")

    monkeypatch.setattr(tool_suggestion, "ask_choose_multiple", fail)

    candidates = build_tool_candidates(_tools())
    decision = asyncio.run(suggest_tools("what's the weather", candidates))

    assert decision.suggested == []
    assert decision.reason == "disabled"


def test_suggest_tools_returns_selected_tools(monkeypatch):
    monkeypatch.setattr(tool_suggestion.settings, "tool_suggestion_enabled", True)

    async def fake_ask_choose_multiple(message, instructions, candidates, threshold):
        selected = ["get_current_weather"]
        return {
            "selected": selected,
            "options": [{"name": n, "probability": 0.9 if n in selected else 0.1} for n in candidates],
            "latency_ms": 5.0,
        }

    monkeypatch.setattr(tool_suggestion, "ask_choose_multiple", fake_ask_choose_multiple)

    candidates = build_tool_candidates(_tools())
    decision = asyncio.run(suggest_tools("what's the weather", candidates))

    assert decision.suggested == ["get_current_weather"]
    assert decision.probabilities["get_current_weather"] == 0.9
    assert decision.reason == "ok"


def test_suggest_tools_nothing_clears_threshold(monkeypatch):
    monkeypatch.setattr(tool_suggestion.settings, "tool_suggestion_enabled", True)

    async def fake_ask_choose_multiple(message, instructions, candidates, threshold):
        return {
            "selected": [],
            "options": [{"name": n, "probability": 0.1} for n in candidates],
            "latency_ms": 5.0,
        }

    monkeypatch.setattr(tool_suggestion, "ask_choose_multiple", fake_ask_choose_multiple)

    candidates = build_tool_candidates(_tools())
    decision = asyncio.run(suggest_tools("hello", candidates))

    assert decision.suggested == []
    assert decision.reason == "none_suggested"
    assert decision.probabilities is not None


def test_suggest_tools_laya_not_installed(monkeypatch):
    monkeypatch.setattr(tool_suggestion.settings, "tool_suggestion_enabled", True)

    async def fake_ask_choose_multiple(*args, **kwargs):
        raise LayaNotInstalled()

    monkeypatch.setattr(tool_suggestion, "ask_choose_multiple", fake_ask_choose_multiple)

    candidates = build_tool_candidates(_tools())
    decision = asyncio.run(suggest_tools("what's the weather", candidates))

    assert decision.suggested == []
    assert decision.reason == "laya_not_installed"


def test_suggest_tools_generic_error(monkeypatch):
    monkeypatch.setattr(tool_suggestion.settings, "tool_suggestion_enabled", True)

    async def fake_ask_choose_multiple(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(tool_suggestion, "ask_choose_multiple", fake_ask_choose_multiple)

    candidates = build_tool_candidates(_tools())
    decision = asyncio.run(suggest_tools("what's the weather", candidates))

    assert decision.suggested == []
    assert decision.reason == "error:RuntimeError"
