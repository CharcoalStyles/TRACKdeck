"""
agent/checkin_prompts.py
--------------------------
Prompt library for jobs/checkin.py's mental-health micro-interventions
(EMI — Ecological Momentary Intervention), categorized by cognitive load.

Plain Python data, no LLM call, no vault note, no DB seeding — same
philosophy as agent/keywords.py's ADJECTIVES/NOUNS: cheap and deterministic
is the house style here, not something worth spending a generation on.

Categories, lightest to heaviest:
  low    - somatosensory/grounding (breathing, posture, senses)
  medium - micro-gratitude / cognitive reappraisal
  high   - values / self-efficacy reflection, capped at once/day by
           jobs/checkin.py's category picker
"""
from __future__ import annotations

PROMPTS: dict[str, list[str]] = {
    "low": [
        "Drop your shoulders away from your ears, unclench your jaw, and take one slow breath.",
        "Look away from what you're doing. Find the furthest object you can see and focus on it for a few seconds.",
        "Name one sound, one texture, and one temperature you can notice right now.",
        "Inhale for 4 seconds, hold for 4, exhale for 4, hold for 4. Once through is enough.",
        "Roll your neck slowly, once each direction. Notice where you're holding tension.",
    ],
    "medium": [
        "What's a small win from the last few hours?",
        "Name one thing you're grateful for right now.",
        "Think of one minor frustration from today — is there a neutral or positive way to look at it?",
        "Who's someone you interacted with recently, even briefly, that you appreciate?",
        "What's one small detail of your surroundings right now that you're glad is there?",
    ],
    "high": [
        "What's a skill or trait you used today that you're proud of?",
        "Did you protect your time or say no to something today in a way that felt good?",
        "What's something hard you handled well recently?",
        "What's one small action in the next hour your evening self will thank you for?",
    ],
}

# A skipped prompt's fallback retry always drops toward a lighter category.
# "low" has no lighter tier to drop to, so it bumps to "medium" instead —
# the one case where "different category" and "lower load" can't both hold.
FALLBACK_CATEGORY: dict[str, str] = {
    "high": "low",
    "medium": "low",
    "low": "medium",
}
