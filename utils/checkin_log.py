"""
utils/checkin_log.py
----------------------
Vault record of check-ins: one markdown file per local day at
Check-ins/YYYY-MM-DD.md, one section per resolved check-in (time, prompt,
the user's answer or "no answer"). Written when the check-in resolves;
checkins.db keeps only scheduling/pending state. The user's answer is
stored verbatim in a blockquote, so nothing a person types can break the
section structure.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

from utils import vault

CHECKINS_DIRNAME = "Check-ins"
_lock = threading.Lock()
_ENTRY_SPLIT = re.compile(r"^## ", re.MULTILINE)
_ID_RE = re.compile(r"<!-- ci:([\w-]+) -->")


def checkin_file(date_str: str) -> Path:
    return vault.vault_root() / CHECKINS_DIRNAME / f"{date_str}.md"


def _format_entry(checkin_id: str, local_dt: datetime, status: str, prompt: str, answer: str | None) -> str:
    prompt = " ".join(prompt.split())
    lines = [f"## {local_dt:%H:%M} · {status}", f"<!-- ci:{checkin_id} -->", f"**Prompt:** {prompt}", ""]
    if status == "answered" and answer:
        lines += [f"> {line}" if line else ">" for line in answer.strip().splitlines()]
    else:
        lines.append(f"*No answer ({status}).*")
    return "\n".join(lines) + "\n"


def append_entry(
    checkin_id: str,
    local_dt: datetime,
    status: str,
    prompt: str,
    answer: str | None = None,
) -> Path:
    """Add one resolved check-in to its day's file (created on first use).
    Reads the file fresh each time and replaces it atomically; a repeat call
    for the same check-in id is a no-op."""
    date_str = f"{local_dt:%Y-%m-%d}"
    path = checkin_file(date_str)
    with _lock:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if f"<!-- ci:{checkin_id} -->" in text:
                return path
        else:
            text = (
                f"---\ntype: check-ins\ndate: {date_str}\n---\n\n"
                f"# Check-ins — {local_dt:%A} {local_dt.day} {local_dt:%B %Y}\n"
            )
        text = text.rstrip("\n") + "\n\n" + _format_entry(checkin_id, local_dt, status, prompt, answer)
        vault.write_note_atomic(path, text)
    return path


def read_entries(date_str: str) -> list[dict]:
    """Entries for one day, in file order: id, time ("HH:MM"), status,
    prompt, answer (None unless answered)."""
    path = checkin_file(date_str)
    if not path.exists():
        return []
    entries = []
    for section in _ENTRY_SPLIT.split(path.read_text(encoding="utf-8"))[1:]:
        head, _, rest = section.partition("\n")
        time_part, _, status = head.partition(" · ")
        id_match = _ID_RE.search(rest)
        prompt = ""
        answer_lines: list[str] = []
        for line in rest.splitlines():
            if line.startswith("**Prompt:** "):
                prompt = line[len("**Prompt:** "):]
            elif line.startswith(">"):
                answer_lines.append(line[1:].removeprefix(" "))
        answer = "\n".join(answer_lines) if status.strip() == "answered" and answer_lines else None
        entries.append(
            {
                "id": id_match.group(1) if id_match else None,
                "time": time_part.strip(),
                "status": status.strip(),
                "prompt": prompt,
                "answer": answer,
            }
        )
    return entries
