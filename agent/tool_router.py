"""
agent/tool_router.py
---------------------
Optional, feature-flagged narrowing of which tool schemas get bound to the
LLM per turn, via Laya (utils/laya_client.py's ask_choose_multiple) picking
zero or more of ~9 tool categories instead of always offering the full
~31(+MCP)-tool list.

Off by default (agent/settings.py's tool_router_enabled) — this exists so
it can be A/B tested against the unmodified baseline, not something forced
on. Deliberately has NO "does this need a tool at all?" gate: Laya's Noul
question type was tested against 5 real historical not_called failures and
said "no" on all 5 — using it to suppress tool-calling would make that
exact failure mode worse, not better. Only narrows WHICH tools are
offered, and always fails open (full tool list) when nothing clears the
confidence threshold or on any error — never a path that offers zero
tools.

This is deliberately multi-category, not single-choice: an earlier version
used one Laya Choice call to pick exactly one category, which measured
worse than no router at all (58% vs 62% correct on a 45-prompt eval of
liquid/lfm2.5-1.2b) — not because narrowing itself hurts, but because a
single wrong-but-confident category pick made the actually-needed tool
completely unavailable for that turn, with no recovery path (fail-open
only triggers on low confidence, never on confidently-wrong). Running one
Noul ("does this category apply?") per category instead means a request
that genuinely spans categories can keep tools from all of them, and a
wrong "yes" on one category doesn't evict the right one from a different
category that also said "yes".

agent/graph.py's build_graph() calls build_category_index() once (the tool
list is "fixed for the process lifetime", same reasoning as its own
_tools_token_estimate); call_llm() calls choose_tool_subset() fresh every
turn.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from agent.settings import settings
from utils.laya_client import LayaNotInstalled, ask_choose_multiple

logger = logging.getLogger(__name__)

# Per-category yes/no cutoff for ask_choose_multiple. 0.5 measured best of
# three configurations tried on a 45-prompt eval of liquid/lfm2.5-1.2b
# (28/45 router off, 29/45 at 0.5, 25/45 at 0.3, 26/45 for the earlier
# single-Choice design) — but the margins between all of them are within
# noise at this sample size, not a settled, confidently-tuned value.
# Lowering it amplified a different systematic bias in Laya's classifier
# (log_activity got spuriously selected far more often) rather than fixing
# anything, so this isn't just "lower is more permissive, higher is
# safer" — re-tune from real logged probabilities via
# utils/tool_router_log.py against a larger eval, same story as
# agent/settings.py's recall_max_distance, rather than nudging this by feel.
CONFIDENCE_THRESHOLD = 0.5

CATEGORY_MAP: dict[str, str] = {
    # calendar (6)
    "get_todays_events": "calendar",
    "get_calendar_event": "calendar",
    "add_calendar_event": "calendar",
    "delete_calendar_event": "calendar",
    "get_calendar_events": "calendar",
    "update_calendar_event": "calendar",
    "move_calendar_event": "calendar",
    # weather (3)
    "get_current_weather": "weather",
    "get_weather_forecast": "weather",
    "get_range_forecast": "weather",
    # notes (10)
    "save_note": "notes",
    "search_notes": "notes",
    "read_note": "notes",
    "append_to_note": "notes",
    "update_note_section": "notes",
    "remember_about_me": "notes",
    "get_or_create_linked_note": "notes",
    "get_or_create_project": "notes",
    "list_projects": "notes",
    "read_about_me": "notes",
    # planning (2)
    "add_planning_task": "planning",
    "generate_schedule_blocks": "planning",
    # reminders (4)
    "set_reminder": "reminders",
    "set_timer": "reminders",
    "list_reminders": "reminders",
    "cancel_reminder": "reminders",
    # checkin (1)
    "get_reflection_prompt": "checkin",
    # general (4)
    "get_current_datetime": "general",
    "fetch_webpage": "general",
    "mark_onboarding_complete": "general",
    "set_home_location": "general",
    # activity_log (1)
    "log_activity": "activity_log",
    # web (0-5, MCP — only present if settings.mcp_servers configures searxng)
    "search_web": "web",
    "search_images": "web",
    "search_videos": "web",
    "search_news": "web",
    "fetch_url": "web",
}

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "calendar": "Viewing, creating, updating, or deleting calendar events and schedules.",
    "weather": "Current conditions, hourly/daily forecasts, or multi-day weather outlooks.",
    "notes": "Saving, searching, reading, or updating notes, projects, or facts about the user.",
    "planning": "Adding a task to the plan, or generating a day's schedule blocks.",
    "reminders": "Setting, listing, or cancelling reminders and timers.",
    "checkin": "A reflection or check-in prompt about how the day/week went.",
    "general": "Current date/time, fetching a specific webpage's content, onboarding, or home location.",
    "activity_log": "Logging that an activity/exercise/event just happened.",
    "web": "Searching the web, images, videos, or news, or fetching a URL's content.",
}


@dataclass
class CategoryIndex:
    by_category: dict[str, list]
    candidates: dict[str, str]
    # Tools with no CATEGORY_MAP entry — always included in any narrowed
    # subset (see choose_tool_subset) so a forgotten mapping entry for a
    # newly added tool never makes it silently unreachable.
    uncategorized: list


@dataclass
class RouterDecision:
    tools: list
    narrowed: bool
    categories: list[str]  # every category that cleared CONFIDENCE_THRESHOLD; [] when not narrowed
    probabilities: dict[str, float] | None  # every candidate's own yes-probability, for tuning the threshold from data — None when disabled/laya_not_installed/error
    latency_ms: float | None
    reason: str  # "disabled" | "ok" | "low_confidence" | "empty_category" | "laya_not_installed" | "error:<ExceptionType>"


def build_category_index(tools: list) -> CategoryIndex:
    """Called once at graph-build time (tools are fixed for the process
    lifetime — see agent/graph.py's _tools_token_estimate comment for the
    same reasoning), not per turn."""
    by_category: dict[str, list] = {}
    uncategorized: list = []
    for t in tools:
        category = CATEGORY_MAP.get(t.name)
        if category is None:
            uncategorized.append(t)
            continue
        by_category.setdefault(category, []).append(t)

    if uncategorized:
        logger.warning(
            "tool_router: %d tool(s) have no CATEGORY_MAP entry and will always "
            "be included in any narrowed subset regardless of routing: %s",
            len(uncategorized), [t.name for t in uncategorized],
        )

    candidates = {cat: CATEGORY_DESCRIPTIONS.get(cat, cat) for cat in by_category}
    return CategoryIndex(by_category=by_category, candidates=candidates, uncategorized=uncategorized)


async def choose_tool_subset(message: str, index: CategoryIndex, full_tools: list) -> RouterDecision:
    """Called fresh every turn. full_tools is the always-safe fallback —
    exactly what ToolNode can execute, unaffected by any routing outcome
    here. Self-contained: safe to call regardless of whether the caller
    already checked settings.tool_router_enabled (defense in depth, and
    keeps this function directly unit-testable)."""
    if not settings.tool_router_enabled:
        return RouterDecision(full_tools, False, [], None, None, "disabled")

    try:
        result = await ask_choose_multiple(
            message,
            "Does this request need a tool from this category?",
            index.candidates,
            CONFIDENCE_THRESHOLD,
        )
    except LayaNotInstalled:
        # Routine in real production today (pydecide isn't deployed there
        # yet) — info, not warning.
        logger.info("tool_router: pydecide not installed, falling back to full tool list")
        return RouterDecision(full_tools, False, [], None, None, "laya_not_installed")
    except Exception as e:
        logger.warning("tool_router: Laya call failed (%s: %s), falling back to full tool list", type(e).__name__, e)
        return RouterDecision(full_tools, False, [], None, None, f"error:{type(e).__name__}")

    selected = result["selected"]
    probabilities = {o["name"]: o["probability"] for o in result["options"]}
    latency_ms = result.get("latency_ms")

    if not selected:
        return RouterDecision(full_tools, False, [], probabilities, latency_ms, "low_confidence")

    subset = []
    for category in selected:
        subset.extend(index.by_category.get(category, []))
    subset.extend(index.uncategorized)

    if not subset:
        return RouterDecision(full_tools, False, selected, probabilities, latency_ms, "empty_category")

    return RouterDecision(subset, True, selected, probabilities, latency_ms, "ok")
