"""Story Agent 测试：大纲加载、场景约束和图端到端导出。"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import Story_Agent.app as app
import Story_Agent.state as state


def _source():
    return {
        "outline_id": "OUT_TEST",
        "snapshot_id": "snapshot_x",
        "pattern_name": "P",
        "genre": "01_悬疑惊悚",
        "seed": {"characters": [{"id": "P1", "role": "hero"}], "core_conflict": "c"},
        "mechanism_plan": {"steps": [
            {
                "segment_index": 1, "function_name": "F1", "role_bindings": {"P1": "发现者"},
                "who_does_what": "P1发现危险", "why": "确认威胁",
                "state_change": "P1从不知情变为警觉", "connects_to_next": "促使P1处理危险",
                "character_state_changes": {"P1": "不知情→发现符号→保持警觉"},
            },
            {
                "segment_index": 2, "function_name": "F2", "role_bindings": {"P1": "解决者"},
                "who_does_what": "P1解决危险", "why": "恢复安全",
                "state_change": "危险消失", "connects_to_next": "",
                "character_state_changes": {"P1": "受威胁→关闭危险源→恢复安全"},
            },
        ]},
        "narrative_plan": {"steps": [
            {
                "segment_index": 1, "function_name": "F1",
                "genre_realization": "P1在街道水塔发现异常符号",
                "motivation_setup": "失踪案持续发生，P1必须确认危险",
                "connective_event": "符号指向仓库中的危险源",
                "reaction_beat": "",
                "setup_payoffs": [{
                    "content": "水塔符号", "payoff_segment_index": 2,
                    "payoff": "符号帮助P1确认仓库异常",
                }],
            },
            {
                "segment_index": 2, "function_name": "F2",
                "genre_realization": "P1利用符号定位并关闭危险源",
                "motivation_setup": "", "connective_event": "进入结局",
                "reaction_beat": "P1确认危险解除后处理余波",
                "setup_payoffs": [],
            },
        ]},
        "contract_ledger": {
            "enabled": False, "states": [], "obligations": [], "transitions": [], "issues": [],
        },
        "ending_spec": {"resolves": "c", "must_show": ["解决"], "final_state": "稳定"},
        "outline": {
            "segments": [
                {"function_name": "F1", "beats": ["P1发现危险"], "link": "进入冲突"},
                {"function_name": "F2", "beats": ["P1解决危险"], "link": ""},
            ],
            "ending": {
                "resolution_actions": ["P1解决危险"],
                "conflict_resolution": "危险消失",
                "final_state": "P1安全",
            },
        },
        "validation": {"overall_ok": True},
    }


def _mock_store(monkeypatch, source, outcomes=None):
    class FakeStore:
        def __init__(self, path):
            assert path == "knowledge.db"

        def load_outline(self, outline_id):
            assert outline_id == "OUT_TEST"
            return source

        def record_generation_outcome(self, *args, **kwargs):
            assert args[0] == "snapshot_x"
            assert args[1] is None
            assert args[2] == "OUT_TEST"
            if outcomes is not None:
                outcomes.append((args, kwargs))
            return "GO_TEST"

    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)


def _scene_plan_draft():
    return state.ScenePlanDraft(segments=[
        state.SegmentScenePlan(segment_index=1, scenes=[state.SceneDraft(
            characters=["P1"], setting="街道", goal="确认危险", conflict="视线受阻",
            beats=["P1发现危险"], state_change="P1警觉", transition="继续追查",
        )]),
        state.SegmentScenePlan(segment_index=2, scenes=[state.SceneDraft(
            characters=["P1"], setting="仓库", goal="解决危险", conflict="敌人阻拦",
            beats=["P1解决危险"], state_change="P1安全",
        )]),
    ])


def _function_constraints():
    return state.FunctionConstraintPlan(
        segments=[
            state.FunctionSegmentConstraint(
                segment_index=2, function_name="F2", role_bindings={"P1": "解决者"},
                required_preconditions=["P1已经发现危险"], required_effects=["危险已经消失"],
                obligations_opened=[], obligations_advanced=[], obligations_resolved=["恢复安全"],
                required_action="P1解决危险", required_reason="恢复安全",
                required_state_change="P1从受威胁变为安全", causal_to_next="",
            ),
            state.FunctionSegmentConstraint(
                segment_index=1, function_name="F1", role_bindings={"P1": "发现者"},
                required_preconditions=["P1尚不知道危险"], required_effects=["P1已经确认危险"],
                obligations_opened=["恢复安全"], obligations_advanced=[], obligations_resolved=[],
                required_action="P1发现危险", required_reason="确认威胁",
                required_state_change="P1从不知情变为警觉",
                causal_to_next="已确认的危险迫使P1采取解决行动",
            ),
        ],
        story=state.StoryLevelConstraint(
            core_conflict="危险威胁P1", ending_resolves="危险是否会伤害P1",
            ending_must_show=["P1解决危险"], required_final_state="P1安全",
            resolution_actions=["P1解决危险"],
        ),
    )


def _scene_developments():
    return state.SceneDevelopmentPlan(developments=[
        state.SceneDevelopment(
            scene_id="S2", pacing_mode="DRAMATIZE",
            expand_points=["P1完成解决危险的行动"],
            causal_moments=[state.CausalMoment(
                stimulus="危险源暴露", interpretation="P1确认必须立即关闭",
                response="P1执行关闭行动",
            )],
            exit_aftereffect="危险解除，P1恢复安全",
            literary_plan=state.LiteraryPlan(
                environment_function="仓库的封闭感强化危险压力",
                sensory_anchor=["金属声"], image_or_motif="灯塔",
                dialogue_subtext="P1必须证明自己",
                rhetoric_focus=["对照"], sentence_rhythm="紧促",
            ),
        ),
        state.SceneDevelopment(
            scene_id="S1", pacing_mode="DEVELOP",
            expand_points=["P1确认异常符号与危险有关"],
            reaction_decision=state.ReactionDecision(
                stimulus="P1发现异常符号", reaction="P1提高警觉",
                dilemma="离开现场或继续追查", decision="P1继续追查仓库",
            ),
            exit_aftereffect="P1带着已确认的危险线索前往仓库",
            literary_plan=state.LiteraryPlan(
                environment_function="街道的雾气遮挡视线",
                sensory_anchor=["潮湿的雾"], image_or_motif="",
                dialogue_subtext="", rhetoric_focus=[], sentence_rhythm="舒缓",
            ),
        ),
    ])


def _story_validation(**overrides):
    values = {
        "user_request_ok": True,
        "causal_constraints_ok": True,
        "character_consistency_ok": True,
        "ending_ok": True,
        "unsupported_solution_ok": True,
        "length_ok": True,
        "overall_ok": True,
        "repairable": False,
        "issues": [],
    }
    values.update(overrides)
    return state.StoryValidation(**values)


def test_load_outline_document_requires_existing_id(monkeypatch):
    class MissingStore:
        def __init__(self, _path):
            pass

        def load_outline(self, outline_id):
            raise ValueError(f"知识库中不存在大纲: {outline_id}")

    monkeypatch.setattr(app, "StoryKnowledgeStore", MissingStore)
    with pytest.raises(ValueError, match="不存在大纲"):
        app.load_outline_document("knowledge.db", "OUT_MISSING")


def test_load_outline_document_rejects_failed_validation(monkeypatch):
    source = _source()
    source["validation"]["overall_ok"] = False
    _mock_store(monkeypatch, source)
    with pytest.raises(ValueError, match="校验未通过"):
        app.load_outline_document("knowledge.db", "OUT_TEST")


def test_load_outline_document_requires_narrative_plan(monkeypatch):
    source = _source()
    source.pop("narrative_plan")
    _mock_store(monkeypatch, source)
    with pytest.raises(ValueError, match="narrative_plan"):
        app.load_outline_document("knowledge.db", "OUT_TEST")


def test_scene_plan_requires_coverage_order_and_ending():
    source = _source()
    assert [item["segment_index"] for item in app._indexed_segments(source)] == [1, 2]
    plan = app.build_scene_plan(source, _scene_plan_draft().model_dump())
    assert app._scene_plan_issues(source, plan) == []
    incomplete = plan
    incomplete["scenes"].pop()
    assert any("覆盖" in issue for issue in app._scene_plan_issues(source, incomplete))


def test_scene_plan_rejects_unknown_character_id():
    source = _source()
    plan = app.build_scene_plan(source, _scene_plan_draft().model_dump())
    plan["scenes"][0]["characters"] = ["P9"]
    assert any("未定义人物" in issue for issue in app._scene_plan_issues(source, plan))


def test_plan_scenes_retries_unknown_character_id(monkeypatch):
    source = _source()
    invalid = _scene_plan_draft().model_dump()
    invalid["segments"][0]["scenes"][0]["characters"] = ["P9"]
    calls = []

    def fake_chat(messages, output_schema, **_kwargs):
        assert output_schema is state.ScenePlanDraft
        calls.append(messages)
        if len(calls) == 1:
            return state.ScenePlanDraft.model_validate(invalid)
        assert "allowed_character_ids" in messages[-1]["content"]
        return _scene_plan_draft()

    monkeypatch.setattr(app, "chat_structured", fake_chat)
    result = app.plan_scenes_node({
        "outline_data": source,
        "function_constraints": _function_constraints().model_dump(),
    })

    assert len(calls) == 2
    assert result["scene_plan"]["scenes"][0]["characters"] == ["P1"]


def test_character_names_must_cover_seed_characters():
    source = _source()
    story = {"title": "标题", "scenes": [{"scene_id": "S1", "text": "正文"}]}
    with pytest.raises(ValueError, match="恰好覆盖"):
        app.validate_character_names(source, story)
    story["character_names"] = {"P1": "林晚"}
    assert app.validate_character_names(source, story)["character_names"] == {"P1": "林晚"}


def test_function_constraints_lock_segment_function():
    source = _source()
    constraints = app.align_function_constraints(source, _function_constraints().model_dump())
    assert [item["segment_index"] for item in constraints["segments"]] == [1, 2]
    constraints["segments"][0]["function_name"] = "OTHER"
    with pytest.raises(ValueError, match="Function 约束"):
        app.align_function_constraints(source, constraints)


def test_scene_developments_require_exact_scene_ids():
    plan = app.build_scene_plan(_source(), _scene_plan_draft().model_dump())
    developments = app.align_scene_developments(
        plan, _scene_developments().model_dump(),
    )
    assert [item["scene_id"] for item in developments["developments"]] == ["S1", "S2"]
    developments["developments"].pop()
    with pytest.raises(ValueError, match="一一对应"):
        app.align_scene_developments(plan, developments)


def test_prompts_do_not_promote_relationships_beyond_outline_evidence():
    assert "状态上界" in app.FUNCTION_CONSTRAINT_PROMPT
    assert "场景结构" in app.SCENE_PLAN_PROMPT
    assert "allowed_character_ids" in app.SCENE_PLAN_PROMPT
    assert "pacing_mode" not in app.SCENE_PLAN_PROMPT
    assert "刺激 → 反应 → 两难 → 决定" in app.DEVELOP_SCENES_PROMPT
    assert "literary_plan" in app.DEVELOP_SCENES_PROMPT
    assert "不撰写正文" in app.DEVELOP_SCENES_PROMPT
    assert "scene_developments" in app.STORY_PROMPT
    assert "环境描写" in app.STORY_PROMPT


def test_scene_development_normalizes_optional_nulls():
    development = state.SceneDevelopment.model_validate({
        "scene_id": "S1",
        "pacing_mode": "DEVELOP",
        "expand_points": [],
        "causal_moments": None,
        "exit_aftereffect": None,
        "literary_plan": {
            "environment_function": None,
            "sensory_anchor": None,
            "image_or_motif": None,
            "dialogue_subtext": None,
            "rhetoric_focus": None,
            "sentence_rhythm": None,
        },
    })

    assert development.causal_moments == []
    assert development.exit_aftereffect == ""
    assert development.literary_plan.image_or_motif == ""
    assert development.literary_plan.sensory_anchor == []


def test_graph_end_to_end(tmp_path, monkeypatch):
    _mock_store(monkeypatch, _source())
    calls = []

    def fake_chat(messages, output_schema, **_kwargs):
        calls.append(output_schema)
        payload = json.loads(messages[-1]["content"])
        if output_schema is state.FunctionConstraintPlan:
            assert payload["contract_ledger"]["enabled"] is False
            assert payload["ending_target"]["source"] == "pattern"
            assert "ending_spec" not in payload
            return _function_constraints()
        if output_schema is state.ScenePlanDraft:
            assert payload["function_constraints"]["segments"][0]["function_name"] == "F1"
            assert payload["narrative_plan"]["steps"][0]["genre_realization"]
            assert payload["allowed_character_ids"] == ["P1"]
            return _scene_plan_draft()
        if output_schema is state.SceneDevelopmentPlan:
            assert payload["scene_plan"]["scenes"][0]["scene_id"] == "S1"
            assert "mechanism_plan" not in payload
            return _scene_developments()
        if output_schema is state.StoryDraft:
            assert _kwargs["reasoning_effort"] == "medium"
            assert payload["function_constraints"]["story"]["required_final_state"] == "P1安全"
            assert "mechanism_plan" not in payload
            assert "narrative_plan" not in payload
            assert [item["scene_id"] for item in payload["scene_developments"]["developments"]] == ["S1", "S2"]
            assert payload["writing_requirements"] == {
                "min_chinese_chars": 3000,
            }
            long_text = "他在仓库里解决了危险。" * 200
            return state.StoryDraft(title="雾中灯塔", character_names={"P1": "林晚"}, scenes=[
                state.StoryScene(scene_id="S2", text=long_text),
                state.StoryScene(scene_id="S1", text=long_text),
            ])
        if output_schema is state.StoryValidation:
            return _story_validation()
        raise AssertionError(output_schema)

    monkeypatch.setattr(app, "chat_structured", fake_chat)
    result = app._build_graph().invoke({
        "outline_id": "OUT_TEST", "knowledge_db": "knowledge.db",
        "user_request": None, "out_dir": str(tmp_path / "stories"),
        "outline_data": None, "function_constraints": None,
        "scene_plan": None, "scene_developments": None,
        "story": None, "story_validation": None,
        "first_story_validation": None, "story_revalidation": None,
        "story_repair_count": 0, "result_path": "",
    })
    with open(result["result_path"], encoding="utf-8") as f:
        exported = json.load(f)
    assert [scene["scene_id"] for scene in exported["story"]["scenes"]] == ["S1", "S2"]
    assert [item["scene_id"] for item in exported["scene_developments"]["developments"]] == ["S1", "S2"]
    assert calls == [
        state.FunctionConstraintPlan,
        state.ScenePlanDraft,
        state.SceneDevelopmentPlan,
        state.StoryDraft,
        state.StoryValidation,
    ]
    assert [item["segment_index"] for item in exported["function_constraints"]["segments"]] == [1, 2]
    assert exported["source_outline"]["contract_ledger"]["enabled"] is False
    assert exported["source_outline"]["validation"]["overall_ok"] is True
    assert exported["source_outline_id"] == "OUT_TEST"
    assert exported["story"]["character_names"] == {"P1": "林晚"}
    assert exported["story_status"] == "accepted"
    assert exported["generation_outcome_id"] == "GO_TEST"
    assert os.path.exists(result["result_path"].replace(".json", ".md"))
    markdown = open(result["result_path"].replace(".json", ".md"), encoding="utf-8").read()
    assert "F1" not in markdown and "scene_plan" not in markdown and "P1" not in markdown


def _run_story_graph(tmp_path, monkeypatch, validations):
    source = _source()
    outcomes = []
    _mock_store(monkeypatch, source, outcomes)
    calls = []
    story_calls = 0
    validation_calls = 0

    def fake_chat(messages, output_schema, **_kwargs):
        nonlocal story_calls, validation_calls
        calls.append(output_schema)
        if output_schema is state.FunctionConstraintPlan:
            return _function_constraints()
        if output_schema is state.ScenePlanDraft:
            return _scene_plan_draft()
        if output_schema is state.SceneDevelopmentPlan:
            return _scene_developments()
        if output_schema is state.StoryDraft:
            story_calls += 1
            if story_calls > 1:
                assert "Story Validator" in messages[-1]["content"]
            long_text = "他在仓库里解决了危险。" * 200
            return state.StoryDraft(
                title="雾中灯塔", character_names={"P1": "林晚"}, scenes=[
                    state.StoryScene(scene_id="S1", text=long_text),
                    state.StoryScene(scene_id="S2", text=long_text),
                ],
            )
        if output_schema is state.StoryValidation:
            validation = validations[validation_calls]
            validation_calls += 1
            return validation
        raise AssertionError(output_schema)

    monkeypatch.setattr(app, "chat_structured", fake_chat)
    result = app._build_graph().invoke({
        "outline_id": "OUT_TEST", "knowledge_db": "knowledge.db",
        "user_request": None, "out_dir": str(tmp_path / "stories"),
        "outline_data": None, "function_constraints": None,
        "scene_plan": None, "scene_developments": None, "story": None,
        "story_validation": None, "first_story_validation": None,
        "story_revalidation": None, "story_repair_count": 0,
        "result_path": "",
    })
    with open(result["result_path"], encoding="utf-8") as f:
        return json.load(f), calls, outcomes


def test_story_validator_rewrites_once_then_accepts(tmp_path, monkeypatch):
    exported, calls, outcomes = _run_story_graph(
        tmp_path, monkeypatch,
        [_story_validation(overall_ok=False, repairable=True, ending_ok=False, issues=["结局没有完成解决动作"]),
         _story_validation()],
    )

    assert calls.count(state.StoryDraft) == 2
    assert calls.count(state.StoryValidation) == 2
    assert exported["story_repair_count"] == 1
    assert exported["story_status"] == "rewritten"
    assert exported["first_story_validation"]["issues"] == ["结局没有完成解决动作"]
    assert exported["story_revalidation"]["overall_ok"] is True
    assert outcomes[0][0][5] is True
    assert outcomes[0][0][7] == "rewritten"


def test_story_validator_stops_after_second_failure_and_rejects(tmp_path, monkeypatch):
    failed = _story_validation(
        overall_ok=False, repairable=True, causal_constraints_ok=False, issues=["因果链断裂"],
    )
    exported, calls, outcomes = _run_story_graph(tmp_path, monkeypatch, [failed, failed])

    assert calls.count(state.StoryDraft) == 2
    assert calls.count(state.StoryValidation) == 2
    assert exported["story_repair_count"] == 1
    assert exported["story_status"] == "rejected"
    assert exported["needs_human_review"] is True
    assert exported["story_revalidation"]["issues"] == ["因果链断裂"]
    assert outcomes[0][0][4] is False
    assert outcomes[0][0][5] is True
    assert outcomes[0][0][7] == "rejected"


def test_story_validator_unrepairable_failure_stops_without_rewrite(tmp_path, monkeypatch):
    exported, calls, outcomes = _run_story_graph(
        tmp_path, monkeypatch,
        [_story_validation(
            overall_ok=False, repairable=False, ending_ok=False,
            issues=["固定结局目标互相矛盾"],
        )],
    )

    assert calls.count(state.StoryDraft) == 1
    assert calls.count(state.StoryValidation) == 1
    assert exported["story_repair_count"] == 0
    assert exported["story_status"] == "rejected"
    assert exported["needs_human_review"] is True
    assert exported["story_revalidation"] is None
    assert outcomes[0][0][4] is False
    assert outcomes[0][0][5] is False
    assert outcomes[0][0][7] == "rejected"
