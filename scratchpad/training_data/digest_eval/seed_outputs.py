"""Turn a digest_outputs*.jsonl into per-doc JSON + a batch-writes list for the taste-test artifact.
usage: seed_outputs.py <outputs.jsonl> <outdir>"""
import json, sys, pathlib
src, out = sys.argv[1], pathlib.Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
writes = []
for line in open(src):
    r = json.loads(line)
    doc_id = f"{r['id']}__{r['model']}"
    p = out / f"out_{doc_id}.json"
    p.write_text(json.dumps({"day": r["id"], "model": r["model"], "text": r["output"].strip()}, ensure_ascii=False))
    writes.append({"op": "set", "collection": "outputs", "doc_id": doc_id, "file_path": str(p)})
(out / "out_writes.json").write_text(json.dumps(writes))
print(len(writes))
