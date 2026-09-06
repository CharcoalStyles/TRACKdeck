import importlib

import utils.llm_client as llm_client


def test_defaults_to_chatopenai(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("LMSTUDIO_OPENAI_URL", "http://x")
    monkeypatch.setenv("CHAT_MODEL", "m")
    importlib.reload(llm_client)
    assert type(llm_client.get_chat_llm(0.5)).__name__ == "ChatOpenAI"


def test_gemini_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_CHAT_MODEL", "gemini-flash-latest")
    importlib.reload(llm_client)
    assert type(llm_client.get_chat_llm(0.5)).__name__ == "ChatGoogleGenerativeAI"


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
