from utils.vault import Note, list_notes_summary, serialize_note, write_note_atomic


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
