"""Pipeline Agent 测试：两个 Agent 的自动串联。"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import Pipeline_Agent.app as app
import Pipeline_Agent.best_of as best_of


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
        "user_request": "女主必须在暴雨夜揭开真相",
        "planner_mode": "dynamic",
        "out_dir": str(tmp_path / "run"),
        "outline_id": None,
        "outline_path": None,
        "outline_result": None,
        "story_path": None,
        "manifest_path": "",
    })

    assert calls[0]["genre"] == "03_现代情感"
    assert calls[0]["user_request"] == "女主必须在暴雨夜揭开真相"
    assert calls[0]["planner_mode"] == "dynamic"
    assert calls[1]["outline_id"] == "OUT_TEST"
    assert calls[1]["knowledge_db"] == "knowledge.db"
    assert calls[1]["user_request"] == "女主必须在暴雨夜揭开真相"
    assert result["manifest_path"]
    manifest = json.loads((tmp_path / "run" / "pipeline_manifest.json").read_text(encoding="utf-8"))
    assert manifest["pattern_name"] == "P"
    assert manifest["user_request"] == "女主必须在暴雨夜揭开真相"
    assert manifest["planner_mode"] == "dynamic"
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


def test_pipeline_cli_forwards_request(tmp_path, monkeypatch):
    captured = {}

    class FakeGraph:
        def invoke(self, state):
            captured.update(state)
            return {"manifest_path": str(tmp_path / "manifest.json")}

    monkeypatch.setattr(app, "_build_graph", lambda: FakeGraph())
    monkeypatch.setattr(sys, "argv", [
        "pipeline",
        "--genre", "现代情感",
        "--snapshot-id", "snapshot_x",
        "--request", "结局必须完成复仇",
        "--out-dir", str(tmp_path / "run"),
    ])

    app.main()

    assert captured["user_request"] == "结局必须完成复仇"
    assert captured["planner_mode"] == "published"


def _best_candidate(index, function_name, passed=True):
    return {
        "candidate_index": index,
        "candidate_id": f"DYN_{index}",
        "function_ids": [f"F{index}"],
        "chain": [{"function_id": f"F{index}", "function_name": function_name}],
        "operations": ["EXPLORE"],
        "score": 0.8 - index / 10,
        "validation": {"valid": True},
        "hard_gate": passed,
    }


def test_best_of_selection_direct_and_rejects_without_review(monkeypatch):
    one = _best_candidate(1, "F1", True)
    two = _best_candidate(2, "F2", False)
    assert best_of._select_best_of("要求", [one, two])["winner"] == "DYN_1"

    assert best_of._select_best_of("要求", [two, _best_candidate(3, "F3", False)]) == {
        "mode": "best_of_2",
        "status": "rejected",
        "winner": None,
        "winner_index": None,
        "reason": "两个候选均未通过 Story Validator 硬门禁。",
        "review": None,
    }
    monkeypatch.setattr(best_of, "chat_structured", lambda *_args: pytest.fail("不应评审"))


def test_best_of_two_runs_candidates_and_reviews_once(tmp_path, monkeypatch):
    outline_paths = [tmp_path / "outline1.json", tmp_path / "outline2.json"]
    story_paths = [tmp_path / "story1.json", tmp_path / "story2.json"]
    for path in outline_paths:
        path.write_text("{}", encoding="utf-8")
    validation = {
        "user_request_ok": True,
        "causal_constraints_ok": True,
        "character_consistency_ok": True,
        "ending_ok": True,
        "unsupported_solution_ok": True,
        "overall_ok": True,
        "length_ok": True,
        "function_execution_evidence": [{
            "segment_index": 1, "function_name": "F1", "scene_id": "S1",
            "evidence": "行动造成结果", "status": "PASS",
        }],
    }
    for index, path in enumerate(story_paths, 1):
        path.write_text(json.dumps({
            "story": {"title": f"候选{index}", "scenes": [{"scene_id": "S1", "text": "正文"}]},
            "story_status": "accepted",
            "story_validation": {**validation, "function_execution_evidence": [{
                **validation["function_execution_evidence"][0], "function_name": f"F{index}",
            }]},
            "story_repair_count": 0,
            "length_ok": True,
        }, ensure_ascii=False), encoding="utf-8")

    candidates = [_best_candidate(1, "F1"), _best_candidate(2, "F2")]
    outline_results = iter([
        {
            "outline_id": "OUT_1", "result_path": str(outline_paths[0]), "pattern_name": "DYN_1",
            "pattern_id": None, "validation": {"overall_ok": True},
            "dynamic_candidates": candidates, "dynamic_candidate": candidates[0],
            "seed": {"core_conflict": "冲突"},
        },
        {
            "outline_id": "OUT_2", "result_path": str(outline_paths[1]), "pattern_name": "DYN_2",
            "pattern_id": None, "validation": {"overall_ok": True},
            "dynamic_candidates": candidates, "dynamic_candidate": candidates[1],
            "seed": {"core_conflict": "冲突"},
        },
    ])
    outline_calls = []

    class FakeOutlineGraph:
        def invoke(self, state):
            outline_calls.append(state)
            return next(outline_results)

    story_results = iter([{"result_path": str(path)} for path in story_paths])
    story_calls = []

    class FakeStoryGraph:
        def invoke(self, state):
            story_calls.append(state)
            return next(story_results)

    monkeypatch.setattr(app.outline_app, "normalize_genre", lambda genre: "03_现代情感")
    monkeypatch.setattr(app.outline_app, "_build_graph", lambda: FakeOutlineGraph())
    monkeypatch.setattr(app.story_app, "_build_graph", lambda: FakeStoryGraph())
    reviews = []

    def fake_review(messages, schema, **_kwargs):
        assert schema is best_of.BestOfReview
        assert "用户创作要求" in messages[0]["content"]
        assert "不要重新抽取" in messages[0]["content"]
        assert "json" in messages[0]["content"]
        reviews.append(messages)
        return best_of.BestOfReview(winner=2, reason="候选2的结局和正文更完整")

    monkeypatch.setattr(best_of, "chat_structured", fake_review)
    outcomes = []

    class FakeStore:
        def __init__(self, _path):
            pass

        def record_generation_outcome(self, *args):
            outcomes.append(args)
            return "GO_BEST"

    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    result = app._build_graph().invoke({
        "genre": "现代情感", "snapshot_id": "snapshot_x", "knowledge_db": "knowledge.db",
        "pattern_request": None, "user_request": "要求结局兑现",
        "planner_mode": "dynamic", "best_of": 2, "out_dir": str(tmp_path / "run"),
        "outline_id": None, "outline_path": None, "outline_result": None,
        "outline_results": [], "story_path": None, "candidate_results": [],
        "selection": None, "manifest_path": "",
    })

    assert len(outline_calls) == len(story_calls) == 2
    assert outline_calls[1]["dynamic_candidate"] == candidates[1]
    assert outline_calls[1]["seed"] == {"core_conflict": "冲突"}
    assert outline_calls[1]["dynamic_candidates"] == candidates
    assert [call["outline_id"] for call in story_calls] == ["OUT_1", "OUT_2"]
    assert len(reviews) == 1

    manifest = json.loads((tmp_path / "run" / "pipeline_manifest.json").read_text(encoding="utf-8"))
    assert manifest["generation_mode"] == "best_of_2"
    assert manifest["selection"]["winner"] == "DYN_2"
    assert manifest["selection"]["review"] == {
        "winner": 2, "reason": "候选2的结局和正文更完整",
    }
    assert [item["function_chain"] for item in manifest["candidates"]] == [["F1"], ["F2"]]
    assert all(item["hard_gate"] for item in manifest["candidates"])
    assert manifest["selection_outcome_id"] == "GO_BEST"
    assert outcomes[-1][-1]["generation_stage"] == "best_of_2"
    assert result["manifest_path"]
