"""
agent/tools/notes.py
---------------------
Agent-facing tools for the Obsidian-backed notes vault.

Notes live as markdown files on disk (utils/vault.py owns the format);
Chroma (via MemoryStore) is just a search index over them, kept in sync
by agent/vault_watcher.py. These tools read/write files directly and then
re-index synchronously, so a search immediately after a write reflects
the change without waiting on the watcher.

Two ways a note grows through the agent, matching how they're actually
meant to be used:
  - append_to_note      — adds a new entry under a heading, log-style.
    Can only add; never touches existing content. Use for history that
    should accumulate (e.g. a service record, a dated observation).
  - update_note_section  — replaces everything under one named heading,
    for when something has superseded the old value (a status, a due
    date). Never touches anything outside that heading.

Manual, precise corrections (fixing a typo, a wrong number) are expected
to happen by hand directly in Obsidian — these tools don't try to do
find-and-replace edits against arbitrary note text.

remember_about_me/read_about_me are a special case: unlike ordinary notes
(found via search_notes, referenced by whatever id that search returns),
the About Me note is a singleton at a fixed, known path
(utils.vault.get_or_create_about_me). Routing it through search — and
requiring the model to correctly remember an id from an earlier tool
call — turned out to be exactly the kind of multi-step chain a smaller
local model doesn't reliably get right. These tools resolve it directly
every time, so there's nothing to remember and nothing to get wrong.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Literal, Optional

from langchain_core.tools import tool

from agent.memory import MemoryStore
from agent.vault_watcher import index_note_file
from utils import vault


def _derive_title(content: str) -> str:
    """Best-effort title from a note's content, for when the model omits
    title — observed in practice (project-scoped save_note calls) as
    exactly the kind of extra required field a smaller local model doesn't
    reliably keep supplying once a tool result nudges it toward a shorter
    call shape. Cheaper and more reliable than continuing to prompt-engineer
    around it."""
    first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
    first_line = re.sub(r"^[#>\-\s]+", "", first_line)  # leading heading/quote/bullet markers
    first_line = re.sub(r"[*_`]+", "", first_line).strip()  # emphasis/code markers anywhere
    if not first_line:
        return "Untitled Note"
    return first_line[:60] + ("…" if len(first_line) > 60 else "")


def _normalize_tags(tags: Optional[list[str]]) -> list[str]:
    """Tags are used as-is in frontmatter/search, so enforce the
    space-free, hyphenated convention here rather than relying on the
    model to always phrase them that way (see vault.slugify)."""
    return [vault.slugify(t) for t in (tags or []) if t and t.strip()]


# About Me is a single fixed-path note (utils.vault.get_or_create_about_me),
# and LangGraph's ToolNode can run multiple tool calls from one LLM turn
# concurrently. Everything that does a read-modify-write on it (the tools
# below, and agent/profile_import.py) shares this lock; without it, two
# concurrent calls can read before either writes and clobber each other, or
# both decide a linked-note topic is new and create duplicates.
about_me_lock = asyncio.Lock()

# Sections that hold many distinct entries: a "replace" on one wipes them all.
MULTI_ENTRY_SECTIONS = {"people", "important dates", "events"}

# Section names that are profile topics, not people/things deserving their
# own linked note, and not to be mistaken for a linked note's name.
PROFILE_SECTION_NAMES = {
    "basics", "preferences", "people", "routine", "interests", "health & goals",
    "important dates", "values", "goals", "occupation", "current job",
    "current projects", "projects", "events", "health", "career", "location",
}


@dataclass
class LinkedNoteResult:
    status: str  # "created" | "adopted" | "exists" | "refused"
    note_id: str | None = None
    message: str = ""


async def create_linked_note(
    memory: MemoryStore, topic: str, category: str, content: str = "", link_label: str = ""
) -> LinkedNoteResult:
    """Create (or reuse) the dedicated note for `topic`, linked from About
    Me under `category`. An unlinked note already sitting at the topic's
    filename with the same title and category tag (left over after an About
    Me reset) is adopted rather than duplicated."""
    topic = topic.strip()
    if not topic:
        return LinkedNoteResult("refused", message="A topic name is required.")
    async with about_me_lock:
        about_me = vault.get_or_create_about_me()
        if topic.lower() in PROFILE_SECTION_NAMES or topic.lower() in {
            h.lower() for h in vault.list_headings(about_me.body)
        }:
            return LinkedNoteResult(
                "refused",
                message=(
                    f"'{topic}' is a profile section, not a person or thing that needs its own "
                    f"note. Use remember_about_me(section='{topic}', content=...) instead."
                ),
            )
        existing_id = vault.find_linked_note_id(about_me.linked_notes, topic)
        if existing_id is not None:
            return LinkedNoteResult(
                "exists",
                existing_id,
                f"'{topic}' already has a note (id: {existing_id}). "
                f"Use read_note/append_to_note/update_note_section with this id — "
                f"do not create a new note for this topic.",
            )

        now = vault.now_iso()
        tag = vault.slugify(category)
        note = None
        orphan = vault.parse_note(vault.vault_root() / f"{vault.slugify(topic)}.md")
        if (
            orphan is not None
            and orphan.title.strip().lower() == topic.lower()
            and tag in orphan.tags
            and orphan.id
        ):
            note, status = orphan, "adopted"
            if content.strip() and content.strip() not in note.body:
                note.body = f"{note.body.rstrip()}\n{content.strip()}".strip()
                note.updated = now
                vault.write_note_atomic(note.path, vault.serialize_note(note))
        if note is None:
            note = vault.Note(
                id=vault.generate_id(), title=topic, created=now, updated=now,
                tags=[tag], source="agent", body=content.strip(),
            )
            note.path = vault.unique_note_path(topic)
            vault.write_note_atomic(note.path, vault.serialize_note(note))
            status = "created"
        await index_note_file(memory, note.path)

        about_me.linked_notes[topic] = note.id
        link = f"- [[{topic}]]" + (f" ({link_label.strip()})" if link_label.strip() else "")
        if link not in vault.section_lines(about_me.body, category):
            about_me.body = vault.append_to_section(about_me.body, category, link)
        about_me.updated = now
        vault.write_note_atomic(about_me.path, vault.serialize_note(about_me))
        await index_note_file(memory, about_me.path)

    wrote = " The details you gave are already saved in it." if content.strip() else (
        " Use read_note/append_to_note/update_note_section with this id to add details."
    )
    verb = "Created a new" if status == "created" else "Reused an existing"
    return LinkedNoteResult(
        status, note.id,
        f"{verb} note for '{topic}' (id: {note.id}), linked from About Me's '{category}' section.{wrote}",
    )


def make_note_tools(memory: MemoryStore):
    # Same race as about_me_lock, but for project folders: two concurrent
    # get_or_create_project calls fuzzy-matching the same not-yet-created
    # name shouldn't both decide it's new and each write a starter overview
    # note into it.
    _project_lock = asyncio.Lock()

    @tool
    async def save_note(
        content: str,
        title: Optional[str] = None,
        tags: Optional[list[str]] = None,
        project: Optional[str] = None,
    ) -> str:
        """Create a brand new note in the vault. If it might relate to an
        existing note, search_notes first — prefer append_to_note/
        update_note_section over a near-duplicate note.

        Args:
            content: The note's body.
            title: A short, specific title. Optional — derived from content if omitted.
            tags: Optional lowercase category tags (spaces are fine, normalized to hyphens).
            project: If part of an ongoing project, its name (from
                get_or_create_project) — files the note in that project's folder.
                Keep [[wikilinks]] within the same project, don't link out to the
                rest of the vault.
        """
        title = (title or "").strip() or _derive_title(content)
        now = vault.now_iso()
        note = vault.Note(
            id=vault.generate_id(),
            title=title,
            created=now,
            updated=now,
            tags=_normalize_tags(tags),
            aliases=[],
            source="agent",
            body=content.strip() + "\n",
        )
        project_dir = None
        if project:
            project_dir, _ = vault.get_or_create_project_dir(project)
        path = vault.unique_note_path(title, project=project_dir)
        note.path = path
        vault.write_note_atomic(path, vault.serialize_note(note))
        await index_note_file(memory, path)
        return f"Note saved: '{title}' (id: {note.id})."

    @tool
    def search_notes(query: str, project: Optional[str] = None) -> str:
        """Search saved notes. Returns short excerpts with each note's id —
        use read_note with that id for the full note before editing.

        Args:
            query: What to search for.
            project: If actively discussing a specific project, its name
                (from get_or_create_project) to scope the search to it.
                Leave unset for a vault-wide search.
        """
        resolved_project = None
        if project:
            match = vault.match_project_dir(project)
            resolved_project = match.name if match else None
        results = memory.search_notes(query, n_results=5, project=resolved_project)
        if not results:
            return "No matching notes found."
        lines = [f"[id: {r['id']}] {r['title']} — {r['excerpt']}" for r in results]
        return "\n".join(lines)

    @tool
    def read_note(note_id: str) -> str:
        """Read the full content of a note, including its tags. Use this
        before append_to_note or update_note_section so you know what
        sections already exist. Get note_id from search_notes.

        Args:
            note_id: The note's id, as returned by search_notes.
        """
        path = vault.find_note_by_id(note_id)
        if path is None:
            return f"No note found with id '{note_id}'."
        note = vault.parse_note(path)
        if note is None:
            return f"Note '{note_id}' could not be read."
        return f"# {note.title}\ntags: {', '.join(note.tags) or 'none'}\n\n{note.body}"

    @tool
    async def append_to_note(note_id: str, section: str, content: str) -> str:
        """Add an entry to a note under a heading, without touching what's
        already there — for log-style additions (a new service record, a
        dated observation). Creates the heading if it doesn't exist.

        Args:
            note_id: The note's id, from search_notes.
            section: The heading to append under (e.g. "Service Log").
            content: The text to add.
        """
        path = vault.find_note_by_id(note_id)
        if path is None:
            return f"No note found with id '{note_id}'."
        note = vault.parse_note(path)
        if note is None:
            return f"Note '{note_id}' could not be read."

        note.body = vault.append_to_section(note.body, section, content)
        note.updated = vault.now_iso()
        vault.write_note_atomic(path, vault.serialize_note(note))
        await index_note_file(memory, path)
        return f"Added to '{section}' in '{note.title}'."

    @tool
    async def update_note_section(note_id: str, section: str, new_content: str) -> str:
        """Replace the content under one heading in a note, leaving the rest
        untouched. Use when a value is superseded (a status, a due date) —
        not for adding new history (use append_to_note). Creates the
        heading if it doesn't exist.

        Args:
            note_id: The note's id, from search_notes.
            section: The heading to replace (e.g. "Current Status").
            new_content: The new content for that section.
        """
        path = vault.find_note_by_id(note_id)
        if path is None:
            return f"No note found with id '{note_id}'."
        note = vault.parse_note(path)
        if note is None:
            return f"Note '{note_id}' could not be read."

        note.body = vault.replace_section(note.body, section, new_content)
        note.updated = vault.now_iso()
        vault.write_note_atomic(path, vault.serialize_note(note))
        await index_note_file(memory, path)
        return f"Updated '{section}' in '{note.title}'."

    @tool
    async def remember_about_me(
        section: str, content: str, mode: Literal["append", "replace"] = "append"
    ) -> str:
        """Record/update a fact in the user's About Me note — the only tool
        for this; it always resolves the right note automatically, no need
        to search or track an id.

        Never use mode="replace" on a section holding multiple distinct
        entries (People, Important Dates, Events) — it would wipe every
        entry, so it is refused. Use get_or_create_linked_note for a
        specific person/topic instead.

        Args:
            section: Profile section (e.g. "Preferences", "Routine") —
                single-topic only. Created automatically if missing.
            content: The fact or update to record. Only what the user
                actually said.
            mode: "append" (default) adds without touching existing content
                — use for new facts. "replace" overwrites the section
                entirely — only for superseding an old value, never on a
                multi-entry section.
        """
        async with about_me_lock:
            note = vault.get_or_create_about_me()
            heading = vault.match_heading(note.body, section) or section.strip()
            key = heading.lower()
            linked_id = vault.find_linked_note_id(note.linked_notes, heading)
            if linked_id is not None and key not in PROFILE_SECTION_NAMES:
                return (
                    f"'{heading}' has its own note (id: {linked_id}). Add details with "
                    f"append_to_note(note_id='{linked_id}', ...), not as an About Me section."
                )
            if mode == "replace" and key in MULTI_ENTRY_SECTIONS:
                return (
                    f"Refused: '{heading}' holds many entries and replace would wipe them all. "
                    f"Use mode='append' to add one, or get_or_create_linked_note for one person/topic."
                )
            before = len(vault.section_lines(note.body, heading))
            if mode == "replace":
                note.body = vault.replace_section(note.body, heading, content)
                result = f"Replaced '{heading}' (was {before} lines, now {len(vault.section_lines(note.body, heading))})."
            else:
                new_text = vault.drop_present_lines(note.body, heading, content)
                if not new_text:
                    return f"Already recorded under '{heading}' — nothing added."
                note.body = vault.append_to_section(note.body, heading, new_text)
                result = f"Added to '{heading}' (now {len(vault.section_lines(note.body, heading))} lines)."
            note.updated = vault.now_iso()
            vault.write_note_atomic(note.path, vault.serialize_note(note))
            await index_note_file(memory, note.path)
        return result

    @tool
    async def get_or_create_linked_note(topic: str, category: str, content: str = "") -> str:
        """Get (or create) a dedicated note for one specific person/project/
        topic, linked from About Me. Returns its id.

        Use instead of writing into a shared About Me section when: the
        section holds multiple distinct entries (e.g. "People") and you're
        updating ONE of them, or a single topic is accumulating enough
        detail to outgrow a short line in About Me. Not for profile
        sections like Interests, Values or Routine — those go through
        remember_about_me.

        Always resolves to the same note for the same topic — never search
        for it or guess an id from earlier in the conversation. Safe to
        call even when one already exists.

        Args:
            topic: The specific name (e.g. "Alex", not "People"). Use the
                same name consistently — it's the key used to find this
                note again.
            category: Which About Me section this is indexed under (e.g.
                "People", "Career", "Health").
            content: Optional details to save in the new note right away.
                Only what the user actually said — leave blank if unknown.
        """
        return (await create_linked_note(memory, topic, category, content)).message

    @tool
    async def get_or_create_project(name: str) -> str:
        """Get (or create) a dedicated vault folder for one ongoing project,
        so its notes live together and can be searched as a unit. Returns
        the project's canonical name — use that exact string with
        save_note's/search_notes's `project` argument afterward.

        For a recurring body of work the user returns to across sessions —
        not a one-off note, and not a person/topic (use
        get_or_create_linked_note for that). Fuzzy-matches close variations
        of a name already used, so it always resolves to the same folder.
        Safe to call even if it already exists.

        Args:
            name: The project's name (e.g. "Track Deck"). Use the same name
                consistently once created.
        """
        async with _project_lock:
            project_dir, created = vault.get_or_create_project_dir(name)
            if not created:
                return (
                    f"Project '{project_dir.name}' already exists. Use save_note(title=..., "
                    f"content=..., project='{project_dir.name}') and search_notes(query=..., "
                    f"project='{project_dir.name}') to work with it."
                )

            now = vault.now_iso()
            note = vault.Note(
                id=vault.generate_id(),
                title=name,
                created=now,
                updated=now,
                tags=[],
                aliases=[],
                source="agent",
                body="## Overview\n\n## Notes\n",
            )
            path = vault.unique_note_path(name, project=project_dir)
            note.path = path
            vault.write_note_atomic(path, vault.serialize_note(note))
            await index_note_file(memory, path)

        return (
            f"Created a new project folder '{project_dir.name}' with an overview note. "
            f"Use save_note(title=..., content=..., project='{project_dir.name}') to add "
            f"notes to it, and search_notes(query=..., project='{project_dir.name}') to "
            f"search only within it."
        )

    @tool
    def list_projects() -> str:
        """List all existing project folders in the vault. Check this before
        calling get_or_create_project if you're unsure whether a project the
        user mentions already exists."""
        projects = vault.list_project_dirs()
        if not projects:
            return "No projects yet."
        return "\n".join(f"- {p.name}" for p in projects)

    @tool
    def read_about_me() -> str:
        """Read everything currently known about the user from their About
        Me note. Use this to check what's already recorded before deciding
        whether something new is actually worth adding."""
        note = vault.get_or_create_about_me()
        if not note.body.strip():
            return "About Me note exists but is empty — nothing recorded yet."
        return note.body

    return (
        save_note,
        search_notes,
        read_note,
        append_to_note,
        update_note_section,
        remember_about_me,
        get_or_create_linked_note,
        get_or_create_project,
        list_projects,
        read_about_me,
    )
