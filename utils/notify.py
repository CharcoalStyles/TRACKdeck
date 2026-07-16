"""
utils/notify.py
----------------
Push notifications for background-task failures, via a self-hosted Gotify
instance.

Required env vars: GOTIFY_URL, GOTIFY_TOKEN
"""
from __future__ import annotations

import os

import httpx


def send_gotify(title: str, message: str, priority: int = 5) -> None:
    """
    Fire a push notification via Gotify. This is a blocking call (httpx
    sync client) — call it from async code via `asyncio.to_thread`.

    Deliberately swallows its own failures: if Gotify itself is
    unreachable, there's no further fallback channel configured, so we
    just log it rather than raising and losing the original error context
    the caller was trying to report.
    """
    url = f"{os.environ['GOTIFY_URL'].rstrip('/')}/message"
    params = {"token": os.environ["GOTIFY_TOKEN"]}
    payload = {"title": title, "message": message, "priority": priority}

    try:
        response = httpx.post(url, params=params, json=payload, timeout=10.0)
        response.raise_for_status()
    except Exception as e:
        print(f"⚠️ Failed to send Gotify notification: {e}")


def notify_error(context: str, error: Exception) -> None:
    """Convenience wrapper for reporting a background-task failure."""
    send_gotify(
        title="Assistant error",
        message=f"{context}: {error}",
        priority=8,
    )
