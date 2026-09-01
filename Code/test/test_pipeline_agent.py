"""Pipeline Agent 测试：两个 Agent 的自动串联。"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import Pipeline_Agent.app as app


def test_pipeline_connects_outline_story_and_export(tmp_path, monkeypatch):
    outline_path = tmp_path / "outline.json"
    outline_path.write_text("{}", encoding="utf-8")
    story_path = tmp_path / "story.json"
    story_path.write_text("{}", encoding="utf-8")
    story_path.with_suffix(".md").write_text("# 故事\n", encoding="utf-8")
    calls = []

    class FakeGraph:
        def __init__(self, result):
            self.result = result

        def invoke(self, state):
            calls.append(state)
            return self.result

    graphs = iter([
        FakeGraph({
            "outline_id": "OUT_TEST",
            "result_path": str(outline_path),
            "pattern_name": "P",
            "validation": {"overall_ok": True},
        }),
        FakeGraph({"result_path": str(story_path)}),
    ])
    monkeypatch.setattr(app.outline_app, "normalize_genre", lambda genre: "03_现代情感")
    monkeypatch.setattr(app.outline_app, "_build_graph", lambda: next(graphs))
    monkeypatch.setattr(app.story_app, "_build_graph", lambda: next(graphs))

    result = app._build_graph().invoke({
        "genre": "现代情感",
        "snapshot_id": "snapshot_x",
        "knowledge_db": "knowledge.db",
        "pattern_request": None,
        "out_dir": str(tmp_path / "run"),
        "outline_id": None,
        "outline_path": None,
        "outline_result": None,
        "story_path": None,
        "manifest_path": "",
    })

    assert calls[0]["genre"] == "03_现代情感"
    assert calls[1]["outline_id"] == "OUT_TEST"
    assert calls[1]["knowledge_db"] == "knowledge.db"
    assert result["manifest_path"]
    manifest = json.loads((tmp_path / "run" / "pipeline_manifest.json").read_text(encoding="utf-8"))
    assert manifest["pattern_name"] == "P"
    assert manifest["outline_id"] == "OUT_TEST"
    assert manifest["story_markdown"] == os.path.abspath(story_path.with_suffix(".md"))


def test_pipeline_stops_when_outline_validation_fails(tmp_path, monkeypatch):
    outline_path = tmp_path / "outline.json"
    outline_path.write_text("{}", encoding="utf-8")

    class FakeGraph:
        def invoke(self, _state):
            return {
                "result_path": str(outline_path),
                "pattern_name": "P",
                "validation": {"overall_ok": False},
            }

    monkeypatch.setattr(app.outline_app, "normalize_genre", lambda genre: "03_现代情感")
    monkeypatch.setattr(app.outline_app, "_build_graph", lambda: FakeGraph())
    with pytest.raises(ValueError, match="正文未启动"):
        app.generate_outline_node({
            "genre": "现代情感",
            "snapshot_id": "snapshot_x",
            "knowledge_db": "knowledge.db",
            "pattern_request": None,
            "out_dir": str(tmp_path / "run"),
        })
