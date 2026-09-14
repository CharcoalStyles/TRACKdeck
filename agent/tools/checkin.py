"""
agent/tools/checkin.py
-----------------------
On-demand access to the mental-health check-in prompt library
(agent/checkin_prompts.py), for when the user asks for a grounding/
reflection exercise mid-conversation rather than waiting for the
randomized schedule in jobs/checkin.py to fire one.

Deliberately does NOT touch utils/checkins_store or jobs/checkin.py's
state machine: no DB row is created, it doesn't count toward the day's
3-5 target, and it has no cooldown/fallback interaction. The exchange
happens in the assistant's normal conversation thread (no checkin_id,
see voice.py), so it's captured by the ordinary conversation-history/
Chroma pipeline and shows up in jobs/digest.py's generic recap like any
other topic, just without the dedicated "reflections" formatting that
section gives rows that exist in checkins_store.
"""
from __future__ import annotations

import random
from typing import Optional

from langchain_core.tools import tool

from agent.checkin_prompts import PROMPTS

_ALL_PROMPTS = [prompt for prompts in PROMPTS.values() for prompt in prompts]


@tool
def get_reflection_prompt(category: Optional[str] = None) -> str:
    """Give the user a short grounding/reflection exercise when they ask
    for one directly (e.g. "give me a grounding exercise", "I need to
    check in with myself"). Relay the returned prompt conversationally —
    it already ends in a question. Separate from the app's randomized
    check-in schedule: doesn't create a scheduled check-in or affect
    today's count/cooldowns.

    Args:
        category: Optional effort level — "low" (quick grounding/somatic),
            "medium" (brief reflection), "high" (deeper values/self-efficacy
            reflection). Omit for a random one from any category.
    """
    pool = PROMPTS.get(category, _ALL_PROMPTS) if category else _ALL_PROMPTS
    return random.choice(pool)
