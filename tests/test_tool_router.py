import asyncio
from dataclasses import dataclass

import agent.tool_router as tool_router
from agent.tool_router import build_category_index, choose_tool_subset
from utils.laya_client import LayaNotInstalled


@dataclass
class FakeTool:
    name: str
    description: str = ""


def _tools():
    return [
        FakeTool("get_current_weather"),
        FakeTool("get_weather_forecast"),
        FakeTool("set_reminder"),
        FakeTool("some_new_tool_nobody_mapped_yet"),
    ]


def test_build_category_index_groups_and_omits_empty_categories():
    index = build_category_index(_tools())

    assert {t.name for t in index.by_category["weather"]} == {"get_current_weather", "get_weather_forecast"}
    assert {t.name for t in index.by_category["reminders"]} == {"set_reminder"}
    # A category with no matching tool (e.g. "checkin") is omitted entirely,
    # not present with an empty list.
    assert "checkin" not in index.by_category
    assert "checkin" not in index.candidates


def test_build_category_index_keeps_unmapped_tool_reachable():
    index = build_category_index(_tools())

    assert [t.name for t in index.uncategorized] == ["some_new_tool_nobody_mapped_yet"]


def test_choose_tool_subset_disabled_never_calls_laya(monkeypatch):
    monkeypatch.setattr(tool_router.settings, "tool_router_enabled", False)

    def fail(*args, **kwargs):
        raise AssertionError("ask_choose_multiple should not be called when disabled")

    monkeypatch.setattr(tool_router, "ask_choose_multiple", fail)

    tools = _tools()
    index = build_category_index(tools)
    decision = asyncio.run(choose_tool_subset("what's the weather", index, tools))

    assert decision.tools == tools
    assert decision.narrowed is False
    assert decision.categories == []
    assert decision.reason == "disabled"


def test_choose_tool_subset_narrows_to_single_selected_category(monkeypatch):
    monkeypatch.setattr(tool_router.settings, "tool_router_enabled", True)

    async def fake_ask_choose_multiple(message, instructions, candidates, threshold):
        selected = ["weather"]
        return {
            "selected": selected,
            "options": [{"name": name, "probability": 0.9 if name in selected else 0.05} for name in candidates],
            "latency_ms": 12.5,
        }

    monkeypatch.setattr(tool_router, "ask_choose_multiple", fake_ask_choose_multiple)

    tools = _tools()
    index = build_category_index(tools)
    decision = asyncio.run(choose_tool_subset("what's the weather", index, tools))

    assert decision.narrowed is True
    assert decision.categories == ["weather"]
    assert decision.probabilities["weather"] == 0.9
    assert decision.reason == "ok"
    # The unmapped tool always rides along, so it's never made unreachable
    # by routing.
    names = {t.name for t in decision.tools}
    assert names == {"get_current_weather", "get_weather_forecast", "some_new_tool_nobody_mapped_yet"}


def test_choose_tool_subset_narrows_to_multiple_selected_categories(monkeypatch):
    monkeypatch.setattr(tool_router.settings, "tool_router_enabled", True)

    async def fake_ask_choose_multiple(message, instructions, candidates, threshold):
        selected = ["weather", "reminders"]
        return {
            "selected": selected,
            "options": [{"name": name, "probability": 0.8 if name in selected else 0.1} for name in candidates],
            "latency_ms": 12.5,
        }

    monkeypatch.setattr(tool_router, "ask_choose_multiple", fake_ask_choose_multiple)

    tools = _tools()
    index = build_category_index(tools)
    decision = asyncio.run(choose_tool_subset("remind me about the weather", index, tools))

    assert decision.narrowed is True
    assert set(decision.categories) == {"weather", "reminders"}
    names = {t.name for t in decision.tools}
    # A compound request spanning two categories keeps tools from both —
    # this is exactly the case a single-Choice design couldn't handle.
    assert names == {
        "get_current_weather", "get_weather_forecast", "set_reminder", "some_new_tool_nobody_mapped_yet",
    }


def test_choose_tool_subset_nothing_clears_threshold_falls_back(monkeypatch):
    monkeypatch.setattr(tool_router.settings, "tool_router_enabled", True)

    async def fake_ask_choose_multiple(message, instructions, candidates, threshold):
        # Every candidate below CONFIDENCE_THRESHOLD (0.5) — nothing selected.
        return {
            "selected": [],
            "options": [{"name": name, "probability": 0.3} for name in candidates],
            "latency_ms": 12.5,
        }

    monkeypatch.setattr(tool_router, "ask_choose_multiple", fake_ask_choose_multiple)

    tools = _tools()
    index = build_category_index(tools)
    decision = asyncio.run(choose_tool_subset("do a thing", index, tools))

    assert decision.tools == tools
    assert decision.narrowed is False
    assert decision.categories == []
    assert decision.reason == "low_confidence"
    # Probabilities are still carried through on a fallback, for tuning.
    assert decision.probabilities is not None


def test_choose_tool_subset_empty_category_falls_back(monkeypatch):
    monkeypatch.setattr(tool_router.settings, "tool_router_enabled", True)

    async def fake_ask_choose_multiple(message, instructions, candidates, threshold):
        # "web" is selected but no MCP tool is present in this test's tool
        # list, so by_category has no "web" entry — and with only mapped
        # tools (no unmapped one), uncategorized can't paper over it either.
        return {
            "selected": ["web"],
            "options": [{"name": name, "probability": 0.95 if name == "web" else 0.01} for name in candidates],
            "latency_ms": 12.5,
        }

    monkeypatch.setattr(tool_router, "ask_choose_multiple", fake_ask_choose_multiple)

    tools = [FakeTool("get_current_weather"), FakeTool("set_reminder")]
    index = build_category_index(tools)
    index.candidates["web"] = "Searching the web."

    decision = asyncio.run(choose_tool_subset("search the web for X", index, tools))

    assert decision.tools == tools
    assert decision.narrowed is False
    assert decision.categories == ["web"]
    assert decision.reason == "empty_category"


def test_choose_tool_subset_laya_not_installed_falls_back(monkeypatch):
    monkeypatch.setattr(tool_router.settings, "tool_router_enabled", True)

    async def fake_ask_choose_multiple(*args, **kwargs):
        raise LayaNotInstalled()

    monkeypatch.setattr(tool_router, "ask_choose_multiple", fake_ask_choose_multiple)

    tools = _tools()
    index = build_category_index(tools)
    decision = asyncio.run(choose_tool_subset("what's the weather", index, tools))

    assert decision.tools == tools
    assert decision.narrowed is False
    assert decision.reason == "laya_not_installed"


def test_choose_tool_subset_generic_error_falls_back(monkeypatch):
    monkeypatch.setattr(tool_router.settings, "tool_router_enabled", True)

    async def fake_ask_choose_multiple(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(tool_router, "ask_choose_multiple", fake_ask_choose_multiple)

    tools = _tools()
    index = build_category_index(tools)
    decision = asyncio.run(choose_tool_subset("what's the weather", index, tools))

    assert decision.tools == tools
    assert decision.narrowed is False
    assert decision.reason == "error:RuntimeError"
