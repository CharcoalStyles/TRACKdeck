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

from utils.notify import send_gotify, notify_error

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


def prune_thread_locks() -> int:
    """Drop lock entries that aren't currently held. thread_ids are unique
    per session and never reused, so once a thread is gone (swept nightly,
    per jobs/digest.py) its lock entry is pure garbage — this dict is
    otherwise never cleaned up and grows for the life of the process.
    Skips anything currently locked so an in-flight turn can't have its
    lock object pulled out from under it (a new get_thread_lock call for
    the same thread_id would hand out a second Lock that no longer
    mutually excludes the first)."""
    stale = [tid for tid, lock in _thread_locks.items() if not lock.locked()]
    for tid in stale:
        del _thread_locks[tid]
    return len(stale)


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


def create_new_thread() -> ThreadInfo:
    """
    Explicitly mint a new addressable thread with no message sent yet —
    used by the main chat page's "New Chat" button, so a fresh thread
    shows up in the sidebar immediately rather than only appearing after
    the first reply. Threads made this way are identical to ones started
    by voice — same keyword addressing, same nightly sweep, no special
    casing by origin.
    """
    now = time.time()
    info = _start_new_thread(now)
    app_state.default_thread_id = info.thread_id
    app_state.default_last_activity = now
    return info


def list_threads() -> list[ThreadInfo]:
    """All currently addressable threads, most recently active first."""
    return sorted(app_state.threads.values(), key=lambda t: t.last_activity, reverse=True)


async def get_thread_messages(thread_id: str) -> list[dict]:
    """
    Reads a thread's conversation history directly from the checkpointer
    (not from the memory.py conversation-summary log, which is a
    separate, lossier long-term-recall mechanism). Filtered down to just
    human/assistant turns with real content — internal tool-call and
    tool-result messages are left out, since they wouldn't make sense
    rendered as chat bubbles.
    """
    if app_state.graph is None:
        raise HTTPException(status_code=503, detail="Agent not initialised")

    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await app_state.graph.aget_state(config)
    messages = snapshot.values.get("messages", []) if snapshot else []

    history = []
    for m in messages:
        content = getattr(m, "content", None)
        if not content:
            continue  # tool-call-only AI messages, empty messages
        msg_type = getattr(m, "type", None)
        if msg_type == "human":
            history.append({"role": "user", "content": content})
        elif msg_type == "ai":
            history.append({"role": "assistant", "content": content})
        # msg_type == "tool" (tool results) intentionally skipped
    return history


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


async def run_agent(
    text: str,
    thread_id: str | None = None,
    one_shot: bool = False,
    mode: str | None = None,
) -> AgentResult:
    """
    Runs one turn through the agent graph and returns the reply, along
    with which thread it landed in and that thread's keyword.

    If thread_id isn't given, it's resolved automatically: a keyword
    prefix in `text` takes priority, otherwise the recency rule applies.
    Passing thread_id explicitly (e.g. manual testing, or the fixed
    "onboarding"/"profile_chat" threads used by the dashboard's chat
    pages) skips keyword resolution entirely and uses that thread as-is.

    mode switches the system prompt into a different active behavior —
    "onboarding" (driving a getting-to-know-you interview) or
    "profile_chat" (answering/updating questions about the profile) —
    mutually exclusive with passive learning mode.
    """
    if app_state.graph is None:
        raise HTTPException(status_code=503, detail="Agent not initialised")

    if thread_id is not None:
        cleaned_text = text
        info = app_state.threads.get(thread_id)
        keyword = info.keyword if info else ""
    else:
        thread_id, keyword, cleaned_text = resolve_thread(text)

    if not cleaned_text.strip():
        # A keyword-only utterance (e.g. an accidental double button-press)
        # — nothing was actually said beyond the callsign. resolve_thread
        # has already done the reconnect (last_activity, default thread).
        # Treat this as a no-op: skip the LLM call, the memory embed, and
        # the Gotify push, none of which should fire for a turn that
        # carried no real content.
        return AgentResult(
            reply=f'Reconnected to "{keyword}".' if keyword else "Ready.",
            thread_id=thread_id,
            keyword=keyword,
        )

    config = {"configurable": {"thread_id": thread_id, "one_shot": one_shot, "mode": mode}}

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
    await asyncio.to_thread(send_gotify, label, summary, priority=3)

    # The reply is already final at this point — a failure here (embeddings
    # backend down, Chroma write error) shouldn't turn a successful turn
    # into an unhandled 500 on /text, or a false "voice pipeline failed"
    # alert from /voice's catch-all. Isolate it, but still surface it since
    # a silent failure here means future recall silently degrades.
    try:
        app_state.memory.save_conversation_summary(summary, thread_id=thread_id)
    except Exception as e:
        print(f"⚠️ Failed to save conversation summary for thread {thread_id}: {e}")
        notify_error("Conversation memory save failed (reply was still delivered)", e)

    return AgentResult(reply=reply, thread_id=thread_id, keyword=keyword)
