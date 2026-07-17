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
"""
from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

from agent.memory import MemoryStore
from agent.vault_watcher import index_note_file
from utils import vault


def make_note_tools(memory: MemoryStore):

    @tool
    async def save_note(title: str, content: str, tags: Optional[list[str]] = None) -> str:
        """Create a brand new note in the vault. Use this when the user wants
        to jot something down or remember something new. If it might relate
        to an existing note, search_notes first — prefer append_to_note or
        update_note_section over creating a near-duplicate note.

        Args:
            title: A short, specific title for the note.
            content: The body of the note.
            tags: Optional list of lowercase category tags.
        """
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
        path = vault.unique_note_path(title)
        note.path = path
        vault.write_note_atomic(path, vault.serialize_note(note))
        await index_note_file(memory, path)
        return f"Note saved: '{title}' (id: {note.id})."

    @tool
    def search_notes(query: str) -> str:
        """Search saved notes for information. Returns short excerpts with
        each note's id — use read_note with that id if you need the full
        note before editing it.

        Args:
            query: What to search for in past notes.
        """
        results = memory.search_notes(query, n_results=5)
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

    return save_note, search_notes, read_note, append_to_note, update_note_section
