"""
utils/vault.py
---------------
Core file I/O and markdown/frontmatter handling for the Obsidian-synced
notes vault. This module owns the on-disk format; agent/vault_watcher.py
builds on top of it rather than touching files directly.

Vault layout:
    <VAULT_PATH>/
        Inbox/       Landing pad for notes not created via direct agent
                      interaction (e.g. typed on your phone via Obsidian
                      mobile). Watched and auto-processed into a real,
                      indexed note, then removed from Inbox.
        <note>.md     Processed notes live flat at the vault root by
                      default — no category folders. Tags and [[links]] do
                      the organizing, not folder placement.
        <folder>/    One level deep, no nesting — is_project_dir() treats
                      any such folder (other than Inbox/dotfiles) as a
                      content folder for list_vault_notes() to scan.

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
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import yaml

INBOX_DIRNAME = "Inbox"
FRONTMATTER_DELIM = "---"

# The About Me note is a singleton with a fixed, known location, unlike
# ordinary notes — no dependency on embedding similarity, and no risk of an
# id remembered from an earlier turn going stale or getting hallucinated.
ABOUT_ME_FILENAME = "about-me.md"
ABOUT_ME_TITLE = "About Me"

# Daily digest notes use a deterministic, date-keyed filename (like About
# Me's fixed path) rather than unique_note_path's slug-collision handling
# — re-running the digest for a day that already has one (manual testing
# via POST /debug/digest, a retry) should update that day's note in place,
# not create a second one.
DAILY_NOTE_TAG = "daily-digest"

# Task-planning notes (agent/tools/planning.py) use the same date-keyed
# filename pattern as daily digest notes, but a distinct one — the two
# serve different purposes and shouldn't collide.
PLANNING_NOTE_TAG = "planning-session"
PLANNING_STARTER_BODY = (
    "## Tasks\n\n## Fixed Blocks\n\n## Generated Schedule & Sprints\n\n## End of Day Reflection\n"
)


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
    # topic name -> note id, written on About Me by the now-removed
    # get_or_create_linked_note tool. Nothing writes or reads this anymore;
    # kept only so an existing About Me note's frontmatter still round-trips.
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
        linked_notes=fm.get("linked_notes") or {},
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


def _claim_path(path: Path) -> bool:
    """Atomically claims a filename via exclusive create, returning False if
    it already existed. Used instead of an exists()-then-write check, which
    has a TOCTOU gap two concurrent writers can both pass."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.close(fd)
    return True


def unique_note_path(title: str) -> Path:
    """Pick a non-colliding filename for a new note in the vault root.

    The candidate is claimed with an exclusive create (not just an
    existence check) so a concurrent writer computing the same slug —
    the Inbox watcher — can't race past a stale check and overwrite this
    note once real content is written. The caller's subsequent
    write_note_atomic replaces this empty placeholder with the actual
    content.
    """
    target_dir = vault_root()
    target_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(title)

    candidate = target_dir / f"{slug}.md"
    if _claim_path(candidate):
        return candidate

    for _ in range(5):
        candidate = target_dir / f"{slug}-{generate_id()}.md"
        if _claim_path(candidate):
            return candidate

    raise RuntimeError(f"Could not claim a unique note path for title: {title!r}")


# ---------------------------------------------------------------------------
# Project folders
# ---------------------------------------------------------------------------

def is_project_dir(path: Path) -> bool:
    """True for a vault-root subdirectory that groups one project's notes —
    everything except Inbox and dotfile directories (e.g. Obsidian's own
    .obsidian)."""
    return (
        path.is_dir()
        and path.parent == vault_root()
        and path.name != INBOX_DIRNAME
        and not path.name.startswith(".")
    )


# ---------------------------------------------------------------------------
# Listing / lookup
# ---------------------------------------------------------------------------

def list_vault_notes() -> list[Path]:
    """All managed note files at the vault root and one level inside any
    project folder (excludes Inbox)."""
    root = vault_root()
    if not root.exists():
        return []
    notes = [p for p in root.iterdir() if p.is_file() and not is_ignorable(p)]
    for project_dir in (p for p in root.iterdir() if is_project_dir(p)):
        notes.extend(p for p in project_dir.iterdir() if p.is_file() and not is_ignorable(p))
    return notes


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


def daily_note_path(date_str: str) -> Path:
    """Deterministic path for a given day's digest note. `date_str` is
    "YYYY-MM-DD" in the user's configured timezone (see jobs/digest.py)."""
    return vault_root() / f"daily-{date_str}.md"


def planning_note_path(date_str: str) -> Path:
    """Deterministic path for a given day's task-planning note (see
    get_or_create_planning_note). `date_str` is "YYYY-MM-DD" in the
    user's configured timezone — same pattern as daily_note_path, but a
    distinct filename since the two notes serve different purposes."""
    return vault_root() / f"planning-{date_str}.md"


def get_or_create_planning_note(date_str: str, template_note_id: str | None = None) -> Note:
    """Get (or create) the day's task-planning note. A new note clones
    the body of the configured template note (`template_note_id`, from
    agent/settings.py's planning_template_note_id) so it starts with the
    usual Tasks/Generated Schedule/End of Day Reflection layout; if no
    template is configured (or it's gone missing), falls back to just
    those three empty section headings — same graceful-fallback shape
    get_or_create_about_me already uses."""
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
        body=(
            "## Basics\n\n## Preferences\n\n## People\n\n## Routine\n\n## Interests\n"
            "\n## Health & Goals\n\n## Important Dates\n"
        ),
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


def list_headings(body: str) -> list[str]:
    """Every `##` heading in `body`, in order."""
    return [m.group(1).strip() for m in re.finditer(r"(?m)^##[ \t]+(.+?)[ \t]*$", body)]


def match_heading(body: str, heading: str, cutoff: float = 0.85) -> str | None:
    """The existing heading `heading` refers to: exact (case-insensitive) first,
    then the closest near-miss ("Importance Dates" -> "Important Dates").
    None when nothing in `body` is close enough."""
    want = heading.strip().lower()
    candidates = list_headings(body)
    for h in candidates:
        if h.lower() == want:
            return h
    best, best_ratio = None, cutoff
    for h in candidates:
        ratio = SequenceMatcher(None, want, h.lower()).ratio()
        if ratio >= best_ratio:
            best, best_ratio = h, ratio
    return best


def section_lines(body: str, heading: str) -> list[str]:
    """Non-empty stripped lines under `heading` ([] if the section is missing)."""
    text = get_section(body, heading) or ""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def drop_present_lines(body: str, heading: str, addition: str) -> str:
    """`addition` minus any line already present under `heading` (compared
    case-insensitively, whitespace-stripped). Empty string if nothing is new."""
    have = {ln.lower() for ln in section_lines(body, heading)}
    kept = [ln for ln in addition.splitlines() if ln.strip() and ln.strip().lower() not in have]
    return "\n".join(kept)
