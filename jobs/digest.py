"""
jobs/digest.py
---------------
Generates and sends the end-of-day recap email.

Scheduled (see main.py) for 20:45 Australia/Canberra time — 35 minutes
before the 21:20 bedtime-routine read, giving it headroom to run even on
a slow day or a slow local model.

Pulls today's conversation summaries out of long-term memory (the
`conversations` Chroma collection, already populated by
agent.runtime.run_agent on every successful turn) and asks the LLM to
write a short recap, rather than emailing the raw log.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

from langchain_openai import ChatOpenAI

from agent.memory import MemoryStore
from agent.runtime import app_state
from utils.mailer import send_email

LOCAL_TZ = ZoneInfo("Australia/Canberra")

DIGEST_PROMPT = """You are writing a short, warm end-of-day recap for the person these \
notes belong to, based on a log of things they asked their personal assistant to do today.

Write a few short paragraphs (not a bullet list of raw log lines) that read like a brief, \
friendly summary of the day's activity — what they did, asked about, or got done. Keep it \
concise. If the log is sparse or empty, that's fine — just say the day looked quiet.

Also, tease out any themes or trends in the lo for today. It would also be helpful to \
surface any trends or themes that are surfacing over the past few days and weeks.

Today's logged activity:
{entries}
"""


def _todays_utc_bounds(now_local: datetime | None = None) -> tuple[int, int]:
    """Return (start, end) as UTC epoch seconds for 'today' in LOCAL_TZ."""
    now_local = now_local or datetime.now(LOCAL_TZ)
    start_local = datetime.combine(now_local.date(), dtime.min, tzinfo=LOCAL_TZ)
    end_local = datetime.combine(now_local.date(), dtime.max, tzinfo=LOCAL_TZ)
    start_utc = int(start_local.astimezone(ZoneInfo("UTC")).timestamp())
    end_utc = int(end_local.astimezone(ZoneInfo("UTC")).timestamp())
    return start_utc, end_utc


def _write_recap(entries: list[str]) -> str:
    """Blocking LLM call — run via asyncio.to_thread from async code."""
    llm = ChatOpenAI(
        base_url=os.environ["LM_STUDIO_URL"],
        api_key="lm-studio",
        model=os.environ["CHAT_MODEL"],
        temperature=0.7,
    )
    joined = "\n---\n".join(entries) if entries else "(nothing logged today)"
    response = llm.invoke(DIGEST_PROMPT.format(entries=joined))
    return response.content


async def send_daily_digest(memory: MemoryStore) -> None:
    """Build today's recap and email it. Called by the scheduler in main.py."""
    start_ts, end_ts = _todays_utc_bounds()
    entries = memory.get_conversations_between(start_ts, end_ts)

    recap = await asyncio.to_thread(_write_recap, entries)

    today_str = datetime.now(LOCAL_TZ).strftime("%A, %d %B %Y")
    subject = f"Daily recap — {today_str}"

    await asyncio.to_thread(send_email, subject, recap)
    print(f"Daily digest sent for {today_str} ({len(entries)} logged entries).")

    # Keyword-addressed threads are a same-day concept — free them all up
    # now that the day's been recapped. The underlying LangGraph
    # checkpoint history isn't touched, just the keyword mapping that
    # makes a thread reachable by name.
    freed = len(app_state.threads)
    app_state.threads.clear()
    app_state.keywords.clear()
    app_state.default_thread_id = None
    print(f"Cleared {freed} addressable thread keyword(s) for the new day.")
