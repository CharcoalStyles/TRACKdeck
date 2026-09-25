import asyncio

import httpx

import utils.lmstudio_client as lmstudio_client


_RealAsyncClient = httpx.AsyncClient


def _mock_client(handler):
    # Patching lmstudio_client.httpx.AsyncClient mutates the actual httpx
    # module (module attributes are shared, not copied) — so this closes
    # over the real class captured above rather than calling through the
    # patched name and recursing into itself.
    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _RealAsyncClient(*args, **kwargs)

    return fake_async_client


def test_fetch_models_excludes_embeddings_but_keeps_vlm(monkeypatch):
    monkeypatch.setenv("LMSTUDIO_MANAGEMENT_URL", "http://x/api/v0")

    def handler(request):
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "qwen2.5-7b-instruct",
                        "type": "llm",
                        "state": "loaded",
                        "max_context_length": 32768,
                        "loaded_context_length": 8192,
                    },
                    # Embedding models are downloaded in LM Studio too, but
                    # aren't chat-completion candidates — excluded.
                    {"id": "nomic-embed-text", "type": "embeddings", "state": "loaded"},
                    {"id": "llama-3.1-8b", "type": "llm", "state": "not-loaded", "max_context_length": 131072},
                    # Vision-capable models report as "vlm", not "llm", but
                    # are just as usable for chat completions — must not be
                    # filtered out the way an allowlist of just "llm" would.
                    {"id": "gemma-4-e4b-it", "type": "vlm", "state": "loaded", "max_context_length": 131072},
                ]
            },
        )

    monkeypatch.setattr(lmstudio_client.httpx, "AsyncClient", _mock_client(handler))

    models = asyncio.run(lmstudio_client.fetch_models())

    assert [m.id for m in models] == ["qwen2.5-7b-instruct", "llama-3.1-8b", "gemma-4-e4b-it"]
    assert models[0].state == "loaded"
    assert models[0].loaded_context_length == 8192
    assert models[1].state == "not-loaded"
    assert models[1].loaded_context_length is None


def test_fetch_models_empty_when_management_url_unset(monkeypatch):
    monkeypatch.delenv("LMSTUDIO_MANAGEMENT_URL", raising=False)
    assert asyncio.run(lmstudio_client.fetch_models()) == []


def test_fetch_models_empty_on_request_failure(monkeypatch):
    monkeypatch.setenv("LMSTUDIO_MANAGEMENT_URL", "http://x/api/v0")

    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(lmstudio_client.httpx, "AsyncClient", _mock_client(handler))

    assert asyncio.run(lmstudio_client.fetch_models()) == []


def test_get_loaded_context_length_matches_configured_model(monkeypatch):
    monkeypatch.setenv("LMSTUDIO_MANAGEMENT_URL", "http://x/api/v0")
    monkeypatch.setattr(lmstudio_client.settings, "lmstudio_chat_model", "qwen2.5-7b-instruct")

    def handler(request):
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "qwen2.5-7b-instruct",
                        "type": "llm",
                        "state": "loaded",
                        "loaded_context_length": 8192,
                    },
                ]
            },
        )

    monkeypatch.setattr(lmstudio_client.httpx, "AsyncClient", _mock_client(handler))

    assert asyncio.run(lmstudio_client.get_loaded_context_length()) == 8192


def test_get_loaded_context_length_none_when_no_match(monkeypatch):
    monkeypatch.setenv("LMSTUDIO_MANAGEMENT_URL", "http://x/api/v0")
    monkeypatch.setattr(lmstudio_client.settings, "lmstudio_chat_model", "some-other-model")

    def handler(request):
        return httpx.Response(
            200,
            json={"data": [{"id": "qwen2.5-7b-instruct", "type": "llm", "state": "loaded"}]},
        )

    monkeypatch.setattr(lmstudio_client.httpx, "AsyncClient", _mock_client(handler))

    assert asyncio.run(lmstudio_client.get_loaded_context_length()) is None
