"""
utils/notify.py
----------------
Push notifications for background-task failures, via a self-hosted Gotify
instance.

Gotify URL/token are agent.settings fields (seeded from GOTIFY_URL/
GOTIFY_TOKEN at startup, editable/persisted live via the Settings page
from there) rather than read directly from os.environ.
"""
from __future__ import annotations

import logging
import time

import httpx

from agent.settings import settings

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
    url = f"{settings.gotify_url.rstrip('/')}/message"
    params = {"token": settings.gotify_token}
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


_DEVICE_ERROR_COOLDOWN_SECONDS = 1800  # 30 min — adjustable

# Process-memory only, resets on restart — same reasoning as auth.py's
# _login_attempts tracking, not worth a DB table for this.
_last_device_error_alert: dict[str, float] = {}


def notify_device_error(
    error_type: str, message: str, cooldown_seconds: int = _DEVICE_ERROR_COOLDOWN_SECONDS
) -> bool:
    """
    Push a priority-8 Gotify alert for a device-reported error (main.py's
    POST /device/error), deduped per error_type so a firmware retry loop
    hitting the same failure every wake doesn't spam Gotify — same
    "don't alert on every transient failure" philosophy
    jobs/calendar_sync.py already applies to its own transient errors.

    Deduping is keyed on error_type alone, not the full message, since
    the goal is suppressing repeats of the same underlying condition even
    if its detail text varies (e.g. a changing free-heap number). The
    cooldown clock only advances on an actual send, not on a suppressed
    call, so a continuous retry loop can't keep resetting it and prevent
    ever re-alerting.

    Always logs, sent or suppressed, so a stuck retry loop stays visible
    in server logs even while Gotify itself is throttled.

    Returns True if a notification was actually sent, False if
    suppressed by the cooldown.
    """
    logger.warning("Device reported error [%s]: %s", error_type, message)

    now = time.time()
    last = _last_device_error_alert.get(error_type)
    if last is not None and now - last < cooldown_seconds:
        return False

    _last_device_error_alert[error_type] = now
    send_gotify(title=f"Device error: {error_type}", message=message, priority=8)
    return True
