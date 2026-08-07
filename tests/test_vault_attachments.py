import pytest

from utils.vault import (
    list_project_attachments,
    list_vault_notes,
    save_project_attachment,
)


def test_save_project_attachment_roundtrips_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    saved_path = save_project_attachment(project_dir, "photo.png", b"fake-image-bytes")

    assert saved_path.read_bytes() == b"fake-image-bytes"
    assert [p.name for p in list_project_attachments(project_dir)] == ["photo.png"]


def test_save_project_attachment_dedupes_name_collision(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    first = save_project_attachment(project_dir, "photo.png", b"one")
    second = save_project_attachment(project_dir, "photo.png", b"two")

    assert first != second
    assert first.read_bytes() == b"one"
    assert second.read_bytes() == b"two"


def test_save_project_attachment_sanitizes_traversal_filename(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    saved_path = save_project_attachment(project_dir, "../../evil.png", b"data")

    attachments_dir = project_dir / "attachments"
    assert saved_path.resolve().is_relative_to(attachments_dir.resolve())


def test_attachments_are_invisible_to_note_listing(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    save_project_attachment(project_dir, "photo.png", b"data")

    assert list_vault_notes() == []
