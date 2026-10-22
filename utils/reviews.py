"""
utils/reviews.py
-----------------
Vault review files, written by jobs/evening.py (daily commentary) and
jobs/reviews.py (weekly, monthly). Plain markdown with a small frontmatter
block, one file per period:

    Reviews/Daily/YYYY-MM-DD.md
    Reviews/Weekly/YYYY-Www.md      (ISO week)
    Reviews/Monthly/YYYY-MM.md

Re-running a job for the same period overwrites its file.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from utils import vault

REVIEWS_DIRNAME = "Reviews"
KINDS = ("daily", "weekly", "monthly")


def period_key(kind: str, day: date) -> str:
    if kind == "daily":
        return day.isoformat()
    if kind == "weekly":
        iso = day.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if kind == "monthly":
        return f"{day.year}-{day.month:02d}"
    raise ValueError(f"unknown review kind: {kind}")


def review_file(kind: str, key: str) -> Path:
    if kind not in KINDS:
        raise ValueError(f"unknown review kind: {kind}")
    return vault.vault_root() / REVIEWS_DIRNAME / kind.capitalize() / f"{key}.md"


def write_review(kind: str, key: str, title: str, body: str) -> Path:
    path = review_file(kind, key)
    content = (
        f"---\ntype: review-{kind}\nperiod: {key}\ngenerated: {vault.now_iso()}\n---\n\n"
        f"# {title}\n\n{body.strip()}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    vault.write_note_atomic(path, content)
    return path


def read_review_body(kind: str, key: str) -> str | None:
    """The review's text without frontmatter and title heading, or None."""
    path = review_file(kind, key)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        _, _, text = text[4:].partition("\n---\n")
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip() or None
