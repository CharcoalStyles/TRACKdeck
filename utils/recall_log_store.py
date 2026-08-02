"""
utils/recall_log_store.py
--------------------------
sqlite3-backed log of what agent/memory.py's search_conversations actually
recalled/injected into the system prompt on each turn — computed live and
otherwise thrown away (see agent/graph.py's call_llm). Exists purely to
make the "thread-debug" dashboard page useful: seeing real distances/
source threads/ages is how recall_max_distance/recall_recency_days
(agent/settings.py) get tuned from data instead of guesses.

Same plain-sqlite3, blocking-calls-wrapped-in-asyncio.to_thread convention
as utils/reminders_store.py.
"""
from __future__ import annotations

import json
import sqlite3
import time

DB_PATH = "recall_log.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recall_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                turn_timestamp INTEGER NOT NULL,
                query TEXT NOT NULL,
                recalled_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_recall_log_thread_id ON recall_log(thread_id)"
        )


def log_recall(thread_id: str, query: str, recalled: list[dict]) -> None:
    """recalled is search_conversations' return value — a list of
    {"document", "thread_id", "timestamp", "distance"} dicts, stored as-is
    so the debug page can show exactly what was considered relevant."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO recall_log (thread_id, turn_timestamp, query, recalled_json) "
            "VALUES (?, ?, ?, ?)",
            (thread_id, int(time.time()), query, json.dumps(recalled)),
        )


def get_recall_for_thread(thread_id: str) -> list[dict]:
    """This thread's recall history, oldest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT turn_timestamp, query, recalled_json FROM recall_log "
            "WHERE thread_id = ? ORDER BY turn_timestamp ASC",
            (thread_id,),
        ).fetchall()
        return [
            {
                "turn_timestamp": row["turn_timestamp"],
                "query": row["query"],
                "recalled": json.loads(row["recalled_json"]),
            }
            for row in rows
        ]
