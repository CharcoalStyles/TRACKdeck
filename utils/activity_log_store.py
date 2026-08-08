"""
utils/activity_log_store.py
-----------------------------
sqlite3-backed persistence for the structured activity log (agent/tools/
activity_log.py's log_activity tool). Separate from the vault: the point
of this data is exact/numeric analysis and charting (dashboard's
Activity Log page), which frontmatter/markdown can't do well — see
utils/vault.py and agent/memory.py for why notes weren't a fit.

Plain stdlib sqlite3, not aiosqlite — same convention as
utils/checkins_store.py/utils/reminders_store.py: blocking calls,
wrapped in asyncio.to_thread by every async call site.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Optional

DB_PATH = "data/activity_log.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                id TEXT PRIMARY KEY,
                occurred_at INTEGER NOT NULL,
                activity_type TEXT NOT NULL,
                subject TEXT NOT NULL,
                duration TEXT,
                mood_energy INTEGER,
                reflection TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_activity_log_occurred_at "
            "ON activity_log(occurred_at)"
        )


def create_entry(
    entry_id: str,
    occurred_at: int,
    activity_type: str,
    subject: str,
    duration: Optional[str],
    mood_energy: Optional[int],
    reflection: Optional[str],
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO activity_log (id, occurred_at, activity_type, subject, "
            "duration, mood_energy, reflection, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry_id,
                occurred_at,
                activity_type,
                subject,
                duration,
                mood_energy,
                reflection,
                int(time.time()),
            ),
        )


def list_between(
    start_ts: int, end_ts: int, activity_type: Optional[str] = None
) -> list[dict]:
    """Entries with occurred_at BETWEEN start_ts AND end_ts (UTC epoch
    seconds, inclusive), newest first. Optional activity_type filter.
    Backs both GET /activity-log (raw list) and GET /activity-log/summary
    (jobs/activity_log.py aggregates this same result set in Python,
    since duration parsing can't be expressed in SQL)."""
    with _connect() as conn:
        if activity_type:
            rows = conn.execute(
                "SELECT * FROM activity_log WHERE occurred_at BETWEEN ? AND ? "
                "AND activity_type = ? ORDER BY occurred_at DESC",
                (start_ts, end_ts, activity_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM activity_log WHERE occurred_at BETWEEN ? AND ? "
                "ORDER BY occurred_at DESC",
                (start_ts, end_ts),
            ).fetchall()
        return [dict(row) for row in rows]
