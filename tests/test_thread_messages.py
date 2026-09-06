import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.runtime import app_state, get_thread_messages


def test_get_thread_messages_drops_tool_call_and_whitespace_ai_messages(monkeypatch):
    messages = [
        HumanMessage(content="what's the weather like"),
        AIMessage(content=" ", tool_calls=[{"name": "get_weather", "args": {}, "id": "1"}]),
        ToolMessage(content="15C, cloudy", tool_call_id="1"),
        AIMessage(content="\n", tool_calls=[{"name": "get_forecast", "args": {}, "id": "2"}]),
        ToolMessage(content="rain tomorrow", tool_call_id="2"),
        AIMessage(content="It's 15C and cloudy now, with rain expected tomorrow."),
    ]

    class FakeGraph:
        async def aget_state(self, config):
            return SimpleNamespace(values={"messages": messages})

    monkeypatch.setattr(app_state, "graph", FakeGraph())

    history = asyncio.run(get_thread_messages("some-thread"))

    assert history == [
        {"role": "user", "content": "what's the weather like"},
        {"role": "assistant", "content": "It's 15C and cloudy now, with rain expected tomorrow."},
    ]


def test_get_thread_messages_flattens_list_content(monkeypatch):
    """Gemini's AIMessage.content is a list of content blocks (each with a
    "text" key plus provider-specific extras like a thought signature), not
    a plain string — this must be flattened or FastAPI's response model
    (content: str) rejects it."""
    messages = [
        HumanMessage(content="what's Finian's birthday"),
        AIMessage(content=[{"type": "text", "text": "August 20, 2020.", "extras": {"signature": "abc"}}]),
    ]

    class FakeGraph:
        async def aget_state(self, config):
            return SimpleNamespace(values={"messages": messages})

    monkeypatch.setattr(app_state, "graph", FakeGraph())

    history = asyncio.run(get_thread_messages("some-thread"))

    assert history == [
        {"role": "user", "content": "what's Finian's birthday"},
        {"role": "assistant", "content": "August 20, 2020."},
    ]
