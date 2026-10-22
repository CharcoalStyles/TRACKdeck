"""
jobs/common.py
---------------
Shared pieces for the scheduled messages and reviews: one blocking writer-model
call and the wording rules every prompt shares.
"""
from __future__ import annotations

from utils.llm_client import get_writer_llm, stringify_content

WRITING_RULES = """Ground rules:
- Speak to the user directly ("you", "I"), as their assistant. Plain text only: no markdown, no headings, no bullet symbols other than "-".
- Only state what the material below shows. Never add names, numbers, times or outcomes that are not in it, and do not guess at feelings it doesn't show.
- A suggestion or offer is not something the user did.
- If a section says "(none)", say nothing about it."""


def or_none(text: str) -> str:
    return text.strip() if text and text.strip() else "(none)"


def write(prompt: str, temperature: float = 0.7) -> str:
    """Blocking writer-model call — run via asyncio.to_thread."""
    response = get_writer_llm(temperature=temperature).invoke(prompt)
    text = (stringify_content(response.content) or "").strip()
    if not text:
        raise RuntimeError("writer model returned no text")
    return text
