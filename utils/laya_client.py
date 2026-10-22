"""
utils/laya_client.py
---------------------
Thin wrapper around pydecide's decision-model client (Laya by default —
see decision-model-brief.md and the scratchpad/ Phase A/B investigation),
backing the dashboard's Laya Playground admin page
(routes/laya_playground.py). This is a standalone experimentation surface,
not the tool-router integration the Phase A/B plan explored — nothing
here is wired into agent/graph.py's actual tool-calling path.

pydecide is deliberately NOT a project dependency yet (not in
pyproject.toml/uv.lock, same as Phase B's scratch-venv approach) — every
import of `decide` here is lazy, so this module (and anything that
imports it, including main.py at startup) loads fine even before it's
installed. Calling any function below without it installed raises
LayaNotInstalled with the exact command to fix it.

To actually deploy this: `uv add "pydecide[laya]"` (CPU wheels — see
scratchpad/'s note about avoiding the CUDA-tagged torch wheel via
--index-url .../whl/cpu on a GPU-less box), then restart the app so
get_client() below picks it up.
"""
from __future__ import annotations

import asyncio
from typing import Any


class LayaNotInstalled(RuntimeError):
    """pydecide isn't installed in this environment yet."""

    def __init__(self):
        super().__init__('pydecide isn\'t installed — run `uv add "pydecide[laya]"` first.')


_client_singleton: Any = None


def _get_client():
    """Client.from_env(), built once and cached — loading Laya's weights
    is the expensive part (seconds, not milliseconds), so this must not
    happen per-request. Matches this codebase's existing pattern for
    expensive-to-construct clients (agent/graph.py's cached per-provider
    LLM clients)."""
    global _client_singleton
    if _client_singleton is None:
        try:
            from decide import Client
        except ImportError as e:
            raise LayaNotInstalled() from e
        _client_singleton = Client.from_env()
    return _client_singleton


def get_tool_candidates() -> dict[str, str]:
    """Live tool name -> one-line description, straight from the actual
    registered tool surface (agent/tools/all_tools.py) rather than a
    hand-maintained copy that could drift — backs the Playground's "Tool"
    mode so it's always testing against what the agent can really call
    today. Constructing get_tools() with a dummy memory object is safe:
    the note tools only close over it, never touch it until actually
    invoked (same approach used for yesterday's tool-schema token-cost
    measurement)."""
    from agent.tools.all_tools import get_tools

    tools = get_tools(memory=object())
    candidates = {}
    for t in tools:
        first_line = (t.description or t.name).strip().splitlines()[0]
        candidates[t.name] = first_line[:200]
    return candidates


def _answer_to_dict(name: str, answer: Any) -> dict:
    """Normalizes any of pydecide's three Answer dataclasses into one
    JSON-friendly shape the frontend can render generically."""
    from decide import ChoiceAnswer, NoulAnswer, ScoreAnswer

    if isinstance(answer, ChoiceAnswer):
        return {
            "choice": answer.choice,
            "options": [{"name": k, "probability": v} for k, v in answer.probabilities.items()],
        }
    if isinstance(answer, NoulAnswer):
        return {"yes_probability": answer.noul}
    if isinstance(answer, ScoreAnswer):
        return {
            "score": answer.score,
            "levels": answer.levels,
            "options": [
                {"name": level, "probability": p} for level, p in zip(answer.levels, answer.probabilities)
            ],
        }
    raise TypeError(f"Unrecognized answer type for {name!r}: {type(answer)}")


def _meta_to_dict(meta: Any) -> dict:
    return {"backend": meta.backend, "model": meta.model, "latency_ms": meta.latency_ms, "route": list(meta.route)}


async def ask_yes_no(text: str, instructions: str, yes_label: str | None, no_label: str | None) -> dict:
    from decide import Noul

    criteria = [yes_label, no_label] if (yes_label or no_label) else None
    client = _get_client()
    resp = await asyncio.to_thread(
        client.decide, text, {"answer": Noul(instructions=instructions, criteria=criteria)}
    )
    return {**_answer_to_dict("answer", resp["answer"]), **_meta_to_dict(resp.meta)}


async def ask_choose_one(text: str, instructions: str, candidates: dict[str, str | None]) -> dict:
    from decide import Choice

    client = _get_client()
    resp = await asyncio.to_thread(
        client.decide, text, {"answer": Choice(instructions=instructions, criteria=candidates)}
    )
    return {**_answer_to_dict("answer", resp["answer"]), **_meta_to_dict(resp.meta)}


async def ask_choose_multiple(
    text: str, instructions: str, candidates: dict[str, str | None], threshold: float
) -> dict:
    """No native "select multiple" primitive in pydecide — composed here
    as one Noul ("does this candidate apply?") per candidate, sent as a
    single multi-question decide() call (one round trip, not N). Being
    explicit about this in the response (each candidate's own yes/no
    probability, not a single joint distribution) rather than pretending
    it's a native call the model was actually asked."""
    from decide import Noul

    client = _get_client()
    questions = {
        name: Noul(instructions=f"{instructions}\n\nSpecifically: does '{name}'{f' ({desc})' if desc else ''} apply?")
        for name, desc in candidates.items()
    }
    resp = await asyncio.to_thread(client.decide, text, questions)
    options = [{"name": name, "probability": resp[name].noul} for name in candidates]
    selected = [o["name"] for o in options if o["probability"] >= threshold]
    return {"selected": selected, "options": options, **_meta_to_dict(resp.meta)}


async def ask_scale(text: str, instructions: str, levels: list[str]) -> dict:
    from decide import Score

    client = _get_client()
    resp = await asyncio.to_thread(client.decide, text, {"answer": Score(instructions=instructions, criteria=levels)})
    return {**_answer_to_dict("answer", resp["answer"]), **_meta_to_dict(resp.meta)}


async def ask_tool(text: str, instructions: str) -> dict:
    candidates = get_tool_candidates()
    return await ask_choose_one(text, instructions, candidates)
