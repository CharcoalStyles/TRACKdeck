"""
utils/vault.py
---------------
Core file I/O and markdown/frontmatter handling for the Obsidian-synced
notes vault. This module owns the on-disk format; agent/vault_watcher.py
and agent/tools/notes.py both build on top of it rather than touching
files directly.

Vault layout:
    <VAULT_PATH>/
        Inbox/       Landing pad for notes not created via direct agent
                      interaction (e.g. typed on your phone via Obsidian
                      mobile). Watched and auto-processed into a real,
                      indexed note, then removed from Inbox.
        <note>.md     Processed notes live flat at the vault root — no
                      category folders. Tags and [[links]] do the
                      organizing, not folder placement.

Frontmatter schema:
    id:      stable short id, generated once, never changes. This is the
             key used to look the note up in the Chroma index — filenames
             can change if you rename a note in Obsidian, ids don't.
    title:   display title
    created: ISO8601 UTC timestamp
    updated: ISO8601 UTC timestamp, bumped on every agent-driven change
    tags:    list of strings
    aliases: list of strings (Obsidian reads this natively)
    source:  "agent" | "inbox"

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
from datetime import datetime, timezone
from pathlib import Path

import yaml

INBOX_DIRNAME = "Inbox"
FRONTMATTER_DELIM = "---"

# The About Me note is a singleton with a fixed, known location, unlike
# ordinary notes. It's referenced constantly (every turn learning mode is
# on), so it deliberately doesn't go through search_notes/find_note_by_id
# at all — no dependency on embedding similarity, and no risk of an id
# remembered from an earlier turn going stale or getting hallucinated.
# See agent/tools/notes.py's remember_about_me/read_about_me.
ABOUT_ME_FILENAME = "about-me.md"
ABOUT_ME_TITLE = "About Me"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def vault_root() -> Path:
    return Path(os.environ.get("VAULT_PATH", "./data/vault"))


def inbox_dir() -> Path:
    return vault_root() / INBOX_DIRNAME


def ensure_vault_dirs() -> None:
    vault_root().mkdir(parents=True, exist_ok=True)
    inbox_dir().mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_id() -> str:
    return uuid.uuid4().hex[:8]


def slugify(title: str) -> str:
    slug = title.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug or "note"


def is_ignorable(path: Path) -> bool:
    """Files the watcher/reconciler should never treat as notes."""
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
    # topic name -> note id. Only meaningfully used on About Me today (see
    # get_or_create_linked_note in agent/tools/notes.py) — a deterministic
    # registry so a specific person/project/topic can always be found the
    # same reliable way About Me itself is found, rather than through
    # search or a remembered id that can go stale or get hallucinated.
    linked_notes: dict = field(default_factory=dict)

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
        if self.linked_notes:
            fm["linked_notes"] = self.linked_notes
        return fm


def serialize_note(note: Note) -> str:
    fm = yaml.safe_dump(note.frontmatter_dict(), sort_keys=False, allow_unicode=True).strip()
    body = note.body if note.body.endswith("\n") else note.body + "\n"
    return f"{FRONTMATTER_DELIM}\n{fm}\n{FRONTMATTER_DELIM}\n\n{body}"


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
        created=fm.get("created") or now_iso(),
        updated=fm.get("updated") or now_iso(),
        tags=fm.get("tags") or [],
        aliases=fm.get("aliases") or [],
        source=fm.get("source") or "agent",
        body=body.lstrip("\n"),
        path=path,
        linked_notes=fm.get("linked_notes") or {},
    )


def write_note_atomic(path: Path, content: str) -> None:
    """
    Write via temp file + rename so a concurrent reader (or Syncthing
    mid-scan) never sees a half-written file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


def unique_note_path(title: str) -> Path:
    """Pick a non-colliding filename in the vault root for a new note."""
    slug = slugify(title)
    candidate = vault_root() / f"{slug}.md"
    if not candidate.exists():
        return candidate
    suffix = generate_id()
    return vault_root() / f"{slug}-{suffix}.md"


# ---------------------------------------------------------------------------
# Listing / lookup
# ---------------------------------------------------------------------------

def list_vault_notes() -> list[Path]:
    """All managed note files at the vault root (flat, excludes Inbox)."""
    root = vault_root()
    if not root.exists():
        return []
    return [p for p in root.iterdir() if p.is_file() and not is_ignorable(p)]


def list_inbox_files() -> list[Path]:
    inbox = inbox_dir()
    if not inbox.exists():
        return []
    return [p for p in inbox.iterdir() if p.is_file() and not is_ignorable(p)]


def find_note_by_id(note_id: str) -> Path | None:
    """Linear scan over the vault root — fine at personal-vault scale."""
    for path in list_vault_notes():
        note = parse_note(path)
        if note is not None and note.id == note_id:
            return path
    return None


def about_me_path() -> Path:
    return vault_root() / ABOUT_ME_FILENAME


def find_linked_note_id(linked_notes: dict, topic: str) -> str | None:
    """
    Look up `topic` in a linked_notes registry, tolerant of case/whitespace
    differences (the model may not phrase a topic identically every time).
    Exact match first, then a case-insensitive fallback.
    """
    if topic in linked_notes:
        return linked_notes[topic]
    topic_lower = topic.strip().lower()
    for key, note_id in linked_notes.items():
        if key.strip().lower() == topic_lower:
            return note_id
    return None


def get_or_create_about_me() -> Note:
    """
    Always resolves to the same file, every time, regardless of what any
    tool call earlier in the conversation thought its id was. If it
    doesn't exist yet, it's created empty (with a starter set of section
    headings) rather than requiring a separate create-vs-update decision
    upstream.
    """
    path = about_me_path()
    note = parse_note(path)
    if note is not None:
        return note

    now = now_iso()
    note = Note(
        id=generate_id(),
        title=ABOUT_ME_TITLE,
        created=now,
        updated=now,
        tags=["about-me"],
        aliases=[],
        source="agent",
        body="## Preferences\n\n## People\n\n## Routine\n\n## Interests\n",
        path=path,
    )
    write_note_atomic(path, serialize_note(note))
    return note


# ---------------------------------------------------------------------------
# Section-level editing
# ---------------------------------------------------------------------------

def _section_span(body: str, heading: str) -> tuple[int, int] | None:
    """
    Returns (content_start, content_end) spanning the text under `heading`,
    not including the heading line itself. None if the heading isn't
    present in the body.
    """
    pattern = re.compile(rf"(?m)^##[ \t]+{re.escape(heading.strip())}[ \t]*$")
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
