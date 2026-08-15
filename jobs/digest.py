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
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

from langchain_openai import ChatOpenAI

from agent.memory import MemoryStore
from agent.runtime import app_state, prune_thread_locks
from agent.settings import settings
from agent.vault_watcher import index_note_file
from jobs import checkin as checkin_jobs
from utils import checkins_store, vault
from utils.mailer import send_email
from utils.notify import notify_error
from voice import UPLOAD_DIR

logger = logging.getLogger(__name__)

RECEIVED_NOTES_MAX_AGE_SECONDS = 24 * 60 * 60

DIGEST_PROMPT = """You are writing a short, warm end-of-day recap for the person these \
notes belong to, based on a log of things they asked their personal assistant to do today.

Write a few short paragraphs (not a bullet list of raw log lines) that read like a brief, \
friendly summary of the day's activity — what they did, asked about, or got done. Keep it \
concise. If the log is sparse or empty, that's fine — just say the day looked quiet.

Also, tease out any themes or trends in the lo for today. It would also be helpful to \
surface any trends or themes that are surfacing over the past few days and weeks.

Today's logged activity:
{entries}

Today's check-in reflections (short gratitude/mood/wins prompts answered over the course \
of the day, if any): if there are entries below, weave any real mood/gratitude pattern \
they show into the recap warmly — don't just list them back. If it says none were \
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


def _write_recap(entries: list[str], reflections: list[str]) -> str:
    """Blocking LLM call — run via asyncio.to_thread from async code."""
    llm = ChatOpenAI(
        base_url=os.environ["LMSTUDIO_OPENAI_URL"],
        api_key="lm-studio",
        model=os.environ["CHAT_MODEL"],
        temperature=0.7,
    )
    joined = "\n---\n".join(entries) if entries else "(nothing logged today)"
    joined_reflections = "\n---\n".join(reflections) if reflections else "(none answered today)"
    response = llm.invoke(DIGEST_PROMPT.format(entries=joined, reflections=joined_reflections))
    return response.content


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
        recap = await asyncio.to_thread(_write_recap, entries, reflections)
    except Exception as e:
        logger.error("Daily digest failed to generate: %s", e)
        notify_error("Daily digest failed to generate", e)
        recap = None

    if recap is not None:
        now_local = datetime.now(settings.zoneinfo())
        today_str = now_local.strftime("%A, %d %B %Y")

        try:
            rating_block = _build_rating_block(answered)
            await asyncio.to_thread(send_email, f"Daily recap — {today_str}", recap + rating_block)
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
