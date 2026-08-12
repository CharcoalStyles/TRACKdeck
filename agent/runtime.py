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
import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException

from langchain_core.messages.utils import count_tokens_approximately

from agent.graph import get_fixed_overhead_tokens
from agent.keywords import generate_keyword, match_keyword_prefix
from agent.memory import MemoryStore
from agent.settings import settings
from utils.lmstudio_client import get_history_budget_tokens

from utils.notify import send_gotify, notify_error
from utils.recall_log_store import get_recall_for_thread

logger = logging.getLogger(__name__)

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
    # thread_id -> {"steps": [...], "done": bool} — populated live by a
    # run_agent(agent_run=True) call so a project page can poll progress
    # while it's still in flight. In-memory only: this is ephemeral,
    # in-flight-request data, not worth persisting (a restart mid-run
    # loses the request itself anyway).
    agent_activity: dict[str, dict] = {}


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


def create_background_thread() -> ThreadInfo:
    """
    Mint a new addressable thread without touching the default/recency
    pointer (app_state.default_thread_id/default_last_activity) — for
    threads created by a background process (jobs/checkin.py firing a
    mental-health check-in prompt) rather than direct user action.

    create_new_thread() is NOT a substitute here: it deliberately hijacks
    the default thread pointer for the dashboard's "New Chat" button, which
    would misroute the user's next unprefixed voice command into a
    check-in's thread instead of their actual last conversation.
    """
    return _start_new_thread(time.time())


def list_threads() -> list[ThreadInfo]:
    """All currently addressable threads, most recently active first."""
    return sorted(app_state.threads.values(), key=lambda t: t.last_activity, reverse=True)


def _last_digest_boundary(now: float) -> float:
    """The most recent moment jobs/digest.py's nightly sweep would have
    fired (today's settings.digest_time, or yesterday's if that hasn't
    happened yet today) — mirrors CronTrigger's own daily-firing logic."""
    tz = settings.zoneinfo()
    now_local = datetime.fromtimestamp(now, tz)
    hour, minute = (int(p) for p in settings.digest_time.split(":"))
    boundary = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if boundary > now_local:
        boundary -= timedelta(days=1)
    return boundary.timestamp()


async def rehydrate_threads_from_checkpoints() -> int:
    """
    Rebuilds app_state.threads/keywords from memory.db on startup — without
    this, the dashboard sidebar (GET /threads, sourced purely from those
    in-process dicts) shows no conversations after every restart even
    though memory.db itself is untouched (see CLAUDE.md's known
    limitations note). Only restores threads created after the most recent
    digest sweep boundary, since that sweep unconditionally clears
    app_state.threads/keywords once a day (jobs/digest.py) and memory.db's
    checkpoint rows are never deleted — this reproduces exactly what the
    in-memory dict would still hold had the process never restarted,
    rather than resurrecting the entire history every restart.

    Keywords aren't recoverable (never persisted anywhere), so each
    restored thread gets a freshly generated one via the same
    generate_keyword() normal thread creation uses.
    """
    boundary = _last_digest_boundary(time.time())
    checkpoints = await list_checkpoint_thread_ids()

    restored = []
    for row in checkpoints:
        thread_id = row["thread_id"]
        parts = thread_id.split("_")
        if len(parts) != 3 or parts[0] != "session" or not parts[1].isdigit():
            continue  # not a normal addressable thread (e.g. "onboarding", "profile_chat")
        created_at = float(parts[1])
        if created_at < boundary:
            continue
        keyword = generate_keyword(app_state.keywords)
        info = ThreadInfo(thread_id=thread_id, keyword=keyword, last_activity=created_at)
        app_state.threads[thread_id] = info
        app_state.keywords[keyword] = thread_id
        restored.append(info)

    if restored:
        latest = max(restored, key=lambda t: t.last_activity)
        app_state.default_thread_id = latest.thread_id
        app_state.default_last_activity = latest.last_activity

    return len(restored)


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
        if getattr(m, "tool_calls", None):
            continue  # AI requested a tool call, not a reply to show
        content = getattr(m, "content", None)
        if isinstance(content, str):
            content = content.strip()
        if not content:
            continue  # empty/whitespace-only messages
        msg_type = getattr(m, "type", None)
        if msg_type == "human":
            history.append({"role": "user", "content": content})
        elif msg_type == "ai":
            history.append({"role": "assistant", "content": content})
        # msg_type == "tool" (tool results) intentionally skipped
    return history


def _list_checkpoint_thread_ids_sync() -> list[dict]:
    conn = sqlite3.connect("data/memory.db")
    try:
        rows = conn.execute(
            "SELECT thread_id, MAX(checkpoint_id) AS latest_checkpoint_id "
            "FROM checkpoints GROUP BY thread_id ORDER BY 2 DESC"
        ).fetchall()
    except sqlite3.OperationalError:
        # Fresh memory.db, no checkpoints table yet — no thread has run a
        # turn through the graph since this file was created.
        rows = []
    finally:
        conn.close()
    return [{"thread_id": r[0], "latest_checkpoint_id": r[1]} for r in rows]


async def list_checkpoint_thread_ids() -> list[dict]:
    """
    Every thread_id that has ever run a turn through the graph, straight
    from memory.db's checkpoints table — independent of app_state.threads,
    which only holds currently-addressable threads and is swept nightly
    (jobs/digest.py). Used by the thread-debug dashboard page so a thread
    from before today's sweep (or before the last app restart) is still
    reachable, not just what GET /threads shows. Most recently active
    first (checkpoint_id is monotonically increasing per thread).
    """
    return await asyncio.to_thread(_list_checkpoint_thread_ids_sync)


def _stringify_message_content(content):
    """LangChain message content is typed as str | list[dict] — the list
    form is a sequence of multimodal content blocks (e.g.
    {"type": "text", "text": "..."}), which is what MCP-sourced tools
    (search_web and its searxng-mcp-server siblings, see
    agent/settings.py's _default_mcp_servers) actually hand back as
    ToolMessage.content; langchain_core/langgraph both pass that shape
    through unconverted rather than stringifying it. This repo's own
    tools all return plain str, so they're unaffected — but rendering the
    list form as-is (main.py's /debug/thread/{id} -> static/thread-debug.html)
    would just show "[object Object]" once JSON-serialized and dropped
    into the DOM. Flatten text blocks back into plain text; anything else
    falls back to a JSON dump so at least the raw shape is visible."""
    if content is None or isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    try:
        return json.dumps(content)
    except TypeError:
        return str(content)


async def get_thread_debug(thread_id: str) -> dict:
    """
    Unfiltered per-thread history for the thread-debug dashboard page —
    unlike get_thread_messages (which drops tool-call/tool-result messages
    since they don't render as chat bubbles), this keeps every message so
    tool calls and their results are visible. Also attaches this thread's
    recall log (utils/recall_log_store.py) — what agent/graph.py's
    search_conversations actually recalled — directly onto the "ai" turn
    it belongs to, not as a separate trailing section: agent/graph.py's
    call_llm logs exactly one recall_log row per invocation, and every
    invocation produces exactly one "ai" message in state, in the same
    order — including the tool-calling loop's intermediate steps, which
    re-run search_conversations against the same last_user_msg each time
    since no new human message arrives mid-loop. So the two lists are
    reliably 1:1 orderable by simple zip, no timestamp matching needed.
    """
    if app_state.graph is None:
        raise HTTPException(status_code=503, detail="Agent not initialised")

    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await app_state.graph.aget_state(config)
    messages = snapshot.values.get("messages", []) if snapshot else []

    turns = []
    opening_message = None
    for m in messages:
        msg_type = getattr(m, "type", None)
        entry = {"type": msg_type, "content": _stringify_message_content(getattr(m, "content", None))}
        if msg_type == "ai" and getattr(m, "tool_calls", None):
            entry["tool_calls"] = [
                {"name": tc["name"], "args": tc["args"]} for tc in m.tool_calls
            ]
        elif msg_type == "tool":
            entry["tool_name"] = getattr(m, "name", None)
            entry["tool_call_id"] = getattr(m, "tool_call_id", None)
        turns.append(entry)
        if opening_message is None and msg_type == "human":
            opening_message = entry["content"]

    recall_log = await asyncio.to_thread(get_recall_for_thread, thread_id)
    recall_iter = iter(recall_log)
    for entry in turns:
        if entry["type"] != "ai":
            continue
        recalled = next(recall_iter, None)
        if recalled is not None:
            entry["recall_query"] = recalled["query"]
            entry["recalled"] = recalled["recalled"]
        # else: this thread predates recall_log.db, or has more "ai" turns
        # than logged recalls for some other reason — leave unannotated
        # rather than mismatching a later turn's recall onto this one.

    return {
        "thread_id": thread_id,
        "opening_message": opening_message,
        "turns": turns,
    }


async def get_thread_size(thread_id: str) -> dict:
    """Rough context-load readout for a thread — same approximate counter
    and budget source agent/graph.py's call_llm trims against
    (count_tokens_approximately, and LM Studio's live loaded_context_length
    or the max_history_tokens fallback — see utils/lmstudio_client.py), so
    this reports what trimming will actually act on rather than a
    separately-drifting estimate. budget_tokens has the same fixed system
    prompt + tool schema overhead subtracted that call_llm reserves (see
    agent/graph.py's get_fixed_overhead_tokens) — mode addendum/memory block
    aren't known here, so this slightly underestimates the real headroom for
    onboarding/profile_chat, erring toward this reading going low too early
    rather than too late."""
    if app_state.graph is None:
        raise HTTPException(status_code=503, detail="Agent not initialised")

    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await app_state.graph.aget_state(config)
    messages = snapshot.values.get("messages", []) if snapshot else []

    budget = await get_history_budget_tokens()
    return {
        "message_count": len(messages),
        "estimated_tokens": count_tokens_approximately(messages),
        "budget_tokens": max(budget - get_fixed_overhead_tokens(), 0),
    }


async def clear_thread(thread_id: str) -> None:
    """Wipes a thread's LangGraph checkpoint history so its next turn
    starts fresh — the manual counterpart to call_llm's automatic trimming,
    for when the user wants a deliberate reset rather than gradual
    truncation of old context."""
    if app_state.graph is None:
        raise HTTPException(status_code=503, detail="Agent not initialised")
    await app_state.graph.checkpointer.adelete_thread(thread_id)


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


async def _run_graph_streamed(thread_id: str, cleaned_text: str, config: dict) -> dict:
    """
    Same graph execution as app_state.graph.ainvoke(), but consumed via
    astream(stream_mode="updates") so each node's output (an LLM step's
    tool calls, a tools step's results) can be recorded into
    app_state.agent_activity as it happens rather than only once the
    whole turn finishes — the polled feed behind a project page's "Run as
    agent" Activity panel. Checkpointing/tool binding/loop behavior is
    identical either way; astream just exposes it incrementally.
    """
    activity = {"steps": [], "done": False}
    app_state.agent_activity[thread_id] = activity
    try:
        async for step in app_state.graph.astream(
            {"messages": [{"role": "user", "content": cleaned_text}]},
            config=config,
            stream_mode="updates",
        ):
            for node_output in step.values():
                for msg in node_output.get("messages", []):
                    if getattr(msg, "tool_calls", None):
                        for tool_call in msg.tool_calls:
                            activity["steps"].append({
                                "type": "calling",
                                "tool": tool_call["name"],
                                "args": tool_call["args"],
                            })
                    elif getattr(msg, "type", None) == "tool":
                        content = _stringify_message_content(msg.content) or ""
                        activity["steps"].append({
                            "type": "result",
                            "tool": getattr(msg, "name", None),
                            "content": content[:300],
                        })
    finally:
        # Guarantees a polling client sees done=True even if the graph
        # raises, so the frontend poll loop can't spin forever — the
        # exception itself still propagates normally after this.
        activity["done"] = True

    snapshot = await app_state.graph.aget_state(config)
    return {"messages": snapshot.values.get("messages", [])}


def get_agent_activity(thread_id: str) -> dict:
    """Current (or last) agent_run progress for thread_id — always safe
    to poll, even for a thread that never ran one."""
    return app_state.agent_activity.get(thread_id, {"steps": [], "done": True})


async def run_agent(
    text: str,
    thread_id: str | None = None,
    one_shot: bool = False,
    mode: str | None = None,
    agent_run: bool = False,
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

    agent_run (only valid with mode="project_chat") reframes `text` as a
    goal to complete autonomously (PROJECT_AGENT_ADDENDUM) and records
    progress into app_state.agent_activity as it runs, pollable via
    get_agent_activity — see _run_graph_streamed.
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

    config = {
        "configurable": {
            "thread_id": thread_id, "one_shot": one_shot, "mode": mode, "agent_run": agent_run,
        }
    }

    async with get_thread_lock(thread_id):
        if agent_run:
            result = await _run_graph_streamed(thread_id, cleaned_text, config)
        else:
            result = await app_state.graph.ainvoke(
                {"messages": [{"role": "user", "content": cleaned_text}]},
                config=config,
            )
            for msg in result["messages"]:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        logger.info("Tool called: %s(%s)", tool_call["name"], tool_call["args"])
                elif msg.type == "tool":
                    logger.debug("Tool output: %s", msg.content)

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
        logger.error("Failed to save conversation summary for thread %s: %s", thread_id, e)
        notify_error("Conversation memory save failed (reply was still delivered)", e)

    return AgentResult(reply=reply, thread_id=thread_id, keyword=keyword)
