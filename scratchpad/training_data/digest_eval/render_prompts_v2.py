"""Render each synthetic day into the CURRENT jobs/digest.py DIGEST_PROMPT (with {history}) -> digest_prompts_v2.jsonl.
History for day N = the reference-style summaries of up to the 7 previous *calendar* days that exist in the
set. We have no stored recaps for synthetic days, so history uses a compact one-line digest of each earlier
day's entries (first sentence of each user turn) -- good enough to test the 'trend only if 3+ days' guard.
Pass --empty-history to test the no-history path."""
import glob
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from jobs.digest import DIGEST_PROMPT  # noqa: E402

here = Path(__file__).parent
days = []
for f in sorted(glob.glob(str(here / "days_*.json"))):
    days += json.loads(Path(f).read_text())
days.sort(key=lambda d: d["date"])
by_date = {d["date"]: d for d in days}
empty = "--empty-history" in sys.argv


def brief(d):
    if not d["entries"]:
        return "Quiet day, nothing logged."
    asks = []
    for e in d["entries"]:
        m = re.match(r"User:\s*(.+?)(?:\n|$)", e)
        if m:
            asks.append(m.group(1).split(". ")[0].strip()[:140])
    return "You asked me: " + "; ".join(asks[:8]) + "."


with open(here / "digest_prompts_v2.jsonl", "w") as out:
    for d in sorted(days, key=lambda x: x["id"]):
        today = date.fromisoformat(d["date"])
        hist = []
        if not empty:
            for off in range(7, 0, -1):
                p = by_date.get((today - timedelta(days=off)).isoformat())
                if p:
                    hist.append(f"[{date.fromisoformat(p['date']).strftime('%A %d %B %Y')}]\n{brief(p)}")
        entries = "\n---\n".join(d["entries"]) if d["entries"] else "(nothing logged today)"
        refl = "\n---\n".join(d["reflections"]) if d["reflections"] else "(none answered today)"
        h = "\n\n".join(hist) if hist else "(no earlier recaps available)"
        out.write(json.dumps({"id": d["id"], "date": d["date"], "kind": d["kind"],
                              "prompt": DIGEST_PROMPT.format(entries=entries, history=h, reflections=refl)},
                             ensure_ascii=False) + "\n")
print(f"{len(days)} days -> digest_prompts_v2.jsonl (history={'off' if empty else 'on'})")
