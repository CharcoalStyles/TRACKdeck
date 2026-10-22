"""
Phase A of the local decision-model tool-router plan (see
as-you-know-we-ve-prancy-ritchie.md): pull every tool call this assistant
has ever made straight out of memory.db's checkpoints table, for manual
failure-type labeling.

Standalone and throwaway -- NOT part of the app, not imported by it.
Read-only against data/memory.db: only ever SELECTs, via LangGraph's own
AsyncSqliteSaver (its setup() issues an idempotent CREATE TABLE IF NOT
EXISTS + PRAGMA journal_mode=WAL, both no-ops against an existing,
already-WAL memory.db). Does not boot the app, so no scheduler jobs,
Gotify pushes, or tool clients are ever touched.

Usage: uv run python scratchpad/dump_tool_calls.py
Output: scratchpad/tool_call_dump.json
"""
import asyncio
import json
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

DB_PATH = "data/memory.db"
OUT_PATH = Path(__file__).parent / "tool_call_dump.json"


def stringify_content(content):
    """Mirrors utils/llm_client.py's stringify_content, duplicated here so
    this script has zero imports from the app package."""
    if content is None or isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    try:
        return json.dumps(content)
    except TypeError:
        return str(content)


def list_thread_ids() -> list[str]:
    # mode=ro: this connection can never write, even accidentally.
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT thread_id, MAX(checkpoint_id) FROM checkpoints "
            "GROUP BY thread_id ORDER BY 2 DESC"
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


async def dump_thread(checkpointer: AsyncSqliteSaver, thread_id: str) -> list[dict]:
    """One record per tool call in the thread's latest checkpoint (which
    holds the full cumulative message history, not a delta -- MessagesState
    accumulates via add_messages)."""
    tup = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
    if tup is None:
        return []
    messages = tup.checkpoint.get("channel_values", {}).get("messages", [])

    records: list[dict] = []
    last_user_msg = None
    pending_by_call_id: dict[str, dict] = {}

    for m in messages:
        msg_type = getattr(m, "type", None)
        if msg_type == "human":
            last_user_msg = stringify_content(getattr(m, "content", None))
        elif msg_type == "ai" and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                rec = {
                    "thread_id": thread_id,
                    "user_message": last_user_msg,
                    "tool_name": tc["name"],
                    "tool_args": tc["args"],
                    "error": None,
                    "result_preview": None,
                    "label": "",  # hand-fill: wrong_tool / not_called / unneeded / bad_args / correct
                }
                records.append(rec)
                call_id = tc.get("id")
                if call_id:
                    pending_by_call_id[call_id] = rec
        elif msg_type == "tool":
            rec = pending_by_call_id.get(getattr(m, "tool_call_id", None))
            if rec is not None:
                rec["error"] = getattr(m, "status", None) == "error"
                content = stringify_content(getattr(m, "content", None))
                rec["result_preview"] = content[:200] if content else None

    return records


async def main():
    thread_ids = list_thread_ids()
    print(f"Found {len(thread_ids)} thread(s) in {DB_PATH}")

    all_records: list[dict] = []
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        for tid in thread_ids:
            all_records.extend(await dump_thread(checkpointer, tid))

    OUT_PATH.write_text(json.dumps(all_records, indent=2, default=str))
    print(f"Wrote {len(all_records)} tool-call record(s) to {OUT_PATH}")

    from collections import Counter
    by_tool = Counter(r["tool_name"] for r in all_records)
    by_error = Counter(r["error"] for r in all_records)
    print("By tool:", dict(by_tool.most_common()))
    print("By error status:", dict(by_error))


if __name__ == "__main__":
    asyncio.run(main())
