"""
utils/planning.py
------------------
Pure functions for the Sunday/Saturday task-planning note: parsing the
"## Tasks" checklist, merging it with the day's calendar into a timeline
of sprint/break blocks, and the read/write format for the "## Generated
Schedule & Sprints" / "## End of Day Reflection" sections. No I/O here —
vault reads/writes live in utils/vault.py, CalDAV reads in
utils/caldav_client.py; agent/tools/planning.py wires them together.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

TASK_LINE = re.compile(
    r"^-\s*\[ \]\s*(?:Task\s*\d+:\s*)?(?P<task>.+?)\s*[-—]+\s*Est:?\s*(?P<minutes>\d+)\s*min",
    re.IGNORECASE,
)

# Matches "- [ ] Work — 09:00 to 17:00" style lines in a "## Fixed Blocks"
# section — a name plus an already-occupied HH:MM-HH:MM window, as
# opposed to TASK_LINE's name-plus-duration shape.
FIXED_BLOCK_LINE = re.compile(
    r"^-\s*\[ \]\s*(?P<name>.+?)\s*[-—]+\s*(?P<start>\d{1,2}:\d{2})\s*to\s*(?P<end>\d{1,2}:\d{2})",
    re.IGNORECASE,
)

# Matches the template's own "(5-10 min)" break guidance: a short sprint
# gets a short break, a longer one gets more recovery time. Not a
# setting — see compute_schedule_blocks' ponytail note.
SHORT_BREAK_MINUTES = 5
LONG_BREAK_MINUTES = 10
LONG_TASK_THRESHOLD_MINUTES = 25


def parse_target_tasks(section_text: str) -> list[tuple[str, int]]:
    """Extracts (description, minutes) from a "## Tasks" section's
    checklist lines. Checked-off ("- [x]") and unparseable lines are
    silently skipped — same "don't guess, just exclude" convention
    jobs/activity_log.py's duration parsing already uses."""
    tasks = []
    for line in section_text.splitlines():
        match = TASK_LINE.match(line.strip())
        if match:
            tasks.append((match.group("task").strip(), int(match.group("minutes"))))
    return tasks


def parse_fixed_blocks(section_text: str) -> list[tuple[str, str, str]]:
    """Extracts (name, start "HH:MM", end "HH:MM") from a "## Fixed
    Blocks" section's checklist lines — time already spoken for (e.g.
    "Work — 09:00 to 17:00") that the scheduler should treat as occupied
    on top of the day's real calendar events. Checked-off and
    unparseable lines are silently skipped, same convention as
    parse_target_tasks."""
    blocks = []
    for line in section_text.splitlines():
        match = FIXED_BLOCK_LINE.match(line.strip())
        if match:
            blocks.append((match.group("name").strip(), match.group("start"), match.group("end")))
    return blocks


@dataclass
class Block:
    kind: str  # "task" | "break"
    start: datetime
    end: datetime
    label: str  # task description, or "Break" for a break block


def _merge_intervals(
    intervals: list[tuple[datetime, datetime]], window_start: datetime, window_end: datetime
) -> list[tuple[datetime, datetime]]:
    clipped = []
    for start, end in intervals:
        start, end = max(start, window_start), min(end, window_end)
        if start < end:
            clipped.append((start, end))
    clipped.sort()

    merged: list[list[datetime]] = []
    for start, end in clipped:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def _free_gaps(
    occupied: list[tuple[datetime, datetime]], window_start: datetime, window_end: datetime
) -> list[tuple[datetime, datetime]]:
    gaps = []
    cursor = window_start
    for start, end in occupied:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < window_end:
        gaps.append((cursor, window_end))
    return gaps


def compute_schedule_blocks(
    tasks: list[tuple[str, int]],
    occupied: list[tuple[datetime, datetime]],
    window_start: datetime,
    window_end: datetime,
) -> tuple[list[Block], list[str]]:
    """Greedy first-fit: walk the free gaps between `occupied` intervals
    (the day's real calendar events) within [window_start, window_end),
    placing each task — in the order given — followed by a break, moving
    to the next gap whenever the current one runs out of room. A break
    that hits the end of its gap is trimmed rather than spilling into the
    next occupied interval. Returns (blocks, unscheduled) — a task that
    never finds a big enough gap before window_end is reported in
    `unscheduled` rather than silently dropped.

    # ponytail: greedy first-fit, no reordering/optimization — revisit
    # only if a real day's plan is dense enough that ordering visibly
    # wastes gaps.
    """
    gaps = _free_gaps(_merge_intervals(occupied, window_start, window_end), window_start, window_end)

    blocks: list[Block] = []
    unscheduled: list[str] = []
    gap_idx = 0
    cursor: Optional[datetime] = None

    for description, minutes in tasks:
        duration = timedelta(minutes=minutes)
        break_duration = timedelta(
            minutes=LONG_BREAK_MINUTES if minutes >= LONG_TASK_THRESHOLD_MINUTES else SHORT_BREAK_MINUTES
        )

        placed = False
        while gap_idx < len(gaps):
            gap_start, gap_end = gaps[gap_idx]
            start = cursor if cursor is not None and cursor > gap_start else gap_start
            if start + duration <= gap_end:
                end = start + duration
                blocks.append(Block(kind="task", start=start, end=end, label=description))
                break_end = min(end + break_duration, gap_end)
                blocks.append(Block(kind="break", start=end, end=break_end, label="Break"))
                cursor = break_end
                placed = True
                break
            gap_idx += 1
            cursor = None

        if not placed:
            unscheduled.append(description)

    return blocks, unscheduled


def occupied_from_calendar_events(events: list[dict], tz: timezone) -> list[tuple[datetime, datetime]]:
    """Converts CalDAV event dicts (utils/caldav_client.parse_ics shape —
    "start"/"end" as RFC 5545 UTC strings) into `tz`-local intervals for
    compute_schedule_blocks. An event without a UTC ("Z"-suffixed)
    start/end is skipped — same "floating/TZID-local start is silently
    skipped" convention jobs/calendar_sync.py already uses."""
    occupied = []
    for event in events:
        start = _parse_utc_ics(event.get("start"))
        end = _parse_utc_ics(event.get("end"))
        if start is None or end is None:
            continue
        occupied.append((start.astimezone(tz), end.astimezone(tz)))
    return occupied


def _parse_utc_ics(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def format_schedule_section(blocks: list[Block], unscheduled: list[str]) -> str:
    if not blocks and not unscheduled:
        return "*(No tasks to schedule yet — add some to the Tasks section above.)*"

    lines = []
    for block in blocks:
        label = f" {block.label}" if block.kind == "task" else ""
        kind = "Block" if block.kind == "task" else "Break"
        lines.append(f"- [ ] {kind}: {block.start.strftime('%H:%M')}–{block.end.strftime('%H:%M')}{label}")

    if unscheduled:
        lines.append("")
        lines.append("**Couldn't fit today:** " + ", ".join(unscheduled))

    return "\n".join(lines)


# Heading name for the reflection section — the one source of truth so
# routes/reflection.py and agent/tools/planning.py don't each redefine it.
REFLECTION_SECTION_HEADING = "End of Day Reflection"

# (field key, note bullet label) — order controls both display and
# read/write round-tripping through the "## End of Day Reflection" section.
REFLECTION_FIELDS: list[tuple[str, str]] = [
    ("energy_rating", "Energy & Mood (1-10)"),
    ("what_worked_well", "What worked well"),
    ("what_had_friction", "What had friction"),
    ("adjustments", "Adjustments for next time"),
]


def parse_reflection_section(section_text: Optional[str]) -> dict[str, Optional[str]]:
    values: dict[str, Optional[str]] = {key: None for key, _ in REFLECTION_FIELDS}
    if not section_text:
        return values
    for line in section_text.splitlines():
        match = re.match(r"^-\s*\*\*(?P<label>[^*]+)\*\*:\s*(?P<value>.*)$", line.strip())
        if not match:
            continue
        label = match.group("label").strip().lower()
        value = match.group("value").strip() or None
        for key, field_label in REFLECTION_FIELDS:
            if field_label.lower() == label:
                values[key] = value
    return values


def format_reflection_section(values: dict[str, Optional[str]]) -> str:
    return "\n".join(f"- **{label}**: {values.get(key) or ''}" for key, label in REFLECTION_FIELDS)


def reflection_is_filled(values: dict[str, Optional[str]]) -> bool:
    """True if the user actually filled in at least one reflection field —
    an empty/never-visited reflection section shouldn't count as history."""
    return any(values.get(key) for key, _ in REFLECTION_FIELDS)


def format_reflection_digest(entries: list[tuple[str, dict[str, Optional[str]]]]) -> str:
    """Format past days' filled-in reflections into a short digest for
    generate_schedule_blocks to surface back to the LLM. `entries` is
    (date_str, parsed_reflection_values) pairs, already filtered to ones
    reflection_is_filled — most recent first. Returns "" for an empty
    list so callers can unconditionally append the result."""
    if not entries:
        return ""
    lines = ["", "Recent reflections to consider:"]
    for date_str, values in entries:
        bits = [f"{label}: {values[key]}" for key, label in REFLECTION_FIELDS if values.get(key)]
        if bits:
            lines.append(f"- {date_str} — " + "; ".join(bits))
    return "\n".join(lines)
