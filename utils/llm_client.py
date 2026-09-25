"""
utils/llm_client.py
--------------------
Single factory for the chat-completion LLM client. Embeddings are
untouched — always LM Studio, see agent/memory.py's make_embedding_function.
settings.llm_provider (agent/settings.py, seeded from the LLM_PROVIDER env
var, default "lmstudio") picks between the local OpenAI-compatible
endpoint, a hosted Gemini model, and OpenRouter (also OpenAI-compatible —
same ChatOpenAI shape as lmstudio, just pointed at OpenRouter's endpoint;
see utils/openrouter_client.py for its model catalog/pricing browser).
Unlike before, lmstudio/openrouter are live-switchable from the dashboard's
Settings page, no restart needed — every call site here reads
settings.llm_provider fresh rather than a value frozen at import time (the
one exception, agent/graph.py's tool-bound LLM, caches one client per
provider it has actually been asked for, since building a fresh
ChatOpenAI/ChatGoogleGenerativeAI client is pure object construction, but
still keyed by the live value each turn — see build_graph's
_get_llm_with_tools). gemini remains reachable only via LLM_PROVIDER at
startup, not the dashboard switch — see agent/settings.py's llm_provider
docstring. Which *model* OpenRouter uses is a separate, live-editable
concern — see settings.openrouter_chat_model and agent/graph.py's
call_llm, which re-binds it fresh every turn rather than trusting whatever
get_chat_llm() built at startup/job-run time.
"""
from __future__ import annotations

import json
import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from agent.settings import settings


def openrouter_configured() -> bool:
    """Whether OPENROUTER_API_KEY is set — the dashboard's llm_provider
    switch (main.py's SettingsUpdate validation) only allows switching to
    "openrouter" when this is true, since get_chat_llm() below raises a
    KeyError constructing that client otherwise."""
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def stringify_content(content):
    """LangChain message content is typed as str | list[dict] — the list
    form is a sequence of multimodal content blocks (e.g.
    {"type": "text", "text": "..."}), which is what MCP-sourced tools
    (search_web and its searxng-mcp-server siblings) hand back as
    ToolMessage.content, and what Gemini's AIMessage.content looks like too
    (each block carries a "signature"/thought-signature key alongside
    "text") — langchain_core/langgraph both pass either shape through
    unconverted rather than stringifying it. Flatten text blocks back into
    plain text; anything else falls back to a JSON dump so at least the
    raw shape is visible."""
    if content is None or isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    try:
        return json.dumps(content)
    except TypeError:
        return str(content)


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def get_chat_llm(temperature: float, provider: str | None = None) -> BaseChatModel:
    provider = provider or settings.llm_provider
    if provider == "gemini":
        return ChatGoogleGenerativeAI(
            model=os.environ["GEMINI_CHAT_MODEL"],
            google_api_key=os.environ["GEMINI_API_KEY"],
            temperature=temperature,
        )
    if provider == "openrouter":
        return ChatOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=os.environ["OPENROUTER_API_KEY"],
            model=settings.openrouter_chat_model,
            temperature=temperature,
        )
    return ChatOpenAI(
        base_url=os.environ["LMSTUDIO_OPENAI_URL"],
        api_key="lm-studio",
        model=settings.lmstudio_chat_model,
        temperature=temperature,
    )


def describe_chat_llm() -> dict:
    """Which provider/model/base_url get_chat_llm() actually builds right
    now, straight from the live settings.llm_provider — for the
    dashboard's Testing page. No credentials included."""
    provider = settings.llm_provider
    if provider == "gemini":
        return {
            "provider": "gemini",
            "model": os.environ.get("GEMINI_CHAT_MODEL"),
            "base_url": None,
        }
    if provider == "openrouter":
        return {
            "provider": "openrouter",
            "model": settings.openrouter_chat_model or None,
            "base_url": OPENROUTER_BASE_URL,
        }
    return {
        "provider": "lmstudio",
        "model": settings.lmstudio_chat_model or None,
        "base_url": os.environ.get("LMSTUDIO_OPENAI_URL"),
    }
