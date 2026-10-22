"""
jobs/digest.py
---------------
Generates and sends the end-of-day recap email.

Scheduled (see main.py) via settings.digest_time/settings.timezone,
defaulting to 20:45 local — 35 minutes before a 21:20 bedtime-routine
read, giving it headroom to run even on a slow day or a slow local model.

Pulls today's conversation summaries out of long-term memory (the
`conversations` Chroma collection, already populated by
agent.runtime.run_agent on every successful turn) and asks the LLM to
write a short recap, rather than emailing the raw log.

Today's answered mental-health check-ins (jobs/checkin.py) are pulled out
separately via checkins_store.list_answered_between and their replies
looked up by thread, so gratitude/mood/wins reflections get their own
prompt section instead of blending anonymously into the general log.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

from agent.memory import MemoryStore
from agent.runtime import app_state, prune_thread_locks
from agent.settings import settings
from agent.vault_watcher import index_note_file
from jobs import checkin as checkin_jobs
from utils import checkins_store, vault
from utils.llm_client import get_writer_llm, stringify_content
from utils.mailer import send_email
from utils.notify import notify_error
from voice import UPLOAD_DIR

logger = logging.getLogger(__name__)

RECEIVED_NOTES_MAX_AGE_SECONDS = 24 * 60 * 60

HISTORY_DAYS = 7
HISTORY_MAX_CHARS_PER_DAY = 1500

DIGEST_PROMPT = """You are the user's personal assistant, writing them a short, warm \
end-of-day recap. Speak to them directly ("you asked me to...", "I set..."), as their \
assistant. Do not write it as a journal entry in their voice.

Based on the log of what they asked you to do today, write a few short paragraphs (not a \
bullet list of raw log lines): what they did, asked about, or got done. Keep it concise. \
If the log is sparse or empty, just say the day looked quiet.

Ground rules:
- Only state what the log below shows. Do not add details, names, numbers, times or \
outcomes that are not in it, and do not guess at feelings the log doesn't show.
- Suggestions and offers you made are not things the user did. Do not say a suggested \
walk, task or plan was completed unless the log says so.
- If a request failed or went unanswered in the log, say so plainly rather than glossing it.

Themes and trends: mention a theme from today if there is a real one. A trend across days \
counts only if the same thing appears in the earlier recaps below on 3 or more separate \
days (including today). Judge that from what those recaps say happened, not from any \
"trend" they claim. If the earlier recaps are missing, too few, or show no such pattern, \
say nothing about trends, weeks, or "lately".

Today's logged activity:
{entries}

Earlier recaps, oldest first (may be empty):
{history}

Today's check-in reflections (short gratitude/mood/wins prompts answered over the course \
of the day, if any): if there are entries below, weave any real mood/gratitude pattern \
they show into the recap warmly, without listing them back. If it says none were \
answered, don't mention check-ins at all.
{reflections}
"""


def _todays_utc_bounds(now_local: datetime | None = None) -> tuple[int, int]:
    """Return (start, end) as UTC epoch seconds for 'today' in the user's
    configured timezone (settings.timezone)."""
    local_tz = settings.zoneinfo()
    now_local = now_local or datetime.now(local_tz)
    start_local = datetime.combine(now_local.date(), dtime.min, tzinfo=local_tz)
    end_local = datetime.combine(now_local.date(), dtime.max, tzinfo=local_tz)
    start_utc = int(start_local.astimezone(ZoneInfo("UTC")).timestamp())
    end_utc = int(end_local.astimezone(ZoneInfo("UTC")).timestamp())
    return start_utc, end_utc


def _load_previous_recaps(today: date, days: int = HISTORY_DAYS) -> list[str]:
    """Blocking vault reads — run via asyncio.to_thread. The last `days`
    daily-digest notes before `today`, oldest first, each headed by its
    date. Days with no note (app was down, digest failed) are simply
    absent, never filled in, so the model can't mistake a gap for data."""
    recaps = []
    for offset in range(days, 0, -1):
        day = today - timedelta(days=offset)
        note = vault.parse_note(vault.daily_note_path(day.isoformat()))
        if note is None or vault.DAILY_NOTE_TAG not in note.tags:
            continue
        body = note.body.strip()
        if not body:
            continue
        if len(body) > HISTORY_MAX_CHARS_PER_DAY:
            body = body[:HISTORY_MAX_CHARS_PER_DAY].rstrip() + "..."
        recaps.append(f"[{day.strftime('%A %d %B %Y')}]\n{body}")
    return recaps


def _write_recap(entries: list[str], reflections: list[str], history: list[str] | None = None) -> str:
    """Blocking LLM call — run via asyncio.to_thread from async code."""
    llm = get_writer_llm(temperature=0.7, surface="digest")
    joined = "\n---\n".join(entries) if entries else "(nothing logged today)"
    joined_reflections = "\n---\n".join(reflections) if reflections else "(none answered today)"
    joined_history = "\n\n".join(history) if history else "(no earlier recaps available)"
    response = llm.invoke(
        DIGEST_PROMPT.format(entries=joined, history=joined_history, reflections=joined_reflections)
    )
    return stringify_content(response.content) or ""


def _todays_checkin_reflections(memory: MemoryStore, answered: list[dict]) -> tuple[list[str], set[str]]:
    """Today's answered check-ins (jobs/checkin.py), formatted as
    prompt/reply pairs, plus the set of their thread_ids so the caller can
    keep them out of the generic conversation log. A reply's summary lives
    in Chroma under the check-in's own dedicated thread, not in
    checkins.db itself, so this looks it up via
    MemoryStore.get_conversation_by_thread. Takes the already-fetched
    answered list rather than querying itself — send_daily_digest needs
    that same list for the rating block below too."""
    reflections = []
    thread_ids = set()
    for checkin in answered:
        thread_id = checkin["thread_id"]
        if not thread_id:
            continue
        thread_ids.add(thread_id)
        reply = memory.get_conversation_by_thread(thread_id)
        if reply:
            reflections.append(f'Prompt ({checkin["category"]}): "{checkin["prompt_text"]}"\nReply: {reply}')
    return reflections, thread_ids


def _build_rating_block(answered: list[dict]) -> str:
    """Deterministic string-building, no LLM call — a thumbs-up/down link
    pair per answered check-in, appended to the email body only (not the
    vault note, which is a long-lived document that shouldn't carry
    tracking-link plumbing). Empty string (nothing appended) if there were
    no answered check-ins today, or if public_base_url isn't configured
    (checkin_jobs._rate_urls returns None) — same graceful-degradation
    contract as the rest of this feature's link-building."""
    lines = []
    for checkin in answered:
        urls = checkin_jobs._rate_urls(checkin["id"])
        if urls is None:
            return ""
        up_url, down_url = urls
        snippet = checkin["prompt_text"]
        if len(snippet) > 80:
            snippet = snippet[:77] + "..."
        lines.append(f'{checkin["category"]} check-in: "{snippet}" — helpful? Yes: {up_url}  No: {down_url}')
    return "\n\nHow were today's check-in prompts?\n" + "\n".join(lines) if lines else ""


def _reflection_url(date_str: str) -> str | None:
    """Deep link into the dashboard's authenticated /reflection page —
    same None-if-unset contract as checkin_jobs._checkin_click_url/
    _rate_urls. Unlike those (magic-link, no session), this route sits
    behind require_session_or_token — it's opened from your own
    logged-in browser via the recap email, not a bare push notification."""
    base = settings.public_base_url
    if not base:
        return None
    return f"{base.rstrip('/')}/reflection?date={date_str}&session=planning"


def _build_reflection_block(date_str: str) -> str:
    """Only links to a reflection if a planning note actually exists for
    today — a plain Tuesday shouldn't offer a reflection link for a plan
    that was never made."""
    if vault.parse_note(vault.planning_note_path(date_str)) is None:
        return ""
    url = _reflection_url(date_str)
    if url is None:
        return ""
    return f"\n\nHow did today's plan go? {url}"


def _write_recap_to_vault(recap: str, now_local: datetime) -> vault.Note:
    """Write today's recap into the vault as a dated note, alongside the
    email rather than instead of it. Deterministic path (see
    vault.daily_note_path) — re-running the digest for a day that already
    has a note updates it in place rather than creating a duplicate."""
    date_str = now_local.strftime("%Y-%m-%d")
    path = vault.daily_note_path(date_str)
    existing = vault.parse_note(path)
    now = vault.now_iso()

    note = vault.Note(
        id=existing.id if existing else vault.generate_id(),
        title=f"Daily Digest — {now_local.strftime('%A, %d %B %Y')}",
        created=existing.created if existing else now,
        updated=now,
        tags=[vault.DAILY_NOTE_TAG],
        source="agent",
        body=recap.strip() + "\n",
        path=path,
    )
    vault.write_note_atomic(path, vault.serialize_note(note))
    return note


def _prune_received_notes() -> int:
    """Blocking filesystem sweep — run via asyncio.to_thread. Raw voice
    recordings are only ever useful briefly (debugging a misheard command);
    there's no reason to keep them longer than about a day."""
    if not os.path.isdir(UPLOAD_DIR):
        return 0
    cutoff = time.time() - RECEIVED_NOTES_MAX_AGE_SECONDS
    pruned = 0
    for name in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                pruned += 1
        except OSError:
            continue
    return pruned


async def send_daily_digest(memory: MemoryStore) -> None:
    """Build today's recap, email it and write it into the vault, then
    sweep the thread/keyword registry. Called by the scheduler in main.py.

    The email and vault write are independent once the recap text exists —
    one failing (transient SMTP error, a vault write error) shouldn't cost
    you the other. The sweep always runs regardless of either succeeding —
    keyword-addressed threads are a same-day concept independent of
    whether the day actually got recapped, and silently keeping
    yesterday's keywords alive would be a worse failure mode than losing
    one day's digest.
    """
    answered: list[dict] = []
    try:
        start_ts, end_ts = _todays_utc_bounds()
        answered = await asyncio.to_thread(checkins_store.list_answered_between, start_ts, end_ts)
        reflections, checkin_thread_ids = await asyncio.to_thread(
            _todays_checkin_reflections, memory, answered
        )
        entries = memory.get_conversations_between(start_ts, end_ts, exclude_thread_ids=checkin_thread_ids)
        today_local = datetime.now(settings.zoneinfo()).date()
        history = await asyncio.to_thread(_load_previous_recaps, today_local)
        recap = await asyncio.to_thread(_write_recap, entries, reflections, history)
    except Exception as e:
        logger.error("Daily digest failed to generate: %s", e)
        notify_error("Daily digest failed to generate", e)
        recap = None

    if recap is not None:
        now_local = datetime.now(settings.zoneinfo())
        today_str = now_local.strftime("%A, %d %B %Y")

        try:
            rating_block = _build_rating_block(answered)
            reflection_block = _build_reflection_block(now_local.strftime("%Y-%m-%d"))
            await asyncio.to_thread(
                send_email, f"Daily recap — {today_str}", recap + rating_block + reflection_block
            )
            logger.info("Daily digest emailed for %s (%d logged entries).", today_str, len(entries))
        except Exception as e:
            logger.error("Daily digest email failed: %s", e)
            notify_error("Daily digest email failed", e)

        try:
            note = await asyncio.to_thread(_write_recap_to_vault, recap, now_local)
            await index_note_file(memory, note.path)
            logger.info("Daily digest written to vault note %s.", note.path.name)
        except Exception as e:
            logger.error("Daily digest vault write failed: %s", e)
            notify_error("Daily digest vault write failed", e)

    # Keyword-addressed threads are a same-day concept — free them all up
    # now that the day's over, regardless of whether the recap/email/vault
    # write above succeeded. The underlying LangGraph checkpoint history
    # isn't touched, just the keyword mapping that makes a thread
    # reachable by name.
    freed = len(app_state.threads)
    app_state.threads.clear()
    app_state.keywords.clear()
    app_state.default_thread_id = None
    pruned = prune_thread_locks()
    logger.info(
        "Cleared %d addressable thread keyword(s) for the new day (%d stale lock(s) pruned).",
        freed, pruned,
    )

    try:
        notes_pruned = await asyncio.to_thread(_prune_received_notes)
        logger.info("Pruned %d received voice recording(s) older than a day.", notes_pruned)
    except Exception as e:
        logger.error("Failed to prune received_notes: %s", e)
        notify_error("Received-notes cleanup failed", e)
