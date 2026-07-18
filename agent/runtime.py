"""
agent/runtime.py
-----------------
Shared application state and the core agent-invocation logic.

Factored out of main.py so both the /text route and the fire-and-forget
/voice pipeline can share the same session/threading rules and the same
run_agent() call, without voice.py needing to import from main.py
(which would be circular, since main.py mounts voice.py's router).

Thread resolution has two layers:
  1. Keyword addressing — a spoken prefix ("Copper Wolf, ...") always
     reopens that specific thread, regardless of how long ago it was
     last used. Keywords are generated (not chosen) when a new thread
     starts, and stay addressable until the daily digest sweeps them at
     end of day (see jobs/digest.py).
  2. Recency — with no keyword prefix, falls back to the original
     inactivity rule: continue the most recent thread if used within
     SESSION_TIMEOUT_SECONDS, otherwise start a new one.
Keyword addressing always takes priority over recency when both could
apply.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

from fastapi import HTTPException

from agent.keywords import generate_keyword, match_keyword_prefix
from agent.memory import MemoryStore

from utils.notify import send_gotify

# A new default thread starts if more than this many seconds pass with
# no request and no keyword-addressed continuation.
SESSION_TIMEOUT_SECONDS = 5 * 60


@dataclass
class ThreadInfo:
    thread_id: str
    keyword: str
    last_activity: float


class AppState:
    graph = None
    memory: MemoryStore = None
    default_thread_id: str | None = None
    default_last_activity: float = 0.0
    threads: dict[str, ThreadInfo] = {}
    keywords: dict[str, str] = {}  # keyword -> thread_id


app_state = AppState()

_thread_locks: dict[str, asyncio.Lock] = {}


def get_thread_lock(thread_id: str) -> asyncio.Lock:
    if thread_id not in _thread_locks:
        _thread_locks[thread_id] = asyncio.Lock()
    return _thread_locks[thread_id]


def _start_new_thread(now: float) -> ThreadInfo:
    # int(now) alone can collide if two threads are created within the
    # same wall-clock second (e.g. rapid testing) — the random suffix
    # guarantees uniqueness regardless of timing.
    thread_id = f"session_{int(now)}_{uuid.uuid4().hex[:6]}"
    keyword = generate_keyword(app_state.keywords)
    info = ThreadInfo(thread_id=thread_id, keyword=keyword, last_activity=now)
    app_state.threads[thread_id] = info
    app_state.keywords[keyword] = thread_id
    return info


def resolve_thread(text: str) -> tuple[str, str, str]:
    """
    Figures out which thread `text` belongs to, and strips any keyword
    prefix from it before it's sent to the agent.

    Returns (thread_id, keyword, cleaned_text).
    """
    now = time.time()

    matched_keyword, cleaned_text = match_keyword_prefix(text, app_state.keywords)
    if matched_keyword is not None:
        thread_id = app_state.keywords[matched_keyword]
        info = app_state.threads.get(thread_id)
        if info is not None:
            info.last_activity = now
            app_state.default_thread_id = thread_id
            app_state.default_last_activity = now
            return thread_id, matched_keyword, cleaned_text
        # Keyword pointed at a thread that's since been cleared (shouldn't
        # normally happen — the keyword and thread are cleared together —
        # but fall through to normal resolution rather than erroring.

    stale = (
        app_state.default_thread_id is None
        or app_state.default_thread_id not in app_state.threads
        or (now - app_state.default_last_activity) > SESSION_TIMEOUT_SECONDS
    )
    if stale:
        info = _start_new_thread(now)
        app_state.default_thread_id = info.thread_id
    else:
        info = app_state.threads[app_state.default_thread_id]
        info.last_activity = now

    app_state.default_last_activity = now
    return info.thread_id, info.keyword, text


@dataclass
class AgentResult:
    reply: str
    thread_id: str
    keyword: str


async def run_agent(text: str, thread_id: str | None = None, one_shot: bool = False) -> AgentResult:
    """
    Runs one turn through the agent graph and returns the reply, along
    with which thread it landed in and that thread's keyword.

    If thread_id isn't given, it's resolved automatically: a keyword
    prefix in `text` takes priority, otherwise the recency rule applies.
    Passing thread_id explicitly (e.g. manual testing) skips keyword
    resolution entirely and uses that thread as-is.
    """
    if app_state.graph is None:
        raise HTTPException(status_code=503, detail="Agent not initialised")

    if thread_id is not None:
        cleaned_text = text
        info = app_state.threads.get(thread_id)
        keyword = info.keyword if info else ""
    else:
        thread_id, keyword, cleaned_text = resolve_thread(text)

    config = {"configurable": {"thread_id": thread_id, "one_shot": one_shot}}

    async with get_thread_lock(thread_id):
        result = await app_state.graph.ainvoke(
            {"messages": [{"role": "user", "content": cleaned_text}]},
            config=config,
        )

    for msg in result["messages"]:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tool_call in msg.tool_calls:
                print(f"🛠️ Tool Called: {tool_call['name']}")
                print(f"   Arguments:   {tool_call['args']}")
        elif msg.type == "tool":
            print(f"🔄 Tool Output: {msg.content}\n")

    reply = next(
        (m.content for m in reversed(result["messages"]) if m.content),
        "Done.",
    )

    summary = f"User: {cleaned_text}\nAssistant: {reply}"
    label = f"Assistant [{keyword}]" if keyword else "Assistant"
    # Priority 3 keeps this in Android's low-importance channel (silent,
    # shows in the shade) rather than the default channel (sound +
    # heads-up) — see the notes on Gotify priority tiers. Errors from
    # utils.notify.notify_error stay at priority 8, which is the tier
    # meant to interrupt you.
    send_gotify(label, summary, priority=3)
    app_state.memory.save_conversation_summary(summary, thread_id=thread_id)

    return AgentResult(reply=reply, thread_id=thread_id, keyword=keyword)
