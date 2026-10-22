"""Flag trend-ish phrases in trainer outputs so they can be checked against trend_cases by hand.
usage: flag_trends.py <outputs.jsonl>   (rows: {id|day, model, text|output})"""
import json
import re
import sys
from pathlib import Path

PATTERNS = r"trend|lately|recent(ly| days)|past (few|couple|several) (days|weeks)|last (few|couple) (days|weeks)|this week|all week|recurring|pattern|again|as usual|as always|consistent|every (day|night|morning)|keeps? (coming|happening)|ongoing|continu|streak|week after week|for (days|weeks)|building up|piling up|third (day|time)|yet again|once more|steady|regular"
rx = re.compile(PATTERNS, re.I)
for line in Path(sys.argv[1]).read_text().splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    text = r.get("text") or r.get("output") or r.get("response") or ""
    hits = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        m = rx.search(sent)
        if m:
            hits.append(f"    [{m.group(0)}] {sent.strip()}")
    print(f"{r.get('id') or r.get('day')}  {r.get('model')}: {len(hits)} hit(s)")
    print("\n".join(hits))
