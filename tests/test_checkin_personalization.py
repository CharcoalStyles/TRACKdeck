import asyncio
from types import SimpleNamespace

import jobs.checkin as checkin_mod


def _stub_context(monkeypatch, has_context=True):
    """Bypass real vault/activity_log reads — _personalize_prompt only
    needs *some* non-empty context to proceed past its early-out."""
    monkeypatch.setattr(
        checkin_mod.vault, "get_or_create_about_me", lambda: SimpleNamespace(body="## Values\nHonesty\n")
    )
    monkeypatch.setattr(checkin_mod.activity_log_store, "list_between", lambda *a, **k: [])
    if not has_context:
        monkeypatch.setattr(checkin_mod.vault, "get_or_create_about_me", lambda: SimpleNamespace(body=""))


def _force_level(monkeypatch, level):
    monkeypatch.setattr(checkin_mod.random, "choice", lambda seq: level if level in seq else seq[0])


def test_select_rejects_prompt_not_in_bank(monkeypatch):
    _stub_context(monkeypatch)
    _force_level(monkeypatch, "select")
    monkeypatch.setattr(checkin_mod, "_llm_select", lambda bank, context: "not a real prompt")

    prompt, level = asyncio.run(checkin_mod._personalize_prompt("low"))

    assert level == "none"
    assert prompt in checkin_mod.PROMPTS["low"]


def test_light_rejects_reworded_text_without_question_mark(monkeypatch):
    _stub_context(monkeypatch)
    _force_level(monkeypatch, "light")
    monkeypatch.setattr(checkin_mod, "_llm_light_reword", lambda base, context: "This has no question mark.")

    prompt, level = asyncio.run(checkin_mod._personalize_prompt("medium"))

    assert level == "none"
    assert prompt in checkin_mod.PROMPTS["medium"]


def test_llm_error_falls_back_without_raising(monkeypatch):
    _stub_context(monkeypatch)
    _force_level(monkeypatch, "select")

    def _raise(*args, **kwargs):
        raise RuntimeError("LM Studio unreachable")

    monkeypatch.setattr(checkin_mod, "_llm_select", _raise)

    prompt, level = asyncio.run(checkin_mod._personalize_prompt("high"))

    assert level == "none"
    assert prompt in checkin_mod.PROMPTS["high"]


def test_select_happy_path_preserves_level(monkeypatch):
    _stub_context(monkeypatch)
    _force_level(monkeypatch, "select")
    chosen = checkin_mod.PROMPTS["low"][0]
    monkeypatch.setattr(checkin_mod, "_llm_select", lambda bank, context: chosen)

    prompt, level = asyncio.run(checkin_mod._personalize_prompt("low"))

    assert level == "select"
    assert prompt == chosen


def test_no_context_skips_llm_call_entirely(monkeypatch):
    _stub_context(monkeypatch, has_context=False)
    _force_level(monkeypatch, "select")

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("LLM should not be called when there's no context to personalize on")

    monkeypatch.setattr(checkin_mod, "_llm_select", _fail_if_called)

    prompt, level = asyncio.run(checkin_mod._personalize_prompt("low"))

    assert level == "none"
    assert prompt in checkin_mod.PROMPTS["low"]


def test_preview_moderate_is_never_in_the_live_rotation():
    assert "moderate" not in checkin_mod.PERSONALIZATION_LEVELS


def test_preview_reports_invalid_output_instead_of_hiding_it(monkeypatch):
    """Unlike the live path, preview must surface a failing response as-is
    — that's the whole point of the preview tool."""
    _stub_context(monkeypatch)
    monkeypatch.setattr(checkin_mod, "_llm_moderate_reword", lambda base, context: "no question mark here")

    result = asyncio.run(checkin_mod.preview_personalization("low", "moderate"))

    assert result["result"] == "no question mark here"
    assert result["would_pass_validation"] is False
    assert result["base_prompt"] in checkin_mod.PROMPTS["low"]


def test_preview_select_validates_against_bank(monkeypatch):
    _stub_context(monkeypatch)
    chosen = checkin_mod.PROMPTS["high"][2]
    monkeypatch.setattr(checkin_mod, "_llm_select", lambda bank, context: chosen)

    result = asyncio.run(checkin_mod.preview_personalization("high", "select"))

    assert result["result"] == chosen
    assert result["would_pass_validation"] is True
    assert result["base_prompt"] is None


def test_preview_pins_light_and_moderate_to_the_given_base_prompt(monkeypatch):
    _stub_context(monkeypatch)
    fixed_prompt = checkin_mod.PROMPTS["medium"][3]
    seen_bases = []

    def _capture(base, context):
        seen_bases.append(base)
        return f"{base[:-1]} — reworded?"

    monkeypatch.setattr(checkin_mod, "_llm_light_reword", _capture)
    monkeypatch.setattr(checkin_mod, "_llm_moderate_reword", _capture)

    light = asyncio.run(checkin_mod.preview_personalization("medium", "light", base_prompt=fixed_prompt))
    moderate = asyncio.run(checkin_mod.preview_personalization("medium", "moderate", base_prompt=fixed_prompt))

    assert light["base_prompt"] == fixed_prompt
    assert moderate["base_prompt"] == fixed_prompt
    assert seen_bases == [fixed_prompt, fixed_prompt]


def test_preview_rejects_base_prompt_not_in_that_categorys_bank(monkeypatch):
    _stub_context(monkeypatch)
    foreign_prompt = checkin_mod.PROMPTS["high"][0]

    try:
        asyncio.run(checkin_mod.preview_personalization("low", "light", base_prompt=foreign_prompt))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_preview_unknown_level_raises():
    try:
        asyncio.run(checkin_mod.preview_personalization("low", "bogus"))
        assert False, "expected ValueError"
    except ValueError:
        pass
