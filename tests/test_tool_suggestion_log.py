from dataclasses import dataclass

import utils.tool_suggestion_log as tool_suggestion_log


def _use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_suggestion_log, "DB_PATH", str(tmp_path / "tool_suggestion_log.db"))
    tool_suggestion_log.init_db()


@dataclass
class FakeDecision:
    suggested: list
    probabilities: dict | None
    latency_ms: float | None
    reason: str


def test_log_and_get_round_trip(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    decision = FakeDecision(
        suggested=["get_current_weather", "set_reminder"],
        probabilities={"get_current_weather": 0.9, "set_reminder": 0.6, "save_note": 0.05},
        latency_ms=5.0, reason="ok",
    )
    tool_suggestion_log.log_tool_suggestion("thread-1", "what's the weather", decision)

    entries = tool_suggestion_log.get_tool_suggestion_log_for_thread("thread-1")

    assert len(entries) == 1
    assert entries[0]["message"] == "what's the weather"
    assert entries[0]["suggested"] == ["get_current_weather", "set_reminder"]
    assert entries[0]["probabilities"]["get_current_weather"] == 0.9
    assert entries[0]["reason"] == "ok"
    assert entries[0]["latency_ms"] == 5.0


def test_log_and_get_handles_no_probabilities(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    decision = FakeDecision(suggested=[], probabilities=None, latency_ms=None, reason="disabled")
    tool_suggestion_log.log_tool_suggestion("thread-1", "hi", decision)

    entries = tool_suggestion_log.get_tool_suggestion_log_for_thread("thread-1")

    assert entries[0]["suggested"] == []
    assert entries[0]["probabilities"] is None


def test_get_returns_oldest_first_and_scoped_to_thread(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    disabled = FakeDecision([], None, None, "disabled")
    ok = FakeDecision(["save_note"], {"save_note": 0.8}, 5.0, "ok")

    tool_suggestion_log.log_tool_suggestion("thread-1", "first", disabled)
    tool_suggestion_log.log_tool_suggestion("thread-1", "second", ok)
    tool_suggestion_log.log_tool_suggestion("thread-2", "other thread", ok)

    entries = tool_suggestion_log.get_tool_suggestion_log_for_thread("thread-1")

    assert [e["message"] for e in entries] == ["first", "second"]
