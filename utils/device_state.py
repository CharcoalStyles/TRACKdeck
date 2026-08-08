"""
utils/device_state.py
-----------------------
sqlite3-backed snapshot of the ESP32's last-reported telemetry
(main.py's POST /device/sync). One physical device, dual-purpose
(push-to-talk voice + periodic check-in/reminder sync) — no fleet/
multi-device concept, so this is a fixed single row (id=1), upserted on
every sync, rather than a table keyed by device id.

Same plain-sqlite3, blocking-calls-wrapped-in-asyncio.to_thread
convention as utils/reminders_store.py and utils/checkins_store.py.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

DB_PATH = "data/device_state.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS device_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                battery_mv INTEGER,
                wake_reason TEXT,
                firmware_version TEXT,
                rssi_dbm INTEGER,
                time_awake_ms INTEGER,
                reset_reason TEXT,
                last_synced_at INTEGER NOT NULL
            )
            """
        )
        # Migration guard for a device_state.db created before
        # time_awake_ms/reset_reason existed — CREATE TABLE IF NOT
        # EXISTS above doesn't add columns to an already-existing table.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(device_state)")}
        if "time_awake_ms" not in columns:
            conn.execute("ALTER TABLE device_state ADD COLUMN time_awake_ms INTEGER")
        if "reset_reason" not in columns:
            conn.execute("ALTER TABLE device_state ADD COLUMN reset_reason TEXT")


def record_sync(
    battery_mv: Optional[int],
    wake_reason: Optional[str],
    firmware_version: Optional[str],
    rssi_dbm: Optional[int],
    time_awake_ms: Optional[int],
    reset_reason: Optional[str],
    synced_at: int,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO device_state (
                id, battery_mv, wake_reason, firmware_version, rssi_dbm,
                time_awake_ms, reset_reason, last_synced_at
            )
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                battery_mv = excluded.battery_mv,
                wake_reason = excluded.wake_reason,
                firmware_version = excluded.firmware_version,
                rssi_dbm = excluded.rssi_dbm,
                time_awake_ms = excluded.time_awake_ms,
                reset_reason = excluded.reset_reason,
                last_synced_at = excluded.last_synced_at
            """,
            (battery_mv, wake_reason, firmware_version, rssi_dbm, time_awake_ms, reset_reason, synced_at),
        )


def get_state() -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM device_state WHERE id = 1").fetchone()
        return dict(row) if row else None
