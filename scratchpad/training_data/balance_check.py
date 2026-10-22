"""
scratchpad/training_data/balance_check.py
--------------------------------------------
Counter-based coverage/balance report across one or more tranche JSONL files:
per-tool frequency, per-category frequency (via agent/tool_router.py's
CATEGORY_MAP), no-tool-needed fraction, mode fraction. Flags any tool over
~10% of the combined set or a negative fraction under ~10%.

Usage: uv run python scratchpad/training_data/balance_check.py <jsonl_file> [...]
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agent.tool_router import CATEGORY_MAP  # noqa: E402


def main():
    records = []
    for path in sys.argv[1:]:
        for line in open(path):
            if line.strip():
                records.append(json.loads(line))

    total = len(records)
    tool_counter = Counter()
    category_counter = Counter()
    no_tool = 0
    mode_counter = Counter()

    for r in records:
        mode_counter[r["mode"]] += 1
        tools_called = set()
        for turn in r["turns"]:
            for tc in turn.get("tool_calls", []):
                tools_called.add(tc["name"])
        if not tools_called:
            no_tool += 1
        for t in tools_called:
            tool_counter[t] += 1
            category_counter[CATEGORY_MAP.get(t, "uncategorized")] += 1

    print(f"Total records: {total}\n")
    print("Per-tool frequency (flag >10% of total):")
    for tool, n in tool_counter.most_common():
        pct = 100 * n / total
        flag = "  <-- OVER 10%" if pct > 10 else ""
        print(f"  {tool}: {n} ({pct:.1f}%){flag}")

    print("\nPer-category frequency:")
    for cat, n in category_counter.most_common():
        print(f"  {cat}: {n} ({100*n/total:.1f}%)")

    print(f"\nNo-tool-needed: {no_tool} ({100*no_tool/total:.1f}%)" + (" <-- UNDER 10%" if 100*no_tool/total < 10 else ""))
    print(f"\nMode distribution: {dict(mode_counter)}")

    all_tools = set(CATEGORY_MAP.keys())
    uncovered = all_tools - set(tool_counter.keys())
    if uncovered:
        print(f"\n{len(uncovered)} tool(s) with ZERO coverage so far:")
        for t in sorted(uncovered):
            print(f"  - {t} ({CATEGORY_MAP.get(t)})")


if __name__ == "__main__":
    main()
