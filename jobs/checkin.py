"""
jobs/checkin.py
-----------------
Mental-health check-in prompts — an Ecological Momentary Intervention (EMI)
pattern: 3-5 short reflective prompts a day, at randomized intervals bounded
to waking hours, deliberately NOT a fixed timer (avoids "alert fatigue").

Delivery is device-first (a future ESP32-S3 with an eink display, mic,
speaker — see main.py's GET /device/sync / POST /device/checkin/{id}/skip),
not phone-push-first; Gotify here is a secondary, silent record.

Scheduling state machine, mirroring jobs/reminders.py's one-shot pattern
("checkin:<id>" / "checkin_expire:<id>" DateTrigger jobs, see
agent/scheduler.py):
  - Answered, or a fallback retry that got skipped again -> full cooldown
    (STANDARD_COOLDOWN_RANGE) before the next prompt.
  - A fresh (non-retry) skip -> a fallback retry (FALLBACK_RETRY_RANGE)
    with a lighter category, via agent/checkin_prompts.FALLBACK_CATEGORY.
    Only one fallback retry is ever allowed in a row — a second skip on
    that retry forces the standard cooldown branch instead (the circuit
    breaker that keeps this from nagging on a busy day).
  - Fired-but-never-answered (expire_checkin) is treated as "expired" and
    routed to the standard cooldown branch too, not another fallback retry
    — silence more likely means offline/dead-battery than "too much right
    now", so a 30-90min retry would likely just expire again.

Every place that's about to schedule a NEW check-in checks the day's
target (3-5, decided once by jobs/day_start.py and persisted via
utils.checkins_store's day_plans table) and the waking-hours window
(settings.wake_time/settings.bedtime) first, and no-ops if either is
exhausted.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.date import DateTrigger

from agent.checkin_prompts import FALLBACK_CATEGORY, PROMPTS
from agent.runtime import AgentResult, create_background_thread, run_agent
from agent.scheduler import scheduler
from agent.settings import settings
from utils import checkins_store
from utils.notify import notify_error, send_gotify

logger = logging.getLogger(__name__)

STANDARD_COOLDOWN_RANGE = (timedelta(hours=3, minutes=30), timedelta(hours=5))
FALLBACK_RETRY_RANGE = (timedelta(minutes=30), timedelta(minutes=90))
WAKE_JITTER_RANGE = (timedelta(minutes=0), timedelta(minutes=45))
CHECKIN_EXPIRY = timedelta(hours=2)  # fired-but-never-answered -> 'expired'
CHECKIN_PRIORITY = 3  # silent/routine — the device's eink display is the primary surface


def _random_delay(bounds: tuple[timedelta, timedelta]) -> timedelta:
    low, high = bounds
    return timedelta(seconds=random.uniform(low.total_seconds(), high.total_seconds()))


def _pick_category(exclude: str | None, high_used: bool) -> str:
    eligible = [c for c in ("low", "medium", "high") if c != exclude]
    if high_used:
        eligible = [c for c in eligible if c != "high"]
    return random.choice(eligible)  # always non-empty: excludes at most 2 of 3


def _local_wake_and_bedtime(now_local: datetime) -> tuple[datetime, datetime]:
    wake_hour, wake_minute = (int(p) for p in settings.wake_time.split(":"))
    bed_hour, bed_minute = (int(p) for p in settings.bedtime.split(":"))
    wake_dt = now_local.replace(hour=wake_hour, minute=wake_minute, second=0, microsecond=0)
    bed_dt = now_local.replace(hour=bed_hour, minute=bed_minute, second=0, microsecond=0)
    return wake_dt, bed_dt


def waking_day_bounds(now_local: datetime) -> tuple[int, int]:
    """UTC epoch (start, end) for today's waking window ([wake_time,
    bedtime) on now_local's calendar date) — the day-boundary concept this
    feature uses for its 3-5/day cap and once/day 'high' rule. Deliberately
    separate from jobs/digest.py's midnight-anchored _todays_utc_bounds:
    the whole feature lives inside the waking window, not the calendar
    day."""
    wake_dt, bed_dt = _local_wake_and_bedtime(now_local)
    return (
        int(wake_dt.astimezone(timezone.utc).timestamp()),
        int(bed_dt.astimezone(timezone.utc).timestamp()),
    )


async def get_or_create_day_target(day_start_utc: int) -> int:
    """Today's check-in count (3-5), decided once and persisted so a
    restart doesn't reroll it. Normally decided by jobs/day_start.py at
    wake_time; the create path here is just a defensive fallback in case
    something needs it before that's run."""
    plan = await asyncio.to_thread(checkins_store.get_day_plan, day_start_utc)
    if plan is not None:
        return plan["target_count"]
    target = random.randint(3, 5)
    await asyncio.to_thread(checkins_store.create_day_plan, day_start_utc, target)
    return target


def _mint_thread() -> tuple[str, str]:
    info = create_background_thread()
    return info.thread_id, info.keyword


def _checkin_click_url(checkin: dict) -> str | None:
    """Deep-link into static/checkin.html for Gotify's tap-to-open extras.
    None (no click action, plain notification still fires) if
    PUBLIC_BASE_URL isn't set — additive, not required, so a missing var
    degrades gracefully instead of turning every firing into a reported
    error."""
    base = os.environ.get("PUBLIC_BASE_URL")
    if not base:
        return None
    params = urlencode({
        "id": checkin["id"],
        "category": checkin["category"],
        "prompt_text": checkin["prompt_text"],
    })
    return f"{base.rstrip('/')}/static/checkin.html?{params}"


async def answer_checkin(checkin_id: str, text: str) -> AgentResult | None:
    """Resolve a check-in by treating `text` (typed or transcribed) as the
    reply. Shared by every reply path (device voice, magic-link voice,
    magic-link text). Returns None if checkin_id is stale/unresolvable
    (unknown, already resolved, or never fired) so an *authenticated*
    caller can fall back to normal thread resolution — the magic-link
    routes in main.py/voice.py must NOT do that fallback themselves: an
    anonymous visitor with a stale id must get a hard error, never a
    live, unscoped conversation thread."""
    checkin = await asyncio.to_thread(checkins_store.get_checkin, checkin_id)
    if checkin is None or checkin["status"] != "pending" or checkin["thread_id"] is None:
        logger.warning("checkin_id %s not resolvable — falling back to normal resolution", checkin_id)
        return None
    text_for_agent = f'(Replying to check-in prompt: "{checkin["prompt_text"]}") {text}'
    result = await run_agent(text_for_agent, thread_id=checkin["thread_id"], one_shot=True)
    await resolve_checkin(checkin_id, outcome="answered")
    return result


async def _create_and_schedule(
    scheduled_at_local: datetime, category: str, retry_of: str | None
) -> None:
    checkin_id = str(uuid.uuid4())
    prompt_text = random.choice(PROMPTS[category])
    scheduled_at_utc = scheduled_at_local.astimezone(timezone.utc)
    await asyncio.to_thread(
        checkins_store.create_checkin,
        checkin_id,
        category,
        prompt_text,
        int(scheduled_at_utc.timestamp()),
        retry_of,
    )
    if scheduled_at_utc <= datetime.now(timezone.utc):
        await fire_checkin(checkin_id)
    else:
        scheduler.add_job(
            fire_checkin,
            trigger=DateTrigger(run_date=scheduled_at_utc),
            args=[checkin_id],
            id=f"checkin:{checkin_id}",
            replace_existing=True,
        )


async def schedule_first_of_day(
    now_local: datetime, day_start_utc: int, day_end_utc: int, target: int
) -> None:
    """Called by jobs/day_start.py's start_of_day_setup(). Idempotent —
    no-ops if today already has any scheduled/fired row, or we're outside
    [wake_time, bedtime) right now — safe to call unconditionally at
    startup as a catch-up for "app was down through today's wake_time"."""
    wake_dt, bed_dt = _local_wake_and_bedtime(now_local)
    if not (wake_dt <= now_local < bed_dt):
        return
    if await asyncio.to_thread(checkins_store.count_scheduled_today, day_start_utc, day_end_utc):
        return
    if target <= 0:
        return

    scheduled_at = max(now_local, wake_dt) + _random_delay(WAKE_JITTER_RANGE)
    if scheduled_at >= bed_dt:
        return
    await _create_and_schedule(scheduled_at, _pick_category(None, False), None)


async def fire_checkin(checkin_id: str) -> None:
    """Mirrors jobs/reminders.py's fire_reminder: re-fetches fresh from
    the DB, no-ops if the row is gone, already resolved, or already
    fired (guards against a stale/duplicate scheduler job)."""
    try:
        checkin = await asyncio.to_thread(checkins_store.get_checkin, checkin_id)
        if checkin is None or checkin["status"] != "pending" or checkin["fired_at"] is not None:
            return

        thread_id: str | None = None
        keyword: str | None = None
        if checkin["retry_of"] is not None:
            original = await asyncio.to_thread(checkins_store.get_checkin, checkin["retry_of"])
            if original and original["thread_id"]:
                thread_id, keyword = original["thread_id"], original["keyword"]
        if thread_id is None:
            thread_id, keyword = _mint_thread()

        fired_at = int(time.time())
        await asyncio.to_thread(checkins_store.mark_fired, checkin_id, thread_id, keyword, fired_at)
        await asyncio.to_thread(
            send_gotify,
            f"Check-in ({checkin['category']})",
            checkin["prompt_text"],
            CHECKIN_PRIORITY,
            _checkin_click_url(checkin),
        )
        scheduler.add_job(
            expire_checkin,
            trigger=DateTrigger(run_date=datetime.now(timezone.utc) + CHECKIN_EXPIRY),
            args=[checkin_id],
            id=f"checkin_expire:{checkin_id}",
            replace_existing=True,
        )
        logger.info("Fired check-in %s (%s): %s", checkin_id, checkin["category"], checkin["prompt_text"])
    except Exception as e:
        logger.error("Check-in %s failed to fire: %s", checkin_id, e)
        notify_error(f"Check-in failed to fire ({checkin_id})", e)


async def _schedule_next(resolved: dict, outcome: str) -> None:
    now_local = datetime.now(settings.zoneinfo())
    day_start_utc, day_end_utc = waking_day_bounds(now_local)
    target = await get_or_create_day_target(day_start_utc)
    scheduled_today = await asyncio.to_thread(
        checkins_store.count_scheduled_today, day_start_utc, day_end_utc
    )
    if scheduled_today >= target:
        return

    if outcome == "skipped" and resolved["retry_of"] is None:
        delay = _random_delay(FALLBACK_RETRY_RANGE)
        category = FALLBACK_CATEGORY[resolved["category"]]
        retry_of = resolved["id"]
    else:
        delay = _random_delay(STANDARD_COOLDOWN_RANGE)
        high_used = await asyncio.to_thread(
            checkins_store.high_used_today, day_start_utc, day_end_utc
        )
        last = await asyncio.to_thread(checkins_store.get_most_recent_fired)
        category = _pick_category(last["category"] if last else None, high_used)
        retry_of = None

    scheduled_at = now_local + delay
    _, bed_dt = _local_wake_and_bedtime(now_local)
    if scheduled_at >= bed_dt:
        return  # tomorrow's wake_time cron job (jobs/day_start.py) starts the next day's plan
    await _create_and_schedule(scheduled_at, category, retry_of)


async def resolve_checkin(checkin_id: str, outcome: str) -> None:
    """outcome: 'answered' | 'skipped' | 'expired'. Called from voice.py
    (answered), main.py's skip endpoint (skipped), and expire_checkin
    (expired)."""
    checkin = await asyncio.to_thread(checkins_store.get_checkin, checkin_id)
    if checkin is None or checkin["status"] != "pending":
        return  # already resolved elsewhere — don't double-schedule
    await asyncio.to_thread(checkins_store.mark_resolved, checkin_id, outcome, int(time.time()))
    try:
        scheduler.remove_job(f"checkin_expire:{checkin_id}")
    except JobLookupError:
        pass
    await _schedule_next(checkin, outcome)


async def expire_checkin(checkin_id: str) -> None:
    await resolve_checkin(checkin_id, outcome="expired")


async def next_wake_at() -> int:
    """Epoch seconds the device should set its next RTC wake alarm for —
    the earliest still-pending check-in, or tomorrow's wake_time if none
    are queued (e.g. today's target is already met)."""
    pending = await asyncio.to_thread(checkins_store.list_pending_unfired)
    if pending:
        return pending[0]["scheduled_at"]

    now_local = datetime.now(settings.zoneinfo())
    wake_dt, _ = _local_wake_and_bedtime(now_local)
    if now_local >= wake_dt:
        wake_dt += timedelta(days=1)
    return int(wake_dt.astimezone(timezone.utc).timestamp())
