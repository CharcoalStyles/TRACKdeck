"""Deterministic basics-form import (vault in tmp_path)."""
import asyncio
from types import SimpleNamespace as NS

import pytest

from agent import profile_import
from agent.tools import notes as notes_mod
from utils import vault

ROUTINE = "Mon: swim at 6\nTue: school pickup at 3\nSun: handover at 5"
PEOPLE = [NS(name=f"Person{i}", relation=r) for i, r in enumerate(
    ["Son", "Friend", "Friend", "Friend", "Counselor", "Ex-Wife", "Neighbour", "Mum", "Friend"])]


def form(**over):
    base = dict(
        name="Test User", birthday="1983-12-02", occupation="Engineer", current_job="Lead at Acme",
        people=PEOPLE, preferences="Likes trying new things", routine=ROUTINE,
        interests="Knitting", values="1. Calm 2. Logic", health_goals="Lose weight",
        important_dates="Birthday: 2 December\nSon's birthday: 5 May",
    )
    base.update(over)
    return NS(**base)


@pytest.fixture(autouse=True)
def sandbox(monkeypatch, tmp_path):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    async def no_index(memory, path):
        return None

    monkeypatch.setattr(notes_mod, "index_note_file", no_index)
    monkeypatch.setattr(profile_import, "index_note_file", no_index)


def run(req):
    return asyncio.run(profile_import.import_basics(NS(), req))


def test_form_sections_formats_and_orders_fields():
    sections = dict(profile_import.form_sections(form()))
    assert sections["Basics"] == (
        "Name: Test User\nBirthday: 2 December 1983\nOccupation: Engineer\nCurrent job: Lead at Acme"
    )
    assert sections["Routine"] == ROUTINE
    assert list(sections)[0] == "Basics"


def test_unparseable_birthday_is_kept_as_typed():
    sections = dict(profile_import.form_sections(form(birthday="the 2nd of Dec")))
    assert "Birthday: the 2nd of Dec" in sections["Basics"]


def test_empty_fields_are_skipped():
    sections = dict(profile_import.form_sections(form(routine=None, values="  ")))
    assert "Routine" not in sections and "Values" not in sections


def test_import_writes_everything_verbatim():
    run(form())
    body = vault.get_or_create_about_me().body
    assert ROUTINE in body
    assert "Son's birthday: 5 May" in body
    assert "Birthday: 2 December 1983" in body
    assert "Location" not in body


def test_each_person_gets_a_relation_only_note_and_one_link():
    result = run(form())
    assert len(result["people"]["created"]) == 9
    about_me = vault.get_or_create_about_me()
    assert len(about_me.linked_notes) == 9
    assert about_me.body.count("[[Person0]] (Son)") == 1
    note = vault.parse_note(vault.find_note_by_id(about_me.linked_notes["Person0"]))
    assert note.body.strip() == "Relation to you: Son"
    assert about_me.body.count("## People") == 1


def test_second_import_changes_nothing():
    run(form())
    before = vault.about_me_path().read_text()
    notes_before = sorted(p.name for p in vault.list_vault_notes())
    result = run(form())
    assert result["sections"] == []
    assert len(result["people"]["exists"]) == 9
    assert vault.about_me_path().read_text() == before
    assert sorted(p.name for p in vault.list_vault_notes()) == notes_before


def test_orphan_person_note_is_adopted_after_about_me_reset():
    run(form())
    old_id = vault.parse_note(vault.vault_root() / "person0.md").id
    vault.about_me_path().unlink()
    result = run(form())
    assert "Person0" in result["people"]["adopted"]
    assert vault.get_or_create_about_me().linked_notes["Person0"] == old_id
    assert len([p for p in vault.list_vault_notes() if p.name.startswith("person0")]) == 1
