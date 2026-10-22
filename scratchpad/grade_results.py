"""
Quick grader for scratchpad/eval_results*.json against scratchpad/eval_prompts.json's
expected.tool field. Usable = text_ok and no error. Correct = usable AND (expected.tool
is None and no tool was called) OR (expected.tool is a "|"-separated list of acceptable
tool names, at least one of which was actually called; "null" in that list means "no
tool call is also acceptable").

This only checks tool NAME correctness, not argument correctness (dates, durations,
etc.) that many prompts' "notes" field also describes -- a coarser signal than full
manual grading, but the same signal the model most obviously either gets right or
doesn't, and enough to compare two conditions (router off vs on) on the same prompt set.

Usage: .venv/bin/python scratchpad/grade_results.py <results.json> [<model_id>]
"""
import json
import sys

RESULTS_PATH = sys.argv[1] if len(sys.argv) > 1 else "scratchpad/eval_results.json"
MODEL_FILTER = sys.argv[2] if len(sys.argv) > 2 else None
PROMPTS_PATH = "scratchpad/eval_prompts.json"


def is_correct(expected_tool: str | None, called_names: set[str]) -> bool:
    if expected_tool is None:
        return len(called_names) == 0
    options = expected_tool.split("|")
    if "null" in options and len(called_names) == 0:
        return True
    return bool(called_names & set(options) - {"null"})


def main():
    prompts = {p["id"]: p["expected"]["tool"] for p in json.load(open(PROMPTS_PATH))}
    results = json.load(open(RESULTS_PATH))
    if MODEL_FILTER:
        results = [r for r in results if r["model"] == MODEL_FILTER]

    by_model: dict[str, list] = {}
    for r in results:
        by_model.setdefault(r["model"], []).append(r)

    for model, records in by_model.items():
        usable = [r for r in records if r.get("text_ok")]
        correct = [
            r for r in usable
            if is_correct(prompts.get(r["prompt_id"]), {tc["name"] for tc in r.get("tool_calls", [])})
        ]
        print(f"{model}: {len(records)} total, {len(usable)} usable, {len(correct)} correct "
              f"({100*len(correct)/len(records):.0f}% of total, {100*len(correct)/len(usable):.0f}% of usable)")
        wrong = [r for r in usable if r not in correct]
        if wrong:
            print("  incorrect/mismatched:")
            for r in wrong:
                names = [tc["name"] for tc in r.get("tool_calls", [])]
                print(f"    {r['prompt_id']}: expected={prompts.get(r['prompt_id'])!r} got={names}")


if __name__ == "__main__":
    main()
