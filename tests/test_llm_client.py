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
