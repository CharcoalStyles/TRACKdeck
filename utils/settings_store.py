"""
utils/settings_store.py
-------------------------
sqlite3-backed persistence for agent/settings.py's standing app-level
toggles. Settings themselves are plain in-memory class attributes on
that module's `Settings` singleton; this store is the source of truth
across restarts — loaded once via agent.settings.apply_persisted() at
startup (main.py's lifespan), and write-through updated on every
POST /settings change.

Plain stdlib sqlite3, not aiosqlite, same reasoning as
utils/reminders_store.py: callers are synchronous, wrapped in
asyncio.to_thread from async call sites, and a single-user personal
assistant doesn't have enough write volume to need connection pooling.

Values are stored as plain TEXT — sqlite3 has no native bool, and every
setting here is a str/bool/int, so the caller (agent.settings) parses
each field back to its real type on load.
"""
from __future__ import annotations

import sqlite3

DB_PATH = "data/settings.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )


def load_all() -> dict[str, str]:
    with _connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}


def set_many(values: dict[str, str]) -> None:
    """Upsert every key/value pair in one connection — a multi-field
    /settings save (e.g. the Location & Time card's default_location +
    timezone) is one write, not one per field."""
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            list(values.items()),
        )
