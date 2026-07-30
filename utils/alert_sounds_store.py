"""
utils/alert_sounds_store.py
-----------------------------
sqlite3-backed catalog of converted alert-sound WAV files
(routes/alert_sounds.py). The audio itself lives on disk under
ALERT_SOUNDS_DIR as `{id}.wav`; this table is just the metadata the
dashboard and jobs/device_sync.py need — display name, duration/size for
the manage page, and a sha256 so the ESP32-S3 can tell a new/changed file
from one it already has on its SD card.

Same plain-sqlite3, blocking-calls-wrapped-in-asyncio.to_thread
convention as utils/reminders_store.py and utils/device_state.py.
"""
from __future__ import annotations

import os
import sqlite3

DB_PATH = "alert_sounds.db"
ALERT_SOUNDS_DIR = "./alert_sounds"

os.makedirs(ALERT_SOUNDS_DIR, exist_ok=True)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_sounds (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )


def audio_path(sound_id: str) -> str:
    return os.path.join(ALERT_SOUNDS_DIR, f"{sound_id}.wav")


def create_sound(
    sound_id: str,
    display_name: str,
    duration_seconds: float,
    size_bytes: int,
    sha256: str,
    created_at: int,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO alert_sounds "
            "(id, display_name, duration_seconds, size_bytes, sha256, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sound_id, display_name, duration_seconds, size_bytes, sha256, created_at),
        )


def get_sound(sound_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM alert_sounds WHERE id = ?", (sound_id,)).fetchone()
        return dict(row) if row else None


def list_sounds() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM alert_sounds ORDER BY created_at ASC").fetchall()
        return [dict(row) for row in rows]


def delete_sound(sound_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM alert_sounds WHERE id = ?", (sound_id,))
