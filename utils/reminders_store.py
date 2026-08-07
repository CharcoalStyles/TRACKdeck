"""
utils/reminders_store.py
-------------------------
sqlite3-backed persistence for ad-hoc reminders (agent/tools/alerts.py,
jobs/reminders.py). Separate from memory.db (LangGraph checkpoints) since
reminders are operational state, not conversation history.

Plain stdlib sqlite3, not aiosqlite: the tool functions that call most of
these are synchronous (same convention as agent/tools/calendar.py's
blocking `requests` calls), and a single-user personal assistant doesn't
have enough write volume to need connection pooling. Async call sites
(main.py's lifespan, jobs/reminders.py) wrap these in asyncio.to_thread,
same as jobs/digest.py already does for its own blocking calls.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Optional

DB_PATH = "reminders.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY,
                message TEXT NOT NULL,
                due_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                event_uid TEXT
            )
            """
        )
        # Migration guard for a reminders.db created before event_uid
        # existed (jobs/calendar_sync.py) — CREATE TABLE IF NOT EXISTS
        # above doesn't add columns to an already-existing table.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(reminders)")}
        if "event_uid" not in columns:
            conn.execute("ALTER TABLE reminders ADD COLUMN event_uid TEXT")

        # event_uid is a unique key among calendar-derived reminders (one
        # row tracks "the current known reminder state" for a given
        # calendar event); NULL (plain ad-hoc reminders) is unconstrained.
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_reminders_event_uid "
            "ON reminders(event_uid) WHERE event_uid IS NOT NULL"
        )


def create_reminder(reminder_id: str, message: str, due_at: int, event_uid: Optional[str] = None) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO reminders (id, message, due_at, status, created_at, event_uid) "
            "VALUES (?, ?, ?, 'pending', ?, ?)",
            (reminder_id, message, due_at, int(time.time()), event_uid),
        )


def upsert_calendar_reminder(event_uid: str, message: str, due_at: int) -> tuple[str, bool]:
    """
    Insert or update the single reminder linked to a calendar event
    (jobs/calendar_sync.py). event_uid is treated as a unique key: one
    call per sync pass per event that currently has a native calendar
    alarm.

    Returns (reminder_id, changed). changed is False only when a pending
    row already exists with this exact due_at — nothing for the caller to
    (re)schedule. A prior 'fired' or 'cancelled' row is revived to
    'pending' if due_at has moved (the event was rescheduled), but left
    alone if due_at is unchanged (already delivered, or the user
    explicitly cancelled this occurrence).
    """
    with _connect() as conn:
        existing = conn.execute(
            "SELECT * FROM reminders WHERE event_uid = ?", (event_uid,)
        ).fetchone()

        if existing is None:
            reminder_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO reminders (id, message, due_at, status, created_at, event_uid) "
                "VALUES (?, ?, ?, 'pending', ?, ?)",
                (reminder_id, message, due_at, int(time.time()), event_uid),
            )
            return reminder_id, True

        existing = dict(existing)
        if existing["due_at"] == due_at:
            return existing["id"], False

        conn.execute(
            "UPDATE reminders SET message = ?, due_at = ?, status = 'pending' WHERE id = ?",
            (message, due_at, existing["id"]),
        )
        return existing["id"], True


def get_reminder(reminder_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        return dict(row) if row else None


def list_pending() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE status = 'pending' ORDER BY due_at ASC"
        ).fetchall()
        return [dict(row) for row in rows]


def list_pending_due_within_24h(now_epoch: int) -> list[dict]:
    """Mirrors checkins_store.list_next_24h's shape — everything pending
    and due within the next 24h from now_epoch, including anything
    already overdue (still pending). Used by jobs/device_sync.py."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE status = 'pending' AND due_at <= ? "
            "ORDER BY due_at ASC",
            (now_epoch + 86400,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_pending_calendar_linked() -> list[dict]:
    """Pending reminders derived from a calendar event's own alarm — used
    by jobs/calendar_sync.py to notice an event was deleted or had its
    alarm removed outside the current lookahead window's result set."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE status = 'pending' AND event_uid IS NOT NULL"
        ).fetchall()
        return [dict(row) for row in rows]


def find_pending_by_text(query: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE status = 'pending' AND message LIKE ? "
            "ORDER BY due_at ASC",
            (f"%{query}%",),
        ).fetchall()
        return [dict(row) for row in rows]


def update_reminder(reminder_id: str, message: Optional[str] = None, due_at: Optional[int] = None) -> Optional[dict]:
    """Partial update — only non-None fields are changed."""
    with _connect() as conn:
        if message is not None:
            conn.execute("UPDATE reminders SET message = ? WHERE id = ?", (message, reminder_id))
        if due_at is not None:
            conn.execute("UPDATE reminders SET due_at = ? WHERE id = ?", (due_at, reminder_id))
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        return dict(row) if row else None


def mark_status(reminder_id: str, status: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id))
