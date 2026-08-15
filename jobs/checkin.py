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
(settings.wake_time/settings.latest_checkin_time) first, and no-ops if
either is exhausted.
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
from langchain_openai import ChatOpenAI

from agent.checkin_prompts import FALLBACK_CATEGORY, PROMPTS
from agent.memory import MemoryStore
from agent.runtime import AgentResult, create_background_thread, run_agent
from agent.scheduler import scheduler
from agent.settings import settings
from utils import activity_log_store, checkins_store, vault
from utils.notify import notify_error, send_gotify

logger = logging.getLogger(__name__)

STANDARD_COOLDOWN_RANGE = (timedelta(hours=3, minutes=30), timedelta(hours=5))
FALLBACK_RETRY_RANGE = (timedelta(minutes=30), timedelta(minutes=90))
WAKE_JITTER_RANGE = (timedelta(minutes=0), timedelta(minutes=45))
CHECKIN_EXPIRY = timedelta(hours=2)  # fired-but-never-answered -> 'expired'
CHECKIN_PRIORITY = 3  # silent/routine — the device's eink display is the primary surface

PERSONALIZATION_LEVELS = ("none", "select", "light")  # the live rotation real
# check-ins are randomly assigned from — "moderate" (below) is deliberately
# excluded, reachable only via preview_personalization for manual testing.

SELECT_PROMPT_TEMPLATE = """You are choosing which single check-in prompt best fits this \
person right now, from a fixed list. Output ONLY one of the listed prompts, copied \
character-for-character — do not write a new one, do not alter punctuation or wording.

{context}

Candidate prompts:
{candidates}

Reply with ONLY the chosen prompt text, nothing else."""

LIGHT_PROMPT_TEMPLATE = """Lightly reword the check-in prompt below so it references \
something specific about this person. Keep the same rough length and tone, keep the same \
core meaning, and it must still end in a question mark.

{context}

Base prompt: "{base_prompt}"

Reply with ONLY the reworded prompt, nothing else — no quotes, no preamble."""

MODERATE_PROMPT_TEMPLATE = """Rework the check-in prompt below so it draws more directly \
on this person's context — you can restructure the sentence, not just swap in a \
reference, as long as the core meaning and category of prompt stay the same. Keep it \
roughly the same length, and it must still end in a question mark.

{context}

Base prompt: "{base_prompt}"

Reply with ONLY the reworked prompt, nothing else — no quotes, no preamble."""


def _random_delay(bounds: tuple[timedelta, timedelta]) -> timedelta:
    low, high = bounds
    return timedelta(seconds=random.uniform(low.total_seconds(), high.total_seconds()))


def _pick_category(exclude: str | None, high_used: bool) -> str:
    eligible = [c for c in ("low", "medium", "high") if c != exclude]
    if high_used:
        eligible = [c for c in eligible if c != "high"]
    return random.choice(eligible)  # always non-empty: excludes at most 2 of 3


def _local_checkin_window(now_local: datetime) -> tuple[datetime, datetime]:
    wake_hour, wake_minute = (int(p) for p in settings.wake_time.split(":"))
    end_hour, end_minute = (int(p) for p in settings.latest_checkin_time.split(":"))
    wake_dt = now_local.replace(hour=wake_hour, minute=wake_minute, second=0, microsecond=0)
    checkin_end_dt = now_local.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    return wake_dt, checkin_end_dt


def waking_day_bounds(now_local: datetime) -> tuple[int, int]:
    """UTC epoch (start, end) for today's check-in window ([wake_time,
    latest_checkin_time) on now_local's calendar date) — the day-boundary
    concept this feature uses for its 3-5/day cap and once/day 'high'
    rule. Deliberately separate from jobs/digest.py's midnight-anchored
    _todays_utc_bounds: the whole feature lives inside this window, not
    the calendar day."""
    wake_dt, checkin_end_dt = _local_checkin_window(now_local)
    return (
        int(wake_dt.astimezone(timezone.utc).timestamp()),
        int(checkin_end_dt.astimezone(timezone.utc).timestamp()),
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
    public_base_url isn't set — additive, not required, so a missing
    value degrades gracefully instead of turning every firing into a
    reported error."""
    base = settings.public_base_url
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


def _personalization_llm() -> ChatOpenAI:
    return ChatOpenAI(
        base_url=os.environ["LMSTUDIO_OPENAI_URL"],
        api_key="lm-studio",
        model=os.environ["CHAT_MODEL"],
        temperature=0.35,
    )


def _llm_select(bank: list[str], context: str) -> str:
    """Blocking — call via asyncio.to_thread, wrapped in asyncio.wait_for."""
    candidates = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(bank))
    llm = _personalization_llm()
    return llm.invoke(SELECT_PROMPT_TEMPLATE.format(context=context, candidates=candidates)).content.strip()


def _llm_light_reword(base_prompt: str, context: str) -> str:
    """Blocking — call via asyncio.to_thread."""
    llm = _personalization_llm()
    return llm.invoke(LIGHT_PROMPT_TEMPLATE.format(context=context, base_prompt=base_prompt)).content.strip()


def _llm_moderate_reword(base_prompt: str, context: str) -> str:
    """Blocking — call via asyncio.to_thread. Preview-only (see
    PERSONALIZATION_LEVELS) — not part of the live rotation."""
    llm = _personalization_llm()
    return llm.invoke(MODERATE_PROMPT_TEMPLATE.format(context=context, base_prompt=base_prompt)).content.strip()


def _personalization_context(values_text: str | None, recent_activity: list[dict]) -> str:
    parts = []
    if values_text:
        parts.append(f"Their stated personal values:\n{values_text}")
    if recent_activity:
        summary = "; ".join(f"{a['activity_type']}: {a['subject']}" for a in recent_activity[:8])
        parts.append(f"Their logged activity in the last 24h: {summary}")
    return "\n\n".join(parts)


async def _gather_context() -> str:
    about_me = await asyncio.to_thread(vault.get_or_create_about_me)
    values_text = vault.get_section(about_me.body, "Values")
    now = int(time.time())
    recent_activity = await asyncio.to_thread(activity_log_store.list_between, now - 86400, now)
    return _personalization_context(values_text, recent_activity)


async def _personalize_prompt(category: str) -> tuple[str, str]:
    """Picks the prompt text and returns (prompt_text, level_actually_delivered)
    — NOT the level attempted. "select"/"light" fall back to the plain bank
    pick (recording "none") on any validation miss or LLM error, so a
    check-in's recorded level always reflects what the user actually
    received, keeping later helpfulness ratings honest.

    No timeout on the LLM call — check-in timing was never meant to be
    tight (there's no external trigger like location/heart-rate driving
    it, just a semi-randomized spread through the day), so there's nothing
    for a fast local response to protect; a slow model just takes longer
    to schedule the next one.

    Random three-way split (none/select/light) per check-in is deliberate —
    it's the A/B mechanism for comparing whether personalization is worth it
    for this person at all, decided from their own helpfulness ratings over
    time rather than assumed upfront. "moderate" is excluded from this live
    rotation on purpose — see preview_personalization to try it out first."""
    bank = PROMPTS[category]
    level = random.choice(PERSONALIZATION_LEVELS)
    if level == "none":
        return random.choice(bank), "none"

    context = await _gather_context()
    if not context:
        # Nothing to personalize against yet (no Values section, no recent
        # activity) — skip the LLM call entirely rather than spend a round
        # trip asking it to personalize against nothing.
        return random.choice(bank), "none"

    try:
        if level == "select":
            chosen = await asyncio.to_thread(_llm_select, bank, context)
            if chosen in bank:
                return chosen, "select"
        else:  # "light"
            base = random.choice(bank)
            reworded = await asyncio.to_thread(_llm_light_reword, base, context)
            if reworded and reworded.endswith("?") and len(reworded) < 300:
                return reworded, "light"
    except Exception as e:
        logger.warning("Check-in personalization (%s) failed, falling back: %s", level, e)

    return random.choice(bank), "none"


async def preview_personalization(category: str, level: str) -> dict:
    """Debug-only: run one personalization level on demand and return the
    raw LLM output plus whether it would pass the real validation — without
    creating a checkin row, scheduling anything, or silently falling back.
    The point is to let you actually see what a given (possibly slow) local
    model returns, not hide a bad output behind a fallback the way the live
    path does. "moderate" only exists on this path — it's never part of
    PERSONALIZATION_LEVELS, so it can't be picked for a real check-in."""
    bank = PROMPTS[category]
    context = await _gather_context()

    base_prompt: str | None = None
    if level == "select":
        raw = await asyncio.to_thread(_llm_select, bank, context)
        valid = raw in bank
    elif level == "light":
        base_prompt = random.choice(bank)
        raw = await asyncio.to_thread(_llm_light_reword, base_prompt, context)
        valid = bool(raw) and raw.endswith("?") and len(raw) < 300
    elif level == "moderate":
        base_prompt = random.choice(bank)
        raw = await asyncio.to_thread(_llm_moderate_reword, base_prompt, context)
        valid = bool(raw) and raw.endswith("?") and len(raw) < 300
    else:
        raise ValueError(f"Unknown personalization level: {level}")

    return {
        "category": category,
        "level": level,
        "context_used": context or None,
        "base_prompt": base_prompt,
        "result": raw,
        "would_pass_validation": valid,
    }


def _rate_urls(checkin_id: str) -> tuple[str, str] | None:
    """(up_url, down_url) for the daily digest's thumbs-up/down links. None
    if public_base_url isn't set — same degrade-gracefully contract as
    _checkin_click_url below; the digest omits the rating block entirely
    rather than emailing a broken link."""
    base = settings.public_base_url
    if not base:
        return None
    root = f"{base.rstrip('/')}/checkin/{checkin_id}/rate"
    return f"{root}?helpful=yes", f"{root}?helpful=no"


async def _create_and_schedule(
    scheduled_at_local: datetime, category: str, retry_of: str | None
) -> None:
    checkin_id = str(uuid.uuid4())
    prompt_text, personalization_level = await _personalize_prompt(category)
    scheduled_at_utc = scheduled_at_local.astimezone(timezone.utc)
    await asyncio.to_thread(
        checkins_store.create_checkin,
        checkin_id,
        category,
        prompt_text,
        int(scheduled_at_utc.timestamp()),
        retry_of,
        personalization_level,
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


async def trigger_test_checkin() -> None:
    """Debug-only on-demand check-in (see main.py's POST /debug/checkin).
    Reuses _create_and_schedule exactly as a real check-in would — real
    DB row, real minted thread, real Gotify push — but deliberately
    bypasses the day's 3-5 target and waking-hours checks that
    schedule_first_of_day/_schedule_next enforce for real prompts, since
    this is an explicit manual test. scheduled_at_local is 'now', so
    _create_and_schedule's own `<= now` check fires it immediately."""
    now_local = datetime.now(settings.zoneinfo())
    await _create_and_schedule(now_local, _pick_category(None, False), None)


async def schedule_first_of_day(
    now_local: datetime, day_start_utc: int, day_end_utc: int, target: int
) -> None:
    """Called by jobs/day_start.py's start_of_day_setup(). Idempotent —
    no-ops if today already has any scheduled/fired row, or we're outside
    [wake_time, latest_checkin_time) right now — safe to call
    unconditionally at startup as a catch-up for "app was down through
    today's wake_time"."""
    wake_dt, checkin_end_dt = _local_checkin_window(now_local)
    if not (wake_dt <= now_local < checkin_end_dt):
        return
    if await asyncio.to_thread(checkins_store.count_scheduled_today, day_start_utc, day_end_utc):
        return
    if target <= 0:
        return

    scheduled_at = max(now_local, wake_dt) + _random_delay(WAKE_JITTER_RANGE)
    if scheduled_at >= checkin_end_dt:
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
    _, checkin_end_dt = _local_checkin_window(now_local)
    if scheduled_at >= checkin_end_dt:
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
    wake_dt, _ = _local_checkin_window(now_local)
    if now_local >= wake_dt:
        wake_dt += timedelta(days=1)
    return int(wake_dt.astimezone(timezone.utc).timestamp())


async def reflections_between(memory: MemoryStore, start_ts: int, end_ts: int) -> list[dict]:
    """Structured record of every check-in resolved within
    [start_ts, end_ts] (UTC epoch seconds) — answered, skipped, or
    expired. An answered check-in's reply text is looked up by its own
    dedicated thread from Chroma (checkins.db doesn't store the reply
    itself — every check-in mints its own thread via _mint_thread, and
    agent.runtime.run_agent summarizes+embeds each turn there like any
    other conversation); skipped/expired ones have reply=None. Used by
    main.py's GET /checkins/today for the dashboard's check-in history
    page."""
    resolved = await asyncio.to_thread(checkins_store.list_resolved_between, start_ts, end_ts)
    results = []
    for checkin in resolved:
        reply = None
        if checkin["status"] == "answered" and checkin["thread_id"]:
            reply = memory.get_conversation_by_thread(checkin["thread_id"])
        results.append(
            {
                "id": checkin["id"],
                "category": checkin["category"],
                "prompt_text": checkin["prompt_text"],
                "status": checkin["status"],
                "scheduled_at": checkin["scheduled_at"],
                "fired_at": checkin["fired_at"],
                "resolved_at": checkin["resolved_at"],
                "reply": reply,
                "personalization_level": checkin["personalization_level"],
                "helpfulness": checkin["helpfulness"],
            }
        )
    return results
