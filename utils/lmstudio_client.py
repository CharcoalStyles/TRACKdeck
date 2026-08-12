"""
utils/lmstudio_client.py
-------------------------
Live lookup of the currently loaded chat model's actual context length,
via LM Studio's own management REST API (LMSTUDIO_MANAGEMENT_URL) — a
different server surface from LMSTUDIO_OPENAI_URL, the OpenAI-compatible
endpoint used for chat/embeddings. LM Studio has no way to report the
model's context length over that OpenAI-compatible surface; the
management API's /models endpoint has it as loaded_context_length (what
the model was actually loaded with, e.g. tuned down from its max to fit
RAM — as opposed to max_context_length, its architectural ceiling).

Optional and best-effort throughout: if LMSTUDIO_MANAGEMENT_URL isn't
set, the model isn't currently loaded, or the request fails for any
reason (host unreachable, timeout, unexpected shape), callers fall back
to their own default rather than this being treated as fatal.
"""
from __future__ import annotations

import logging
import os

import httpx

from agent.settings import settings

logger = logging.getLogger(__name__)


async def get_loaded_context_length() -> int | None:
    """loaded_context_length for CHAT_MODEL from LM Studio's
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

    chat_model = os.environ["CHAT_MODEL"]
    for entry in data.get("data", []):
        if entry.get("id") == chat_model and entry.get("state") == "loaded":
            return entry.get("loaded_context_length")
    return None


async def get_history_budget_tokens() -> int:
    """Token budget for message history sent to the LLM — LM Studio's
    live loaded_context_length when available, else the dashboard-tunable
    settings.max_history_tokens fallback (agent/settings.py)."""
    live = await get_loaded_context_length()
    return live if live is not None else settings.max_history_tokens
