"""
scratchpad/training_data/check_contamination.py
---------------------------------------------------
Hard gate against train/eval contamination: checks every training example's
user_message against all 45 scratchpad/eval_prompts.json texts (all three
eval sources, not just historical), via exact-normalized match and fuzzy
similarity. Anything above the threshold is flagged for manual resolution —
never silently dropped.

Usage: uv run python scratchpad/training_data/check_contamination.py <jsonl_file> [...]
"""
import difflib
import json
import sys
from pathlib import Path

THRESHOLD = 0.85
EVAL_PATH = Path(__file__).parent.parent / "eval_prompts.json"


def normalize(text: str) -> str:
    return " ".join(text.lower().split())


def main():
    eval_prompts = json.load(open(EVAL_PATH))
    eval_texts = [(p["id"], normalize(p["text"])) for p in eval_prompts]

    flagged = []
    total = 0
    for path in sys.argv[1:]:
        for line in open(path):
            if not line.strip():
                continue
            rec = json.loads(line)
            total += 1
            msg = normalize(rec["user_message"])
            for eval_id, eval_text in eval_texts:
                if msg == eval_text:
                    flagged.append((rec["id"], eval_id, 1.0, "exact"))
                    continue
                ratio = difflib.SequenceMatcher(None, msg, eval_text).ratio()
                if ratio >= THRESHOLD:
                    flagged.append((rec["id"], eval_id, round(ratio, 3), "fuzzy"))

    print(f"Checked {total} training record(s) against {len(eval_texts)} eval prompts.")
    if flagged:
        print(f"\n{len(flagged)} FLAGGED — manual resolution required, nothing auto-dropped:")
        for rid, eid, score, kind in flagged:
            print(f"  {rid} ~ {eid} ({kind}, {score})")
        sys.exit(1)
    else:
        print("Clean — no contamination detected.")


if __name__ == "__main__":
    main()
