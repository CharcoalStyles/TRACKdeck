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


def test_order_hint_round_trips_and_defaults_to_none(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    task_library_store.create("t1", "Shower", 10, None)
    task_library_store.create("t2", "Clean the kitchen", 20, "Chores", "before Shower")
    assert task_library_store.get("t1")["order_hint"] is None
    assert task_library_store.get("t2")["order_hint"] == "before Shower"
    updated = task_library_store.update("t1", "Shower", 10, None, "after Clean the kitchen")
    assert updated["order_hint"] == "after Clean the kitchen"
    assert task_library_store.hints_by_label() == {
        "shower": "after Clean the kitchen",
        "clean the kitchen": "before Shower",
    }


def test_init_db_adds_order_hint_to_an_existing_table(tmp_path, monkeypatch):
    import sqlite3

    path = str(tmp_path / "task_library.db")
    monkeypatch.setattr(task_library_store, "DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE task_library (id TEXT PRIMARY KEY, label TEXT NOT NULL, "
            "default_minutes INTEGER NOT NULL, group_name TEXT, created_at INTEGER NOT NULL)"
        )
        conn.execute("INSERT INTO task_library VALUES ('t1', 'Old row', 15, NULL, 1)")
    task_library_store.init_db()
    task_library_store.init_db()
    assert task_library_store.get("t1")["order_hint"] is None


def test_hints_without_a_database_do_not_create_one(tmp_path, monkeypatch):
    path = tmp_path / "task_library.db"
    monkeypatch.setattr(task_library_store, "DB_PATH", str(path))
    assert task_library_store.hints_by_label() == {}
    assert not path.exists()
    path.touch()  # setup.sh's empty placeholder file
    assert task_library_store.hints_by_label() == {}
