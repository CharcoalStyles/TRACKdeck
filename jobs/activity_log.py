"""
jobs/activity_log.py
----------------------
Aggregation helpers for GET /activity-log/summary — kept out of main.py
(too much logic for an inline route body) and out of
utils/activity_log_store.py (this is aggregation over already-fetched
rows, not a SQL query — same separation as jobs/checkin.py's
reflections_between vs utils/checkins_store.py's queries).
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from agent.settings import settings

_DURATION_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(h|hr|hour|hrs|hours|m|min|mins|minute|minutes)?",
    re.IGNORECASE,
)


def parse_duration_minutes(duration: Optional[str]) -> Optional[float]:
    """Best-effort parse of a free-text duration into minutes. Returns
    None for anything unparseable (e.g. "All Day", empty, missing) — the
    caller excludes those from the duration_by_type aggregate rather than
    guessing a number for them. Handles "60 minutes", "45 min", "1.5
    hours", "2h", bare "90" (assumed minutes)."""
    if not duration:
        return None
    match = _DURATION_PATTERN.search(duration)
    if not match:
        return None
    value = float(match.group(1))
    unit = (match.group(2) or "").lower()
    if unit.startswith("h"):
        return value * 60
    return value


def summarize(entries: list[dict]) -> dict:
    """entries: rows from activity_log_store.list_between. Returns the
    {mood_by_day, duration_by_type} shape for GET /activity-log/summary."""
    local_tz = settings.zoneinfo()

    mood_by_date: dict[str, list[int]] = defaultdict(list)
    duration_by_type: dict[str, list[float]] = defaultdict(list)

    for entry in entries:
        local_dt = datetime.fromtimestamp(entry["occurred_at"], tz=timezone.utc).astimezone(local_tz)
        if entry["mood_energy"] is not None:
            mood_by_date[local_dt.date().isoformat()].append(entry["mood_energy"])

        minutes = parse_duration_minutes(entry["duration"])
        if minutes is not None:
            duration_by_type[entry["activity_type"]].append(minutes)

    mood_by_day = [
        {"date": date, "avg_mood": round(sum(vals) / len(vals), 1), "count": len(vals)}
        for date, vals in sorted(mood_by_date.items())
    ]
    duration_by_type_out = [
        {"activity_type": t, "total_minutes": round(sum(vals)), "entry_count": len(vals)}
        for t, vals in sorted(duration_by_type.items())
    ]
    return {"mood_by_day": mood_by_day, "duration_by_type": duration_by_type_out}
