"""
Fills in the "label" field on scratchpad/tool_call_dump.json (Phase A of
the tool-router plan). Heuristic, not per-record LLM judgment, given the
volume (853 records) -- documented here so a human can audit the rules.

Labels: wrong_tool | unneeded | bad_args | correct
("not_called" doesn't apply to a per-call dump -- see plan note.)
"""
import json
import re
from collections import defaultdict

IN_PATH = "scratchpad/tool_call_dump.json"

PATHOLOGICAL_THREAD = "session_1789475541_17eaf9"  # 578/853 records, one user msg

LOG_ACTIVITY_META_WORDS = ["remind", "timer", "setting up", "set up", "preparation"]
REAL_ACTIVITY_WORDS = [
    "log", "activity", "workout", "exercise", "walk", "run", "meditat", "slept",
    "nap", "finished", "completed", "practice", "session", "did a", "read for",
]


def parse_hour(when: str):
    m = re.search(r"T(\d{2}):", when or "")
    return int(m.group(1)) if m else None


def am_pm_mismatch(user_msg: str, when: str) -> bool:
    """True when the user's wording implies a time-of-day that doesn't match
    the resolved hour -- e.g. 'in the morning at 3.40' resolving to 15:40."""
    hour = parse_hour(when)
    if hour is None:
        return False
    low = user_msg.lower()
    if "morning" in low and not (0 <= hour < 12):
        return True
    if ("tonight" in low or "this evening" in low or "evening" in low) and not (17 <= hour <= 23):
        return True
    return False


def label_pathological_thread(records: list[dict]) -> None:
    """One user message ('remind me to pick up meds...') triggered a 578-call
    runaway loop. Ground truth: exactly one set_reminder was needed; nothing
    else in this thread serves the user's actual request."""
    seen_reminder = False
    seen_get_dt = False
    for r in records:
        t = r["tool_name"]
        if t == "get_current_datetime":
            r["label"] = "correct" if not seen_get_dt else "unneeded"
            seen_get_dt = True
        elif t == "set_reminder":
            if not seen_reminder:
                seen_reminder = True
                when = r["tool_args"].get("when", "")
                if "T" not in when:  # e.g. bare "15:40", rejected by the tool itself
                    r["label"] = "bad_args"
                elif am_pm_mismatch(r["user_message"], when):
                    r["label"] = "bad_args"  # "in the morning" resolved to 15:40 (PM)
                else:
                    r["label"] = "correct"
            else:
                r["label"] = "unneeded"  # 141 identical repeats
        elif t == "set_timer":
            # user never asked for a timer, and set_reminder already covered
            # the request -- every one of these is the wrong tool
            r["label"] = "wrong_tool"
        elif t == "log_activity":
            # hallucinated self-narration of the tool-calling loop itself
            # ("Setting up reminders and timers", "Timers set for reminders", ...)
            # -- never asked for, and not a real activity
            r["label"] = "wrong_tool"
        elif t == "save_note":
            r["label"] = "unneeded"  # never asked for a note
        else:
            r["label"] = "correct"


def label_general(records: list[dict]) -> None:
    """Non-pathological threads (275 records). Group by (thread_id,
    user_message) to tell legitimate multi-call turns (e.g. adding several
    distinct calendar events one at a time) from actual redundancy (the same
    tool called again with identical, or near-identical, args)."""
    groups = defaultdict(list)
    for r in records:
        groups[(r["thread_id"], r["user_message"])].append(r)

    for (_thread, user_msg), group in groups.items():
        seen_args_by_tool = defaultdict(set)
        search_web_seen = 0
        get_dt_seen = False
        for r in group:
            t = r["tool_name"]
            args_key = json.dumps(r["tool_args"], sort_keys=True)

            if t == "get_current_datetime":
                r["label"] = "correct" if not get_dt_seen else "unneeded"
                get_dt_seen = True
                continue

            if t in ("set_reminder", "set_timer"):
                when = r["tool_args"].get("when", "")
                if args_key in seen_args_by_tool[t]:
                    r["label"] = "unneeded"
                elif "T" not in when and when:
                    r["label"] = "bad_args"
                elif am_pm_mismatch(user_msg, when):
                    r["label"] = "bad_args"
                else:
                    r["label"] = "correct"
                seen_args_by_tool[t].add(args_key)
                continue

            if t == "search_web":
                search_web_seen += 1
                if args_key in seen_args_by_tool[t]:
                    r["label"] = "unneeded"  # exact repeat query
                elif search_web_seen > 2:
                    r["label"] = "unneeded"  # excessive re-querying past reasonable refinement
                else:
                    r["label"] = "correct"
                seen_args_by_tool[t].add(args_key)
                continue

            if t == "log_activity":
                subject = (r["tool_args"].get("subject") or "").lower()
                low_user = user_msg.lower()
                if any(k in subject for k in LOG_ACTIVITY_META_WORDS) and not any(
                    k in low_user for k in REAL_ACTIVITY_WORDS
                ):
                    r["label"] = "wrong_tool"
                elif args_key in seen_args_by_tool[t]:
                    r["label"] = "unneeded"
                else:
                    r["label"] = "correct"
                seen_args_by_tool[t].add(args_key)
                continue

            # everything else (calendar add/delete, notes, planning, checkin,
            # weather, etc.): exact-duplicate call within the same turn is
            # the only heuristically-safe signal at this volume -- default
            # to "correct" otherwise per the labeling brief (uncertain ->
            # correct, not a guessed failure)
            if args_key in seen_args_by_tool[t]:
                r["label"] = "unneeded"
            else:
                r["label"] = "correct"
            seen_args_by_tool[t].add(args_key)


def main():
    data = json.load(open(IN_PATH))
    pathological = [r for r in data if r["thread_id"] == PATHOLOGICAL_THREAD]
    rest = [r for r in data if r["thread_id"] != PATHOLOGICAL_THREAD]

    label_pathological_thread(pathological)
    label_general(rest)

    assert all(r["label"] for r in data), "unlabeled record(s) remain"

    with open(IN_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)

    from collections import Counter
    counts = Counter(r["label"] for r in data)
    print("Label counts:", dict(counts))
    print("As %:", {k: round(100 * v / len(data), 1) for k, v in counts.items()})

    null_error = [r for r in data if r["error"] is None]
    print(f"\n{len(null_error)} null-error records:")
    for r in null_error:
        print(" ", r["thread_id"], r["tool_name"])


if __name__ == "__main__":
    main()
