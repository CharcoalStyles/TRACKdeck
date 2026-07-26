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
    """Give the user a short mental-health grounding or reflection exercise
    to do right now, when they ask for one directly (e.g. "give me a
    grounding exercise", "I need to check in with myself", "got a
    mindfulness thing I could try?"). Just relay the returned prompt to
    the user conversationally — it already ends in a question, so let
    them answer in the same reply.

    This is separate from the app's own randomized check-in schedule:
    calling this does not create a scheduled check-in and has no effect
    on today's check-in count or cooldowns.

    Args:
        category: Optional effort level to draw from: "low" (quick
                  grounding/somatic), "medium" (brief reflection), or
                  "high" (deeper values/self-efficacy reflection). Omit,
                  or pass anything else, to get a random one from any
                  category.
    """
    pool = PROMPTS.get(category, _ALL_PROMPTS) if category else _ALL_PROMPTS
    return random.choice(pool)
