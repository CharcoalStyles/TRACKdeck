import utils.llm_client as llm_client


def test_defaults_to_chatopenai(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "llm_provider", "lmstudio")
    monkeypatch.setattr(llm_client.settings, "lmstudio_chat_model", "m")
    monkeypatch.setenv("LMSTUDIO_OPENAI_URL", "http://x")
    llm = llm_client.get_chat_llm(0.5)
    assert type(llm).__name__ == "ChatOpenAI"
    assert llm.model_name == "m"
    assert llm_client.describe_chat_llm() == {
        "provider": "lmstudio",
        "model": "m",
        "base_url": "http://x",
    }


def test_gemini_provider(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "llm_provider", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_CHAT_MODEL", "gemini-flash-latest")
    assert type(llm_client.get_chat_llm(0.5)).__name__ == "ChatGoogleGenerativeAI"


def test_openrouter_provider(monkeypatch):
    # The model itself comes from the live settings singleton, not
    # OPENROUTER_CHAT_MODEL directly — it's only that setting's seed value
    # (agent/settings.py), and stays dashboard-switchable (no restart) from
    # then on. So set it the same way a real model switch would: as an
    # attribute on the settings object llm_client imported, not the env var.
    monkeypatch.setattr(llm_client.settings, "llm_provider", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(llm_client.settings, "openrouter_chat_model", "google/gemma-4-31b-it:free")
    llm = llm_client.get_chat_llm(0.5)
    assert type(llm).__name__ == "ChatOpenAI"
    assert llm.openai_api_base == "https://openrouter.ai/api/v1"
    assert llm_client.describe_chat_llm() == {
        "provider": "openrouter",
        "model": "google/gemma-4-31b-it:free",
        "base_url": "https://openrouter.ai/api/v1",
    }


def test_get_chat_llm_provider_arg_overrides_settings(monkeypatch):
    # agent/graph.py's build_graph caches one client per provider it's
    # actually asked for, passing the provider explicitly rather than
    # relying on settings.llm_provider at call time.
    monkeypatch.setattr(llm_client.settings, "llm_provider", "openrouter")
    monkeypatch.setattr(llm_client.settings, "lmstudio_chat_model", "m")
    monkeypatch.setenv("LMSTUDIO_OPENAI_URL", "http://x")
    llm = llm_client.get_chat_llm(0.5, provider="lmstudio")
    assert llm.openai_api_base == "http://x"
    assert llm.model_name == "m"


def test_openrouter_configured(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert llm_client.openrouter_configured() is False
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert llm_client.openrouter_configured() is True


def test_stringify_content_passes_through_plain_string_and_none():
    assert llm_client.stringify_content("hello") == "hello"
    assert llm_client.stringify_content(None) is None


def test_stringify_content_flattens_gemini_style_blocks():
    # Gemini's AIMessage.content: a list of blocks, each carrying a "text"
    # key plus provider extras (e.g. a thought-signature blob) that must
    # be dropped, not just str()'d, since that blob can be very large.
    content = [{"type": "text", "text": "Hi there.", "extras": {"signature": "AAAA..."}}]
    assert llm_client.stringify_content(content) == "Hi there."


def test_stringify_content_falls_back_to_json_for_non_text_blocks():
    content = [{"type": "other", "data": 1}]
    assert llm_client.stringify_content(content) == '[{"type": "other", "data": 1}]'
