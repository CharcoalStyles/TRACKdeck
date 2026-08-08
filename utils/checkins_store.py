"""
utils/checkins_store.py
-------------------------
sqlite3-backed persistence for mental-health check-in prompts
(jobs/checkin.py, jobs/day_start.py). Separate from reminders.db: that
table is purpose-built for single-fire, dedup-by-event_uid reminders and
doesn't fit a recurring, stateful check-in with retry/cooldown semantics.

Plain stdlib sqlite3, not aiosqlite — same convention as
utils/reminders_store.py: blocking calls, wrapped in asyncio.to_thread by
every async call site.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Optional

DB_PATH = "data/checkins.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checkins (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                prompt_text TEXT NOT NULL,
                thread_id TEXT,
                keyword TEXT,
                scheduled_at INTEGER NOT NULL,
                fired_at INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                resolved_at INTEGER,
                retry_of TEXT REFERENCES checkins(id),
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS day_plans (
                day_start_utc INTEGER PRIMARY KEY,
                target_count INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )


def create_checkin(
    checkin_id: str,
    category: str,
    prompt_text: str,
    scheduled_at: int,
    retry_of: Optional[str] = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO checkins (id, category, prompt_text, scheduled_at, "
            "status, retry_of, created_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (checkin_id, category, prompt_text, scheduled_at, retry_of, int(time.time())),
        )


def mark_fired(checkin_id: str, thread_id: str, keyword: str, fired_at: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE checkins SET thread_id = ?, keyword = ?, fired_at = ? WHERE id = ?",
            (thread_id, keyword, fired_at, checkin_id),
        )


def mark_resolved(checkin_id: str, status: str, resolved_at: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE checkins SET status = ?, resolved_at = ? WHERE id = ?",
            (status, resolved_at, checkin_id),
        )


def get_checkin(checkin_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM checkins WHERE id = ?", (checkin_id,)).fetchone()
        return dict(row) if row else None


def list_pending_unfired() -> list[dict]:
    """Not-yet-fired scheduled check-ins — re-hydrated into checkin:<id>
    one-shot jobs at startup (main.py's lifespan)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM checkins WHERE status = 'pending' AND fired_at IS NULL "
            "ORDER BY scheduled_at ASC"
        ).fetchall()
        return [dict(row) for row in rows]


def list_fired_awaiting_response() -> list[dict]:
    """Fired but not yet answered/skipped/expired — re-hydrated into
    checkin_expire:<id> jobs at startup, and what GET /device/sync shows
    as currently active."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM checkins WHERE status = 'pending' AND fired_at IS NOT NULL "
            "ORDER BY fired_at ASC"
        ).fetchall()
        return [dict(row) for row in rows]


def list_next_24h(now_epoch: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM checkins WHERE status = 'pending' AND scheduled_at <= ? "
            "ORDER BY scheduled_at ASC",
            (now_epoch + 86400,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_answered_between(start_ts: int, end_ts: int) -> list[dict]:
    """Answered check-ins resolved within [start_ts, end_ts] (UTC epoch
    seconds, inclusive), oldest first. Used by jobs/digest.py to surface
    today's gratitude/mood/wins reflections as their own section instead of
    letting them blend anonymously into the generic conversation log."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM checkins WHERE status = 'answered' "
            "AND resolved_at BETWEEN ? AND ? ORDER BY resolved_at ASC",
            (start_ts, end_ts),
        ).fetchall()
        return [dict(row) for row in rows]


def list_resolved_between(start_ts: int, end_ts: int) -> list[dict]:
    """Every check-in resolved within [start_ts, end_ts] (UTC epoch
    seconds, inclusive), oldest first — answered, skipped, or expired
    (the superset of list_answered_between). resolved_at is NULL for
    still-pending check-ins, so the range comparison already excludes
    them without an explicit status filter. Used by main.py's
    GET /checkins/today for the dashboard's check-in history page."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM checkins WHERE resolved_at BETWEEN ? AND ? "
            "ORDER BY resolved_at ASC",
            (start_ts, end_ts),
        ).fetchall()
        return [dict(row) for row in rows]


def get_most_recent_fired() -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM checkins WHERE fired_at IS NOT NULL ORDER BY fired_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def count_scheduled_today(day_start_utc: int, day_end_utc: int) -> int:
    """Any status — a fallback retry still counts as one of today's
    interruptions even though it's not a fresh, independent prompt."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM checkins WHERE scheduled_at BETWEEN ? AND ?",
            (day_start_utc, day_end_utc),
        ).fetchone()
        return row["n"]


def high_used_today(day_start_utc: int, day_end_utc: int) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM checkins WHERE category = 'high' "
            "AND scheduled_at BETWEEN ? AND ? LIMIT 1",
            (day_start_utc, day_end_utc),
        ).fetchone()
        return row is not None


def create_day_plan(day_start_utc: int, target_count: int) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO day_plans (day_start_utc, target_count, created_at) "
            "VALUES (?, ?, ?)",
            (day_start_utc, target_count, int(time.time())),
        )


def get_day_plan(day_start_utc: int) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM day_plans WHERE day_start_utc = ?", (day_start_utc,)
        ).fetchone()
        return dict(row) if row else None
