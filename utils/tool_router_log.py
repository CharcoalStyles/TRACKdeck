"""
utils/tool_router_log.py
--------------------------
sqlite3-backed log of what agent/tool_router.py's choose_tool_subset actually
decided on each turn — computed live and otherwise thrown away (see
agent/graph.py's call_llm). Exists purely to make the tool-router's
before/after A/B comparison legible on the thread-debug dashboard page,
same reasoning as utils/recall_log_store.py for recall tuning.

Same plain-sqlite3, blocking-calls-wrapped-in-asyncio.to_thread convention
as utils/reminders_store.py/utils/recall_log_store.py.
"""
from __future__ import annotations

import json
import sqlite3
import time

DB_PATH = "data/tool_router_log.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_router_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                turn_timestamp INTEGER NOT NULL,
                message TEXT NOT NULL,
                categories_json TEXT NOT NULL,
                probabilities_json TEXT,
                narrowed INTEGER NOT NULL,
                reason TEXT NOT NULL,
                latency_ms REAL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tool_router_log_thread_id ON tool_router_log(thread_id)"
        )


def log_tool_router(thread_id: str, message: str, decision) -> None:
    """decision is a RouterDecision (agent/tool_router.py). probabilities
    covers every candidate category Laya was asked about (not just the
    selected ones) so CONFIDENCE_THRESHOLD can be tuned from real data
    later, same reasoning as recall_max_distance's own tuning story."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO tool_router_log "
            "(thread_id, turn_timestamp, message, categories_json, probabilities_json, narrowed, reason, latency_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                thread_id, int(time.time()), message,
                json.dumps(decision.categories),
                json.dumps(decision.probabilities) if decision.probabilities is not None else None,
                int(decision.narrowed), decision.reason, decision.latency_ms,
            ),
        )


def get_tool_router_log_for_thread(thread_id: str) -> list[dict]:
    """This thread's router decisions, oldest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT turn_timestamp, message, categories_json, probabilities_json, narrowed, reason, latency_ms "
            "FROM tool_router_log WHERE thread_id = ? ORDER BY turn_timestamp ASC",
            (thread_id,),
        ).fetchall()
        return [
            {
                "turn_timestamp": row["turn_timestamp"],
                "message": row["message"],
                "categories": json.loads(row["categories_json"]),
                "probabilities": json.loads(row["probabilities_json"]) if row["probabilities_json"] else None,
                "narrowed": bool(row["narrowed"]),
                "reason": row["reason"],
                "latency_ms": row["latency_ms"],
            }
            for row in rows
        ]
