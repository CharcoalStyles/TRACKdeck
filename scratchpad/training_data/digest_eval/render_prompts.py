"""Merge days_*.json and render each day into the exact DIGEST_PROMPT text -> digest_prompts.jsonl."""
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from jobs.digest import DIGEST_PROMPT  # noqa: E402

here = Path(__file__).parent
days = []
for f in sorted(glob.glob(str(here / "days_*.json"))):
    days += json.loads(Path(f).read_text())
days.sort(key=lambda d: d["id"])

with open(here / "digest_prompts.jsonl", "w") as out:
    for d in days:
        entries = "\n---\n".join(d["entries"]) if d["entries"] else "(nothing logged today)"
        refl = "\n---\n".join(d["reflections"]) if d["reflections"] else "(none answered today)"
        rec = {
            "id": d["id"],
            "date": d["date"],
            "kind": d["kind"],
            "prompt": DIGEST_PROMPT.format(entries=entries, reflections=refl),
        }
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
print(f"{len(days)} days -> digest_prompts.jsonl")
