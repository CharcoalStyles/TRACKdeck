"""
Labels scratchpad/turn_dump.json (one record per human->AI turn). Heuristic,
documented here for audit -- see scratchpad/label_tool_calls.py for the
same approach applied to the earlier per-tool-call dump.

Labels: wrong_tool | unneeded | bad_args | not_called | correct
"""
import json
import re
from collections import defaultdict

IN_PATH = "scratchpad/turn_dump.json"
PATHOLOGICAL_THREAD = "session_1789475541_17eaf9"

LOG_ACTIVITY_META_WORDS = ["remind", "timer", "setting up", "set up", "preparation"]
REAL_ACTIVITY_WORDS = [
    "log", "activity", "workout", "exercise", "walk", "run", "meditat", "slept",
    "nap", "finished", "completed", "practice", "session", "did a", "read for",
]

# Hand-judged: the 12 turns where NO record sharing that (thread_id, user_message)
# ever called a tool (see fork transcript for the full reasoning per case).
# Keyed by a short unique substring of ai_text.
NOT_CALLED_AI_TEXT_SUBSTR = [
    "I don't have access to real-time weather information",
    "my current capabilities are focused on providing information",
    "I don't have the capability to look up your calendar",
    "I can use a tool to get the current date and time. However, without",
    "get_current_datetime end",
    "search_web end",
    "Got it! Let's create a new planning note with the template",
]


def bucket_model(model_provider: str, model_name: str) -> str:
    if model_provider == "google_genai":
        return "paid-gemini"
    if model_name and "/" in model_name and model_name.endswith(":free"):
        return "openrouter-free"
    if model_provider == "openai":
        return "local-lmstudio"  # bare model names (qwen2.5-*, llama-3-groq-*) via LM Studio's OpenAI-compatible endpoint
    return f"other:{model_provider}"


def parse_hour(when: str):
    m = re.search(r"T(\d{2}):", when or "")
    return int(m.group(1)) if m else None


def am_pm_mismatch(user_msg: str, when: str) -> bool:
    hour = parse_hour(when)
    if hour is None:
        return False
    low = (user_msg or "").lower()
    if "morning" in low and not (0 <= hour < 12):
        return True
    if ("tonight" in low or "evening" in low) and not (17 <= hour <= 23):
        return True
    return False


def classify_call(tc: dict, user_msg: str, seen_args_by_tool: dict, call_index_in_record: int) -> str:
    """Returns one of wrong_tool/unneeded/bad_args/correct for a single tool call."""
    name = tc["tool_name"]
    args_key = json.dumps(tc["tool_args"], sort_keys=True)
    low_user = (user_msg or "").lower()

    if name == "get_current_datetime":
        label = "correct" if args_key not in seen_args_by_tool[name] else "unneeded"
    elif name in ("set_reminder", "set_timer"):
        when = tc["tool_args"].get("when", "")
        if args_key in seen_args_by_tool[name]:
            label = "unneeded"
        elif "T" not in when and when:
            label = "bad_args"
        elif am_pm_mismatch(user_msg, when):
            label = "bad_args"
        elif name == "set_timer" and "timer" not in low_user and ("remind" in low_user):
            label = "wrong_tool"  # reminder language, timer tool
        else:
            label = "correct"
    elif name == "log_activity":
        subject = (tc["tool_args"].get("subject") or "").lower()
        if any(k in subject for k in LOG_ACTIVITY_META_WORDS) and not any(
            k in low_user for k in REAL_ACTIVITY_WORDS
        ):
            label = "wrong_tool"
        elif args_key in seen_args_by_tool[name]:
            label = "unneeded"
        else:
            label = "correct"
    elif name == "search_web":
        if args_key in seen_args_by_tool[name]:
            label = "unneeded"
        elif call_index_in_record > 2:
            label = "unneeded"
        else:
            label = "correct"
    else:
        label = "unneeded" if args_key in seen_args_by_tool[name] else "correct"

    seen_args_by_tool[name].add(args_key)
    return label


PRIORITY = {"bad_args": 3, "wrong_tool": 2, "unneeded": 1, "correct": 0}


def label_group(records: list[dict]) -> None:
    seen_args_by_tool = defaultdict(set)
    search_web_count = 0
    for r in records:
        if not r["tool_calls"]:
            if any(sub in (r["ai_text"] or "") for sub in NOT_CALLED_AI_TEXT_SUBSTR):
                r["label"] = "not_called"
            else:
                r["label"] = "correct"
            continue

        call_labels = []
        for tc in r["tool_calls"]:
            if tc["tool_name"] == "search_web":
                search_web_count += 1
                call_labels.append(classify_call(tc, r["user_message"], seen_args_by_tool, search_web_count))
            else:
                call_labels.append(classify_call(tc, r["user_message"], seen_args_by_tool, 0))
        r["label"] = max(call_labels, key=lambda l: PRIORITY[l])


def label_pathological(records: list[dict]) -> None:
    """Same ground truth as before: exactly one set_reminder was needed; every
    other tool call in this single-user-message thread is not what was asked."""
    seen_reminder = False
    seen_get_dt = False
    for r in records:
        if not r["tool_calls"]:
            r["label"] = "correct"
            continue
        call_labels = []
        for tc in r["tool_calls"]:
            name = tc["tool_name"]
            if name == "get_current_datetime":
                call_labels.append("correct" if not seen_get_dt else "unneeded")
                seen_get_dt = True
            elif name == "set_reminder":
                if not seen_reminder:
                    seen_reminder = True
                    when = tc["tool_args"].get("when", "")
                    if "T" not in when:
                        call_labels.append("bad_args")
                    elif am_pm_mismatch(r["user_message"], when):
                        call_labels.append("bad_args")
                    else:
                        call_labels.append("correct")
                else:
                    call_labels.append("unneeded")
            elif name == "set_timer":
                call_labels.append("wrong_tool")
            elif name == "log_activity":
                call_labels.append("wrong_tool")
            elif name == "save_note":
                call_labels.append("unneeded")
            else:
                call_labels.append("correct")
        r["label"] = max(call_labels, key=lambda l: PRIORITY[l])


def main():
    data = json.load(open(IN_PATH))

    pathological = [r for r in data if r["thread_id"] == PATHOLOGICAL_THREAD]
    label_pathological(pathological)

    rest = [r for r in data if r["thread_id"] != PATHOLOGICAL_THREAD]
    groups = defaultdict(list)
    for r in rest:
        groups[(r["thread_id"], r["user_message"])].append(r)
    for group in groups.values():
        label_group(group)

    assert all(r["label"] for r in data), "unlabeled record(s) remain"
    with open(IN_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)

    from collections import Counter
    data = json.load(open(IN_PATH))
    for r in data:
        r["_bucket"] = bucket_model(r["model_provider"], r["model_name"])

    print("=== Overall (pooled, misleading -- see per-bucket below) ===")
    overall = Counter(r["label"] for r in data)
    print(dict(overall), {k: round(100 * v / len(data), 1) for k, v in overall.items()})

    print("\n=== Per model bucket ===")
    for bucket in ["local-lmstudio", "openrouter-free", "paid-gemini"]:
        sub = [r for r in data if r["_bucket"] == bucket]
        c = Counter(r["label"] for r in sub)
        pct = {k: round(100 * v / len(sub), 1) for k, v in c.items()} if sub else {}
        print(f"{bucket} (n={len(sub)}): {dict(c)}  |  {pct}")

    null_error = []
    for r in data:
        for tc in r["tool_calls"]:
            if tc["error"] is None:
                null_error.append((r["thread_id"], tc["tool_name"]))
    print(f"\n{len(null_error)} null-error tool calls:", null_error)


if __name__ == "__main__":
    main()
