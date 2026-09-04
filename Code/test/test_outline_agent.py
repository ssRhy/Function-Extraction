"""Outline Agent 测试：题材规范化、planner 选链、顺序对齐、rule_check、图端到端。"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import Outline_Agent.app as app
import Outline_Agent.state as state


def _pattern(name, support, categories, functions, ending_spec=None):
    pattern = {
        "pattern_id": f"PAT_{name}",
        "pattern_name": name,
        "story_support": support,
        "category_counts": categories,
        "core_function_chain": [
            {"function_name": fn, "definition": f"d_{fn}"} for fn in functions
        ],
    }
    if ending_spec is not None:
        pattern["ending_spec"] = ending_spec
    return pattern


def test_normalize_genre():
    assert app.normalize_genre("悬疑惊悚") == "01_悬疑惊悚"
    assert app.normalize_genre("01_悬疑惊悚") == "01_悬疑惊悚"
    try:
        app.normalize_genre("武侠")
    except ValueError:
        pass
    else:
        raise AssertionError("未知题材应抛 ValueError")


def test_planner_genre_match():
    catalog = {"published_patterns": [
        _pattern("A", 2, {"01_悬疑惊悚": 1}, ["F1", "F2"]),
        _pattern("C", 5, {"01_悬疑惊悚": 1}, ["F5", "F6"]),
        _pattern("B", 3, {"02_古风仙侠": 1}, ["F3", "F4"]),
    ]}
    pattern, chain = app.planner(catalog, "01_悬疑惊悚")
    assert pattern["pattern_name"] == "C"
    assert [step["function_name"] for step in chain] == ["F5", "F6"]
    assert chain[0]["preconditions"] == []


def test_planner_fallback():
    catalog = {"published_patterns": [
        _pattern("A", 2, {"01_悬疑惊悚": 1}, ["F1", "F2"]),
        _pattern("B", 9, {"02_古风仙侠": 1}, ["F3", "F4"]),
    ]}
    pattern, _ = app.planner(catalog, "03_现代情感")
    assert pattern["pattern_name"] == "B"


def test_planner_tie_break():
    catalog = {"published_patterns": [
        _pattern("BBB", 4, {"01_悬疑惊悚": 1}, ["F1"]),
        _pattern("AAA", 4, {"01_悬疑惊悚": 1}, ["F2"]),
    ]}
    pattern, _ = app.planner(catalog, "01_悬疑惊悚")
    assert pattern["pattern_name"] == "AAA"


def test_candidate_patterns_sorted():
    catalog = {"published_patterns": [
        _pattern("B", 2, {"01_悬疑惊悚": 1}, ["F1"]),
        _pattern("A", 5, {"01_悬疑惊悚": 1}, ["F2"]),
        _pattern("C", 5, {"01_悬疑惊悚": 1}, ["F3"]),
    ]}
    names = [p["pattern_name"] for p in app.candidate_patterns(catalog, "01_悬疑惊悚")]
    assert names == ["A", "C", "B"]


def test_planner_explicit_pattern():
    catalog = {"published_patterns": [
        _pattern("高支持", 9, {"01_悬疑惊悚": 1}, ["F1"]),
        _pattern("低支持", 2, {"01_悬疑惊悚": 1}, ["F2"]),
    ]}
    pattern, chain = app.planner(catalog, "01_悬疑惊悚", pattern_name="低支持")
    assert pattern["pattern_name"] == "低支持"
    assert [step["function_name"] for step in chain] == ["F2"]


def test_planner_explicit_pattern_missing():
    catalog = {"published_patterns": [_pattern("A", 1, {"01_悬疑惊悚": 1}, ["F1"])]}
    try:
        app.planner(catalog, "01_悬疑惊悚", pattern_name="不存在")
    except ValueError:
        pass
    else:
        raise AssertionError("缺失 pattern 应抛 ValueError")


def test_build_function_transitions_collapses_repeated_functions():
    occurrences = [
        {"story_id": "s1", "occurrence_id": "s1-1", "status": "MATCHED", "function_name": "A", "observation_order": 1},
        {"story_id": "s1", "occurrence_id": "s1-2", "status": "MATCHED", "function_name": "A", "observation_order": 2},
        {"story_id": "s1", "occurrence_id": "s1-3", "status": "MATCHED", "function_name": "B", "observation_order": 3},
        {"story_id": "s2", "occurrence_id": "s2-1", "status": "MATCHED", "function_name": "A", "observation_order": 1},
        {"story_id": "s2", "occurrence_id": "s2-2", "status": "MATCHED", "function_name": "B", "observation_order": 2},
    ]
    assert app.build_function_transitions(occurrences)["A"] == [{
        "from": "A", "to": "B", "count": 2, "support_stories": 2,
    }]


def test_planner_attaches_reference_transitions_and_instance_cases():
    catalog = {"published_patterns": [_pattern("P", 2, {"01_悬疑惊悚": 1}, ["A"])]}
    references = {
        "transitions": {"A": [{"from": "A", "to": "B", "count": 2, "support_stories": 2}]},
        "instance_cases": {"A": [{"occurrence_id": "o1", "surface_form": "公开对峙"}]},
    }
    _, chain = app.planner(catalog, "01_悬疑惊悚", references=references)
    assert chain[0]["reference_transitions"][0]["to"] == "B"
    assert chain[0]["reference_instance_cases"][0]["occurrence_id"] == "o1"


def test_load_planner_references_filters_selected_motifs_and_projects_occurrences(monkeypatch):
    class FakeStore:
        def __init__(self, _path):
            pass

        def load_functions(self, _snapshot_id):
            return [{"function_id": "F1", "function_name": "A", "supporting_obs_ids": ["o1"]}]

        def load_occurrences(self, _snapshot_id):
            return [{
                "occurrence_id": "o1", "story_id": "s1", "status": "MATCHED",
                "function_name": "A", "observation_order": 1,
                "surface_form": "公开对峙", "event": "A行动",
                "before_state": "受威胁", "after_state": "暂时安全",
            }]

        def load_motif_evidence(self, _snapshot_id):
            return [{
                "motif_id": "MC_KEEP", "function_ids": ["F1"],
                "function_names": ["A"], "length": 3,
                "evidence": {"story_id": "s1", "occurrence_ids": ["o1"]},
            }, {
                "motif_id": "MC_DROP", "function_ids": ["F1"],
                "function_names": ["A"], "length": 3, "evidence": {},
            }]

    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    pattern = _pattern("P", 2, {"01_悬疑惊悚": 1}, ["A"])
    pattern["member_motif_ids"] = ["MC_KEEP"]
    references = app.load_planner_references(
        "snapshot_x", pattern, [{"function_id": "F1", "function_name": "A"}], "knowledge.db",
    )
    assert [item["motif_id"] for item in references["motifs"]] == ["MC_KEEP"]
    assert references["instance_cases"]["A"][0]["surface_form"] == "公开对峙"
    assert references["transitions"] == {}


def test_planner_node_skips_used_pattern(monkeypatch):
    catalog = {"published_patterns": [
        _pattern("已用", 2, {"01_悬疑惊悚": 1}, ["F1"]),
        _pattern("可用", 1, {"01_悬疑惊悚": 1}, ["F2"]),
    ]}

    class FakeStore:
        def __init__(self, _path):
            pass

        def used_pattern_ids(self):
            return {"PAT_已用"}

        def claim_pattern(self, snapshot_id, pattern_id):
            assert snapshot_id == "snapshot_x"
            assert pattern_id == "PAT_可用"

    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    monkeypatch.setattr(app, "load_catalog", lambda *_args: catalog)
    monkeypatch.setattr(app, "load_contracts", lambda *_args: {})
    monkeypatch.setattr(app, "load_planner_references", lambda *_args: {
        "motifs": [], "transitions": {}, "instance_cases": {},
    })

    result = app.planner_node({
        "snapshot_id": "snapshot_x", "knowledge_db": "knowledge.db",
        "genre": "01_悬疑惊悚", "pattern_request": None,
    })
    assert result["pattern_id"] == "PAT_可用"


def test_planner_node_rejects_explicitly_used_pattern(monkeypatch):
    catalog = {"published_patterns": [
        _pattern("已用", 2, {"01_悬疑惊悚": 1}, ["F1"]),
    ]}

    class FakeStore:
        def __init__(self, _path):
            pass

        def used_pattern_ids(self):
            return {"PAT_已用"}

    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    monkeypatch.setattr(app, "load_catalog", lambda *_args: catalog)
    monkeypatch.setattr(app, "load_planner_references", lambda *_args: {
        "motifs": [], "transitions": {}, "instance_cases": {},
    })
    with pytest.raises(ValueError, match="Pattern 已使用"):
        app.planner_node({
            "snapshot_id": "snapshot_x", "knowledge_db": "knowledge.db",
            "genre": "01_悬疑惊悚", "pattern_request": "已用",
        })


def test_annotate_occurrences():
    chain = [
        {"function_name": "A"},
        {"function_name": "B"},
        {"function_name": "A"},
    ]
    annotated = app.annotate_occurrences(chain)
    assert annotated[0]["occurrence_index"] == 1 and annotated[0]["occurrence_total"] == 2
    assert annotated[1]["occurrence_index"] == 1 and annotated[1]["occurrence_total"] == 1
    assert annotated[2]["occurrence_index"] == 2 and annotated[2]["occurrence_total"] == 2


def test_align():
    chain = [
        {"segment_index": 1, "function_name": "A"},
        {"segment_index": 2, "function_name": "B"},
        {"segment_index": 3, "function_name": "A"},
    ]
    items = [
        {"segment_index": 3, "function_name": "A", "value": "A2"},
        {"segment_index": 1, "function_name": "A", "value": "A1"},
        {"segment_index": 2, "function_name": "B", "value": "B1"},
    ]
    aligned = app._align(chain, items)
    assert [item["function_name"] for item in aligned] == ["A", "B", "A"]
    assert [item["value"] for item in aligned] == ["A1", "B1", "A2"]


def test_rule_check():
    chain = [{"function_name": "A"}, {"function_name": "ACTIVE_COUNTERATTACK"}]
    ending = {
        "resolution_actions": ["解决"],
        "conflict_resolution": "冲突解决",
        "final_state": "稳定",
    }
    ok = {
        "segments": [{"function_name": "A", "beats": ["x"]}, {"function_name": "ACTIVE_COUNTERATTACK", "beats": ["y"]}],
        "ending": ending,
    }
    bad = {
        "segments": [{"function_name": "ACTIVE_COUNTERATTACK", "beats": ["y"]}, {"function_name": "A", "beats": ["x"]}],
        "ending": ending,
    }
    assert app.rule_check(chain, ok) == []
    assert len(app.rule_check(chain, bad)) == 1
    dup = {"segments": [
        {"function_name": "A", "beats": ["x"]},
        {"function_name": "A", "beats": ["x"]},
    ]}
    dup_chain = [{"function_name": "A"}, {"function_name": "A"}]
    assert any("重复 Function 未递进" in issue for issue in app.rule_check(dup_chain, dup))


def test_rule_check_requires_pattern_ending():
    chain = [{"function_name": "A"}]
    ending_spec = {
        "resolves": "核心冲突",
        "must_show": ["解决动作"],
        "final_state": "稳定终态",
    }
    missing = {"segments": [{"function_name": "A", "beats": ["x"]}]}
    valid = {
        "segments": [{"function_name": "A", "beats": ["x"]}],
        "ending": {
            "resolution_actions": ["解决动作"],
            "conflict_resolution": "核心冲突已解决",
            "final_state": "稳定终态",
        },
    }
    assert any("结局收束" in issue for issue in app.rule_check(chain, missing, ending_spec))
    assert app.rule_check(chain, valid, ending_spec) == []


def test_narrative_payoff_must_point_forward_or_ending():
    chain = [
        {"segment_index": 1, "function_name": "A"},
        {"segment_index": 2, "function_name": "B"},
    ]
    valid = {"steps": [
        {"segment_index": 1, "setup_payoffs": [
            {"payoff_segment_index": 2},
            {"payoff_segment_index": None},
        ]},
        {"segment_index": 2, "setup_payoffs": []},
    ]}
    assert app.narrative_plan_issues(chain, valid) == []
    valid["steps"][0]["setup_payoffs"][0]["payoff_segment_index"] = 1
    assert any("后续段或 ending" in issue for issue in app.narrative_plan_issues(chain, valid))
    valid["steps"][0]["setup_payoffs"][0]["payoff_segment_index"] = 3
    assert any("后续段或 ending" in issue for issue in app.narrative_plan_issues(chain, valid))


def test_scaffold_retries_invalid_payoff_once(monkeypatch):
    chain = [
        {"segment_index": 1, "function_name": "A", "definition": "", "preconditions": [],
         "role_slots": [], "contract": {}, "occurrence_index": 1, "occurrence_total": 1},
        {"segment_index": 2, "function_name": "B", "definition": "", "preconditions": [],
         "role_slots": [], "contract": {}, "occurrence_index": 1, "occurrence_total": 1},
    ]
    responses = iter([
        app.NarrativePlan(steps=[
            state.NarrativeStep(
                segment_index=1, function_name="A", genre_realization="a",
                setup_payoffs=[state.SetupPayoff(content="线索", payoff_segment_index=1, payoff="兑现")],
            ),
            state.NarrativeStep(segment_index=2, function_name="B", genre_realization="b"),
        ]),
        app.NarrativePlan(steps=[
            state.NarrativeStep(
                segment_index=1, function_name="A", genre_realization="a",
                setup_payoffs=[state.SetupPayoff(content="线索", payoff_segment_index=2, payoff="兑现")],
            ),
            state.NarrativeStep(segment_index=2, function_name="B", genre_realization="b"),
        ]),
    ])

    def fake_chat(_messages, output_schema, **_kwargs):
        assert output_schema is app.NarrativePlan
        return next(responses)

    monkeypatch.setattr(app, "chat_structured", fake_chat)
    result = app.scaffold_node({
        "snapshot_id": "snapshot_x", "knowledge_db": "knowledge.db",
        "chain": chain, "seed": {}, "mechanism": {}, "ending_spec": None,
    })
    assert result["narrative"]["steps"][0]["setup_payoffs"][0]["payoff_segment_index"] == 2


def test_prompts_limit_relationship_state_to_function_evidence():
    assert "题材标签" in app.SEED_PROMPT
    assert "关系类型" in app.SEED_PROMPT
    assert "状态上界" in app.REALIZE_PROMPT
    assert "overall_ok 必须为 false" in app.VALIDATE_PROMPT


def test_narrative_prompt_does_not_claim_formal_auxiliary_analysis():
    assert "叙事展开" in app.NARRATIVE_PROMPT
    assert "genre_realization" in app.NARRATIVE_PROMPT
    assert "同化与辅助要素" not in app.NARRATIVE_PROMPT
    assert "三重化" not in app.NARRATIVE_PROMPT


def test_graph_end_to_end(tmp_path, monkeypatch):
    functions = ("A", "B", "ACTIVE_COUNTERATTACK")
    ending_spec = {
        "resolves": "核心冲突",
        "must_show": ["明确解决动作"],
        "final_state": "主角恢复稳定",
    }
    catalog = {"published_patterns": [
        _pattern("P", 1, {"01_悬疑惊悚": 1}, functions, ending_spec)
    ]}
    monkeypatch.setattr(app, "load_catalog", lambda *_args: catalog)
    monkeypatch.setattr(app, "load_contracts", lambda *_args: {})
    monkeypatch.setattr(app, "load_planner_references", lambda *_args: {
        "motifs": [], "transitions": {}, "instance_cases": {},
    })

    def fake_chat(messages, output_schema, **kwargs):
        if output_schema is app.StorySeed:
            return app.StorySeed(
                genre="悬疑惊悚", world_setting="w",
                characters=[state.SeedCharacter(
                    id="P1", label="主角", role="hero", goal="g",
                    motivation="m", relationships={},
                )],
                core_conflict="c", ending_direction="e",
            )
        if output_schema is app.MechanismPlan:
            payload = json.loads(messages[-1]["content"])
            assert payload["reference_motifs"] == []
            return app.MechanismPlan(steps=[
                state.MechanismStep(segment_index=index, function_name=name, role_bindings={}, who_does_what="",
                                  why="", state_change="", character_state_changes={}, connects_to_next="")
                for index, name in reversed(list(enumerate(functions, 1)))  # 故意逆序，靠 _align 修正
            ])
        if output_schema is app.NarrativePlan:
            payload = json.loads(messages[-1]["content"])
            assert payload["reference_motifs"] == []
            return app.NarrativePlan(steps=[
                state.NarrativeStep(
                    segment_index=index,
                    function_name=name,
                    genre_realization=f"题材化-{index}",
                    connective_event="进入下一步" if index < len(functions) else "进入结局",
                    setup_payoffs=[state.SetupPayoff(
                        content="提前线索", payoff_segment_index=None, payoff="结局使用",
                    )] if index == 1 else [],
                )
                for index, name in reversed(list(enumerate(functions, 1)))
            ])
        if output_schema is app.OutlineRealization:
            payload = json.loads(messages[-1]["content"])
            assert payload["narrative_plan"]["steps"][0]["genre_realization"] == "题材化-1"
            return app.OutlineRealization(
                segments=[state.OutlineSegment(segment_index=index, function_name=name, beats=["x"])
                          for index, name in reversed(list(enumerate(functions, 1)))],
                final_ledger=["l"],
                ending=state.EndingRealization(
                    resolution_actions=["明确解决动作"],
                    conflict_resolution="核心冲突已解决",
                    final_state="主角恢复稳定",
                ),
            )
        if output_schema is app.OutlineValidation:
            payload = json.loads(messages[-1]["content"])
            assert payload["mechanism_plan"]["steps"][0]["function_name"] == "A"
            assert payload["narrative_plan"]["steps"][0]["function_name"] == "A"
            return app.OutlineValidation(
                segment_checks=[state.SegmentCheck(segment_index=index, function_name=name,
                                                   recoverable=True, issue="")
                                for index, name in enumerate(functions, 1)],
                overall_ok=True, issues=[],
            )
        raise AssertionError(output_schema)

    monkeypatch.setattr(app, "chat_structured", fake_chat)
    class FakeStore:
        def __init__(self, _path):
            pass

        def used_pattern_ids(self):
            return set()

        def claim_pattern(self, snapshot_id, pattern_id):
            assert snapshot_id == "x"
            assert pattern_id == "PAT_P"

        def record_outline(self, document, markdown):
            assert document["pattern_name"] == "P"
            assert markdown.startswith("# 大纲：P")
            return "OUT_TEST"

    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    result = app._build_graph().invoke({
        "snapshot_id": "x", "knowledge_db": "knowledge.db",
        "genre": "01_悬疑惊悚", "out_dir": str(tmp_path),
        "pattern_request": None, "user_request": None, "pattern_id": None,
        "pattern_name": "", "chain": [], "seed": None, "mechanism": None,
        "narrative": None, "outline": None, "validation": None,
        "outline_id": "", "result_path": "",
    })
    assert [step["function_name"] for step in result["chain"]] == list(functions)
    assert [step["function_name"] for step in result["mechanism"]["steps"]] == list(functions)
    assert [step["function_name"] for step in result["narrative"]["steps"]] == list(functions)
    assert [segment["function_name"] for segment in result["outline"]["segments"]] == list(functions)
    assert result["ending_spec"] == ending_spec
    assert result["outline"]["ending"]["final_state"] == "主角恢复稳定"
    assert result["validation"]["rule_issues"] == []
    assert result["outline_id"] == "OUT_TEST"
    exported = json.loads(open(result["result_path"], encoding="utf-8").read())
    assert exported["outline_id"] == "OUT_TEST"
    assert exported["narrative_plan"]["steps"][0]["genre_realization"] == "题材化-1"
    assert os.path.exists(result["result_path"])
    assert os.path.exists(result["result_path"].replace(".json", ".md"))
