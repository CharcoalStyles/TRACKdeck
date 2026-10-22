"""
agent/profile_import.py
-----------------------
Writes the onboarding basics form into About Me directly, with no LLM in
the loop. The form is already structured (fields, and a list of people with
relations), and handing it to the small tool model as chat text got it
dropped, overwritten and partly invented. Free-text answers are copied
verbatim; each person gets a linked note holding only what the form says
about them (their relation).

Safe to run twice: lines already present under a heading are skipped, and
people who already have a linked note (or an unlinked one left over from an
About Me reset) are reused.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.memory import MemoryStore
from agent.tools.notes import about_me_lock, create_linked_note
from agent.vault_watcher import index_note_file
from utils import vault


def _long_date(raw: str) -> str:
    try:
        d = datetime.strptime(raw.strip(), "%Y-%m-%d")
    except ValueError:
        return raw.strip()
    return f"{d.day} {d:%B %Y}"


def _text(req: Any, field: str) -> str:
    return (getattr(req, field, None) or "").strip()


def form_sections(req: Any) -> list[tuple[str, str]]:
    """Ordered (About Me heading, text) pairs for every filled-in field
    except people (see import_basics) and location/wake/bed time (settings)."""
    basics = [
        ("Name", _text(req, "name")),
        ("Birthday", _long_date(_text(req, "birthday")) if _text(req, "birthday") else ""),
        ("Occupation", _text(req, "occupation")),
        ("Current job", _text(req, "current_job")),
    ]
    sections = [("Basics", "\n".join(f"{k}: {v}" for k, v in basics if v))]
    for heading, field in [
        ("Important Dates", "important_dates"),
        ("Preferences", "preferences"),
        ("Routine", "routine"),
        ("Interests", "interests"),
        ("Values", "values"),
        ("Health & Goals", "health_goals"),
    ]:
        sections.append((heading, _text(req, field)))
    return [(h, t) for h, t in sections if t]


async def import_basics(memory: MemoryStore, req: Any) -> dict:
    written: list[str] = []
    async with about_me_lock:
        note = vault.get_or_create_about_me()
        for heading, text in form_sections(req):
            new_text = vault.drop_present_lines(note.body, heading, text)
            if new_text:
                note.body = vault.append_to_section(note.body, heading, new_text)
                written.append(heading)
        if written:
            note.updated = vault.now_iso()
            vault.write_note_atomic(note.path, vault.serialize_note(note))
            await index_note_file(memory, note.path)

    people: dict[str, list[str]] = {"created": [], "adopted": [], "exists": [], "refused": []}
    for person in getattr(req, "people", None) or []:
        name = (person.name or "").strip()
        if not name:
            continue
        relation = (person.relation or "").strip()
        result = await create_linked_note(
            memory, name, "People",
            content=f"Relation to you: {relation}" if relation else "",
            link_label=relation,
        )
        people[result.status].append(name)
    return {"sections": written, "people": people}
