"""
utils/task_library_store.py
-----------------------------
sqlite3-backed persistence for the reusable task library on the Day
Planning page ("Clean the kitchen", "Tidy the study", ...) — a plain
CRUD list the dashboard reads to let you click a saved task straight
into the current plan, with its default duration pre-filled into the
task row for editing. Same stdlib-sqlite3 pattern as
utils/reminders_store.py; no relation to the vault or any planning
note — this is just a template list, never scheduled or generated from
directly.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Optional

DB_PATH = "data/task_library.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_library (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                default_minutes INTEGER NOT NULL,
                group_name TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )


def list_all() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM task_library ORDER BY group_name IS NULL, group_name, label"
        ).fetchall()
        return [dict(row) for row in rows]


def get(item_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM task_library WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None


def create(item_id: str, label: str, default_minutes: int, group_name: Optional[str]) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO task_library (id, label, default_minutes, group_name, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (item_id, label, default_minutes, group_name, int(time.time())),
        )


def update(item_id: str, label: str, default_minutes: int, group_name: Optional[str]) -> Optional[dict]:
    with _connect() as conn:
        conn.execute(
            "UPDATE task_library SET label = ?, default_minutes = ?, group_name = ? WHERE id = ?",
            (label, default_minutes, group_name, item_id),
        )
        row = conn.execute("SELECT * FROM task_library WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None


def delete(item_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM task_library WHERE id = ?", (item_id,))
