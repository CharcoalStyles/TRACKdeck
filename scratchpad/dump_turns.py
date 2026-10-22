"""
Phase A extraction, v2: one record per human->AI turn (not per tool call),
so a text-only reply where a tool was warranted (not_called) is captured,
and each record carries which model/provider produced it (so local
LM Studio failure rates can be isolated from OpenRouter/Gemini calls sitting
in the same memory.db).

Standalone, read-only against data/memory.db via LangGraph's own
AsyncSqliteSaver -- same approach as dump_tool_calls.py, not part of the app.

Usage: uv run python scratchpad/dump_turns.py
Output: scratchpad/turn_dump.json
"""
import asyncio
import json
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

DB_PATH = "data/memory.db"
OUT_PATH = Path(__file__).parent / "turn_dump.json"


def stringify_content(content):
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
    tup = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
    if tup is None:
        return []
    messages = tup.checkpoint.get("channel_values", {}).get("messages", [])

    records: list[dict] = []
    last_user_msg = None

    for i, m in enumerate(messages):
        msg_type = getattr(m, "type", None)
        if msg_type == "human":
            last_user_msg = stringify_content(getattr(m, "content", None))
            continue
        if msg_type != "ai":
            continue

        meta = getattr(m, "response_metadata", None) or {}
        model_name = meta.get("model_name") or meta.get("model")
        model_provider = meta.get("model_provider")

        tool_calls_raw = getattr(m, "tool_calls", None) or []

        # ToolMessages for this ai turn are the run of "tool"-typed messages
        # immediately following it, before the next ai/human message.
        j = i + 1
        tool_msgs = []
        while j < len(messages) and getattr(messages[j], "type", None) == "tool":
            tool_msgs.append(messages[j])
            j += 1
        tool_msg_by_id = {getattr(tm, "tool_call_id", None): tm for tm in tool_msgs}

        tc_list = []
        for tc in tool_calls_raw:
            tm = tool_msg_by_id.get(tc.get("id"))
            error = (getattr(tm, "status", None) == "error") if tm is not None else None
            tc_list.append({"tool_name": tc["name"], "tool_args": tc["args"], "error": error})

        records.append({
            "thread_id": thread_id,
            "user_message": last_user_msg,
            "model_name": model_name,
            "model_provider": model_provider,
            "tool_calls": tc_list,
            "ai_text": stringify_content(getattr(m, "content", None)) if not tc_list else None,
            "label": "",
        })

    return records


async def main():
    thread_ids = list_thread_ids()
    print(f"Found {len(thread_ids)} thread(s) in {DB_PATH}")

    all_records: list[dict] = []
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        for tid in thread_ids:
            all_records.extend(await dump_thread(checkpointer, tid))

    OUT_PATH.write_text(json.dumps(all_records, indent=2, default=str))
    print(f"Wrote {len(all_records)} turn record(s) to {OUT_PATH}")

    from collections import Counter
    by_model = Counter((r["model_provider"], r["model_name"]) for r in all_records)
    no_tool = sum(1 for r in all_records if not r["tool_calls"])
    print("By (provider, model):", dict(by_model.most_common()))
    print(f"Turns with zero tool_calls: {no_tool}/{len(all_records)}")


if __name__ == "__main__":
    asyncio.run(main())
