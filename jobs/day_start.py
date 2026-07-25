"""
jobs/day_start.py
-------------------
Beginning-of-day setup — the symmetric counterpart to jobs/digest.py's
end-of-day recap. Scheduled (see main.py) via agent/scheduler.py's
wake_trigger() at settings.wake_time.

Right now this only decides today's mental-health check-in target (3-5,
randomized, persisted so a restart doesn't reroll it — see jobs/checkin.py)
and schedules the first prompt of the day. Expected to grow the same way
jobs/digest.py did (recap -> +email -> +vault write -> +thread sweep ->
+received-notes prune), not meant to stay single-purpose.
"""
from __future__ import annotations

import logging
from datetime import datetime

from agent.settings import settings
from jobs import checkin

logger = logging.getLogger(__name__)


async def start_of_day_setup() -> None:
    now_local = datetime.now(settings.zoneinfo())
    day_start_utc, day_end_utc = checkin.waking_day_bounds(now_local)

    target = await checkin.get_or_create_day_target(day_start_utc)
    logger.info("Day plan for today: %d check-in(s) targeted.", target)

    # Idempotent — no-ops if today already has a scheduled/fired row, or
    # we're outside [wake_time, bedtime) right now. Safe to call
    # unconditionally at startup as a catch-up for "app was down through
    # wake_time".
    await checkin.schedule_first_of_day(now_local, day_start_utc, day_end_utc, target)
