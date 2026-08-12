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
        <note>.md     Processed notes live flat at the vault root by
                      default — no category folders. Tags and [[links]] do
                      the organizing, not folder placement.
        <Project>/    The one deliberate exception: a project folder groups
                      together all the notes for one ongoing project (see
                      get_or_create_project_dir/get_or_create_project in
                      agent/tools/notes.py). One level deep only, no
                      nesting — a note's containing folder *is* its
                      project, there's no separate registry to keep in
                      sync.

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
from difflib import SequenceMatcher
from pathlib import Path

import yaml

INBOX_DIRNAME = "Inbox"
FRONTMATTER_DELIM = "---"

# Same threshold convention as agent/keywords.py's fuzzy thread-keyword
# matching — tolerates the model or a voice transcription phrasing a
# project name slightly differently without spawning a near-duplicate
# folder for what's really the same project.
PROJECT_MATCH_THRESHOLD = 0.75

# The About Me note is a singleton with a fixed, known location, unlike
# ordinary notes. It's referenced constantly (every turn learning mode is
# on), so it deliberately doesn't go through search_notes/find_note_by_id
# at all — no dependency on embedding similarity, and no risk of an id
# remembered from an earlier turn going stale or getting hallucinated.
# See agent/tools/notes.py's remember_about_me/read_about_me.
ABOUT_ME_FILENAME = "about-me.md"
ABOUT_ME_TITLE = "About Me"

# Daily digest notes use a deterministic, date-keyed filename (like About
# Me's fixed path) rather than unique_note_path's slug-collision handling
# — re-running the digest for a day that already has one (manual testing
# via POST /debug/digest, a retry) should update that day's note in place,
# not create a second one.
DAILY_NOTE_TAG = "daily-digest"


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


def unique_note_path(title: str, project: Path | None = None) -> Path:
    """Pick a non-colliding filename for a new note — in the vault root, or
    inside `project` (a project folder from get_or_create_project_dir) if
    given.

    The candidate is claimed with an exclusive create (not just an
    existence check) so a concurrent writer computing the same slug —
    another save_note call, or the Inbox watcher — can't race past a
    stale check and overwrite this note once real content is written.
    The caller's subsequent write_note_atomic replaces this empty
    placeholder with the actual content.
    """
    target_dir = project if project is not None else vault_root()
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


def list_project_dirs() -> list[Path]:
    root = vault_root()
    if not root.exists():
        return []
    return [p for p in root.iterdir() if is_project_dir(p)]


def match_project_dir(name: str) -> Path | None:
    """Fuzzy-match `name` against existing project folder names, tolerant of
    the model (or a voice transcription) phrasing a project name slightly
    differently each time. Pure lookup — never creates anything."""
    projects = list_project_dirs()
    slug = slugify(name)
    for p in projects:
        if p.name == slug:
            return p

    candidate = name.strip().lower()
    best_dir = None
    best_ratio = 0.0
    for p in projects:
        ratio = SequenceMatcher(None, candidate, p.name.replace("-", " ").lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_dir = p

    if best_dir is not None and best_ratio >= PROJECT_MATCH_THRESHOLD:
        return best_dir
    return None


def get_or_create_project_dir(name: str) -> tuple[Path, bool]:
    """Get (or create) the folder for a project. Returns (dir, created)."""
    existing = match_project_dir(name)
    if existing is not None:
        return existing, False

    root = vault_root()
    project_dir = root / slugify(name)
    # slugify already strips anything that could escape vault_root() (path
    # separators, "..", etc.) — this is a cheap defense-in-depth check on
    # top of that, since nothing else in this module guards against path
    # traversal from user/model-supplied names.
    if not project_dir.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Unsafe project name: {name!r}")
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir, True


# ---------------------------------------------------------------------------
# Project image attachments
# ---------------------------------------------------------------------------

ATTACHMENTS_DIRNAME = "attachments"
ALLOWED_ATTACHMENT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def project_attachments_dir(project_dir: Path) -> Path:
    return project_dir / ATTACHMENTS_DIRNAME


def save_project_attachment(project_dir: Path, filename: str, data: bytes) -> Path:
    """Save an uploaded/dropped-in image under a project's attachments folder.
    Sanitizes the filename the same way unique_note_path sanitizes a title —
    slugify the stem, keep the extension — and de-dupes a collision with a
    short id suffix rather than overwriting."""
    attachments_dir = project_attachments_dir(project_dir)
    attachments_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(filename).suffix.lower()
    stem = slugify(Path(filename).stem)
    candidate = attachments_dir / f"{stem}{suffix}"
    if candidate.exists():
        candidate = attachments_dir / f"{stem}-{generate_id()}{suffix}"

    # Same defense-in-depth shape as get_or_create_project_dir: slugify
    # already strips path-traversal characters, this just double-checks.
    if not candidate.resolve().is_relative_to(attachments_dir.resolve()):
        raise ValueError(f"Unsafe attachment filename: {filename!r}")

    tmp_path = candidate.with_name(candidate.name + f".tmp{os.getpid()}")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, candidate)
    return candidate


def list_project_attachments(project_dir: Path) -> list[Path]:
    attachments_dir = project_attachments_dir(project_dir)
    if not attachments_dir.exists():
        return []
    return sorted(
        p for p in attachments_dir.iterdir()
        if p.is_file() and p.suffix.lower() in ALLOWED_ATTACHMENT_EXTENSIONS
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
    for project_dir in list_project_dirs():
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


def note_project(path: Path) -> str | None:
    """The project folder name a note lives in, or None for a vault-root
    note. Used to label notes for the vault-browse dashboard page."""
    parent = path.parent
    return parent.name if is_project_dir(parent) else None


def list_notes_summary() -> list[dict]:
    """Lightweight metadata for every processed note (excludes Inbox — see
    list_vault_notes), most recently updated first. Backs GET /vault/notes;
    kept here rather than inline in main.py since it's just another read
    over what this module already owns."""
    notes = []
    for path in list_vault_notes():
        note = parse_note(path)
        if note is None:
            continue
        notes.append(
            {
                "id": note.id,
                "title": note.title,
                "tags": note.tags,
                "project": note_project(path),
                "source": note.source,
                "created": note.created,
                "updated": note.updated,
                "excerpt": note.body.strip()[:200],
            }
        )
    notes.sort(key=lambda n: n["updated"], reverse=True)
    return notes


def about_me_path() -> Path:
    return vault_root() / ABOUT_ME_FILENAME


def daily_note_path(date_str: str) -> Path:
    """Deterministic path for a given day's digest note. `date_str` is
    "YYYY-MM-DD" in the user's configured timezone (see jobs/digest.py)."""
    return vault_root() / f"daily-{date_str}.md"


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
