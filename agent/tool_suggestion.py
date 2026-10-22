"""
agent/tool_suggestion.py
--------------------------
Optional, feature-flagged tool suggestion: appends a soft "I think these
tools will help..." hint to the system prompt, built from Laya
(utils/laya_client.py's ask_choose_multiple) picking zero or more tools out
of the full tool list.

Unlike agent/tool_router.py's narrowing, this NEVER changes which tool
schemas are bound to the LLM — the full tool list stays available every
turn regardless of what's suggested. Worst case a bad/wrong suggestion is
simply ignored by the model, unlike narrowing where a wrong pick could make
the correct tool completely unavailable (see agent/tool_router.py's
docstring for that measured history). Trades away narrowing's one clean win
(a meaningfully shorter prompt, faster generation) for a design that can't
make things worse by omission — worth it here since generation speed on
liquid/lfm2.5-1.2b isn't the bottleneck.

Off by default (agent/settings.py's tool_suggestion_enabled) — same
A/B-testable, fail-open pattern as agent/tool_router.py. Operates on
individual tools, not the ~9 categories agent/tool_router.py groups by —
there's no schema-binding cost to worry about here, so a suggestion can
just name the specific tools directly rather than a whole category.

agent/graph.py's build_graph() calls build_tool_candidates() once (the tool
list is "fixed for the process lifetime", same reasoning as its own
_tools_token_estimate); call_llm() calls suggest_tools() fresh every turn.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from agent.settings import settings
from utils.laya_client import LayaNotInstalled, ask_choose_multiple

logger = logging.getLogger(__name__)

# Per-tool yes/no cutoff for ask_choose_multiple — same starting point as
# agent/tool_router.py's CONFIDENCE_THRESHOLD, not yet tuned from data.
CONFIDENCE_THRESHOLD = 0.5


@dataclass
class SuggestionDecision:
    suggested: list[str]  # tool names suggested this turn; [] if none/disabled/error
    probabilities: dict[str, float] | None  # every candidate's own yes-probability, for tuning
    latency_ms: float | None
    reason: str  # "disabled" | "ok" | "none_suggested" | "laya_not_installed" | "error:<ExceptionType>"


def build_tool_candidates(tools: list) -> dict[str, str]:
    """Called once at graph-build time (tool list is fixed for the process
    lifetime, same reasoning as agent/tool_router.py's build_category_index)
    — tool name -> first line of its description, truncated, matching
    utils/laya_client.py's get_tool_candidates() convention. Built from the
    same `tools` list agent/graph.py actually binds, rather than
    re-deriving it independently, so a suggestion never names a tool this
    graph doesn't actually have (e.g. MCP tools when configured)."""
    candidates = {}
    for t in tools:
        first_line = (t.description or t.name).strip().splitlines()[0]
        candidates[t.name] = first_line[:200]
    return candidates


def build_suggestion_text(suggested: list[str]) -> str:
    if not suggested:
        return ""
    return f"\n\nI think these tools will help you complete what's needed: {', '.join(suggested)}."


async def suggest_tools(message: str, candidates: dict[str, str]) -> SuggestionDecision:
    """Called fresh every turn. Self-contained: safe to call regardless of
    whether the caller already checked settings.tool_suggestion_enabled
    (defense in depth, and keeps this function directly unit-testable)."""
    if not settings.tool_suggestion_enabled:
        return SuggestionDecision([], None, None, "disabled")

    try:
        result = await ask_choose_multiple(
            message,
            "Would this tool help complete the request?",
            candidates,
            CONFIDENCE_THRESHOLD,
        )
    except LayaNotInstalled:
        # Routine in real production today (pydecide isn't deployed there
        # yet) — info, not warning.
        logger.info("tool_suggestion: pydecide not installed, skipping suggestion")
        return SuggestionDecision([], None, None, "laya_not_installed")
    except Exception as e:
        logger.warning("tool_suggestion: Laya call failed (%s: %s), skipping suggestion", type(e).__name__, e)
        return SuggestionDecision([], None, None, f"error:{type(e).__name__}")

    selected = result["selected"]
    probabilities = {o["name"]: o["probability"] for o in result["options"]}
    latency_ms = result.get("latency_ms")

    if not selected:
        return SuggestionDecision([], probabilities, latency_ms, "none_suggested")

    return SuggestionDecision(selected, probabilities, latency_ms, "ok")
