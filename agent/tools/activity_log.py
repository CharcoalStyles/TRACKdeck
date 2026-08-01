"""
agent/tools/activity_log.py
-----------------------------
A structured personal-activity log the user asked for after their beta
test — deliberately stricter-shaped than a free-form note (see
utils/vault.py), since the point is to eventually chart it (mood over
time, time per activity type; dashboard at static/activity-log.html).
Chat/voice entry only for v1, via this one tool — no manual entry form.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from langchain_core.tools import tool

from agent.settings import settings
from utils import activity_log_store
from utils.datetime import parse_local_datetime

logger = logging.getLogger(__name__)

ActivityType = Literal["Meal", "Exercise", "Project Work", "Socializing", "Rest"]


@tool
def log_activity(
    activity_type: ActivityType,
    subject: str,
    when: Optional[str] = None,
    duration: Optional[str] = None,
    mood_energy: Optional[int] = None,
    reflection: Optional[str] = None,
) -> str:
    """Log one entry in the user's structured activity log — a personal
    record of meals, exercise, project work, socializing, and rest,
    intended to be reviewed and charted later (mood over time, time spent
    per activity type) on the dashboard's Activity Log page.

    Call this when the user narrates something they did or are doing —
    "I just had a tofu scramble", "went for a 5k run", "worked on the
    garden project for a couple hours" — not for a general chat message
    with nothing to log. This is a separate, stricter record from
    remember_about_me (durable facts about who the user is) and save_note
    (freeform notes) — use this specifically for a loggable activity
    occurrence with a type/time/duration shape.

    Args:
        activity_type: One of "Meal", "Exercise", "Project Work",
            "Socializing", "Rest" — pick the closest fit.
        subject: A brief description of what it was, e.g. "Tofu scramble
            with roasted veg" or "5k run around the park".
        when: An absolute local date/time the activity happened (resolve
            relative language like "just now" or "this morning" yourself
            first, per the date/time grounding rule). Omit if the user is
            describing something happening right now — defaults to the
            current local time.
        duration: How long it took, in whatever form the user gave it —
            a plain estimate like "60 minutes" or "45 min", or a
            free-form answer like "All Day" or "a couple hours". Omit if
            not mentioned; don't ask for it unless the user seems to be
            deliberately giving a full log entry.
        mood_energy: The user's mood/energy level for this entry on a
            1-10 scale, only if they mentioned or gave one — never invent
            a number on their behalf.
        reflection: Any free-text notes or reflection the user gave about
            it. Omit if they didn't say anything beyond the basic fact.
    """
    if when:
        try:
            occurred_local = parse_local_datetime(when)
        except (ValueError, AttributeError):
            return (
                f"I couldn't understand the time '{when}'. Try an absolute "
                "date and time, or omit it to log it as happening now."
            )
    else:
        occurred_local = datetime.now(settings.zoneinfo())

    if mood_energy is not None and not (1 <= mood_energy <= 10):
        return "mood_energy must be between 1 and 10 — leave it out if the user didn't give a number."

    entry_id = str(uuid.uuid4())
    occurred_epoch = int(occurred_local.astimezone(timezone.utc).timestamp())

    activity_log_store.create_entry(
        entry_id, occurred_epoch, activity_type, subject, duration, mood_energy, reflection
    )

    logger.info(
        "Activity logged: %s — %s at %s (id=%s)",
        activity_type, subject, occurred_local.isoformat(), entry_id,
    )
    return f"Logged: {activity_type} — {subject} at {occurred_local.strftime('%A, %d %B %Y %I:%M %p')}."
