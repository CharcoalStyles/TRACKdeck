"""
jobs/bedtime.py
----------------
A fixed nightly nudge at settings.bedtime (default 21:20) — separate from
the passive daily digest (jobs/digest.py, ~20:45 by default, deliberately
a bit earlier). Distinct trigger, distinct purpose: the digest recaps the
day, this just says it's time to wind down.
"""
from __future__ import annotations

import asyncio
import logging

from utils.notify import notify_error, send_gotify

logger = logging.getLogger(__name__)

BEDTIME_MESSAGE = "Time to start winding down for bed."
BEDTIME_PRIORITY = 7  # same as ad-hoc reminders — should actually alert


async def send_bedtime_reminder() -> None:
    try:
        await asyncio.to_thread(send_gotify, "Bedtime", BEDTIME_MESSAGE, BEDTIME_PRIORITY)
        logger.info("Bedtime reminder sent.")
    except Exception as e:
        logger.error("Bedtime reminder failed: %s", e)
        notify_error("Bedtime reminder failed", e)
