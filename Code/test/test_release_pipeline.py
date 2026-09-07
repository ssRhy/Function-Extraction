"""Release Pipeline 的副本、门禁和失败回滚测试。"""

import release_pipeline as app


def test_sqlite_copy_keeps_integrity(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    import sqlite3

    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO items(value) VALUES ('ok')")
    app._copy_sqlite(source, target)

    assert app._check_db(target) == {"integrity_check": "ok", "foreign_key_check": []}
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT value FROM items").fetchone()[0] == "ok"


def test_parent_snapshot_is_validated_and_copied(tmp_path, monkeypatch):
    source_root = tmp_path / "formal-snapshots"
    source = source_root / "parent"
    source.mkdir(parents=True)
    (source / "function_contracts.jsonl").write_text("parent-contract", encoding="utf-8")
    target_root = tmp_path / "work-snapshots"
    calls = []

    def fake_validate(path):
        calls.append(path)
        return {"snapshot_id": "parent"}

    monkeypatch.setattr(app, "validate_snapshot", fake_validate)
    result = app._copy_parent_snapshot(source_root, target_root, "parent")

    assert result["snapshot_id"] == "parent"
    assert (target_root / "parent" / "function_contracts.jsonl").read_text(encoding="utf-8") == "parent-contract"
    assert calls == [str(source), str(target_root / "parent")]


def test_release_keeps_serving_when_story_fails(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    source.write_bytes(b"source")
    run_dir = tmp_path / "run"

    class FakeStore:
        current = "old"

        def __init__(self, _path):
            pass

        def serving_snapshot_id(self):
            return self.current

        def load_snapshot_manifest(self, _snapshot_id):
            return {"namespace": "ns"}

        def load_pattern_run(self, _snapshot_id):
            return {"status": "SUCCESS", "run_id": "PR_child"}

        def load_snapshot_pattern_rows(self, _snapshot_id):
            return [{"status": "published", "pattern_id": "PAT_1"}]

        def load_pattern_catalog(self, _snapshot_id):
            return {"published_patterns": [{"pattern_name": "P"}]}

        def load_pattern_feedback(self, _snapshot_id):
            return {}

        def promote_snapshot(self, snapshot_id):
            self.current = snapshot_id

    class FakeOutlineGraph:
        def invoke(self, _state):
            return {
                "outline_id": "OUT_1",
                "result_path": str(run_dir / "outline.json"),
                "validation": {"overall_ok": True},
            }

    class FailingStoryGraph:
        def invoke(self, _state):
            raise RuntimeError("story failed")

    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    monkeypatch.setattr(app, "_copy_sqlite", lambda source, target: target.write_bytes(source.read_bytes()))
    monkeypatch.setattr(app, "_check_db", lambda _path: {"integrity_check": "ok", "foreign_key_check": []})
    monkeypatch.setattr(app, "_stage_inputs", lambda *_args: ["story.txt"])
    monkeypatch.setattr(app, "_copy_parent_snapshot", lambda *_args: {"snapshot_id": "old"})
    monkeypatch.setattr(app, "validate_snapshot", lambda _path: {"parent_snapshot_id": "old"})
    monkeypatch.setattr(app.outline_app, "normalize_genre", lambda genre: "03_现代情感")
    monkeypatch.setattr(app.outline_app, "available_patterns", lambda *_args: [{"pattern_name": "P"}])
    monkeypatch.setattr(app.outline_app, "resolve_snapshot_id", lambda *_args: "child")
    monkeypatch.setattr(app.outline_app, "_build_graph", lambda: FakeOutlineGraph())
    monkeypatch.setattr(app.story_app, "_build_graph", lambda: FailingStoryGraph())
    monkeypatch.setattr(
        app,
        "run_coordinator",
        lambda **_kwargs: {
            "status": "SUCCESS",
            "snapshot_id": "child",
            "function_result": {"status": "PASS", "run_id": "FR_child", "snapshot_id": "child"},
            "pattern_result": {"status": "SUCCESS", "run_id": "PR_child"},
        },
    )

    report = app.run_release(
        [str(source)], "现代情感", "完成一个克制的家庭和解故事",
        source_db=source, source_registry_db=tmp_path / "missing-registry.db", out_dir=run_dir,
    )

    assert report["status"] == "FAILED"
    assert report["serving_before"] == "old"
    assert report["serving_after"] == "old"


def test_snapshot_regression_rejects_old_story_cascade():
    class FakeStore:
        def load_pattern_sequences(self, snapshot_id):
            return {f"old_{index}": {} for index in range(10)} if snapshot_id == "parent" else {}

        def load_occurrences(self, snapshot_id):
            return ([{"status": "MATCHED"}] * 10) if snapshot_id == "parent" else [{"status": "UNCERTAIN"}] * 10

        def load_snapshot_pattern_rows(self, snapshot_id):
            count = 7 if snapshot_id == "parent" else 1
            return [{"status": "published"}] * count

        def load_functions(self, _snapshot_id):
            return [{
                "function_id": "F_1", "function_name": "F", "definition": "same",
                "status": "provisional", "hard_negatives": [],
                "realization_patterns": [], "confusable_functions": [],
            }]

    result = app._snapshot_regression(
        FakeStore(), "parent", "child",
        {"story_delta": {"changed": [f"old_{index}" for index in range(9)]}},
        {"new_story"},
    )

    assert result["passed"] is False
    assert {item["code"] for item in result["reasons"]} == {
        "OLD_STORY_SEQUENCE_REGRESSION",
        "ASSIGNMENT_COVERAGE_REGRESSION",
        "PUBLISHED_PATTERN_REGRESSION",
    }
