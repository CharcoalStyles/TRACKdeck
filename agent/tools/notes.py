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


def make_note_tools(memory: MemoryStore):
    # About Me is a single fixed-path note (utils.vault.get_or_create_about_me),
    # and LangGraph's ToolNode can run multiple tool calls from one LLM turn
    # concurrently. Both remember_about_me and get_or_create_linked_note do a
    # read-modify-write on it; without this lock, two concurrent calls can
    # interleave — reading before either writes — and clobber each other's
    # changes, or both decide a linked-note topic is new and create duplicates.
    _about_me_lock = asyncio.Lock()

    # Same race as _about_me_lock, but for project folders: two concurrent
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
        """Create a brand new note in the vault. Use this when the user wants
        to jot something down or remember something new. If it might relate
        to an existing note, search_notes first — prefer append_to_note or
        update_note_section over creating a near-duplicate note.

        Args:
            content: The body of the note.
            title: A short, specific title for the note. Optional — if
                omitted, one is derived from the note's content, but a
                real title is preferred when you have one.
            tags: Optional list of lowercase category tags.
            project: If this note belongs to an ongoing project, its name
                (as returned by get_or_create_project) — files the note
                inside that project's folder instead of the vault root.
                If linking to other notes via [[wikilinks]], keep links
                inside the same project — don't link out to the rest of
                the vault.
        """
        title = (title or "").strip() or _derive_title(content)
        now = vault.now_iso()
        note = vault.Note(
            id=vault.generate_id(),
            title=title,
            created=now,
            updated=now,
            tags=tags or [],
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
        """Search saved notes for information. Returns short excerpts with
        each note's id — use read_note with that id if you need the full
        note before editing it.

        Args:
            query: What to search for in past notes.
            project: If the user is actively discussing a specific ongoing
                project, its name (as returned by get_or_create_project) —
                scopes the search to just that project's notes instead of
                the whole vault. Leave unset for a normal, vault-wide
                search.
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
        """Add a new entry to a note under a given heading, without changing
        anything already there. Use this for log-style additions — a new
        service record, a new dated observation — where old entries should
        stay. Creates the heading if it doesn't already exist on the note.

        Args:
            note_id: The note's id, as returned by search_notes.
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
        """Replace the content under one heading in a note, leaving
        everything else in the note untouched. Use this when something has
        superseded the old value — e.g. a status or a due date changed —
        not for adding new history (use append_to_note for that). Creates
        the heading if it doesn't already exist on the note.

        Args:
            note_id: The note's id, as returned by search_notes.
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
        """Record or update something learned about the user in their
        permanent About Me note. This is the ONLY tool to use for that —
        it always finds or creates the right note automatically, so there
        is no need to search for it first or keep track of its id.

        Do NOT use this for a section that holds multiple distinct entries
        (e.g. "People" covering several different people, or any section
        that's really a collection rather than one coherent topic). Using
        mode="replace" on a collection section wipes every entry in it, not
        just the one being corrected. For that situation, use
        get_or_create_linked_note instead to get a dedicated note for the
        specific person/topic, and edit that note directly.

        Args:
            section: Which part of the profile this belongs to (e.g.
                "Preferences", "Routine", "Interests" — single-topic
                sections only). Created automatically if it doesn't
                already exist.
            content: The fact or update to record.
            mode: "append" (default) adds to what's already under that
                heading without touching it — use for new facts. "replace"
                overwrites that heading's content entirely — use only when
                something supersedes an old value, not for adding new facts,
                and never on a section holding multiple distinct entries.
        """
        async with _about_me_lock:
            note = vault.get_or_create_about_me()
            if mode == "replace":
                note.body = vault.replace_section(note.body, section, content)
            else:
                note.body = vault.append_to_section(note.body, section, content)
            note.updated = vault.now_iso()
            vault.write_note_atomic(note.path, vault.serialize_note(note))
            await index_note_file(memory, note.path)
        return f"Recorded under '{section}' in About Me."

    @tool
    async def get_or_create_linked_note(topic: str, category: str) -> str:
        """Get (or create) a dedicated note for one specific person, project,
        or other distinct sub-topic, linked from About Me. Returns that
        note's id — use read_note/append_to_note/update_note_section with
        that id for everything about this topic afterward, exactly as you
        would for any other note.

        Use this instead of writing into a shared About Me section whenever:
          - The relevant section holds multiple distinct entries (e.g.
            "People" has several different people) and you're about to add
            or correct information about ONE of them specifically.
          - A single topic (a person, an ongoing project, a specific health
            matter) is accumulating enough detail that it no longer fits as
            a short line in About Me.

        This always finds the same note for the same topic — never search
        for it, never guess an id from earlier in the conversation, never
        create a second note for something that already has one. If in
        doubt whether a topic already has a note, call this first; it's
        safe to call even when one already exists.

        Args:
            topic: The specific name of the person/project/topic (e.g.
                "Alex", not "People"). Use the exact same name consistently
                once created — it's the key used to find this note again.
            category: Which About Me section this gets indexed under (e.g.
                "People", "Career", "Health").
        """
        async with _about_me_lock:
            about_me = vault.get_or_create_about_me()
            existing_id = vault.find_linked_note_id(about_me.linked_notes, topic)
            if existing_id is not None:
                return (
                    f"'{topic}' already has a note (id: {existing_id}). "
                    f"Use read_note/append_to_note/update_note_section with this id — "
                    f"do not create a new note for this topic."
                )

            now = vault.now_iso()
            note = vault.Note(
                id=vault.generate_id(),
                title=topic,
                created=now,
                updated=now,
                tags=[category.lower()],
                source="agent",
                body="",
            )
            path = vault.unique_note_path(topic)
            note.path = path
            vault.write_note_atomic(path, vault.serialize_note(note))
            await index_note_file(memory, path)

            about_me.linked_notes[topic] = note.id
            about_me.body = vault.append_to_section(about_me.body, category, f"- [[{topic}]]")
            about_me.updated = now
            vault.write_note_atomic(about_me.path, vault.serialize_note(about_me))
            await index_note_file(memory, about_me.path)

        return (
            f"Created a new note for '{topic}' (id: {note.id}), linked from About Me's "
            f"'{category}' section. Use read_note/append_to_note/update_note_section "
            f"with this id to add details."
        )

    @tool
    async def get_or_create_project(name: str) -> str:
        """Get (or create) a dedicated vault folder for one ongoing project,
        so all the notes/ideas that build up on it over many separate
        conversations live together and can be searched as a unit. Returns
        the project's canonical name — use that exact string with
        save_note's and search_notes's `project` argument afterward.

        Use this for a recurring, evolving body of work (a side project, a
        creative endeavor) the user comes back to repeatedly across
        sessions — not for a single one-off note, and not for a specific
        person/topic that belongs in About Me (use get_or_create_linked_note
        for that instead).

        This always resolves to the same folder for the same project —
        fuzzy-matches close variations of a name used before rather than
        creating a near-duplicate folder for what's really the same
        project. Safe to call even when the project already exists.

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
