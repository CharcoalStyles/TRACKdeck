"""trend_cases/T*.json -> digest_trend_prompts.jsonl (live DIGEST_PROMPT; history formatted like jobs.digest._load_previous_recaps)
and trend_days.json (cases in the taste-test artifact's day format, with the history shown)."""
import glob
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from jobs.digest import DIGEST_PROMPT, HISTORY_MAX_CHARS_PER_DAY  # noqa: E402

here = Path(__file__).parent
cases = [json.loads(Path(f).read_text()) for f in sorted(glob.glob(str(here / "trend_cases" / "T*.json")))]
problems = []
with open(here / "digest_trend_prompts.jsonl", "w") as out:
    for c in cases:
        today = date.fromisoformat(c["date"])
        assert today.strftime("%A") == c["weekday"], c["id"]
        hist = []
        for h in c["history"]:
            d = date.fromisoformat(h["date"])
            if not (today - timedelta(days=7) <= d < today) or d.strftime("%A") != h["weekday"]:
                problems.append(f"{c['id']}: bad history date {h['date']}")
            body = h["recap"].strip()
            if len(body) > HISTORY_MAX_CHARS_PER_DAY:
                body = body[:HISTORY_MAX_CHARS_PER_DAY].rstrip() + "..."
            hist.append(f"[{d.strftime('%A %d %B %Y')}]\n{body}")
        entries = "\n---\n".join(c["entries"]) if c["entries"] else "(nothing logged today)"
        refl = "\n---\n".join(c["reflections"]) if c["reflections"] else "(none answered today)"
        history = "\n\n".join(hist) if hist else "(no earlier recaps available)"
        out.write(json.dumps({"id": c["id"], "date": c["date"], "kind": c["kind"], "prompt":
                              DIGEST_PROMPT.format(entries=entries, history=history, reflections=refl)},
                             ensure_ascii=False) + "\n")
Path(here / "trend_days.json").write_text(json.dumps(
    [{k: c[k] for k in ("id", "date", "weekday", "kind", "entries", "reflections", "history", "expect")} for c in cases],
    ensure_ascii=False, indent=1))
print(f"{len(cases)} cases -> digest_trend_prompts.jsonl, trend_days.json")
for p in problems:
    print("PROBLEM", p)
