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

import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

CHAT_PROVIDER = os.environ.get("LLM_PROVIDER", "lmstudio")


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
