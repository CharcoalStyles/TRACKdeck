"""
utils/vault.py
---------------
Core file I/O and markdown/frontmatter handling for the Obsidian-synced
notes vault: frontmatter notes (the task-planning notes) and section
editing. This module owns that on-disk format; the day-organiser's own
folders have their own modules.

Vault layout:
    <VAULT_PATH>/
        planning-YYYY-MM-DD.md   Task-planning notes (this module)
        Daily Notes/             Capture checklists (utils/daily_notes.py)
        Check-ins/               One file per day (utils/checkin_log.py)
        Reviews/Daily|Weekly|Monthly/   (utils/reviews.py)

Frontmatter schema:
    id:      stable short id, generated once, never changes. This is the
             key used to look the note up (e.g. the planning template) —
             filenames can change if you rename a note in Obsidian, ids don't.
    title:   display title
    created: ISO8601 UTC timestamp
    updated: ISO8601 UTC timestamp, bumped on every agent-driven change
    tags:    list of strings
    aliases: list of strings (Obsidian reads this natively)
    source:  "agent"

Section editing:
    Sections are markdown H2 headings ("## Heading"). append_to_section
    adds content under a heading (creating it if missing) without
    touching anything else. replace_section replaces everything under a
    heading up to the next H2 (or end of note), also creating it if
    missing. Both leave everything outside the target heading untouched.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

FRONTMATTER_DELIM = "---"

# Task-planning notes (agent/tools/planning.py) use a deterministic,
# date-keyed filename so re-planning a day updates its note in place.
PLANNING_NOTE_TAG = "planning-session"
PLANNING_STARTER_BODY = (
    "## Tasks\n\n## Fixed Blocks\n\n## Generated Schedule & Sprints\n\n## End of Day Reflection\n"
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def vault_root() -> Path:
    return Path(os.environ.get("VAULT_PATH", "./data/vault"))


def ensure_vault_dirs() -> None:
    vault_root().mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_id() -> str:
    return uuid.uuid4().hex[:8]


def is_ignorable(path: Path) -> bool:
    """Files that should never be treated as notes."""
    name = path.name
    if not name.endswith(".md"):
        return True
    if "sync-conflict" in name:
        return True
    if name.startswith("."):
        return True
    return False


# ---------------------------------------------------------------------------
# Note dataclass + frontmatter (de)serialization
# ---------------------------------------------------------------------------

@dataclass
class Note:
    id: str
    title: str
    created: str
    updated: str
    tags: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    source: str = "agent"
    body: str = ""
    path: Path | None = None  # populated when loaded from / written to disk

    def frontmatter_dict(self) -> dict:
        fm = {
            "id": self.id,
            "title": self.title,
            "created": self.created,
            "updated": self.updated,
            "tags": self.tags,
            "aliases": self.aliases,
            "source": self.source,
        }
        return fm


def serialize_note(note: Note) -> str:
    fm = yaml.safe_dump(note.frontmatter_dict(), sort_keys=False, allow_unicode=True).strip()
    body = note.body if note.body.endswith("\n") else note.body + "\n"
    return f"{FRONTMATTER_DELIM}\n{fm}\n{FRONTMATTER_DELIM}\n\n{body}"


def _coerce_iso_str(value: object) -> object:
    """serialize_note always quotes created/updated (yaml.safe_dump quotes
    a str that would otherwise round-trip as a different type), so our own
    writes are safe — but a note edited directly in Obsidian can have an
    unquoted date in frontmatter (its Properties panel writes native YAML
    dates), which yaml.safe_load then parses as a real datetime/date
    object instead of the str the Note dataclass declares. Normalize back
    to a string here so every caller can trust created/updated are always
    comparable strings, regardless of how the file got edited."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def parse_note(path: Path) -> Note | None:
    """
    Parse a note file. Returns None if it has no valid frontmatter — e.g.
    it's still mid-sync (Syncthing can land a partial file momentarily),
    or it's simply not one of our managed notes. Callers should treat
    None as "skip this file", not as an error.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError, OSError):
        return None

    if not text.startswith(FRONTMATTER_DELIM):
        return None

    parts = text.split(FRONTMATTER_DELIM, 2)
    if len(parts) < 3:
        return None  # malformed / only one delimiter — likely mid-write

    _, raw_fm, body = parts
    try:
        fm = yaml.safe_load(raw_fm) or {}
    except yaml.YAMLError:
        return None

    if not isinstance(fm, dict) or "id" not in fm:
        return None

    return Note(
        id=fm["id"],
        title=fm.get("title") or path.stem,
        created=_coerce_iso_str(fm.get("created")) or now_iso(),
        updated=_coerce_iso_str(fm.get("updated")) or now_iso(),
        tags=fm.get("tags") or [],
        aliases=fm.get("aliases") or [],
        source=fm.get("source") or "agent",
        body=body.lstrip("\n"),
        path=path,
    )


def write_note_atomic(path: Path, content: str) -> None:
    """
    Write via temp file + rename so a concurrent reader (or Syncthing
    mid-scan) never sees a half-written file.

    The temp suffix includes a uuid, not just the pid: concurrent tool
    calls from one LangGraph turn run in different threads of the same
    process (LangGraph's ToolNode gathers them), so pid alone let two
    concurrent writers to the same path collide on the same temp name —
    whichever's os.replace ran second found the file already renamed
    away and crashed with FileNotFoundError.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp{os.getpid()}-{uuid.uuid4().hex[:8]}")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


# ---------------------------------------------------------------------------
# Project folders
# ---------------------------------------------------------------------------

def is_project_dir(path: Path) -> bool:
    """True for a vault-root subdirectory that groups one project's notes —
    everything except dotfile directories (e.g. Obsidian's own
    .obsidian)."""
    return (
        path.is_dir()
        and path.parent == vault_root()
        and not path.name.startswith(".")
    )


# ---------------------------------------------------------------------------
# Listing / lookup
# ---------------------------------------------------------------------------

def list_vault_notes() -> list[Path]:
    """All managed note files at the vault root and one level inside any
    project folder."""
    root = vault_root()
    if not root.exists():
        return []
    notes = [p for p in root.iterdir() if p.is_file() and not is_ignorable(p)]
    for project_dir in (p for p in root.iterdir() if is_project_dir(p)):
        notes.extend(p for p in project_dir.iterdir() if p.is_file() and not is_ignorable(p))
    return notes


def find_note_by_id(note_id: str) -> Path | None:
    """Linear scan over the vault root — fine at personal-vault scale."""
    for path in list_vault_notes():
        note = parse_note(path)
        if note is not None and note.id == note_id:
            return path
    return None


def planning_note_path(date_str: str) -> Path:
    """Deterministic path for a given day's task-planning note (see
    get_or_create_planning_note). `date_str` is "YYYY-MM-DD" in the
    user's configured timezone."""
    return vault_root() / f"planning-{date_str}.md"


def get_or_create_planning_note(date_str: str, template_note_id: str | None = None) -> Note:
    """Get (or create) the day's task-planning note. A new note clones
    the body of the configured template note (`template_note_id`, from
    agent/settings.py's planning_template_note_id) so it starts with the
    usual Tasks/Generated Schedule/End of Day Reflection layout; if no
    template is configured (or it's gone missing), falls back to just
    those empty section headings."""
    path = planning_note_path(date_str)
    note = parse_note(path)
    if note is not None:
        return note

    body = PLANNING_STARTER_BODY
    if template_note_id:
        template_path = find_note_by_id(template_note_id)
        template = parse_note(template_path) if template_path else None
        if template is not None:
            body = template.body

    now = now_iso()
    note = Note(
        id=generate_id(),
        title=f"Planning — {date_str}",
        created=now,
        updated=now,
        tags=[PLANNING_NOTE_TAG],
        source="agent",
        body=body,
        path=path,
    )
    write_note_atomic(path, serialize_note(note))
    return note


def list_planning_notes() -> list[dict]:
    """Every task-planning note (see PLANNING_NOTE_TAG), most recent date
    first. Backs GET /reflection/history — lets the dashboard list past
    days instead of only reaching one via an exact date in the URL.
    Planning notes use a deterministic date-keyed filename, so this scans
    just the vault root rather than needing a full vault scan."""
    root = vault_root()
    if not root.exists():
        return []
    notes = []
    for path in root.glob("planning-*.md"):
        note = parse_note(path)
        if note is None or PLANNING_NOTE_TAG not in note.tags:
            continue
        notes.append(
            {
                "date": path.stem.removeprefix("planning-"),
                "title": note.title,
                "updated": note.updated,
            }
        )
    notes.sort(key=lambda n: n["date"], reverse=True)
    return notes


# ---------------------------------------------------------------------------
# Section-level editing
# ---------------------------------------------------------------------------

def _section_span(body: str, heading: str) -> tuple[int, int] | None:
    """
    Returns (content_start, content_end) spanning the text under `heading`,
    not including the heading line itself. None if the heading isn't
    present in the body.
    """
    # Case-insensitive: the model may ask for "preferences" when the note has
    # "## Preferences" — without this, that mismatch creates a second,
    # differently-cased heading instead of matching the existing section, and
    # since matching only ever finds the first occurrence, the original
    # becomes permanently unreachable through these tools.
    pattern = re.compile(rf"(?im)^##[ \t]+{re.escape(heading.strip())}[ \t]*$")
    match = pattern.search(body)
    if not match:
        return None

    content_start = match.end()
    if content_start < len(body) and body[content_start] == "\n":
        content_start += 1

    next_heading = re.search(r"(?m)^##[ \t]+", body[content_start:])
    content_end = content_start + next_heading.start() if next_heading else len(body)
    return content_start, content_end


def _append_new_section(body: str, heading: str, content: str) -> str:
    if not body.strip():
        sep = ""
    elif body.endswith("\n\n"):
        sep = ""
    elif body.endswith("\n"):
        sep = "\n"
    else:
        sep = "\n\n"
    return f"{body}{sep}## {heading}\n{content}\n"


def append_to_section(body: str, heading: str, addition: str) -> str:
    """Add `addition` under `heading`, after whatever's already there.
    Creates the heading (as a new section at the end) if it doesn't exist."""
    addition = addition.strip()
    span = _section_span(body, heading)
    if span is None:
        return _append_new_section(body, heading, addition)

    start, end = span
    existing = body[start:end].rstrip("\n")
    new_section_body = f"{existing}\n{addition}\n" if existing else f"{addition}\n"

    tail = body[end:]
    tail_sep = "\n" if tail.strip() else ""
    return f"{body[:start]}{new_section_body}{tail_sep}{tail.lstrip(chr(10))}"


def replace_section(body: str, heading: str, new_content: str) -> str:
    """Replace everything under `heading` with `new_content`, leaving the
    rest of the note untouched. Creates the heading if it doesn't exist."""
    new_content = new_content.strip()
    span = _section_span(body, heading)
    if span is None:
        return _append_new_section(body, heading, new_content)

    start, end = span
    tail = body[end:]
    tail_sep = "\n" if tail.strip() else ""
    return f"{body[:start]}{new_content}\n{tail_sep}{tail.lstrip(chr(10))}"


def get_section(body: str, heading: str) -> str | None:
    """Read-only counterpart to append_to_section/replace_section — the
    text under `heading`, or None if that section doesn't exist or is
    empty."""
    span = _section_span(body, heading)
    if span is None:
        return None
    text = body[span[0]:span[1]].strip()
    return text or None
