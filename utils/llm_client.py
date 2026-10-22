"""
utils/llm_client.py
--------------------
Single factory for the chat-completion LLM client: always LM Studio's
OpenAI-compatible endpoint.
"""
from __future__ import annotations

import json
import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from agent.settings import settings


def stringify_content(content):
    """LangChain message content is typed as str | list[dict] — the list
    form is a sequence of multimodal content blocks (e.g.
    {"type": "text", "text": "..."}), which is what MCP-sourced tools
    (search_web and its searxng-mcp-server siblings) hand back as
    ToolMessage.content — langchain_core/langgraph both pass either shape through
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


def get_chat_llm(temperature: float) -> BaseChatModel:
    return ChatOpenAI(
        base_url=os.environ["LMSTUDIO_OPENAI_URL"],
        api_key="lm-studio",
        model=settings.lmstudio_chat_model,
        temperature=temperature,
    )


def get_writer_llm(temperature: float) -> BaseChatModel:
    """LLM for prose the user reads: settings.lmstudio_writer_model when set,
    otherwise identical to get_chat_llm()."""
    model = settings.lmstudio_writer_model
    if model:
        return ChatOpenAI(
            base_url=os.environ["LMSTUDIO_OPENAI_URL"],
            api_key="lm-studio",
            model=model,
            temperature=temperature,
        )
    return get_chat_llm(temperature)


def describe_chat_llm() -> dict:
    """Model and base_url get_chat_llm() builds right now, for the dashboard's
    Testing page. No credentials included."""
    return {
        "provider": "lmstudio",
        "model": settings.lmstudio_chat_model or None,
        "base_url": os.environ.get("LMSTUDIO_OPENAI_URL"),
    }
