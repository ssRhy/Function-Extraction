"""统一 StoryCLI 的输入、模板 Bundle 和正文串联测试。"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import StoryCLI.app as app
from FunctionExtract_Agent.app import collect_story_files


def test_prepare_corpus_accepts_files_and_directories(tmp_path):
    source_dir = tmp_path / "source"
    nested = source_dir / "nested"
    nested.mkdir(parents=True)
    first = source_dir / "first.txt"
    second = nested / "second.txt"
    first.write_text("第一篇", encoding="utf-8")
    second.write_text("第二篇", encoding="utf-8")
    target = tmp_path / "corpus"

    manifest_path, count = app._prepare_corpus([first, source_dir], target)

    assert count == 2
    assert len(list(target.glob("*.txt"))) == 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [item["txt_file"] for item in manifest] == [
        "0001_first.txt", "0002_second.txt",
    ]
    assert collect_story_files(str(target), recursive=True) == [
        "0001_first.txt", "0002_second.txt",
    ]


def test_build_template_exports_pattern_and_outline_bundle(tmp_path, monkeypatch):
    function_dir = tmp_path / "function"
    function_dir.mkdir()
    observations = function_dir / "bank_cli.jsonl"
    corpus_manifest = function_dir / "manifest.json"
    output_dir = function_dir / "output"
    output_dir.mkdir()
    observations.write_text("", encoding="utf-8")
    corpus_manifest.write_text("[]", encoding="utf-8")
    function_run = function_dir / "function_run.json"
    app._write_json(function_run, {
        "snapshot_id": "snapshot_x",
        "observations_path": str(observations),
        "corpus_manifest_path": str(corpus_manifest),
        "output_dir": str(output_dir),
    })

    class FakeStore:
        def __init__(self, _path):
            pass

        def load_pattern_catalog(self, snapshot_id):
            assert snapshot_id == "snapshot_x"
            return {"published_patterns": [{
                "pattern_name": "P",
                "story_support": 1,
                "core_function_chain": [],
            }]}

    outline_path = tmp_path / "template" / "outline" / "outline.json"
    app._write_json(outline_path, {"outline": {}})
    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    monkeypatch.setattr(app, "_run_outline", lambda *args: {
        "outline_id": "OUT_TEST",
        "result_path": str(outline_path),
        "pattern_name": "P",
        "genre": "03_现代情感",
        "pattern_selection": None,
    })

    bundle_path = app.build_template(
        function_run, "现代情感", out_dir=tmp_path / "template",
    )

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["pattern_name"] == "P"
    assert bundle["outline_id"] == "OUT_TEST"
    assert "pattern_catalog" not in bundle
    assert bundle["outline_json"] == os.path.join("outline", "outline.json")


def test_write_story_regenerates_outline_only_when_request_is_given(tmp_path, monkeypatch):
    bundle_dir = tmp_path / "bundle"
    catalog_path = bundle_dir / "pattern" / "pattern_catalog.json"
    outline_path = bundle_dir / "outline" / "outline.json"
    app._write_json(catalog_path, {"published_patterns": []})
    app._write_json(outline_path, {"outline": {}})
    bundle_path = bundle_dir / "template_bundle.json"
    app._write_json(bundle_path, {
        "snapshot_id": "snapshot_x",
        "genre": "03_现代情感",
        "pattern_name": "P",
        "outline_id": "OUT_TEMPLATE",
        "pattern_catalog": "pattern/pattern_catalog.json",
        "outline_json": "outline/outline.json",
    })
    generated_outline = tmp_path / "new_outline.json"
    generated_outline.write_text("{}", encoding="utf-8")
    calls = []

    def fake_outline(*args):
        calls.append(args)
        return {"outline_id": "OUT_NEW", "result_path": str(generated_outline)}

    class FakeGraph:
        def invoke(self, state):
            assert state["outline_id"] == "OUT_NEW"
            assert state["knowledge_db"] == str(app.KNOWLEDGE_DB)
            assert state["user_request"] == "改成温暖结局"
            story_path = tmp_path / "story" / "story.json"
            app._write_json(story_path, {})
            story_path.with_suffix(".md").write_text("# 标题\n\n正文", encoding="utf-8")
            return {"result_path": str(story_path)}

    monkeypatch.setattr(app, "_run_outline", fake_outline)
    monkeypatch.setattr(app.story_app, "_build_graph", lambda: FakeGraph())

    manifest_path = app.write_story(bundle_path, "改成温暖结局")

    assert calls and calls[0][3] == "P"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["user_request"] == "改成温暖结局"
    assert manifest["actual_outline_id"] == "OUT_NEW"
    assert manifest["actual_outline_json"] == str(generated_outline.resolve())


def test_batch_outlines_skips_used_and_stops_at_valid_count(tmp_path, monkeypatch):
    catalog = {"published_patterns": [
        {"pattern_id": "PAT_USED", "pattern_name": "已用", "story_support": 5,
         "category_counts": {"03_现代情感": 1}},
        {"pattern_id": "PAT_BLOCKED", "pattern_name": "失败", "story_support": 4,
         "category_counts": {"03_现代情感": 1}},
        {"pattern_id": "PAT_OK", "pattern_name": "成功", "story_support": 3,
         "category_counts": {"03_现代情感": 1}},
    ]}

    class FakeStore:
        def __init__(self, _path):
            pass

        def used_pattern_ids(self):
            return {"PAT_USED"}

        def load_pattern_feedback(self, _snapshot_id):
            return {}

    class FakeGraph:
        def invoke(self, state):
            assert state["knowledge_db"] == str(app.KNOWLEDGE_DB)
            if state["pattern_request"] == "失败":
                return {
                    "outline_id": "OUT_BLOCKED", "result_path": "blocked.json",
                    "validation": {"overall_ok": False},
                }
            assert state["pattern_request"] == "成功"
            return {
                "outline_id": "OUT_OK", "result_path": "ok.json",
                "validation": {"overall_ok": True},
            }

    monkeypatch.setattr(app.outline_app, "load_catalog", lambda *_args: catalog)
    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    monkeypatch.setattr(app.outline_app, "_build_graph", lambda: FakeGraph())

    path = app.batch_outlines(
        "snapshot_x", "现代情感", 1, out_dir=tmp_path,
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["accepted_count"] == 1
    assert [item["status"] for item in manifest["results"]] == [
        "skipped", "blocked", "accepted",
    ]
    assert manifest["results"][0]["pattern_id"] == "PAT_USED"


def test_main_accepts_short_outline_command(monkeypatch):
    calls = []

    def fake_batch(*args):
        calls.append(args)

    monkeypatch.setattr(app, "batch_outlines", fake_batch)

    assert app.main([
        "outline", "--genre", "现代情感", "--count", "3", "--snapshot-id", "snapshot_x",
    ]) == 0
    assert calls == [(
        "snapshot_x",
        "现代情感",
        3,
        None,
        "",
        None,
        str(app.KNOWLEDGE_DB),
    )]
