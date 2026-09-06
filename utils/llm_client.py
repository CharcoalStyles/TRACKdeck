"""
utils/llm_client.py
--------------------
Single factory for the chat-completion LLM client. Embeddings are
untouched — always LM Studio, see agent/memory.py's make_embedding_function.
LLM_PROVIDER (env var, default "lmstudio") picks between the local
OpenAI-compatible endpoint and a hosted Gemini model. Env-var only, read
once at import time — switching providers requires an app restart.
"""
from __future__ import annotations

import json
import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

CHAT_PROVIDER = os.environ.get("LLM_PROVIDER", "lmstudio")


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


def get_chat_llm(temperature: float) -> BaseChatModel:
    if CHAT_PROVIDER == "gemini":
        return ChatGoogleGenerativeAI(
            model=os.environ["GEMINI_CHAT_MODEL"],
            google_api_key=os.environ["GEMINI_API_KEY"],
            temperature=temperature,
        )
    return ChatOpenAI(
        base_url=os.environ["LMSTUDIO_OPENAI_URL"],
        api_key="lm-studio",
        model=os.environ["CHAT_MODEL"],
        temperature=temperature,
    )
