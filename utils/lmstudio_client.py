"""
utils/lmstudio_client.py
-------------------------
Live lookup of the currently loaded chat model's actual context length,
plus a catalog of every model LM Studio has downloaded, via LM Studio's
own management REST API (LMSTUDIO_MANAGEMENT_URL) — a different server
surface from LMSTUDIO_OPENAI_URL, the OpenAI-compatible endpoint used for
chat/embeddings. LM Studio has no way to report a model's context length
or its full local catalog over that OpenAI-compatible surface; the
management API's /models endpoint has both — loaded_context_length (what
the model was actually loaded with, e.g. tuned down from its max to fit
RAM — as opposed to max_context_length, its architectural ceiling) and
every downloaded model regardless of whether it's currently loaded.
Backs the dashboard's LM Studio Models admin card, same idea as
utils/openrouter_client.py's catalog but sourced locally instead of from
a public internet endpoint.

Optional and best-effort throughout: if LMSTUDIO_MANAGEMENT_URL isn't
set, the model isn't currently loaded, or the request fails for any
reason (host unreachable, timeout, unexpected shape), callers fall back
to their own default (or an empty catalog) rather than this being
treated as fatal.
"""
from __future__ import annotations

import logging
import os

import httpx
from pydantic import BaseModel

from agent.settings import settings

logger = logging.getLogger(__name__)


class LmStudioModel(BaseModel):
    id: str
    # "loaded" or "not-loaded" — LM Studio only serves chat completions for
    # a model that's actually loaded; picking a "not-loaded" one here just
    # sets which model name gets requested; whether it responds afterward
    # depends on LM Studio's own just-in-time loading setting or you
    # loading it by hand.
    state: str
    max_context_length: int | None
    loaded_context_length: int | None


async def get_loaded_context_length() -> int | None:
    """loaded_context_length for LMSTUDIO_CHAT_MODEL from LM Studio's
    /api/v0/models, or None if it can't be determined (management URL
    not configured, model not currently loaded, or the request failed).
    No caching — this is a cheap LAN call, refetched fresh every time so
    a mid-session model reload in LM Studio is picked up immediately;
    add a short TTL cache if this ever shows up as a real latency cost."""
    base_url = os.environ.get("LMSTUDIO_MANAGEMENT_URL")
    if not base_url:
        return None

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{base_url.rstrip('/')}/models")
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        logger.warning("Could not reach LM Studio's management API for context length: %s", e)
        return None

    chat_model = settings.lmstudio_chat_model
    entries = data.get("data", [])
    for entry in entries:
        if entry.get("id") == chat_model and entry.get("state") == "loaded":
            return entry.get("loaded_context_length")

    # The API call succeeded but nothing matched — silently falling back
    # to settings.max_history_tokens here previously gave zero indication
    # of *why*, which reads as "the model has a tiny context" when the
    # real cause is usually just settings.lmstudio_chat_model not exactly
    # matching what LM Studio reports (quant suffix, exact name) after
    # switching models. Log what we were looking for against what's
    # actually loaded so a mismatch is obvious from the logs instead of a
    # guessing game.
    loaded_ids = [e.get("id") for e in entries if e.get("state") == "loaded"]
    logger.warning(
        "LM Studio's management API has no loaded entry matching "
        "settings.lmstudio_chat_model=%r — currently loaded: %r. Falling "
        "back to the max_history_tokens setting instead of this model's "
        "real context length; check the LM Studio Models admin page picked "
        "a model that's actually loaded.",
        chat_model, loaded_ids,
    )
    return None


async def get_history_budget_tokens() -> int:
    """Token budget for message history sent to the LLM — LM Studio's
    live loaded_context_length when available, else the dashboard-tunable
    settings.max_history_tokens fallback (agent/settings.py)."""
    live = await get_loaded_context_length()
    return live if live is not None else settings.max_history_tokens


async def fetch_models() -> list[LmStudioModel]:
    """Every chat-capable model LM Studio currently has downloaded, via the
    same management API surface as get_loaded_context_length() above. No
    caching — a cheap LAN call, and staying uncached means a model just
    downloaded/loaded in LM Studio shows up on the dashboard's LM Studio
    Models admin card immediately. Empty list if LMSTUDIO_MANAGEMENT_URL
    isn't set or the request fails — the dashboard falls back to a plain
    text field in that case.

    Excludes by type == "embeddings" rather than including by type ==
    "llm": LM Studio also reports vision-capable models as "vlm", which are
    just as chat-completion-capable over the same OpenAI-compatible
    endpoint (get_chat_llm() doesn't care), so an allowlist of just "llm"
    silently dropped every VLM a user had loaded — this excludes only the
    one type that's actually not usable here."""
    base_url = os.environ.get("LMSTUDIO_MANAGEMENT_URL")
    if not base_url:
        return []

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{base_url.rstrip('/')}/models")
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        logger.warning("Could not reach LM Studio's management API for its model catalog: %s", e)
        return []

    return [
        LmStudioModel(
            id=entry["id"],
            state=entry.get("state", "not-loaded"),
            max_context_length=entry.get("max_context_length"),
            loaded_context_length=entry.get("loaded_context_length"),
        )
        for entry in data.get("data", [])
        if entry.get("type") != "embeddings"
    ]
