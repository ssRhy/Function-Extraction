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


def test_batch_outlines_reuses_audited_and_stops_at_valid_count(tmp_path, monkeypatch):
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

        def load_pattern_feedback(self, _snapshot_id):
            return {}

    class FakeGraph:
        def invoke(self, state):
            assert state["knowledge_db"] == str(app.KNOWLEDGE_DB)
            if state["pattern_request"] in {"已用", "失败"}:
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
        "blocked", "blocked", "accepted",
    ]
    assert manifest["results"][0]["pattern_id"] == "PAT_USED"


def test_batch_outlines_does_not_repeat_pattern_in_one_batch(tmp_path, monkeypatch):
    catalog = {"published_patterns": [{
        "pattern_id": "PAT_ONE", "pattern_name": "唯一", "story_support": 1,
        "category_counts": {"03_现代情感": 1},
    }]}
    calls = []

    class FakeStore:
        def __init__(self, _path):
            pass

        def load_pattern_feedback(self, _snapshot_id):
            return {}

    class FakeGraph:
        def invoke(self, state):
            calls.append(state["pattern_request"])
            return {"outline_id": "OUT_ONE", "result_path": "one.json",
                    "validation": {"overall_ok": True}}

    monkeypatch.setattr(app.outline_app, "load_catalog", lambda *_args: catalog)
    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    monkeypatch.setattr(app.outline_app, "_build_graph", lambda: FakeGraph())

    path = app.batch_outlines(
        "snapshot_x", "现代情感", 2, patterns=["唯一", "唯一"], out_dir=tmp_path,
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert calls == ["唯一"]
    assert [item["status"] for item in manifest["results"]] == ["accepted", "skipped"]
    assert "本批次" in manifest["results"][1]["reason"]


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


def test_infer_genre_uses_keywords_and_rejects_ambiguous_requests():
    assert app._infer_genre("悬疑：雨夜追查失踪案") == "01_悬疑惊悚"
    assert app._infer_genre("写一个修仙者守城的故事") == "02_古风仙侠"
    assert app._infer_genre("都市情感中的家庭关系修复") == "03_现代情感"
    assert app._infer_genre("情感类：民国时代银行家和天才画家的相爱故事") == "03_现代情感"
    assert app._infer_genre("末世废土中的求生") == "04_末世科幻"
    assert app._infer_genre("现实家庭中的职场冲突") == "05_现实家庭职场"
    with pytest.raises(ValueError, match="未识别题材"):
        app._infer_genre("写一个人物成长故事")
    with pytest.raises(ValueError, match="多个题材"):
        app._infer_genre("古风与悬疑推理结合")


def test_archive_formal_assets_is_recoverable(tmp_path, monkeypatch):
    data = tmp_path / "data"
    assets = (
        data / "knowledge" / "story_knowledge.db",
        data / "registry",
        data / "bank",
        data / "ontology_snapshots",
        data / "checkpoints",
    )
    assets[0].parent.mkdir(parents=True)
    assets[0].write_text("db", encoding="utf-8")
    for directory in assets[1:]:
        directory.mkdir(parents=True)
        (directory / "marker").write_text("asset", encoding="utf-8")
    monkeypatch.setattr(app, "DATA", data)
    monkeypatch.setattr(app, "FORMAL_ASSETS", assets)

    archive = app._archive_formal_assets()

    assert (archive / "knowledge" / "story_knowledge.db").read_text(encoding="utf-8") == "db"
    assert (archive / "registry" / "marker").exists()
    assert not assets[0].exists()
    assert all(path.is_dir() and not any(path.iterdir()) for path in assets[1:])


def test_bootstrap_forwards_formal_paths_and_promotes_root(tmp_path, monkeypatch):
    source = tmp_path / "story.txt"
    source.write_text("故事", encoding="utf-8")
    second_source = tmp_path / "story-2.txt"
    second_source.write_text("第二个故事", encoding="utf-8")
    output_dir = tmp_path / "run" / "output"
    snapshot = tmp_path / "snapshot"
    captured = {}

    def fake_run_module(_module, arguments):
        captured["arguments"] = arguments
        output_dir.mkdir(parents=True)
        (output_dir / "bank_production.jsonl").write_text("", encoding="utf-8")
        (output_dir / "occurrences_final.jsonl").write_text("", encoding="utf-8")
        snapshot.mkdir()
        return [f"OntologySnapshot → {snapshot}"]

    class FakeStore:
        def __init__(self, path):
            captured["knowledge_db"] = path

        def promote_snapshot(self, snapshot_id):
            captured["promoted"] = snapshot_id
            return {"snapshot_id": snapshot_id}

    import StoryPattern_Agent.app as pattern_app

    monkeypatch.setattr(app, "_run_module", fake_run_module)
    monkeypatch.setattr(app, "_archive_formal_assets", lambda: tmp_path / "archive")
    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    monkeypatch.setattr(pattern_app, "run_pattern_evolve", lambda *_args: {
        "run_id": "PR_TEST", "new_pattern_ids": [],
    })
    monkeypatch.setattr(app, "KNOWLEDGE_DB", tmp_path / "formal.db")
    monkeypatch.setattr(app, "DATA", tmp_path / "data")

    manifest_path = app.run_function(
        "bootstrap", [source, second_source], out_dir=tmp_path / "run",
        namespace="production", reset_formal=True,
    )

    assert "--knowledge-db" in captured["arguments"]
    assert str(tmp_path / "formal.db") in captured["arguments"]
    assert "--snapshot-root" in captured["arguments"]
    assert captured["promoted"] == snapshot.name
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["serving_snapshot_id"] == snapshot.name
    assert manifest["formal_reset_archive"] == str(tmp_path / "archive")


def test_bootstrap_rejects_one_story_before_clearing_working_assets(tmp_path, monkeypatch):
    source = tmp_path / "story.txt"
    source.write_text("故事", encoding="utf-8")
    monkeypatch.setattr(app, "_run_module", lambda *_: pytest.fail("不应启动 FunctionExtract_Agent"))
    monkeypatch.setattr(app, "_archive_formal_assets", lambda: pytest.fail("不应归档正式资产"))

    with pytest.raises(ValueError, match="至少需要 2 个"):
        app.run_function("bootstrap", [source], out_dir=tmp_path / "run")


def test_story_generate_passes_request_and_uses_serving_snapshot(tmp_path, monkeypatch):
    import Pipeline_Agent.app as pipeline_app

    captured = {}

    class FakeStore:
        def __init__(self, path):
            captured["knowledge_db"] = path

        def resolve_snapshot_id(self, snapshot_id):
            return snapshot_id or "SERVING"

    class FakeGraph:
        def invoke(self, state):
            captured["state"] = state
            manifest = tmp_path / "run" / "pipeline_manifest.json"
            manifest.parent.mkdir()
            manifest.write_text("{}", encoding="utf-8")
            return {"manifest_path": str(manifest)}

    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    monkeypatch.setattr(pipeline_app, "_build_graph", lambda: FakeGraph())

    path = app.generate_story(
        "情感类：民国时代银行家和天才画家的相爱故事",
        knowledge_db="formal.db", out_dir=tmp_path / "run",
        planner_mode="dynamic",
    )

    assert path.exists()
    assert captured["state"]["genre"] == "03_现代情感"
    assert captured["state"]["snapshot_id"] == "SERVING"
    assert captured["state"]["user_request"] == "情感类：民国时代银行家和天才画家的相爱故事"
    assert captured["state"]["planner_mode"] == "dynamic"
    assert captured["state"]["knowledge_db"] == "formal.db"


def test_main_dispatches_story_generate_with_request_file(monkeypatch, tmp_path):
    request_file = tmp_path / "request.txt"
    request_file.write_text("末世科幻：写一个废土求生故事", encoding="utf-8")
    calls = []
    monkeypatch.setattr(app, "generate_story", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert app.main(["story", "generate", "--request-file", str(request_file)]) == 0
    assert calls[0][0] == ("末世科幻：写一个废土求生故事",)
    assert calls[0][1] == {
        "snapshot_id": None,
        "knowledge_db": str(app.KNOWLEDGE_DB),
        "out_dir": None,
        "planner_mode": "published",
    }


def test_main_dispatches_dynamic_story_generate(monkeypatch):
    calls = []
    monkeypatch.setattr(app, "generate_story", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert app.main([
        "story", "generate", "--request", "古风仙侠：守城阵师回乡解决水患",
        "--planner-mode", "dynamic",
    ]) == 0
    assert calls[0][1]["planner_mode"] == "dynamic"


def test_story_generate_rejects_two_request_sources(monkeypatch):
    called = []
    monkeypatch.setattr(app, "generate_story", lambda *args, **kwargs: called.append(True))

    assert app.main([
        "story", "generate", "--request", "悬疑故事",
        "--request-file", "request.txt",
    ]) == 1
    assert called == []


def test_evolve_does_not_promote_candidate(tmp_path, monkeypatch):
    source = tmp_path / "story.txt"
    source.write_text("新故事", encoding="utf-8")
    output_dir = tmp_path / "run" / "output"
    snapshot = tmp_path / "candidate"
    captured = {"promote": 0}

    def fake_run_module(_module, arguments):
        output_dir.mkdir(parents=True)
        (output_dir / "bank_story_cli.jsonl").write_text("", encoding="utf-8")
        (output_dir / "occurrences_final.jsonl").write_text("", encoding="utf-8")
        snapshot.mkdir()
        return [f"OntologySnapshot → {snapshot}"]

    class FakeStore:
        def __init__(self, _path):
            pass

        def serving_snapshot_id(self):
            return "BASE"

        def load_snapshot_manifest(self, _snapshot_id):
            return {"namespace": "story_cli"}

        def promote_snapshot(self, _snapshot_id):
            captured["promote"] += 1

    import StoryPattern_Agent.app as pattern_app

    monkeypatch.setattr(app, "_run_module", fake_run_module)
    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    monkeypatch.setattr(pattern_app, "run_pattern_evolve", lambda *_args: {
        "run_id": "PR_TEST", "new_pattern_ids": [],
    })

    manifest_path = app.run_function(
        "evolve", [source], out_dir=tmp_path / "run", namespace="story_cli",
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["base_snapshot_id"] == "BASE"
    assert manifest["snapshot_id"] == snapshot.name
    assert captured["promote"] == 0


def test_evolve_inherits_serving_snapshot_namespace(tmp_path, monkeypatch):
    source = tmp_path / "story.txt"
    source.write_text("新故事", encoding="utf-8")
    output_dir = tmp_path / "run" / "output"
    snapshot = tmp_path / "candidate"
    captured = {}

    def fake_run_module(_module, arguments):
        captured["arguments"] = arguments
        output_dir.mkdir(parents=True)
        (output_dir / "bank_real_coordinator.jsonl").write_text("", encoding="utf-8")
        (output_dir / "occurrences_final.jsonl").write_text("", encoding="utf-8")
        snapshot.mkdir()
        return [f"OntologySnapshot → {snapshot}"]

    class FakeStore:
        def __init__(self, _path):
            pass

        def serving_snapshot_id(self):
            return "BASE"

        def load_snapshot_manifest(self, _snapshot_id):
            return {"namespace": "real_coordinator"}

    import StoryPattern_Agent.app as pattern_app

    monkeypatch.setattr(app, "_run_module", fake_run_module)
    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    monkeypatch.setattr(pattern_app, "run_pattern_evolve", lambda *_args: {
        "run_id": "PR_TEST", "new_pattern_ids": [],
    })

    app.run_function("evolve", [source], out_dir=tmp_path / "run")

    namespace_index = captured["arguments"].index("--namespace")
    assert captured["arguments"][namespace_index + 1] == "real_coordinator"


def test_main_dispatches_public_bootstrap_and_evolve_without_internal_ids(monkeypatch, tmp_path):
    calls = []
    promoted = []
    bootstrap_manifest = tmp_path / "bootstrap" / "function_run.json"
    evolve_manifest = tmp_path / "evolve" / "function_run.json"

    def fake_run_function(*args, **kwargs):
        path = bootstrap_manifest if args[0] == "bootstrap" else evolve_manifest
        app._write_json(path, {"snapshot_id": "candidate"})
        calls.append((args, kwargs))
        return path

    monkeypatch.setattr(app, "run_function", fake_run_function)
    monkeypatch.setattr(
        app.StoryKnowledgeStore, "promote_snapshot",
        lambda *args: promoted.append(args[-1]),
    )

    assert app.main([
        "bootstrap", "--input", "boot-a.txt", "boot-dir", "--reset-formal",
    ]) == 0
    assert app.main([
        "evolve", "--input", "new-a.txt", "new-dir", "--promote",
    ]) == 0
    assert calls[0][0][:2] == ("bootstrap", ["boot-a.txt", "boot-dir"])
    assert calls[0][0][3] == app.PUBLIC_NAMESPACE
    assert calls[0][1]["reset_formal"] is True
    assert calls[1][0][:2] == ("evolve", ["new-a.txt", "new-dir"])
    assert calls[1][0][3] is None
    assert calls[1][1]["batch_size"] is None
    assert promoted == ["candidate"]
