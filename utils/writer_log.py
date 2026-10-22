"""
utils/writer_log.py
--------------------
sqlite3-backed log of every decision agent/writer.py makes in the split-model
setup: who wrote a turn's final reply (the tool model's own draft vs. the
writer model), why, and — for long-text tool arguments — whether the writer's
rewrite was used. Exists to make the split legible and to supply real
before/after pairs as eval/training data later.

Same plain-sqlite3, blocking-calls-wrapped-in-asyncio.to_thread convention
as utils/tool_router_log.py.
"""
from __future__ import annotations

import json
import sqlite3
import time

DB_PATH = "data/writer_log.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS writer_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT,
                ts INTEGER NOT NULL,
                kind TEXT NOT NULL,
                mode TEXT,
                route TEXT NOT NULL,
                reason TEXT NOT NULL,
                tools_json TEXT NOT NULL,
                model TEXT,
                draft TEXT,
                final TEXT,
                latency_ms REAL,
                error TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_writer_log_thread_id ON writer_log(thread_id)")


def log_writer(
    *,
    thread_id: str | None,
    kind: str,
    mode: str | None,
    route: str,
    reason: str,
    tools: list[str],
    model: str | None = None,
    draft: str | None = None,
    final: str | None = None,
    latency_ms: float | None = None,
    error: str | None = None,
) -> None:
    """kind: "reply" (final reply) or "arg:<tool>.<field>" (long-text tool
    argument). route: "tool_model" (draft kept), "writer" (writer's text
    used), "template" (reply built in code from the tool result), or "fallback" (writer
    was tried but failed/invalid, draft kept)."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO writer_log "
            "(thread_id, ts, kind, mode, route, reason, tools_json, model, draft, final, latency_ms, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                thread_id, int(time.time()), kind, mode, route, reason, json.dumps(tools),
                model, draft, final, latency_ms, error,
            ),
        )


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "thread_id": row["thread_id"],
        "ts": row["ts"],
        "kind": row["kind"],
        "mode": row["mode"],
        "route": row["route"],
        "reason": row["reason"],
        "tools": json.loads(row["tools_json"]),
        "model": row["model"],
        "draft": row["draft"],
        "final": row["final"],
        "latency_ms": row["latency_ms"],
        "error": row["error"],
    }


def get_writer_log(thread_id: str | None = None, limit: int = 100) -> list[dict]:
    """Newest first. All threads when thread_id is None."""
    with _connect() as conn:
        if thread_id:
            rows = conn.execute(
                "SELECT * FROM writer_log WHERE thread_id = ? ORDER BY id DESC LIMIT ?",
                (thread_id, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM writer_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_row_to_dict(r) for r in rows]
