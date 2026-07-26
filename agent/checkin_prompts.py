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

Every prompt, "low" included, ends in an explicit question or request for a
spoken response — a bare instruction (e.g. a posture fix with no follow-up)
gives voice.py's checkin_id-tagged reply nothing to reply to, so the somatic
action always gets paired with a one-line reflection on it ("what shifted?",
"how do you feel now?") rather than standing alone.
"""
from __future__ import annotations

PROMPTS: dict[str, list[str]] = {
    "low": [
        "Drop your shoulders away from your ears and unclench your jaw. Take one slow breath — what shifted, even slightly?",
        "Find the furthest object you can see and focus on it for a few seconds. How do your eyes feel now?",
        "Name one sound, one texture, and one temperature you can notice right now — what did you pick?",
        "Inhale for 4 seconds, hold for 4, exhale for 4, hold for 4. Once through is enough — how do you feel?",
        "Roll your neck slowly, once each direction. Where are you holding tension?",
        "Press your feet flat into the floor and notice the contact for a few seconds. What do you notice in your legs right now?",
        "Stretch your arms overhead and take one slow breath out. What does your body feel like right now?",
        "Unclench your hands and let them go soft, then take one slow breath. Were you holding onto something?",
        "Like a compass needle settling back to north, let your attention settle back to this moment. What are you doing right now?",
        "Notice if your mind has wandered off somewhere, and let it curve back like a boomerang to right here. Where had it gone?",
        "If you can, stand up and take a few steps or shift your weight from foot to foot. How does your body feel after moving?",
        "Notice one smell in the air and the taste in your mouth right now, even if it's faint. What did you pick up on?",
    ],
    "medium": [
        "What's a small win from the last few hours?",
        "Name one thing you're grateful for right now.",
        "Think of one minor frustration from today — is there a neutral or positive way to look at it?",
        "Who's someone you interacted with recently, even briefly, that you appreciate?",
        "What's one small detail of your surroundings right now that you're glad is there?",
        "What's something today that went better than you expected?",
        "What's one thing you're looking forward to, even something small?",
        "Is there something you've been putting off that would feel good to finally do?",
        "You've made it this far today — keep up the good work. What's one thing that's helped you get through it?",
        "You have coping skills you can lean on right now, whether that's slowing your breath or stepping away for a minute. Which one sounds most useful right now?",
        "On a scale of 1 to 10, how would you rate your stress level right now? What's driving that number?",
        "Picture your thoughts as water tumbling over a waterfall, falling away instead of pulling you along. What's one thought you can let fall away right now?",
    ],
    "high": [
        "What's a skill or trait you used today that you're proud of?",
        "Did you protect your time or say no to something today in a way that felt good?",
        "What's something hard you handled well recently?",
        "What's one small action in the next hour your evening self will thank you for?",
        "What's a value of yours that you actually lived up to today?",
        "When did you last do something because it mattered to you, not because you had to?",
        "Is there something you've been avoiding because it feels uncomfortable? What's one small step you could take toward it today?",
        "Think of something you're worried about right now. What's the realistic worst case, and how would you handle it if it happened?",
        "Name one value you want to put into action in the next few hours. What will you actually do?",
        "Looking back over the past week, what's a situation that kept stressing you out? What's one thing you could try differently next time it comes up?",
        "Think of a decision you're weighing right now. What's one upside and one downside that stand out to you?",
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
