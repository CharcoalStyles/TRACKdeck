import utils.llm_client as llm_client


def test_defaults_to_chatopenai(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "lmstudio_chat_model", "m")
    monkeypatch.setenv("LMSTUDIO_OPENAI_URL", "http://x")
    llm = llm_client.get_chat_llm(0.5)
    assert type(llm).__name__ == "ChatOpenAI"
    assert llm.model_name == "m"
    assert llm_client.describe_chat_llm() == {
        "model": "m",
        "base_url": "http://x",
    }


def test_stringify_content_passes_through_plain_string_and_none():
    assert llm_client.stringify_content("hello") == "hello"
    assert llm_client.stringify_content(None) is None


def test_stringify_content_flattens_text_blocks():
    # A list of content blocks, each carrying a "text" key plus extras that
    # must be dropped, not just str()'d.
    content = [{"type": "text", "text": "Hi there.", "extras": {"signature": "AAAA..."}}]
    assert llm_client.stringify_content(content) == "Hi there."


def test_stringify_content_falls_back_to_json_for_non_text_blocks():
    content = [{"type": "other", "data": 1}]
    assert llm_client.stringify_content(content) == '[{"type": "other", "data": 1}]'


def test_writer_llm_uses_writer_model_when_set(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "lmstudio_chat_model", "chat")
    monkeypatch.setattr(llm_client.settings, "lmstudio_writer_model", "writer")
    monkeypatch.setenv("LMSTUDIO_OPENAI_URL", "http://x")
    assert llm_client.get_writer_llm(0.7).model_name == "writer"


def test_writer_llm_falls_back_to_chat_model_when_unset(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "lmstudio_chat_model", "chat")
    monkeypatch.setattr(llm_client.settings, "lmstudio_writer_model", "")
    monkeypatch.setenv("LMSTUDIO_OPENAI_URL", "http://x")
    assert llm_client.get_writer_llm(0.7).model_name == "chat"
