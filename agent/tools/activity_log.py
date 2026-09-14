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
    """Log one entry in the user's structured activity log (meals,
    exercise, project work, socializing, rest) — charted later on the
    dashboard.

    Call when the user narrates something they did/are doing ("I just had
    a tofu scramble", "went for a 5k run") — not for general chat.
    Distinct from remember_about_me (durable facts) and save_note
    (freeform notes); use only for a loggable occurrence with a
    type/time/duration shape.

    Args:
        activity_type: Closest fit among the allowed values.
        subject: Brief description, e.g. "Tofu scramble with roasted veg".
        when: Absolute local date/time (resolve relative language like
            "this morning" yourself first). Omit for "happening now".
        duration: However the user phrased it (e.g. "45 min", "a couple
            hours"). Omit if unmentioned.
        mood_energy: 1-10 if the user gave one — never invent a number.
        reflection: Any free-text notes the user gave. Omit if none.
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
