"""
jobs/common.py
---------------
Shared pieces for the scheduled messages and reviews: one blocking writer-model
call, the wording rules every prompt shares, and delivery (Gotify push, plus
email when a recipient is set).
"""
from __future__ import annotations

import logging

from utils import mailer
from utils.llm_client import get_writer_llm, stringify_content
from utils.notify import send_gotify

logger = logging.getLogger(__name__)

WRITING_RULES = """Ground rules:
- Speak to the user directly ("you", "I"), as their assistant. Plain text only: no markdown, no headings, no bullet symbols other than "-".
- Only state what the material below shows. Never add names, numbers, times or outcomes that are not in it, and do not guess at feelings it doesn't show.
- A suggestion or offer is not something the user did. Calendar entries and reminders show what was planned, not what happened: never say the user attended or finished something unless a capture, a check-in answer or a tick says so.
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


def deliver(
    title: str, text: str, priority: int, *, push_text: str | None = None, click_url: str | None = None
) -> None:
    """Gotify push (push_text if given, else text) and, when email_to is set,
    the full text by email. Blocking — run via asyncio.to_thread. Both
    channels are always attempted; any failure is raised afterwards so the
    caller's error notification still fires."""
    errors: list[str] = []
    send_gotify(title, push_text or text, priority, *([click_url] if click_url else []))
    if mailer.email_wanted():
        missing = mailer.missing_smtp_env()
        if missing:
            errors.append(f"email_to is set but {', '.join(missing)} missing from the environment")
        else:
            try:
                mailer.send_email(title, text)
            except Exception as e:
                logger.error("Email send failed: %s", e)
                errors.append(f"email failed: {e}")
    if errors:
        raise RuntimeError("; ".join(errors))
