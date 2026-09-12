"""Outline Agent 测试：题材规范化、planner 选链、顺序对齐、rule_check、图端到端。"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import Outline_Agent.app as app
import Outline_Agent.state as state
from FunctionExtract_Agent.Prompt.Inducer_prompt import INDUCER_SYSTEM_PROMPT


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


def test_candidate_patterns_use_repeated_failure_feedback():
    catalog = {"published_patterns": [
        _pattern("失败", 9, {"01_悬疑惊悚": 1}, ["F1"]),
        _pattern("无反馈", 1, {"01_悬疑惊悚": 1}, ["F2"]),
        _pattern("通过", 2, {"01_悬疑惊悚": 1}, ["F3"]),
    ]}
    feedback = {
        "PAT_失败": {"priority_delta": -1},
        "PAT_通过": {"priority_delta": 1},
    }
    names = [
        p["pattern_name"]
        for p in app.candidate_patterns(catalog, "01_悬疑惊悚", feedback)
    ]
    assert names == ["通过", "无反馈", "失败"]


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

        def load_contracts(self, _snapshot_id):
            return []

        def load_story_profiles(self, _snapshot_id):
            return []

    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    pattern = _pattern("P", 2, {"01_悬疑惊悚": 1}, ["A"])
    pattern["member_motif_ids"] = ["MC_KEEP"]
    references = app.load_planner_references(
        "snapshot_x", pattern, [{"function_id": "F1", "function_name": "A"}], "knowledge.db",
    )
    assert [item["motif_id"] for item in references["motifs"]] == ["MC_KEEP"]
    assert references["instance_cases"]["A"][0]["surface_form"] == "公开对峙"
    assert references["transitions"] == {}


def test_planner_node_reuses_audited_pattern(monkeypatch):
    catalog = {"published_patterns": [
        _pattern("已用", 2, {"01_悬疑惊悚": 1}, ["F1"]),
        _pattern("可用", 1, {"01_悬疑惊悚": 1}, ["F2"]),
    ]}

    class FakeStore:
        def __init__(self, _path):
            pass

        def load_pattern_feedback(self, _snapshot_id):
            return {}

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
    assert result["pattern_id"] == "PAT_已用"


def test_planner_node_allows_audited_pattern(monkeypatch):
    catalog = {"published_patterns": [
        _pattern("已用", 2, {"01_悬疑惊悚": 1}, ["F1"]),
    ]}

    class FakeStore:
        def __init__(self, _path):
            pass

        def load_pattern_feedback(self, _snapshot_id):
            return {}

    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    monkeypatch.setattr(app, "load_catalog", lambda *_args: catalog)
    monkeypatch.setattr(app, "load_contracts", lambda *_args: {})
    monkeypatch.setattr(app, "load_planner_references", lambda *_args: {
        "motifs": [], "transitions": {}, "instance_cases": {},
    })
    result = app.planner_node({
        "snapshot_id": "snapshot_x", "knowledge_db": "knowledge.db",
        "genre": "01_悬疑惊悚", "pattern_request": "已用",
    })
    assert result["pattern_id"] == "PAT_已用"


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


def test_seed_character_has_explicit_initial_stance():
    character = state.SeedCharacter(
        id="P1", label="主角", role="hero", goal="g", motivation="m",
        relationships={}, stance_toward_protagonist="self",
    )
    assert character.stance_toward_protagonist == "self"


def test_build_ending_target_uses_llm_seed():
    target = app.build_ending_target(
        {
            "core_conflict": "解决冲突",
            "ending_direction": "恢复稳定",
            "ending_requirements": ["展示直接结果"],
        },
    )
    assert target == {
        "source": "llm_seed",
        "resolves": "解决冲突",
        "must_show": ["展示直接结果"],
        "final_state": "恢复稳定",
    }


def test_relationship_constraints_include_effect_bounds():
    contract = {
        "role_slots": ["actor", "affected"],
        "effects": [{
            "aspect": "RELATIONSHIP_STATUS", "role_slots": ["actor", "affected"],
            "before": "未建立", "after": "初步合作",
        }],
    }
    constraints = app._relationship_constraints([{
        "segment_index": 1, "function_name": "RELATE", "contract": contract,
    }])
    assert constraints[0]["allowed_role_pairs"] == [["actor", "affected"]]
    assert constraints[0]["allowed_effects"] == [{
        "role_slots": ["actor", "affected"],
        "aspect": "RELATIONSHIP_STATUS",
        "before": "未建立",
        "after": "初步合作",
    }]


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


def test_mechanism_retries_contract_relationship_boundary(monkeypatch):
    contract = {
        "role_slots": ["actor", "affected"],
        "preconditions": [],
        "effects": [{
            "aspect": "RELATIONSHIP_STATUS", "role_slots": ["actor", "affected"],
            "before": "未建立", "after": "已建立",
        }],
        "obligation_effects": {},
    }
    chain = [{"segment_index": 1, "function_name": "RELATE", "contract": contract}]
    calls = []

    def fake_chat(messages, output_schema, **_kwargs):
        assert output_schema is app.MechanismPlan
        if calls:
            assert "segment_index=1:P1/P2" in messages[-1]["content"]
        calls.append(True)
        target = "P3" if len(calls) == 1 else "P2"
        return app.MechanismPlan(steps=[state.MechanismStep(
            segment_index=1, function_name="RELATE",
            role_bindings={"actor": "P1", "affected": "P2"},
            who_does_what="P1影响P2", why="目标要求", state_change="关系变化",
            character_state_changes={"P1": "改变", "P2": "改变"},
            relationship_changes=[{
                "source_id": "P1", "target_id": target, "dimension": "trust",
                "before": "模型填写", "after": "已建立", "evidence": "P1承担代价",
            }],
            connects_to_next="继续",
        )])

    monkeypatch.setattr(app, "chat_structured", fake_chat)
    result = app.mechanism_node({
        "chain": chain,
        "seed": {
            "characters": [{"id": "P1"}, {"id": "P2"}],
            "ending_requirements": ["展示关系变化的直接结果"],
        },
        "planner_references": None,
    })

    assert len(calls) == 2
    assert result["contract_ledger"]["issues"] == []
    assert result["mechanism"]["steps"][0]["relationship_changes"][0]["target_id"] == "P2"


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


def test_rule_check_rejects_ending_repeating_function_action():
    chain = [{"function_name": "A"}]
    outline = {
        "segments": [{
            "function_name": "A",
            "beats": ["P1主动约P2到甲板并明确拒绝继续发展"],
        }],
        "ending": {
            "resolution_actions": ["P1主动约P2到甲板并明确拒绝继续发展"],
            "conflict_resolution": "关系进入稳定收束",
            "final_state": "两人各自返回生活",
        },
    }
    issues = app.rule_check(chain, outline)
    assert any("同一事件只能由一个结构段负责" in issue for issue in issues)


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


def test_narrative_step_drops_incomplete_setup_payoffs():
    step = state.NarrativeStep.model_validate({
        "segment_index": 1,
        "function_name": "A",
        "genre_realization": "实现",
        "setup_payoffs": [
            {"content": "不完整线索", "payoff": None},
            {"content": "有效线索", "payoff": "后续兑现"},
        ],
    })
    assert [item.content for item in step.setup_payoffs] == ["有效线索"]


def _narrative_ending():
    return state.NarrativeEnding(
        resolution_actions=["明确结构结局动作"],
        conflict_resolution="核心冲突已处理",
        final_state="主角恢复稳定",
    )


def _literary_design(function_names):
    return state.LiteraryDesign(
        global_design=state.GlobalLiteraryDesign(
            narrative_strategy="第三人称限知",
            tone="克制",
            prose_texture="细腻",
            character_expression="通过行动表现",
            active_world_forces=["环境限制"],
            sensory_strategy=["触感"],
            expression_boundaries=["不直接总结情绪"],
        ),
        steps=[state.LiteraryStep(
            segment_index=index,
            function_name=name,
            behavioral_expression="通过既定行动表现变化",
            world_pressure="环境改变行动条件",
            sensory_anchor="冷硬的触感",
            delivery_mode="DEVELOP",
            exit_effect="留下未完成的动作",
        ) for index, name in enumerate(function_names, 1)],
        literary_ending=state.LiteraryEnding(
            entry_state="从既定结局结果进入",
            resolution_expression="通过既定行动及其后果呈现结局",
            character_aftereffect="通过沉默和继续行动表现终态",
            world_aftereffect="环境承接结局余波",
            dialogue_subtext="普通话语保留潜台词",
            sensory_anchor="潮湿的触感",
            motif_payoff="",
            delivery_mode="DEVELOP",
            closing_action_or_image="留下一个未完成的小动作",
            restraint_boundary="不直接总结主题",
        ),
    )


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
        ], ending=_narrative_ending()),
        app.NarrativePlan(steps=[
            state.NarrativeStep(
                segment_index=1, function_name="A", genre_realization="a",
                setup_payoffs=[state.SetupPayoff(content="线索", payoff_segment_index=2, payoff="兑现")],
            ),
            state.NarrativeStep(segment_index=2, function_name="B", genre_realization="b"),
        ], ending=_narrative_ending()),
        _literary_design(("A", "B")),
    ])
    calls = []

    def fake_chat(messages, output_schema, **_kwargs):
        payload = next(
            json.loads(message["content"])
            for message in reversed(messages)
            if message["content"].lstrip().startswith("{")
        )
        calls.append((output_schema, payload))
        return next(responses)

    monkeypatch.setattr(app, "chat_structured", fake_chat)
    result = app.scaffold_node({
        "snapshot_id": "snapshot_x", "knowledge_db": "knowledge.db",
        "chain": chain,
        "seed": {"ending_requirements": ["展示直接结果"]},
        "mechanism": {}, "ending_spec": None, "user_request": "保留原始要求",
    })
    assert result["narrative"]["steps"][0]["setup_payoffs"][0]["payoff_segment_index"] == 2
    assert [schema for schema, _payload in calls] == [
        app.NarrativePlan, app.NarrativePlan, app.LiteraryDesign,
    ]
    assert "narrative_plan" not in calls[0][1]
    assert calls[2][1]["narrative_plan"] == result["narrative"]


def test_scaffold_does_not_call_literary_design_after_narrative_failure(monkeypatch):
    chain = [{
        "segment_index": 1, "function_name": "A", "definition": "", "preconditions": [],
        "role_slots": [], "contract": {}, "occurrence_index": 1, "occurrence_total": 1,
    }]
    invalid = app.NarrativePlan(steps=[state.NarrativeStep(
        segment_index=1,
        function_name="A",
        genre_realization="a",
        setup_payoffs=[state.SetupPayoff(content="线索", payoff_segment_index=1, payoff="兑现")],
    )], ending=_narrative_ending())
    schemas = []

    def fake_chat(_messages, output_schema, **_kwargs):
        schemas.append(output_schema)
        return invalid

    monkeypatch.setattr(app, "chat_structured", fake_chat)
    with pytest.raises(ValueError, match="叙事展开方案不合法"):
        app.scaffold_node({
            "chain": chain,
            "seed": {"ending_requirements": ["展示直接结果"]},
            "mechanism": {},
            "ending_spec": None,
            "user_request": "保留原始要求",
        })
    assert schemas == [app.NarrativePlan, app.NarrativePlan]


def test_validate_distinguishes_seed_ending_target_from_generated_ending(monkeypatch):
    def fake_chat(messages, output_schema, **_kwargs):
        assert output_schema is app.OutlineValidation
        payload = json.loads(messages[-1]["content"])
        assert "ending_spec" not in payload
        assert payload["ending_target"] == {
            "source": "llm_seed",
            "resolves": "核心冲突",
            "must_show": ["展示直接结果"],
            "final_state": "恢复稳定",
        }
        assert payload["generated_ending"]["final_state"] == "恢复稳定"
        return app.OutlineValidation(
            segment_checks=[state.SegmentCheck(
                segment_index=1, function_name="A", recoverable=True, issue="",
            )],
            overall_ok=True,
            issues=[],
        )

    monkeypatch.setattr(app, "chat_structured", fake_chat)
    result = app.validate_node({
        "chain": [{"segment_index": 1, "function_name": "A", "contract": {}}],
        "ending_spec": None,
        "seed": {
            "core_conflict": "核心冲突",
            "ending_direction": "恢复稳定",
            "ending_requirements": ["展示直接结果"],
            "characters": [],
        },
        "mechanism": {"steps": []},
        "narrative": {"steps": []},
        "outline": {
            "segments": [{"segment_index": 1, "function_name": "A", "beats": ["x"]}],
            "ending": {
                "resolution_actions": ["完成解决"],
                "conflict_resolution": "核心冲突已解决",
                "final_state": "恢复稳定",
            },
        },
        "contract_ledger": {},
    })
    assert result["validation"]["overall_ok"] is True


def test_prompts_keep_seed_and_narrative_boundaries():
    assert not hasattr(app, "INTERPRET_REQUEST_PROMPT")
    assert not hasattr(app, "CreativeBrief")
    assert "creative_brief" not in app.DYNAMIC_SEED_PROMPT
    assert "ending_spec" not in app.DYNAMIC_SEED_PROMPT
    assert "creative_brief" not in app.SEED_PROMPT
    assert "creative_brief" not in app.NARRATIVE_PROMPT
    assert "creative_brief" not in app.VALIDATE_PROMPT
    assert "关系类型" in app.SEED_PROMPT
    assert "可观察解决动作 → 直接冲突结果 → 稳定终态" in app.SEED_PROMPT
    for prompt in (app.DYNAMIC_SEED_PROMPT, app.SEED_PROMPT):
        assert "用户明确指定的时代、地点、人物关系、核心事件和结局事实必须保留" in prompt
        assert "不得替换、弱化或反转" in prompt
        assert "core_conflict 应说明故事开始时已经存在的具体压力、主人公当下的目标" in prompt
        assert "人物的 goal 和 motivation 必须能够解释其行动" in prompt
        assert "用户明确指定分离、失败、死亡、不复合或其他结局事实时" in prompt
        assert "只补充实现过程、直接后果和稳定终态" in prompt
    assert "`ending_spec` 只作历史参考，不能覆盖用户要求" in app.SEED_PROMPT
    assert "可理解但错误的选择" not in app.DYNAMIC_SEED_PROMPT
    assert "可理解但错误的选择" not in app.SEED_PROMPT
    assert "user_request 中明确提出的每条个人、关系、集体或系统主线" not in app.DYNAMIC_SEED_PROMPT
    assert "不要为了迁就尚未生成的 Function 链" not in app.DYNAMIC_SEED_PROMPT
    assert "ending_target 来自本轮 Seed" in app.NARRATIVE_PROMPT
    assert "genre_realization 必须把 mechanism_plan 的核心行动题材化" in app.NARRATIVE_PROMPT
    assert "尽早呈现已有的主要处境和压力" in app.NARRATIVE_PROMPT
    assert "只用于补足既定行动的动机、前因、反应和信息揭示" in app.NARRATIVE_PROMPT
    assert "每个 step 都应让已有的行动、信息、压力、选择、代价或关系变化得到进一步落实" in app.NARRATIVE_PROMPT
    assert "setup_payoffs 只能服务后续已有 Function 或 ending" in app.NARRATIVE_PROMPT
    assert "ending 必须把 Seed 的 ending_direction 和 ending_requirements 具体化" in app.NARRATIVE_PROMPT
    assert "异常、秘密或威胁" not in app.NARRATIVE_PROMPT
    assert "改变选择或解决条件" not in app.NARRATIVE_PROMPT
    assert "一次性完整供述" not in app.NARRATIVE_PROMPT
    assert "对立或互补的行为方式" not in app.NARRATIVE_PROMPT
    assert "动作或物件作为记忆锚点" not in app.NARRATIVE_PROMPT
    assert "Pattern 的 ending_spec 只能作为历史参考" in app.VALIDATE_PROMPT
    assert "状态上界" in app.REALIZE_PROMPT
    assert "只输出 JSON" in app.REALIZE_PROMPT
    assert "可以保留制度、阵营和利益阻力" in app.REALIZE_PROMPT
    assert app.REALIZE_PROMPT.count("事件所有权") == 1
    assert all(
        "json" in prompt.lower()
        for prompt in (app.NARRATIVE_PROMPT, app.REALIZE_PROMPT, app.VALIDATE_PROMPT)
    )
    assert "不是必须完成的结局义务" in app.VALIDATE_PROMPT
    assert "冲突主线与结局须保持同一尺度" in app.VALIDATE_PROMPT
    assert "overall_ok 必须为 false" in app.VALIDATE_PROMPT


def test_literary_design_prompt_and_schema_are_independent_from_narrative_plan():
    assert "文学设计只能改变既定结构的呈现方式" in app.LITERARY_DESIGN_PROMPT
    assert "全局设计应确定" in app.LITERARY_DESIGN_PROMPT
    assert "逐结构段只说明" in app.LITERARY_DESIGN_PROMPT
    assert "已经完成并校验通过的 NarrativePlan" in app.LITERARY_DESIGN_PROMPT
    assert "从哪个已有的具体处境进入故事" in app.LITERARY_DESIGN_PROMPT
    assert "使读者尽早理解人物目标和压力" in app.LITERARY_DESIGN_PROMPT
    assert "语言应清晰、流畅、适合连续阅读" in app.LITERARY_DESIGN_PROMPT
    assert "关键选择和关系变化必须清楚" in app.LITERARY_DESIGN_PROMPT
    assert "不能为了制造氛围增加新的结构事件" in app.LITERARY_DESIGN_PROMPT
    assert "`motif_plan` 与 `expression_boundaries`" in app.LITERARY_DESIGN_PROMPT
    assert "只有自然出现且能够回收的物件、动作或景象才设置 motif" in app.LITERARY_DESIGN_PROMPT
    assert "连续低强度" in app.LITERARY_DESIGN_PROMPT
    assert "既定核心行动如何被读者看见" in app.LITERARY_DESIGN_PROMPT
    assert "本段采用 DRAMATIZE、DEVELOP 或 COMPRESS 的原因" in app.LITERARY_DESIGN_PROMPT
    assert "段末如何保留已有的后果、未决问题、选择或情绪余波" in app.LITERARY_DESIGN_PROMPT
    assert "motif_state" in app.LITERARY_DESIGN_PROMPT
    assert "现实、浪漫、冷峻、荒诞、悬疑或诗性" not in app.LITERARY_DESIGN_PROMPT
    assert "文学性设计不得" not in app.LITERARY_DESIGN_PROMPT
    assert "文学性设计不负责创造新的核心结构" not in app.LITERARY_DESIGN_PROMPT
    assert "最终输出中的 literary_design" not in app.LITERARY_DESIGN_PROMPT
    assert "开篇钩子" not in app.LITERARY_DESIGN_PROMPT
    assert "motif_plan 只能二选一" in app.LITERARY_DESIGN_PROMPT
    assert "同时包含 motif、initial_meaning、transformation、final_payoff 四个非空字段" in app.LITERARY_DESIGN_PROMPT
    assert "组合输出协议" not in app.NARRATIVE_PROMPT
    assert "组合输出协议" not in app.LITERARY_DESIGN_PROMPT
    assert "steps" in app.NARRATIVE_PROMPT
    assert "global_design" in app.LITERARY_DESIGN_PROMPT
    assert not hasattr(app, "ScaffoldDesignResponse")
    assert not hasattr(state, "ScaffoldDesignResponse")
    assert state.LiteraryDesign.model_fields["global_design"]
    assert state.LiteraryDesign.model_fields["steps"]
    assert state.LiteraryDesign.model_fields["literary_ending"]
    assert state.NarrativePlan.model_fields["ending"]
    assert "ending" not in state.OutlineRealization.model_fields
    assert state.NarrativePlan.model_fields.get("literary_design") is None


def test_inducer_prompt_uses_evidence_without_forcing_domain_coverage():
    assert "至少 2 个不同的 story_id" in INDUCER_SYSTEM_PROMPT
    assert "只输出有多个跨故事 evidence 支持的 Function" not in INDUCER_SYSTEM_PROMPT
    assert "尽可能覆盖不同领域/类型" not in INDUCER_SYSTEM_PROMPT
    assert "只能保留 supporting observations 实际支持的不同实现" in INDUCER_SYSTEM_PROMPT


def test_dynamic_seed_receives_raw_user_request_without_brief(monkeypatch):
    seen = {}

    def fake_chat(messages, output_schema, **_kwargs):
        assert output_schema is app.StorySeed
        seen.update(json.loads(messages[-1]["content"]))
        return app.StorySeed(
            genre="现代情感", world_setting="w", characters=[{
                "id": "P1", "label": "主角", "role": "hero", "goal": "g",
                "motivation": "m", "relationships": {}, "stance_toward_protagonist": "self",
            }], core_conflict="c", ending_direction="e",
            ending_requirements=["完成c的可观察结果"],
        )

    monkeypatch.setattr(app, "chat_structured", fake_chat)
    app.dynamic_seed_node({
        "genre": "03_现代情感",
        "user_request": "保留这句原始创作要求",
    })
    assert seen == {
        "genre": "03_现代情感",
        "user_request": "保留这句原始创作要求",
    }


def test_outline_graph_starts_with_mode_specific_seed_or_pattern_path():
    edges = {(edge.source, edge.target) for edge in app._build_graph().get_graph().edges}
    assert ("__start__", "dynamic_seed") in edges
    assert ("__start__", "select_pattern") in edges
    assert ("__start__", "interpret_request") not in edges
    assert ("interpret_request", "dynamic_seed") not in edges
    assert ("interpret_request", "select_pattern") not in edges
    assert ("dynamic_seed", "dynamic_planner") in edges
    assert ("select_pattern", "planner") in edges
    assert ("planner", "seed") in edges
    assert ("seed", "mechanism") in edges
    assert ("seed", "dynamic_planner") not in edges


def _semantic_validation_state(ending, *, final_ledger=None, mechanism_steps=None, validation=None):
    return {
        "chain": [{"segment_index": 1, "function_name": "A", "contract": {}}],
        "ending_spec": None,
        "seed": {
            "core_conflict": "核心冲突",
            "ending_direction": "恢复稳定",
            "ending_requirements": ["展示直接结果"],
            "characters": [
                {"id": "P1", "relationships": {"P2": "低信任"}},
                {"id": "P2", "relationships": {"P1": "低信任"}},
                {"id": "P3", "relationships": {}},
                {"id": "P4", "relationships": {}},
            ],
        },
        "mechanism": {"steps": mechanism_steps or []},
        "narrative": {"steps": [], "ending": ending},
        "outline": {"segments": [{"segment_index": 1, "function_name": "A", "beats": ["x"]}],
                    "final_ledger": final_ledger or [], "ending": ending},
        "contract_ledger": {},
        "validation": validation,
        "realize_retry_count": 0,
    }


def test_validate_rejects_ending_identity_conflation(monkeypatch):
    monkeypatch.setattr(app, "chat_structured", lambda *_args, **_kwargs: app.OutlineValidation(
        segment_checks=[state.SegmentCheck(segment_index=1, function_name="A", recoverable=True, issue="")],
        overall_ok=True, issues=[],
    ))
    result = app.validate_node(_semantic_validation_state({
        "resolution_actions": ["P3与P4是同一人，身份合并"],
        "conflict_resolution": "核心冲突已解决",
        "final_state": "恢复稳定",
    }))
    assert result["validation"]["overall_ok"] is False
    assert any("合并或互换" in issue for issue in result["validation"]["issues"])


def test_validate_rejects_ending_relationship_conflict(monkeypatch):
    monkeypatch.setattr(app, "chat_structured", lambda *_args, **_kwargs: app.OutlineValidation(
        segment_checks=[state.SegmentCheck(segment_index=1, function_name="A", recoverable=True, issue="")],
        overall_ok=True, issues=[],
    ))
    result = app.validate_node(_semantic_validation_state(
        {
            "resolution_actions": ["P1与P2完全互信并正式结盟"],
            "conflict_resolution": "核心冲突已解决",
            "final_state": "恢复稳定",
        },
        final_ledger=["P1与P2保持低信任的谨慎合作"],
        mechanism_steps=[{
            "segment_index": 1,
            "relationship_changes": [{
                "source_id": "P1", "target_id": "P2", "dimension": "信任",
                "before": "低信任", "after": "谨慎合作", "evidence": "共同承担风险",
            }],
        }],
    ))
    assert result["validation"]["overall_ok"] is False
    assert any("超过前序" in issue for issue in result["validation"]["issues"])


@pytest.mark.parametrize(
    ("sample_id", "ending_phrase"),
    [
        ("OUT_9a6c00b1f97cdfdb", "并不代表彻底的和解或长久的联盟"),
        ("OUT_101c806de7e4b70b", "未涉及婚恋等永久承诺"),
    ],
)
def test_ending_semantic_gate_ignores_negated_strong_relation(sample_id, ending_phrase):
    assert not app._has_unnegated_marker(ending_phrase, app._STRONG_RELATION_MARKERS)
    result = app._ending_semantic_issues(_semantic_validation_state(
        {
            "resolution_actions": [],
            "conflict_resolution": ending_phrase,
            "final_state": "稳定",
        },
        final_ledger=["P1与P2保持低信任的谨慎合作"],
    ))
    assert result == [], sample_id


def test_semantic_failure_retries_realize_once(monkeypatch):
    calls = []

    def fake_chat(messages, output_schema, **_kwargs):
        assert output_schema is app.OutlineRealization
        calls.append(messages)
        return app.OutlineRealization(
            segments=[state.OutlineSegment(segment_index=1, function_name="A", beats=["x"])],
            final_ledger=["ledger"],
        )

    monkeypatch.setattr(app, "chat_structured", fake_chat)
    source = _semantic_validation_state(
        {"resolution_actions": ["解决"], "conflict_resolution": "已解决", "final_state": "稳定"},
        validation={"overall_ok": False, "issues": ["Function 段因果展开不足"], "rule_issues": [], "contract_issues": []},
    )
    result = app.realize_node(source)
    assert len(calls) == 1
    assert "Function 段因果展开不足" in calls[0][-1]["content"]
    assert result["realize_retry_count"] == 1
    assert not app._should_retry_realize({**source, **result, "validation": source["validation"]})


def test_contract_or_rule_failure_does_not_retry_realize():
    base = {"overall_ok": False, "issues": ["x"], "rule_issues": [], "contract_issues": []}
    assert app._should_retry_realize({"validation": {**base, "contract_issues": ["contract"]}}) is False
    assert app._should_retry_realize({"validation": {**base, "rule_issues": ["rule"]}}) is False


def test_second_semantic_failure_stops_retry():
    assert app._should_retry_realize({
        "realize_retry_count": 1,
        "validation": {"overall_ok": False, "issues": ["仍失败"], "rule_issues": [], "contract_issues": []},
    }) is False


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
                    motivation="m", relationships={}, stance_toward_protagonist="self",
                )],
                core_conflict="c", ending_direction="e",
                ending_requirements=["完成c的可观察结果"],
            )
        if output_schema is app.MechanismPlan:
            payload = json.loads(messages[-1]["content"])
            assert payload["reference_motifs"] == []
            assert payload["ending_target"] == {
                "source": "llm_seed",
                "resolves": "c",
                "must_show": ["完成c的可观察结果"],
                "final_state": "e",
            }
            return app.MechanismPlan(steps=[
                state.MechanismStep(segment_index=index, function_name=name, role_bindings={}, who_does_what="",
                                  why="", state_change="", character_state_changes={}, connects_to_next="")
                for index, name in reversed(list(enumerate(functions, 1)))  # 故意逆序，靠 _align 修正
            ])
        if output_schema is app.NarrativePlan:
            payload = json.loads(messages[-1]["content"])
            assert payload["reference_motifs"] == []
            assert payload["user_request"] is None
            assert "narrative_plan" not in payload
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
            ], ending=state.NarrativeEnding(
                resolution_actions=["明确解决动作"],
                conflict_resolution="核心冲突已处理",
                final_state="主角恢复稳定",
            ))
        if output_schema is app.LiteraryDesign:
            payload = json.loads(messages[-1]["content"])
            assert payload["reference_motifs"] == []
            assert payload["user_request"] is None
            assert payload["narrative_plan"]["steps"][0]["genre_realization"] == "题材化-1"
            assert payload["narrative_plan"]["ending"]["final_state"] == "主角恢复稳定"
            assert "literary_design" not in payload
            return _literary_design(functions)
        if output_schema is app.OutlineRealization:
            payload = json.loads(messages[-1]["content"])
            assert payload["narrative_plan"]["steps"][0]["genre_realization"] == "题材化-1"
            return app.OutlineRealization(
                segments=[state.OutlineSegment(segment_index=index, function_name=name, beats=["x"])
                          for index, name in reversed(list(enumerate(functions, 1)))],
                final_ledger=["l"],
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

        def load_pattern_feedback(self, _snapshot_id):
            return {}

        def record_outline(self, document, markdown):
            assert document["pattern_name"] == "P"
            assert markdown.startswith("# 大纲：P")
            return "OUT_TEST"

        def record_generation_outcome(self, *args, **kwargs):
            assert args[0] == "x"
            assert args[2] == "OUT_TEST"

    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    result = app._build_graph().invoke({
        "snapshot_id": "x", "knowledge_db": "knowledge.db",
        "genre": "01_悬疑惊悚", "out_dir": str(tmp_path),
        "pattern_request": None, "user_request": None, "pattern_id": None,
        "pattern_name": "", "chain": [], "seed": None, "mechanism": None,
        "narrative": None, "literary_design": None, "outline": None, "validation": None,
        "outline_id": "", "result_path": "",
    })
    assert [step["function_name"] for step in result["chain"]] == list(functions)
    assert [step["function_name"] for step in result["mechanism"]["steps"]] == list(functions)
    assert [step["function_name"] for step in result["narrative"]["steps"]] == list(functions)
    assert result["narrative"]["ending"]["resolution_actions"] == ["明确解决动作"]
    assert [step["function_name"] for step in result["literary_design"]["steps"]] == list(functions)
    assert result["literary_design"]["literary_ending"]["closing_action_or_image"] == "留下一个未完成的小动作"
    assert [segment["function_name"] for segment in result["outline"]["segments"]] == list(functions)
    assert result["ending_spec"] == ending_spec
    assert result["outline"]["ending"]["final_state"] == "主角恢复稳定"
    assert result["outline"]["ending"] == result["narrative"]["ending"]
    assert result["validation"]["rule_issues"] == []
    assert result["outline_id"] == "OUT_TEST"
    exported = json.loads(open(result["result_path"], encoding="utf-8").read())
    assert exported["outline_id"] == "OUT_TEST"
    assert exported["narrative_plan"]["steps"][0]["genre_realization"] == "题材化-1"
    assert exported["literary_design"]["global_design"]["tone"] == "克制"
    assert os.path.exists(result["result_path"])
    assert os.path.exists(result["result_path"].replace(".json", ".md"))
