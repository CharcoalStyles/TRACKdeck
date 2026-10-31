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

import math
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

TASK_LINE = re.compile(
    r"^-\s*\[ \]\s*(?:Task\s*\d+:\s*)?(?P<task>.+?)\s*[-—]+\s*Est:?\s*(?P<minutes>\d+)\s*min",
    re.IGNORECASE,
)

# Optional trailing "— after Clean kitchen" on a task line: the task must come
# after every chunk of the named task.
TASK_AFTER = re.compile(r"[-—]+\s*after\s+(?P<ref>\S.*?)\s*$", re.IGNORECASE)

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
    silently skipped rather than guessed at."""
    tasks = []
    for line in section_text.splitlines():
        match = TASK_LINE.match(line.strip())
        if match:
            tasks.append((match.group("task").strip(), int(match.group("minutes"))))
    return tasks


def parse_task_dependencies(section_text: str) -> dict[str, str]:
    """{task label (lower-case): label it must come after (lower-case)} from
    "— after X" suffixes on a "## Tasks" section's checklist lines."""
    deps = {}
    for line in section_text.splitlines():
        line = line.strip()
        match = TASK_LINE.match(line)
        after = TASK_AFTER.search(line[match.end():]) if match else None
        if match and after:
            deps[match.group("task").strip().lower()] = after.group("ref").strip().lower()
    return deps


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


ORDER_HINT = re.compile(r"^(?P<rel>before|after)\s+(?P<ref>\S.*?)\s*$", re.IGNORECASE)


def parse_order_hint(text: Optional[str]) -> Optional[tuple[str, str]]:
    """("before" | "after", other task's label) from a task-library hint
    like "after Clean the kitchen"; None for blank or malformed text."""
    match = ORDER_HINT.match((text or "").strip())
    return (match.group("rel").lower(), match.group("ref")) if match else None


def order_tasks(tasks: list[tuple[str, int]], hints: dict[str, str]) -> list[tuple[str, int]]:
    """Moves each hinted task to just before/after the task its hint names
    (labels match case-insensitively; `hints` is lower-cased label -> hint
    text). A hint naming a task that isn't in today's list is ignored, and
    unhinted tasks keep their order. Hints are applied once, in list order,
    so contradictory hints settle deterministically instead of looping."""
    ordered = list(tasks)
    for task in tasks:
        parsed = parse_order_hint(hints.get(task[0].strip().lower()))
        if not parsed:
            continue
        rel, ref = parsed
        ref_key = ref.strip().lower()
        if ref_key == task[0].strip().lower():
            continue
        if not any(other[0].strip().lower() == ref_key for other in ordered):
            continue
        ordered.remove(task)
        ref_index = next(i for i, other in enumerate(ordered) if other[0].strip().lower() == ref_key)
        ordered.insert(ref_index if rel == "before" else ref_index + 1, task)
    return ordered


def split_into_chunks(minutes: int, chunk_min: int, chunk_max: int, rng: random.Random) -> list[int]:
    """Random chunk sizes in [chunk_min, chunk_max] summing to `minutes`. A
    task that already fits in one chunk (or is too short to split) stays whole."""
    if minutes <= chunk_max:
        return [minutes]
    count = max(1, min(math.ceil(minutes / chunk_max), minutes // chunk_min))
    step = 5 if minutes % 5 == 0 and chunk_min % 5 == 0 else 1
    sizes = [chunk_min] * count
    remaining = minutes - chunk_min * count
    while remaining > 0:
        room = [i for i, size in enumerate(sizes) if size + step <= chunk_max]
        if not room:
            sizes[rng.randrange(count)] += remaining
            break
        sizes[rng.choice(room)] += step
        remaining -= step
    return sizes


def _order_chunks(
    chunks: list[tuple[str, int]], after: dict[str, str], shuffle: bool, rng: random.Random
) -> list[tuple[str, int]]:
    """Shuffles chunks, then pulls each one forward only as far as needed so a
    task's chunks all land after every chunk of the task it must follow."""
    pool = list(chunks)
    if shuffle:
        rng.shuffle(pool)
    remaining = {label.lower(): sum(1 for c in pool if c[0] == label) for label, _ in pool}
    ordered: list[tuple[str, int]] = []
    while pool:
        pick = next(
            (c for c in pool if remaining.get(after.get(c[0].lower(), ""), 0) == 0),
            pool[0],  # a cycle: stop honouring the constraint rather than loop
        )
        pool.remove(pick)
        remaining[pick[0].lower()] -= 1
        ordered.append(pick)
    return ordered


def compute_schedule_blocks(
    tasks: list[tuple[str, int]],
    occupied: list[tuple[datetime, datetime]],
    window_start: datetime,
    window_end: datetime,
    *,
    chunk_range: Optional[tuple[int, int]] = None,
    break_range: Optional[tuple[int, int]] = None,
    shuffle: bool = False,
    after: Optional[dict[str, str]] = None,
    rng: Optional[random.Random] = None,
) -> tuple[list[Block], list[str]]:
    """Walk the free gaps between `occupied` intervals (the day's real
    calendar events) within [window_start, window_end), placing each chunk —
    followed by a break — and moving to the next gap whenever the current one
    runs out of room. A break that hits the end of its gap is trimmed rather
    than spilling into the next occupied interval. Returns (blocks,
    unscheduled) — a task with a chunk that never finds a big enough gap
    before window_end is reported in `unscheduled` rather than silently dropped.

    With no options this is plain first-fit in the order given. `chunk_range`
    splits each task into random chunks of that many minutes (labelled
    "Task (2/4)"), `break_range` picks each break at random from that range in
    5-minute steps, `shuffle` randomises chunk order, and `after`
    ({task: task it must follow}, lower-cased) is always honoured.
    """
    rng = rng or random.Random()
    gaps = _free_gaps(_merge_intervals(occupied, window_start, window_end), window_start, window_end)

    chunks: list[tuple[str, int]] = []
    for description, minutes in tasks:
        sizes = split_into_chunks(minutes, *chunk_range, rng) if chunk_range else [minutes]
        chunks.extend((description, size) for size in sizes)
    chunks = _order_chunks(chunks, after or {}, shuffle, rng)

    totals = {description: sum(1 for c in chunks if c[0] == description) for description, _ in chunks}
    seen: dict[str, int] = {}

    blocks: list[Block] = []
    unscheduled: list[str] = []
    gap_idx = 0
    cursor: Optional[datetime] = None

    for description, minutes in chunks:
        duration = timedelta(minutes=minutes)
        if break_range:
            break_minutes = rng.randrange(break_range[0], break_range[1] + 1, 5)
        else:
            break_minutes = LONG_BREAK_MINUTES if minutes >= LONG_TASK_THRESHOLD_MINUTES else SHORT_BREAK_MINUTES
        break_duration = timedelta(minutes=break_minutes)

        placed = False
        while gap_idx < len(gaps):
            gap_start, gap_end = gaps[gap_idx]
            start = cursor if cursor is not None and cursor > gap_start else gap_start
            if start + duration <= gap_end:
                end = start + duration
                seen[description] = seen.get(description, 0) + 1
                label = f"{description} ({seen[description]}/{totals[description]})" if totals[description] > 1 else description
                blocks.append(Block(kind="task", start=start, end=end, label=label))
                break_end = min(end + break_duration, gap_end)
                blocks.append(Block(kind="break", start=end, end=break_end, label="Break"))
                cursor = break_end
                placed = True
                break
            gap_idx += 1
            cursor = None

        if not placed and description not in unscheduled:
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
