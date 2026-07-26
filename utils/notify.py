"""
utils/notify.py
----------------
Push notifications for background-task failures, via a self-hosted Gotify
instance.

Required env vars: GOTIFY_URL, GOTIFY_TOKEN
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)


def send_gotify(title: str, message: str, priority: int = 5, click_url: str | None = None) -> None:
    """
    Fire a push notification via Gotify. This is a blocking call (httpx
    sync client) — call it from async code via `asyncio.to_thread`.

    Deliberately swallows its own failures: if Gotify itself is
    unreachable, there's no further fallback channel configured, so we
    just log it rather than raising and losing the original error context
    the caller was trying to report.

    click_url, when set, adds Gotify's tap-to-open extras so the
    notification opens that URL when tapped — used by jobs/checkin.py's
    fire_checkin to link straight to static/checkin.html.
    """
    url = f"{os.environ['GOTIFY_URL'].rstrip('/')}/message"
    params = {"token": os.environ["GOTIFY_TOKEN"]}
    payload = {"title": title, "message": message, "priority": priority}
    if click_url:
        payload["extras"] = {"client::notification": {"click": {"url": click_url}}}

    try:
        response = httpx.post(url, params=params, json=payload, timeout=10.0)
        response.raise_for_status()
    except Exception as e:
        logger.error("Failed to send Gotify notification: %s", e)


def notify_error(context: str, error: Exception) -> None:
    """Convenience wrapper for reporting a background-task failure."""
    send_gotify(
        title="Assistant error",
        message=f"{context}: {error}",
        priority=8,
    )
