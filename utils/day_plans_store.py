"""
utils/day_plans_store.py
--------------------------
sqlite3-backed persistence for scheduled day plans — the "build my
schedule at T-15" feature. Separate from the vault planning note (which
remains the source of truth for tasks/fixed-blocks/the generated
schedule text itself): this table only tracks *scheduling intent* for a
date — what time it should start, and whether the LLM has run yet —
since that's operational state, not note content, same reasoning as
utils/reminders_store.py's separation from memory.db.

Plain stdlib sqlite3, not aiosqlite — same convention as
utils/reminders_store.py; async call sites (main.py's lifespan,
routes/day_plans.py, jobs/day_plan_trigger.py) wrap these in
asyncio.to_thread.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Optional

DB_PATH = "data/day_plans.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS day_plans (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                start_time TEXT,
                end_time TEXT,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'scheduled',
                reply TEXT,
                created_at INTEGER NOT NULL,
                generated_at INTEGER
            )
            """
        )


def create(
    plan_id: str,
    date: str,
    start_time: Optional[str],
    end_time: Optional[str],
    notes: Optional[str],
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO day_plans (id, date, start_time, end_time, notes, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'scheduled', ?)",
            (plan_id, date, start_time, end_time, notes, int(time.time())),
        )


def get(plan_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM day_plans WHERE id = ?", (plan_id,)).fetchone()
        return dict(row) if row else None


def list_upcoming(from_date: str) -> list[dict]:
    """Every not-yet-generated, not-cancelled plan for `from_date` or
    later, earliest first — backs the dashboard's Upcoming Plans list."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM day_plans WHERE status = 'scheduled' AND date >= ? "
            "ORDER BY date ASC, start_time ASC",
            (from_date,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_scheduled() -> list[dict]:
    """Every not-yet-generated, not-cancelled plan regardless of date —
    used by main.py's lifespan to re-hydrate scheduler jobs across a
    restart, same as reminders_store.list_pending."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM day_plans WHERE status = 'scheduled'").fetchall()
        return [dict(row) for row in rows]


def update(
    plan_id: str,
    start_time: Optional[str],
    end_time: Optional[str],
    notes: Optional[str],
) -> Optional[dict]:
    with _connect() as conn:
        conn.execute(
            "UPDATE day_plans SET start_time = ?, end_time = ?, notes = ? WHERE id = ?",
            (start_time, end_time, notes, plan_id),
        )
        row = conn.execute("SELECT * FROM day_plans WHERE id = ?", (plan_id,)).fetchone()
        return dict(row) if row else None


def mark_generated(plan_id: str, reply: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE day_plans SET status = 'generated', reply = ?, generated_at = ? WHERE id = ?",
            (reply, int(time.time()), plan_id),
        )


def cancel(plan_id: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE day_plans SET status = 'cancelled' WHERE id = ?", (plan_id,))
