from utils.openrouter_client import _normalize


def test_normalize_free_model():
    entry = {
        "id": "google/gemma-4-31b-it:free",
        "name": "Google: Gemma 4 31B IT (free)",
        "context_length": 131072,
        "pricing": {"prompt": "0", "completion": "0"},
    }
    model = _normalize(entry)
    assert model.id == "google/gemma-4-31b-it:free"
    assert model.context_length == 131072
    assert model.prompt_price_per_million == 0
    assert model.completion_price_per_million == 0
    assert model.is_free is True


def test_normalize_paid_model_converts_to_per_million():
    entry = {
        "id": "openai/gpt-5",
        "name": "OpenAI: GPT-5",
        "context_length": 400000,
        "pricing": {"prompt": "0.0000015", "completion": "0.000006"},
    }
    model = _normalize(entry)
    assert model.prompt_price_per_million == 1.5
    assert model.completion_price_per_million == 6.0
    assert model.is_free is False


def test_normalize_missing_name_falls_back_to_id():
    entry = {"id": "some/model", "pricing": {}}
    model = _normalize(entry)
    assert model.name == "some/model"
    assert model.context_length is None
    assert model.prompt_price_per_million is None
    assert model.is_free is False
