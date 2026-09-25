import utils.task_library_store as task_library_store


def _use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(task_library_store, "DB_PATH", str(tmp_path / "task_library.db"))
    task_library_store.init_db()


def test_create_and_get_round_trips(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    task_library_store.create("t1", "Clean the kitchen", 20, "Chores")
    item = task_library_store.get("t1")

    assert item["label"] == "Clean the kitchen"
    assert item["default_minutes"] == 20
    assert item["group_name"] == "Chores"


def test_list_all_orders_grouped_items_before_ungrouped(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    task_library_store.create("t1", "Tidy the study", 15, None)
    task_library_store.create("t2", "Clean the kitchen", 20, "Chores")

    labels = [item["label"] for item in task_library_store.list_all()]
    assert labels == ["Clean the kitchen", "Tidy the study"]


def test_update_changes_fields(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    task_library_store.create("t1", "Clean the kitchen", 20, "Chores")
    updated = task_library_store.update("t1", "Deep-clean the kitchen", 45, "Chores")

    assert updated["label"] == "Deep-clean the kitchen"
    assert updated["default_minutes"] == 45


def test_delete_removes_item(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    task_library_store.create("t1", "Clean the kitchen", 20, "Chores")
    task_library_store.delete("t1")

    assert task_library_store.get("t1") is None
    assert task_library_store.list_all() == []
