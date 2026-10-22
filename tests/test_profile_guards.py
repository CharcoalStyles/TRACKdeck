"""remember_about_me / get_or_create_linked_note guard rails (vault in tmp_path)."""
import asyncio
from types import SimpleNamespace

import pytest

from agent.tools import notes as notes_mod
from utils import vault


@pytest.fixture
def tools(monkeypatch, tmp_path):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    async def no_index(memory, path):
        return None

    monkeypatch.setattr(notes_mod, "index_note_file", no_index)
    t = {x.name: x for x in notes_mod.make_note_tools(SimpleNamespace())}

    def call(name, **args):
        return asyncio.run(t[name].ainvoke(args))

    return call


def about_body():
    return vault.get_or_create_about_me().body


def test_replace_on_people_is_refused_and_keeps_entries(tools):
    tools("remember_about_me", section="People", content="- Alice (friend)")
    out = tools("remember_about_me", section="People", content="- Bob", mode="replace")
    assert out.startswith("Refused")
    assert "Alice" in about_body() and "Bob" not in about_body()


def test_replace_on_values_is_allowed_and_reports_counts(tools):
    tools("remember_about_me", section="Values", content="1. Calm\n2. Logic")
    out = tools("remember_about_me", section="Values", content="1. Logic", mode="replace")
    assert "was 2 lines, now 1" in out
    assert "Calm" not in about_body()


def test_near_miss_heading_snaps_to_existing(tools):
    out = tools("remember_about_me", section="Importance Dates", content="Birthday: 2 December")
    assert "'Important Dates'" in out
    assert "## Importance Dates" not in about_body()
    assert "Birthday: 2 December" in about_body()


def test_duplicate_append_is_skipped(tools):
    tools("remember_about_me", section="Preferences", content="Likes tea")
    out = tools("remember_about_me", section="Preferences", content="likes tea")
    assert out.startswith("Already recorded")
    assert about_body().lower().count("likes tea") == 1


def test_append_reports_line_count(tools):
    tools("remember_about_me", section="Preferences", content="Likes tea")
    out = tools("remember_about_me", section="Preferences", content="Dislikes mushrooms")
    assert "now 2 lines" in out


def test_linked_person_name_is_refused_as_a_section(tools):
    msg = tools("get_or_create_linked_note", topic="Finnian", category="People")
    note_id = msg.split("id: ")[1].split(")")[0]
    out = tools("remember_about_me", section="Finnian", content="Likes games")
    assert note_id in out and "append_to_note" in out
    assert "## Finnian" not in about_body()


def test_profile_section_names_are_refused_as_linked_notes(tools):
    for topic in ("Interests", "Current Projects", "Routine"):
        out = tools("get_or_create_linked_note", topic=topic, category="People")
        assert "remember_about_me" in out
    assert "[[Interests]]" not in about_body()


def test_linked_note_content_is_saved_in_one_call(tools):
    out = tools("get_or_create_linked_note", topic="Finnian", category="People", content="Relation to you: Son")
    note_id = out.split("id: ")[1].split(")")[0]
    note = vault.parse_note(vault.find_note_by_id(note_id))
    assert note.body.strip() == "Relation to you: Son"
    assert "- [[Finnian]]" in about_body()


def test_second_create_for_same_topic_points_at_existing(tools):
    tools("get_or_create_linked_note", topic="Finnian", category="People")
    out = tools("get_or_create_linked_note", topic="finnian", category="People")
    assert "already has a note" in out
    assert about_body().count("[[Finnian]]") == 1


def test_onboarding_cannot_complete_itself():
    from agent import graph as graph_mod

    assert "mark_onboarding_complete" not in graph_mod.MODE_TOOL_NAMES["onboarding"]
