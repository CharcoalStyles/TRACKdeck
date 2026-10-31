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


def open_captures(up_to: str) -> list[dict]:
    """Every unticked capture from any day up to and including `up_to`
    ("YYYY-MM-DD"), oldest day first, each with its "date". Unticked
    captures roll forward until they are ticked off or deleted."""
    folder = vault.vault_root() / DAILY_NOTES_DIRNAME
    if not folder.exists():
        return []
    out = []
    for path in sorted(folder.glob("????-??-??.md")):
        if path.stem <= up_to:
            out.extend({**c, "date": path.stem} for c in read_captures(path.stem) if not c["done"])
    return out


def update_capture(
    date_str: str, capture_id: str, *, text: str | None = None, done: bool | None = None
) -> dict | None:
    """Change one capture's text and/or tick state in place; returns the
    updated capture, or None when that day or id doesn't exist. Raises
    ValueError on empty replacement text."""
    flat = None
    if text is not None:
        flat = " ".join(text.split())
        if not flat:
            raise ValueError("empty capture")
    path = daily_notes_file(date_str)
    with _lock:
        if not path.exists():
            return None
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, raw in enumerate(lines):
            m = _LINE_RE.match(raw)
            if not m or m[4] != capture_id:
                continue
            new_done = (m[1] == "x") if done is None else done
            new_text = m[3] if flat is None else flat
            lines[i] = f"- [{'x' if new_done else ' '}] {m[2]} {new_text} ^{capture_id}"
            vault.write_note_atomic(path, "\n".join(lines) + "\n")
            return {"id": capture_id, "time": m[2], "text": new_text, "done": new_done}
    return None


def delete_capture(date_str: str, capture_id: str) -> dict | None:
    """Remove one capture's line; returns what was removed, or None when that
    day or id doesn't exist."""
    path = daily_notes_file(date_str)
    with _lock:
        if not path.exists():
            return None
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, raw in enumerate(lines):
            m = _LINE_RE.match(raw)
            if m and m[4] == capture_id:
                del lines[i]
                vault.write_note_atomic(path, "\n".join(lines) + "\n")
                return {"id": capture_id, "time": m[2], "text": m[3], "done": m[1] == "x"}
    return None
