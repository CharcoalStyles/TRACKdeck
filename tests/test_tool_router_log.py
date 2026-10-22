from dataclasses import dataclass

import utils.tool_router_log as tool_router_log


def _use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_router_log, "DB_PATH", str(tmp_path / "tool_router_log.db"))
    tool_router_log.init_db()


@dataclass
class FakeDecision:
    tools: list
    narrowed: bool
    categories: list
    probabilities: dict | None
    latency_ms: float | None
    reason: str


def test_log_and_get_round_trip(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    decision = FakeDecision(
        tools=[], narrowed=True, categories=["weather", "reminders"],
        probabilities={"weather": 0.9, "reminders": 0.7, "notes": 0.1}, latency_ms=12.5, reason="ok",
    )
    tool_router_log.log_tool_router("thread-1", "what's the weather", decision)

    entries = tool_router_log.get_tool_router_log_for_thread("thread-1")

    assert len(entries) == 1
    assert entries[0]["message"] == "what's the weather"
    assert entries[0]["categories"] == ["weather", "reminders"]
    assert entries[0]["probabilities"] == {"weather": 0.9, "reminders": 0.7, "notes": 0.1}
    assert entries[0]["narrowed"] is True
    assert entries[0]["reason"] == "ok"
    assert entries[0]["latency_ms"] == 12.5


def test_log_and_get_handles_no_probabilities(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    decision = FakeDecision(tools=[], narrowed=False, categories=[], probabilities=None, latency_ms=None, reason="disabled")
    tool_router_log.log_tool_router("thread-1", "hi", decision)

    entries = tool_router_log.get_tool_router_log_for_thread("thread-1")

    assert entries[0]["categories"] == []
    assert entries[0]["probabilities"] is None


def test_get_returns_oldest_first_and_scoped_to_thread(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    disabled = FakeDecision([], False, [], None, None, "disabled")
    ok = FakeDecision([], True, ["notes"], {"notes": 0.8}, 20.0, "ok")

    tool_router_log.log_tool_router("thread-1", "first", disabled)
    tool_router_log.log_tool_router("thread-1", "second", ok)
    tool_router_log.log_tool_router("thread-2", "other thread", ok)

    entries = tool_router_log.get_tool_router_log_for_thread("thread-1")

    assert [e["message"] for e in entries] == ["first", "second"]
