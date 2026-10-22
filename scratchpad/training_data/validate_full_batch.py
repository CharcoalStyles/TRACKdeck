"""
scratchpad/training_data/validate_full_batch.py
--------------------------------------------------
Validation suite for full-batch chunks written directly in the trainer's
final schema (id/source/category/anchor/flags/text/turns/date_intents/
group/history/notes) — unlike the pilot's tranche1-3 files, there's no
intermediate internal schema here, so check_contamination.py/balance_check.py
(built for that internal schema) don't apply as-is. This supersedes them for
full-batch chunks.

Usage: uv run python scratchpad/training_data/validate_full_batch.py <jsonl_file> [...]
"""
import difflib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agent.tool_router import CATEGORY_MAP  # noqa: E402

ROOT = Path(__file__).parent.parent.parent
EVAL_PATH = ROOT / "scratchpad" / "eval_prompts.json"
TOOL_SCHEMAS_PATH = ROOT / "scratchpad" / "tool_schemas.json"
MCP_SCHEMAS_PATH = ROOT / "scratchpad" / "training_data" / "mcp_tool_schemas.json"
TZ = ZoneInfo("Australia/Canberra")
CONTAM_THRESHOLD = 0.85

UID_PATTERNS = [
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),  # full uuid
    re.compile(r"\b[0-9a-f]{8}\b", re.I),  # bare 8-hex note id
]


def load_tool_schemas():
    schemas = {}
    for path in (TOOL_SCHEMAS_PATH, MCP_SCHEMAS_PATH):
        for entry in json.load(open(path)):
            fn = entry["function"]
            params = fn.get("parameters", {})
            props = params.get("properties", {})
            required = set(params.get("required", []))
            schemas[fn["name"]] = {"props": set(props.keys()), "required": required}
    return schemas


def normalize(text: str) -> str:
    return " ".join(text.lower().split())


def check_contamination(records, eval_texts):
    flagged = []
    for r in records:
        msg = normalize(r["text"])
        for eval_id, eval_text in eval_texts:
            if msg == eval_text:
                flagged.append((r["id"], eval_id, 1.0, "exact"))
                continue
            ratio = difflib.SequenceMatcher(None, msg, eval_text).ratio()
            if ratio >= CONTAM_THRESHOLD:
                flagged.append((r["id"], eval_id, round(ratio, 3), "fuzzy"))
    return flagged


def check_arg_schemas(records, schemas):
    issues = []
    for r in records:
        for turn_list_name, turn_list in (("turns", r.get("turns", [])), ("history", r.get("history", []))):
            for turn in turn_list:
                for tc in turn.get("tool_calls", []):
                    name = tc.get("name")
                    args = tc.get("args", {})
                    if name not in schemas:
                        issues.append(f"{r['id']}: unknown tool '{name}' in {turn_list_name}")
                        continue
                    sch = schemas[name]
                    unknown = set(args.keys()) - sch["props"]
                    missing = sch["required"] - set(args.keys())
                    if unknown:
                        issues.append(f"{r['id']}: {name} has unknown args {unknown} in {turn_list_name}")
                    if missing:
                        issues.append(f"{r['id']}: {name} missing required args {missing} in {turn_list_name}")
    return issues


def check_turn_shape(records):
    """turns uses the trainer's block shape ({tool_calls,content} ->
    {tool_results} -> {content}); history uses flat OpenAI-style
    role-tagged messages (role: user/assistant/tool), per the pilot's own
    convention (e.g. T1-0013's history) -- these are NOT the same shape,
    so each needs its own check."""
    issues = []
    for r in records:
        turn_list = r.get("turns")
        if turn_list:
            last = turn_list[-1]
            if "tool_calls" in last or "content" not in last:
                issues.append(f"{r['id']}: turns doesn't end on a plain content turn")
            for idx, turn in enumerate(turn_list):
                if "tool_calls" in turn:
                    nxt = turn_list[idx + 1] if idx + 1 < len(turn_list) else None
                    if not nxt or "tool_results" not in nxt:
                        issues.append(f"{r['id']}: turns tool_calls not immediately followed by tool_results")
                    elif len(nxt["tool_results"]) != len(turn["tool_calls"]):
                        issues.append(f"{r['id']}: turns tool_results length != tool_calls length")

        history = r.get("history")
        if history:
            last = history[-1]
            if last.get("role") != "assistant" or "tool_calls" in last or not last.get("content"):
                issues.append(f"{r['id']}: history doesn't end on a plain assistant content message")
            i = 0
            while i < len(history):
                msg = history[i]
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    n_calls = len(msg["tool_calls"])
                    tool_msgs = history[i + 1:i + 1 + n_calls]
                    if len(tool_msgs) != n_calls or any(m.get("role") != "tool" for m in tool_msgs):
                        issues.append(f"{r['id']}: history tool_calls not immediately followed by {n_calls} tool-role message(s)")
                    i += 1 + n_calls
                else:
                    i += 1
    return issues


def check_stated_ids(records):
    issues = []
    for r in records:
        text = r.get("text", "")
        for pat in UID_PATTERNS:
            if pat.search(text):
                issues.append(f"{r['id']}: possible stated id in text: {pat.search(text).group()}")
    return issues


def check_reminder_future(records):
    issues = []
    for r in records:
        try:
            anchor = datetime.fromisoformat(r["anchor"])
        except Exception as e:
            issues.append(f"{r['id']}: bad anchor format: {e}")
            continue
        for turn_list in (r.get("turns", []), r.get("history", [])):
            for turn in turn_list:
                for tc in turn.get("tool_calls", []):
                    if tc["name"] in ("set_reminder", "set_timer") and "when" in tc.get("args", {}):
                        when_raw = tc["args"]["when"]
                        try:
                            when = datetime.fromisoformat(when_raw).replace(tzinfo=anchor.tzinfo)
                        except Exception:
                            continue  # error-recovery records may have deliberately bad 'when' strings
                        if when <= anchor:
                            issues.append(f"{r['id']}: {tc['name']}.when ({when_raw}) not after anchor ({r['anchor']})")
    return issues


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _calls_of(r, tool):
    out = []
    for turn in r.get("turns", []):
        for tc in turn.get("tool_calls", []):
            if tc["name"] == tool:
                out.append(tc.get("args", {}))
    return out


def _parse_val(v):
    try:
        return datetime.fromisoformat(v.replace("Z", ""))
    except Exception:
        return None


def check_date_intents(records):
    """phrase-in-text, call index is per-tool (0-based; omit when tool called once),
    and heuristic semantic checks of phrase vs arg value against the anchor."""
    from datetime import timedelta
    issues = []
    for r in records:
        text = r.get("text", "")
        anchor = datetime.fromisoformat(r["anchor"]).replace(tzinfo=None)
        for intent in r.get("date_intents", []):
            ph = intent["phrase"]
            if ph not in text:
                issues.append(f"{r['id']}: date_intent phrase '{ph}' not found in text")
                continue
            tool, field = intent["arg"].split(".")
            calls = _calls_of(r, tool)
            if "call" in intent:
                if intent["call"] >= len(calls):
                    issues.append(f"{r['id']}: call index {intent['call']} out of range for {tool} (only {len(calls)})")
                    continue
                args = calls[intent["call"]]
            elif len(calls) == 1:
                args = calls[0]
            elif not calls:
                issues.append(f"{r['id']}: date_intent tool {tool} never called in turns")
                continue
            else:
                issues.append(f"{r['id']}: {tool} called {len(calls)}x but intent has no call index")
                continue
            if field not in args:
                issues.append(f"{r['id']}: arg {intent['arg']} missing in the call")
                continue
            val = _parse_val(str(args[field]))
            if val is None:
                continue
            low = ph.lower()
            wds = [w for w in WEEKDAYS if w in low]
            ad, vd = anchor.date(), val.date()
            if len(wds) == 1 and "weekend" not in low and "week" not in low.replace(wds[0], ""):
                if vd.weekday() != WEEKDAYS.index(wds[0]):
                    issues.append(f"{r['id']}: '{ph}' -> {args[field]} is a {WEEKDAYS[vd.weekday()]}")
                elif "next" in low and not (ad < vd <= ad + timedelta(days=13)):
                    issues.append(f"{r['id']}: 'next' weekday {args[field]} not within (anchor, +13d] of {r['anchor']}")
                elif "this" in low and not (ad <= vd <= ad + timedelta(days=7)):
                    issues.append(f"{r['id']}: 'this' weekday {args[field]} not within [anchor, +7d] of {r['anchor']}")
                elif "next" in low and ad.weekday() == vd.weekday() and (vd - ad).days != 7:
                    issues.append(f"{r['id']}: 'next {wds[0]}' on a {wds[0]} must be +7 days ({args[field]} vs {r['anchor']})")
            if "day after tomorrow" in low:
                if (vd - ad).days != 2:
                    issues.append(f"{r['id']}: '{ph}' -> {args[field]} not anchor+2d")
            elif "tomorrow" in low and (vd - ad).days != 1:
                issues.append(f"{r['id']}: '{ph}' -> {args[field]} not anchor+1d")
            if re.search(r"\b(today|tonight|this morning|this afternoon|this evening)\b", low) and "tomorrow" not in low and "from today" not in low and vd != ad:
                issues.append(f"{r['id']}: '{ph}' -> {args[field]} not same day as anchor")
            m = re.search(r"\bin (\d+|an?|a couple of|half an?) ?(minute|min|hour|hr|day|week)s?\b", low)
            if m and m.group(1).isdigit():
                n = int(m.group(1)); unit = m.group(2)
                delta = {"minute": timedelta(minutes=n), "min": timedelta(minutes=n), "hour": timedelta(hours=n), "hr": timedelta(hours=n), "day": timedelta(days=n), "week": timedelta(weeks=n)}[unit]
                if "T" in str(args[field]) or " " in str(args[field]):
                    if abs((val - (anchor + delta)).total_seconds()) > 120 and unit in ("minute", "min", "hour", "hr"):
                        issues.append(f"{r['id']}: '{ph}' -> {args[field]} != anchor+{delta} ({r['anchor']})")
                if unit in ("day", "week") and vd != (anchor + delta).date():
                    issues.append(f"{r['id']}: '{ph}' -> {args[field]} != anchor+{delta}")
            tm = re.search(r"\b(\d{1,2})(?:[:.](\d{2}))?\s?(am|pm)\b", low)
            if tm and ("T" in str(args[field])):
                h = int(tm.group(1)) % 12 + (12 if tm.group(3) == "pm" else 0)
                if val.hour != h and field in ("start", "when"):
                    issues.append(f"{r['id']}: '{ph}' hour {h} != {args[field]}")
    return issues


def check_anchor_tz(records):
    issues = []
    for r in records:
        anchor_str = r["anchor"]
        try:
            dt = datetime.fromisoformat(anchor_str)
        except Exception as e:
            issues.append(f"{r['id']}: unparseable anchor: {e}")
            continue
        naive = dt.replace(tzinfo=None)
        real_offset = ZoneInfo("Australia/Canberra")
        expected = naive.replace(tzinfo=real_offset).utcoffset()
        actual = dt.utcoffset()
        if expected != actual:
            issues.append(f"{r['id']}: anchor offset {actual} doesn't match real Australia/Canberra offset {expected} for {naive}")
    return issues


def balance_report(records):
    total = len(records)
    tool_counter = Counter()
    category_counter = Counter()
    mode_counter = Counter()
    one_shot = 0
    parallel = 0
    no_tool = 0
    error_recovery = 0

    for r in records:
        mode_counter[r.get("flags", {}).get("mode", "default")] += 1
        if r.get("flags", {}).get("one_shot"):
            one_shot += 1
        tools_called = []
        has_multi_call_turn = False
        for turn in r.get("turns", []):
            calls = turn.get("tool_calls", [])
            if len(calls) >= 2:
                has_multi_call_turn = True
            for tc in calls:
                tools_called.append(tc["name"])
        if has_multi_call_turn:
            parallel += 1
        if not tools_called:
            no_tool += 1
        for t in set(tools_called):
            tool_counter[t] += 1
            category_counter[CATEGORY_MAP.get(t, "uncategorized")] += 1
        if "error" in (r.get("notes", "") + str(r.get("turns", []))).lower() or "couldn't" in str(r.get("turns", [])).lower() or "failed to" in str(r.get("turns", [])).lower() or "no pending reminder" in str(r.get("turns", [])).lower() or "no note found" in str(r.get("turns", [])).lower():
            error_recovery += 1

    print(f"Total records: {total}\n")
    print("Per-tool frequency (flag >10%):")
    for tool, n in tool_counter.most_common():
        pct = 100 * n / total
        flag = "  <-- OVER 10%" if pct > 10 else ""
        print(f"  {tool}: {n} ({pct:.1f}%){flag}")

    print("\nPer-category frequency:")
    for cat, n in category_counter.most_common():
        print(f"  {cat}: {n} ({100*n/total:.1f}%)")

    print(f"\nno_tool (negatives): {no_tool} ({100*no_tool/total:.1f}%)" + (" <-- UNDER 20%" if 100*no_tool/total < 20 else ""))
    print(f"one_shot: {one_shot} ({100*one_shot/total:.1f}%)")
    print(f"parallel-call turns: {parallel} ({100*parallel/total:.1f}%)" + (" <-- UNDER 10%" if 100*parallel/total < 10 else ""))
    print(f"error-recovery (heuristic): {error_recovery} ({100*error_recovery/total:.1f}%)")
    print(f"\nMode distribution: {dict(mode_counter)}")

    all_tools = set(CATEGORY_MAP.keys()) - {"fetch_url"}
    uncovered = all_tools - set(tool_counter.keys())
    if uncovered:
        print(f"\n{len(uncovered)} tool(s) with ZERO coverage:")
        for t in sorted(uncovered):
            print(f"  - {t} ({CATEGORY_MAP.get(t)})")

    dup_ids = [i for i, c in Counter(r["id"] for r in records).items() if c > 1]
    if dup_ids:
        print(f"\nDUPLICATE IDs: {dup_ids}")
    dup_anchors = [a for a, c in Counter(r["anchor"] for r in records).items() if c > 1]
    if dup_anchors:
        print(f"\n{len(dup_anchors)} duplicate anchor value(s) (may be fine if few, flag if many): {dup_anchors[:10]}")


def main():
    eval_prompts = json.load(open(EVAL_PATH))
    eval_texts = [(p["id"], normalize(p["text"])) for p in eval_prompts]
    schemas = load_tool_schemas()

    records = []
    for path in sys.argv[1:]:
        for line in open(path):
            if line.strip():
                records.append(json.loads(line))

    print(f"Loaded {len(records)} records from {len(sys.argv) - 1} file(s)\n")
    print("=" * 70)

    contam = check_contamination(records, eval_texts)
    print(f"\nCONTAMINATION CHECK: {len(contam)} flagged")
    for rid, eid, score, kind in contam:
        print(f"  {rid} ~ {eid} ({kind}, {score})")

    arg_issues = check_arg_schemas(records, schemas)
    print(f"\nARG SCHEMA CHECK: {len(arg_issues)} issue(s)")
    for i in arg_issues:
        print(f"  {i}")

    shape_issues = check_turn_shape(records)
    print(f"\nTURN SHAPE CHECK: {len(shape_issues)} issue(s)")
    for i in shape_issues:
        print(f"  {i}")

    id_issues = check_stated_ids(records)
    print(f"\nSTATED-ID CHECK: {len(id_issues)} issue(s)")
    for i in id_issues:
        print(f"  {i}")

    reminder_issues = check_reminder_future(records)
    print(f"\nREMINDER-FUTURE CHECK: {len(reminder_issues)} issue(s)")
    for i in reminder_issues:
        print(f"  {i}")

    intent_issues = check_date_intents(records)
    print(f"\nDATE-INTENT CHECK: {len(intent_issues)} issue(s)")
    for i in intent_issues:
        print(f"  {i}")

    tz_issues = check_anchor_tz(records)
    print(f"\nANCHOR TZ CHECK: {len(tz_issues)} issue(s)")
    for i in tz_issues:
        print(f"  {i}")

    print("\n" + "=" * 70)
    print("BALANCE REPORT")
    print("=" * 70)
    balance_report(records)


if __name__ == "__main__":
    main()
