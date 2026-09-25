"""
utils/openrouter_client.py
---------------------------
Thin client over OpenRouter's public model catalog
(https://openrouter.ai/api/v1/models) — no API key required just to list
models, only to actually run inference against one. Backs the dashboard's
"OpenRouter Models" admin page and, when LLM_PROVIDER=openrouter, the
history-trimming budget in agent/graph.py (same live-context-length idea
as utils/lmstudio_client.py, but sourced from this catalog instead of a
management API).

Cached in-memory with a short TTL — this is a ~450-model JSON response
fetched from a third party, no need to hit it on every request, but short
enough that a newly-published free model shows up on the admin page
without an app restart.
"""
from __future__ import annotations

import logging
import time

import httpx
from pydantic import BaseModel

from agent.settings import settings

logger = logging.getLogger(__name__)

MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL_SECONDS = 300


class OpenRouterModel(BaseModel):
    id: str
    name: str
    context_length: int | None
    prompt_price_per_million: float | None
    completion_price_per_million: float | None
    is_free: bool


_cache: list[OpenRouterModel] | None = None
_cache_fetched_at: float = 0.0


def _normalize(entry: dict) -> OpenRouterModel:
    pricing = entry.get("pricing") or {}
    prompt_str = pricing.get("prompt")
    completion_str = pricing.get("completion")
    prompt_price = float(prompt_str) * 1_000_000 if prompt_str is not None else None
    completion_price = float(completion_str) * 1_000_000 if completion_str is not None else None
    return OpenRouterModel(
        id=entry["id"],
        name=entry.get("name", entry["id"]),
        context_length=entry.get("context_length"),
        prompt_price_per_million=prompt_price,
        completion_price_per_million=completion_price,
        is_free=bool(prompt_price == 0 and completion_price == 0),
    )


async def fetch_models(force_refresh: bool = False) -> list[OpenRouterModel]:
    """The full OpenRouter catalog, cached for CACHE_TTL_SECONDS. Raises on
    a real fetch failure (network error, unexpected shape) when the cache
    is cold or force_refresh is set — this backs a user-facing admin page,
    so failures should surface rather than be swallowed; callers wanting a
    best-effort lookup (e.g. get_history_budget_tokens below) should catch
    around this themselves."""
    global _cache, _cache_fetched_at
    if _cache is not None and not force_refresh and (time.monotonic() - _cache_fetched_at) < CACHE_TTL_SECONDS:
        return _cache

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(MODELS_URL)
        response.raise_for_status()
        data = response.json()

    _cache = [_normalize(entry) for entry in data["data"]]
    _cache_fetched_at = time.monotonic()
    return _cache


async def get_history_budget_tokens() -> int:
    """Token budget for message history when LLM_PROVIDER=openrouter —
    settings.openrouter_chat_model's context_length from the cached catalog
    when available, else the dashboard-editable settings.max_history_tokens
    fallback (same one utils/lmstudio_client.py falls back to). Reads the
    live setting (not the OPENROUTER_CHAT_MODEL env var it was seeded from)
    so a dashboard model switch immediately gets the right budget too, not
    just a stale one left over from whatever was configured at startup.
    Best-effort: a catalog fetch failure here shouldn't break every chat
    turn, only the admin page that explicitly asks for the full list."""
    model_id = settings.openrouter_chat_model
    if not model_id:
        return settings.max_history_tokens
    try:
        models = await fetch_models()
    except Exception as e:
        logger.warning("Could not reach OpenRouter's model catalog for context length: %s", e)
        return settings.max_history_tokens

    for model in models:
        if model.id == model_id:
            return model.context_length or settings.max_history_tokens

    logger.warning(
        "OpenRouter's catalog has no entry matching settings.openrouter_chat_model=%r — "
        "falling back to max_history_tokens instead of this model's real context "
        "length; check the id matches exactly (e.g. 'provider/model:free').",
        model_id,
    )
    return settings.max_history_tokens
