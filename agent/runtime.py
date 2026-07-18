"""
agent/runtime.py
-----------------
Shared application state and the core agent-invocation logic.

Factored out of main.py so both the /text route and the fire-and-forget
/voice pipeline can share the same session/threading rules and the same
run_agent() call, without voice.py needing to import from main.py
(which would be circular, since main.py mounts voice.py's router).
"""
from __future__ import annotations

import asyncio
import time

from fastapi import HTTPException

from agent.memory import MemoryStore

from utils.notify import send_gotify

# A new session starts if more than this many seconds pass with no request.
SESSION_TIMEOUT_SECONDS = 5 * 60


class AppState:
    graph = None
    memory: MemoryStore = None
    current_thread_id: str | None = None
    last_activity: float = 0.0


app_state = AppState()

_thread_locks: dict[str, asyncio.Lock] = {}


def get_thread_lock(thread_id: str) -> asyncio.Lock:
    if thread_id not in _thread_locks:
        _thread_locks[thread_id] = asyncio.Lock()
    return _thread_locks[thread_id]


def resolve_thread_id() -> str:
    """
    Returns the thread_id for 'the current session'.

    Starts a new session (new thread_id) if more than SESSION_TIMEOUT_SECONDS
    have passed since the last request; otherwise keeps reusing the active
    one. There's a single logical device/session in play here (one ESP32,
    plus the browser test UI), so this is one global session rather than
    something keyed per-user.
    """
    now = time.time()
    if (
        app_state.current_thread_id is None
        or (now - app_state.last_activity) > SESSION_TIMEOUT_SECONDS
    ):
        app_state.current_thread_id = f"session_{int(now)}"
    app_state.last_activity = now
    return app_state.current_thread_id


async def run_agent(text: str, thread_id: str | None = None, one_shot: bool = False) -> str:
    """
    Runs one turn through the agent graph and returns the reply text.

    If thread_id isn't given, it's resolved automatically via the
    inactivity-based session rule above. Callers that want a specific
    thread (e.g. manual testing) can still pass one explicitly.

    one_shot=True switches the system prompt to a mode that never ends on
    a clarifying question — for testing the behavior real hardware will
    need, where there's no way to hear a follow-up. This is deliberately
    passed via config rather than folded into the persisted message
    state: it's a per-request setting, not something that should get
    saved into this thread's checkpoint and silently affect later turns.
    """
    if app_state.graph is None:
        raise HTTPException(status_code=503, detail="Agent not initialised")

    if thread_id is None:
        thread_id = resolve_thread_id()

    config = {"configurable": {"thread_id": thread_id, "one_shot": one_shot}}

    async with get_thread_lock(thread_id):
        result = await app_state.graph.ainvoke(
            {"messages": [{"role": "user", "content": text}]},
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

    summary = f"User: {text}\nAssistant: {reply}"
    send_gotify("Assistant", summary)
    app_state.memory.save_conversation_summary(summary, thread_id=thread_id)

    return reply
