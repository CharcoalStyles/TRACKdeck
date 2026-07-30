"""
utils/device_errors_store.py
------------------------------
sqlite3-backed history of device error reports (main.py's
POST /device/error) — every report is logged here regardless of whether
it actually triggered a Gotify alert (utils.notify.notify_device_error's
per-error_type cooldown may suppress the push itself), so
static/errors.html can show the full picture: e.g. "this fired 40 times,
alerted twice" rather than only the sparse alerted subset.

Same plain-sqlite3, blocking-calls-wrapped-in-asyncio.to_thread
convention as utils/reminders_store.py and utils/device_state.py.
"""
from __future__ import annotations

import sqlite3
import uuid
from typing import Optional

DB_PATH = "device_errors.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS device_errors (
                id TEXT PRIMARY KEY,
                error_type TEXT NOT NULL,
                message TEXT,
                firmware_version TEXT,
                reset_reason TEXT,
                wake_reason TEXT,
                battery_mv INTEGER,
                battery_pct INTEGER,
                rssi_dbm INTEGER,
                free_internal_heap_bytes INTEGER,
                alerted INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )


def record_error(
    error_type: str,
    message: Optional[str],
    firmware_version: Optional[str],
    reset_reason: Optional[str],
    wake_reason: Optional[str],
    battery_mv: Optional[int],
    battery_pct: Optional[int],
    rssi_dbm: Optional[int],
    free_internal_heap_bytes: Optional[int],
    alerted: bool,
    created_at: int,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO device_errors (
                id, error_type, message, firmware_version, reset_reason,
                wake_reason, battery_mv, battery_pct, rssi_dbm,
                free_internal_heap_bytes, alerted, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()), error_type, message, firmware_version, reset_reason,
                wake_reason, battery_mv, battery_pct, rssi_dbm,
                free_internal_heap_bytes, int(alerted), created_at,
            ),
        )


def list_recent(limit: int = 200) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM device_errors ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
