from utils.vault import Note, list_notes_summary, serialize_note, write_note_atomic

RAW_NOTE_WITH_UNQUOTED_DATE = """---
id: manual
title: Manually Edited
created: 2026-01-01T00:00:00Z
updated: 2026-01-03T00:00:00Z
tags: []
aliases: []
source: agent
---

Edited directly in Obsidian, so 'updated' above is an unquoted YAML
timestamp rather than the quoted string our own serialize_note writes.
"""


def _write(vault_root, name, **overrides):
    note = Note(
        id=name,
        title=overrides.pop("title", name),
        created="2026-01-01T00:00:00Z",
        updated=overrides.pop("updated", "2026-01-01T00:00:00Z"),
        tags=overrides.pop("tags", []),
        body=overrides.pop("body", "Some content."),
    )
    write_note_atomic(vault_root / f"{name}.md", serialize_note(note))


def test_list_notes_summary_sorted_most_recent_first(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _write(tmp_path, "older", updated="2026-01-01T00:00:00Z")
    _write(tmp_path, "newer", updated="2026-01-02T00:00:00Z")

    summary = list_notes_summary()

    assert [n["id"] for n in summary] == ["newer", "older"]


def test_list_notes_summary_handles_unquoted_date_from_manual_edit(tmp_path, monkeypatch):
    """A note edited directly in Obsidian can have an unquoted date in its
    frontmatter, which yaml.safe_load parses as a real datetime object
    instead of a str — mixed with our own (always-quoted, always-str)
    notes, that used to blow up list_notes_summary's sort with
    TypeError: '<' not supported between instances of 'datetime.datetime'
    and 'str'."""
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _write(tmp_path, "agent-note", updated="2026-01-02T00:00:00Z")
    (tmp_path / "manual.md").write_text(RAW_NOTE_WITH_UNQUOTED_DATE, encoding="utf-8")

    summary = list_notes_summary()

    assert [n["id"] for n in summary] == ["manual", "agent-note"]
    assert isinstance(summary[0]["updated"], str)


def test_list_notes_summary_excludes_inbox_and_labels_project(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _write(tmp_path, "root-note")
    (tmp_path / "Inbox").mkdir()
    (tmp_path / "Inbox" / "unprocessed.md").write_text("# scratch\n")
    project_dir = tmp_path / "some-project"
    project_dir.mkdir()
    _write(project_dir, "project-note")

    summary = {n["id"]: n for n in list_notes_summary()}

    assert "unprocessed" not in summary
    assert summary["root-note"]["project"] is None
    assert summary["project-note"]["project"] == "some-project"
