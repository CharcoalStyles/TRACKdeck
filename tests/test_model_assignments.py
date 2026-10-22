import json

import pytest

from agent import model_assignments as ma
from agent.settings import settings


@pytest.fixture(autouse=True)
def base(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "lmstudio")
    monkeypatch.setattr(settings, "lmstudio_chat_model", "lfm")
    monkeypatch.setattr(settings, "lmstudio_writer_model", "gemma")
    monkeypatch.setattr(settings, "model_assignments", "{}")


def set_overrides(monkeypatch, value):
    monkeypatch.setattr(settings, "model_assignments", json.dumps(value))


def test_surface_key():
    assert ma.surface_key(None, False) == "chat"
    assert ma.surface_key(None, True) == "one_shot"
    assert ma.surface_key("day_planning", False) == "day_planning"
    assert ma.surface_key("day_planning", True) == "day_planning"


def test_defaults_without_overrides():
    assert ma.tool_model("chat") == "lfm"
    assert ma.writer_model("day_planning") == "gemma"
    assert ma.writer_model(None) == "gemma"


def test_overrides_apply_per_surface(monkeypatch):
    set_overrides(monkeypatch, {"day_planning": {"tool": "big", "writer": "other"}, "digest": {"writer": ma.NO_WRITER}})
    assert ma.tool_model("day_planning") == "big" and ma.tool_model("chat") == "lfm"
    assert ma.writer_model("day_planning") == "other" and ma.writer_model("chat") == "gemma"
    assert ma.writer_model("digest") == ""


def test_validate_rejects_bad_input():
    with pytest.raises(ValueError):
        ma.validate({"nope": {"tool": "x"}})
    with pytest.raises(ValueError):
        ma.validate({"digest": {"tool": "x"}})
    with pytest.raises(ValueError):
        ma.validate({"chat": {"tool": ma.NO_WRITER}})
    with pytest.raises(ValueError):
        ma.validate({"chat": {"speed": "x"}})


def test_validate_drops_blank_entries():
    assert ma.validate({"chat": {"tool": "  ", "writer": ""}, "digest": {"writer": " g "}}) == {"digest": {"writer": "g"}}


def test_garbage_stored_value_falls_back_to_defaults(monkeypatch):
    monkeypatch.setattr(settings, "model_assignments", "not json")
    assert ma.tool_model("chat") == "lfm"


def test_matrix_rows(monkeypatch):
    set_overrides(monkeypatch, {"digest": {"writer": ma.NO_WRITER}})
    m = ma.matrix()
    rows = {r["key"]: r for r in m["rows"]}
    assert set(rows) == ma.SURFACE_KEYS
    assert rows["digest"]["writer_model"] is None and rows["digest"]["reply_model"] == "lfm"
    assert rows["digest"]["tool_model"] is None
    assert rows["day_planning"]["writer_model"] == "gemma" and rows["day_planning"]["tool_model"] == "lfm"
