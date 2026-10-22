"""
scratchpad/training_data/date_resolver.py
-------------------------------------------
Small, deterministic relative-date/time resolver for authoring LoRA training
examples. NOT a free-text NLP parser — called directly with an explicit
phrase-type + anchor datetime while hand-authoring an example, so every
date/time in the training set is computed by code and verified, never
guessed by a human or an LLM. This is the single highest-leverage lever on
the documented date-arithmetic failure class (a ~316-day-off reminder,
"next Tuesday" miscalculations) — training examples must model CORRECT
arithmetic, which means the arithmetic itself can never come from eyeballing
a calendar.

Usage: run with an anchor and a phrase type, read off the resolved ISO
value, and use that in the training example you're authating by hand. E.g.:

    python3 scratchpad/training_data/date_resolver.py 2026-10-05 next_weekday Tuesday
    python3 scratchpad/training_data/date_resolver.py 2026-10-05 in_days 3
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def next_weekday(anchor: datetime, weekday_name: str) -> datetime:
    """'Next <weekday>' — the next occurrence strictly after today, even if
    today already is that weekday (i.e. always 1-7 days ahead, never 0)."""
    target = WEEKDAYS.index(weekday_name)
    days_ahead = (target - anchor.weekday() + 7) % 7
    if days_ahead == 0:
        days_ahead = 7
    return anchor + timedelta(days=days_ahead)


def this_weekday(anchor: datetime, weekday_name: str) -> datetime:
    """'This <weekday>' — the occurrence in the current week, which IS today
    if today already is that weekday (the "today is already Saturday" trap
    from eval prompt C15)."""
    target = WEEKDAYS.index(weekday_name)
    days_ahead = (target - anchor.weekday() + 7) % 7
    return anchor + timedelta(days=days_ahead)


def in_days(anchor: datetime, n: int) -> datetime:
    return anchor + timedelta(days=n)


def tomorrow(anchor: datetime) -> datetime:
    return anchor + timedelta(days=1)


def day_after_tomorrow(anchor: datetime) -> datetime:
    return anchor + timedelta(days=2)


def this_weekend(anchor: datetime) -> tuple[datetime, datetime]:
    """Returns (Saturday, Sunday) of the current week — if today is already
    Sat/Sun, that's still "this weekend" (today through Sunday)."""
    sat = this_weekday(anchor, "Saturday")
    sun = this_weekday(anchor, "Sunday")
    return sat, sun


def a_week_from(anchor: datetime) -> datetime:
    return anchor + timedelta(days=7)


def end_of_week(anchor: datetime) -> datetime:
    """Sunday of the current week (inclusive range end, e.g. 'what do I have
    on this week')."""
    return this_weekday(anchor, "Sunday")


def with_time(d: datetime, hour: int, minute: int = 0) -> datetime:
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0)


FUNCS = {
    "next_weekday": lambda a, *args: next_weekday(a, args[0]),
    "this_weekday": lambda a, *args: this_weekday(a, args[0]),
    "in_days": lambda a, *args: in_days(a, int(args[0])),
    "tomorrow": lambda a, *args: tomorrow(a),
    "day_after_tomorrow": lambda a, *args: day_after_tomorrow(a),
    "a_week_from": lambda a, *args: a_week_from(a),
    "end_of_week": lambda a, *args: end_of_week(a),
}


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    anchor = datetime.fromisoformat(sys.argv[1])
    phrase_type = sys.argv[2]
    args = sys.argv[3:]

    if phrase_type == "this_weekend":
        sat, sun = this_weekend(anchor)
        print(f"Saturday: {sat.date().isoformat()} ({WEEKDAYS[sat.weekday()]})")
        print(f"Sunday:   {sun.date().isoformat()} ({WEEKDAYS[sun.weekday()]})")
        return

    if phrase_type not in FUNCS:
        print(f"Unknown phrase type {phrase_type!r}. Known: {list(FUNCS)} + this_weekend")
        sys.exit(1)

    result = FUNCS[phrase_type](anchor, *args)
    print(f"{result.date().isoformat()} ({WEEKDAYS[result.weekday()]})")


if __name__ == "__main__":
    main()
