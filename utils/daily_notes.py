"""
utils/daily_notes.py
----------------------
Vault capture list: one markdown file per local day at
Daily Notes/YYYY-MM-DD.md, one checklist line per capture:

    - [ ] 14:32 text of the capture ^a1b2c3d4

Flat append only. Captures are single lines (newlines in the raw text are
folded to spaces), so a line's structure can't be broken by what was said.
The trailing ^id is an Obsidian block id, which also lets the dashboard tick
a capture off or convert it later.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

from utils import vault

DAILY_NOTES_DIRNAME = "Daily Notes"
_lock = threading.Lock()
_LINE_RE = re.compile(r"^- \[( |x)\] (\d{2}:\d{2}) (.*?) \^(\w+)\s*$")


def daily_notes_file(date_str: str) -> Path:
    return vault.vault_root() / DAILY_NOTES_DIRNAME / f"{date_str}.md"


def append_capture(local_dt: datetime, text: str) -> str:
    """Add one capture to its day's file (created on first use) and return
    its id. Raises ValueError on empty text."""
    flat = " ".join(text.split())
    if not flat:
        raise ValueError("empty capture")
    capture_id = vault.generate_id()
    date_str = f"{local_dt:%Y-%m-%d}"
    path = daily_notes_file(date_str)
    line = f"- [ ] {local_dt:%H:%M} {flat} ^{capture_id}"
    with _lock:
        if path.exists():
            content = path.read_text(encoding="utf-8")
        else:
            content = (
                f"---\ntype: daily-notes\ndate: {date_str}\n---\n\n"
                f"# Daily Notes — {local_dt:%A} {local_dt.day} {local_dt:%B %Y}\n"
            )
        has_captures = any(_LINE_RE.match(raw) for raw in content.splitlines())
        sep = "\n" if has_captures else "\n\n"
        vault.write_note_atomic(path, content.rstrip("\n") + sep + line + "\n")
    return capture_id


def read_captures(date_str: str) -> list[dict]:
    """Captures for one day, in file order: id, time ("HH:MM"), text, done."""
    path = daily_notes_file(date_str)
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = _LINE_RE.match(raw)
        if m:
            out.append({"id": m[4], "time": m[2], "text": m[3], "done": m[1] == "x"})
    return out
