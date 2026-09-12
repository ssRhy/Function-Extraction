"""Story Agent 测试：大纲加载、场景约束和图端到端导出。"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import Story_Agent.app as app
import Story_Agent.state as state
import Outline_Agent.app as outline_app


def _source():
    return {
        "outline_id": "OUT_TEST",
        "snapshot_id": "snapshot_x",
        "pattern_name": "P",
        "genre": "01_悬疑惊悚",
        "seed": {
            "characters": [{"id": "P1", "role": "hero"}],
            "core_conflict": "c",
            "ending_direction": "seed创作的稳定终态",
            "ending_requirements": ["展示直接结果"],
        },
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
        ], "ending": {
            "resolution_actions": ["P1解决危险"],
            "conflict_resolution": "危险消失",
            "final_state": "P1安全",
        }},
        "literary_design": {
            "global_design": {
                "narrative_strategy": "第三人称限知",
                "tone": "克制",
                "prose_texture": "细腻",
                "character_expression": "通过行动表现",
                "active_world_forces": ["环境限制"],
                "sensory_strategy": ["触感"],
                "motif_plan": None,
                "expression_boundaries": ["不直接总结情绪"],
            },
            "steps": [
                {
                    "segment_index": 1, "function_name": "F1",
                    "behavioral_expression": "通过发现动作表现警觉",
                    "world_pressure": "街道环境限制视线",
                    "dialogue_subtext": "确认彼此掌握的信息",
                    "sensory_anchor": "冷硬触感",
                    "motif_state": "",
                    "delivery_mode": "DEVELOP",
                    "exit_effect": "留下继续追查的停顿",
                },
                {
                    "segment_index": 2, "function_name": "F2",
                    "behavioral_expression": "通过关闭危险表现决定",
                    "world_pressure": "仓库结构增加行动代价",
                    "dialogue_subtext": "",
                    "sensory_anchor": "刺鼻气味",
                    "motif_state": "",
                    "delivery_mode": "DRAMATIZE",
                    "exit_effect": "危险解除后保留余波",
                },
            ],
            "literary_ending": {
                "entry_state": "从危险已经解除后的结局进入",
                "resolution_expression": "通过解除后的余波表现结局",
                "character_aftereffect": "通过继续行动表现稳定状态",
                "world_aftereffect": "仓库恢复安静",
                "dialogue_subtext": "确认余波而不直接表白",
                "sensory_anchor": "潮湿墙面",
                "motif_payoff": "",
                "delivery_mode": "DEVELOP",
                "closing_action_or_image": "P1收起工具",
                "restraint_boundary": "不直接总结主题",
            },
        },
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


def test_ending_identity_check_ignores_business_merger_but_catches_identity_merge():
    def issues(text):
        return outline_app._ending_semantic_issues({
            "seed": {"characters": [{"id": "P1"}, {"id": "P2"}]},
            "outline": {"ending": {
                "resolution_actions": [text],
                "conflict_resolution": "",
                "final_state": "",
            }},
        })

    assert issues("P1让外资合并案撤回") == []
    assert issues("P1与P2合并为同一人") == ["结局合并或互换了不同人物 ID 的身份"]


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
    ], ending=[state.SceneDraft(
        characters=["P1"], setting="仓库外", goal="确认余波", conflict="残余危险",
        beats=["P1确认危险已解除"], state_change="P1进入稳定状态", transition="故事结束",
    )])


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
    )


def _scene_developments():
    return state.SceneDevelopmentPlan(developments=[
        state.SceneDevelopment(
            scene_id="S2", pacing_mode="DRAMATIZE",
            expand_points=["P1完成解决危险的行动"],
        ),
        state.SceneDevelopment(
            scene_id="S1", pacing_mode="DEVELOP",
            expand_points=["P1确认异常符号与危险有关"],
        ),
        state.SceneDevelopment(
            scene_id="S3", pacing_mode="DRAMATIZE",
            expand_points=["P1确认危险解除后的稳定状态"],
        ),
    ])


def _story_validation(**overrides):
    values = {
        "user_request_ok": True,
        "causal_constraints_ok": True,
        "character_consistency_ok": True,
        "ending_ok": True,
        "unsupported_solution_ok": True,
        "overall_ok": True,
        "repairable": False,
        "issues": [],
        "ending_evidence": [{
            "requirement_index": 0, "scene_id": "S3", "evidence": "P1确认危险解除",
        }],
        "function_execution_evidence": [
            {
                "segment_index": 1, "function_name": "F1", "scene_id": "S1",
                "evidence": "P1发现符号并因此确认危险，开始追查",
                "status": "PASS",
            },
            {
                "segment_index": 2, "function_name": "F2", "scene_id": "S2",
                "evidence": "P1关闭危险源，危险消失并恢复安全",
                "status": "PASS",
            },
        ],
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


def test_load_outline_document_adapts_legacy_ending_and_literary_design(monkeypatch):
    source = _source()
    source["narrative_plan"].pop("ending")
    source["literary_design"].pop("literary_ending")
    _mock_store(monkeypatch, source)

    loaded = app.load_outline_document("knowledge.db", "OUT_TEST")

    assert loaded["narrative_plan"]["ending"] == source["outline"]["ending"]
    assert "literary_ending" not in loaded["literary_design"]
    assert loaded["literary_design"]["steps"][0]["function_name"] == "F1"


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
    assert any("结局" in issue for issue in app._scene_plan_issues(source, incomplete))


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


def test_scene_developments_align_by_plan_order():
    plan = app.build_scene_plan(_source(), _scene_plan_draft().model_dump())
    developments = _scene_developments().model_dump()
    for index, item in enumerate(developments["developments"], 1):
        item["scene_id"] = f"model-{index}"
    developments = app.align_scene_developments(plan, developments)
    assert [item["scene_id"] for item in developments["developments"]] == ["S1", "S2", "S3"]
    developments["developments"].pop()
    with pytest.raises(ValueError, match="一一对应"):
        app.align_scene_developments(plan, developments)


def test_prompts_do_not_promote_relationships_beyond_outline_evidence():
    assert "状态上界" in app.FUNCTION_CONSTRAINT_PROMPT
    assert "场景结构" in app.SCENE_PLAN_PROMPT
    assert "中篇网文小说场景结构策划" in app.SCENE_PLAN_PROMPT
    assert "短篇故事场景结构策划" not in app.SCENE_PLAN_PROMPT
    assert "allowed_character_ids" in app.SCENE_PLAN_PROMPT
    assert "相邻场景应把已有的压力、信息、选择、代价或关系变化继续向前落实" in app.SCENE_PLAN_PROMPT
    assert "transition 只承接已有的 connective_event、causal_to_next 或未决后果" in app.SCENE_PLAN_PROMPT
    assert "不新增核心事件" in app.SCENE_PLAN_PROMPT
    assert "pacing_mode" not in app.SCENE_PLAN_PROMPT
    assert "pacing_mode" in app.DEVELOP_SCENES_PROMPT
    assert "literary_plan" not in app.DEVELOP_SCENES_PROMPT
    assert "不撰写正文" in app.DEVELOP_SCENES_PROMPT
    assert "scene_developments" in app.STORY_PROMPT
    assert "中篇网文小说作者" in app.STORY_PROMPT
    assert "短篇小说作者" not in app.STORY_PROMPT
    assert "避免抽象总结" in app.STORY_PROMPT
    assert "scene_plan 规定的是结构结果，不是逐句写法" in app.STORY_PROMPT
    assert "可以补充不改变主线因果的对话、心理、身体反应、职业细节、环境反应、日常动作和自然过渡" in app.STORY_PROMPT
    assert "关系上界、核心冲突或用户指定的结局" in app.STORY_PROMPT
    assert "具体动作、对话、证据、物件变化、身体反应" in app.STORY_PROMPT
    assert "根据情节重要性和 pacing_mode 自然分配篇幅" in app.STORY_PROMPT
    assert "DRAMATIZE 充分展开" in app.STORY_PROMPT
    assert "DEVELOP 适度展开" in app.STORY_PROMPT
    assert "COMPRESS 简洁处理" in app.STORY_PROMPT
    assert "整体篇幅必须达到 10000 字以上" in app.STORY_PROMPT
    assert "不得通过重复或注水凑数" in app.STORY_PROMPT
    assert "软性建议" not in app.STORY_PROMPT
    assert "writing_requirements" not in app.STORY_PROMPT
    assert "机械重复" in app.STORY_PROMPT
    assert "作为记忆锚点" not in app.STORY_PROMPT
    assert "Function 与 ending 不重复承担同一核心事件" in app.STORY_PROMPT
    assert "重演 Function 核心行动" not in app.STORY_PROMPT
    assert "literary_ending 的表达边界" not in app.STORY_PROMPT
    assert "creative_brief" not in app.STORY_PROMPT
    assert "不得新增核心人物、冲突、关键线索、援助、解决方案或关系升级" not in app.STORY_PROMPT
    assert "Function 场景只完成指定行动" not in app.STORY_PROMPT
    assert "literary_design 作为表达和局部展开依据" in app.STORY_PROMPT
    assert "视角、气质、感官、意象和潜台词" in app.STORY_PROMPT
    assert "不是必须完成的结局义务" in app.STORY_VALIDATOR_PROMPT
    assert "允许制度、阵营和利益余波存在" in app.STORY_VALIDATOR_PROMPT
    assert "同尺度的直接后果" in app.STORY_VALIDATOR_PROMPT
    assert "ending_evidence" in app.STORY_VALIDATOR_PROMPT
    assert "function_execution_evidence" in app.STORY_VALIDATOR_PROMPT
    assert "ending_evidence 只是诊断记录" in app.STORY_VALIDATOR_PROMPT
    assert "事件所有权规则" in app.SCENE_PLAN_PROMPT
    assert "固定输入" in app.STORY_VALIDATOR_PROMPT
    assert "自相矛盾" in app.STORY_VALIDATOR_PROMPT
    assert "正文中文字符数必须达到 10000" in app.STORY_VALIDATOR_PROMPT
    assert "若低于 10000，overall_ok=false、repairable=true" in app.STORY_VALIDATOR_PROMPT
    assert "10000 字是本系统默认要求" in app.STORY_VALIDATOR_PROMPT
    assert "系统建议的 10000 字以上不构成门槛" not in app.STORY_VALIDATOR_PROMPT
    assert "未明确提出时忽略长度" not in app.STORY_VALIDATOR_PROMPT
    assert "篇幅不足" in app.STORY_VALIDATOR_PROMPT
    assert "creative_brief" not in app.STORY_VALIDATOR_PROMPT
    assert all(
        "json" in prompt.lower()
        for prompt in (app.STORY_PROMPT, app.STORY_VALIDATOR_PROMPT)
    )


def test_scene_plan_appends_independent_ending_scene():
    plan = app.build_scene_plan(_source(), _scene_plan_draft().model_dump())
    assert [scene["scene_id"] for scene in plan["scenes"]] == ["S1", "S2", "S3"]
    assert plan["scenes"][1]["function_names"] == ["F2"]
    assert plan["scenes"][2]["is_ending"] is True
    assert plan["scenes"][2]["source_segment_indices"] == []
    assert app._scene_plan_issues(_source(), plan) == []


def test_scene_plan_rejects_ending_repeating_function_action():
    source = _source()
    plan = app.build_scene_plan(source, _scene_plan_draft().model_dump())
    plan["scenes"][-1]["beats"] = ["P1解决危险"]
    issues = app._scene_plan_issues(source, plan)
    assert any("同一事件只能由一个结构段负责" in issue for issue in issues)


def test_scene_development_keeps_only_execution_hints():
    development = state.SceneDevelopment.model_validate({
        "scene_id": "S1",
        "pacing_mode": "DEVELOP",
        "expand_points": ["P1继续追查"],
    })

    assert development.model_dump() == {
        "scene_id": "S1",
        "pacing_mode": "DEVELOP",
        "expand_points": ["P1继续追查"],
    }


def test_function_execution_evidence_checks_target_and_scene_order():
    source = _source()
    plan = app.build_scene_plan(source, _scene_plan_draft().model_dump())
    validation = _story_validation().model_dump()
    assert app._function_execution_issues(source, plan, validation) == []

    validation["function_execution_evidence"][1]["status"] = "MISSING"
    issues = app._function_execution_issues(source, plan, validation)
    assert any("正文执行缺失" in issue for issue in issues)

    validation["function_execution_evidence"][1]["status"] = "PASS"
    validation["function_execution_evidence"][0]["scene_id"] = "S3"
    assert any("不属于对应 Function 场景" in issue for issue in app._function_execution_issues(
        source, plan, validation,
    ))


def test_validate_story_node_turns_missing_function_into_causal_failure(monkeypatch):
    source = _source()
    plan = app.build_scene_plan(source, _scene_plan_draft().model_dump())
    validation = _story_validation(
        function_execution_evidence=[
            {
                "segment_index": 1, "function_name": "F1", "scene_id": "S1",
                "evidence": "P1发现符号并确认危险",
                "status": "PASS",
            },
            {
                "segment_index": 2, "function_name": "F2", "scene_id": "S2",
                "evidence": "正文没有写出关闭危险源或危险消失",
                "status": "MISSING",
            },
        ],
    )
    monkeypatch.setattr(app, "chat_structured", lambda *_args, **_kwargs: validation)
    result = app.validate_story_node({
        "outline_data": source,
        "user_request": None,
        "function_constraints": _function_constraints().model_dump(),
        "scene_plan": plan,
        "scene_developments": _scene_developments().model_dump(),
        "story": {"scenes": [{"scene_id": "S1", "text": "正文" * 2000}]},
        "story_repair_count": 0,
    })
    checked = result["story_validation"]
    assert checked["causal_constraints_ok"] is False
    assert checked["overall_ok"] is False
    assert any("正文执行缺失" in issue for issue in checked["issues"])


def test_graph_end_to_end(tmp_path, monkeypatch):
    _mock_store(monkeypatch, _source())
    calls = []

    def fake_chat(messages, output_schema, **_kwargs):
        calls.append(output_schema)
        payload = json.loads(messages[-1]["content"])
        if output_schema is state.FunctionConstraintPlan:
            assert payload["contract_ledger"]["enabled"] is False
            assert payload["ending_target"] == {
                "source": "llm_seed",
                "resolves": "c",
                "must_show": ["展示直接结果"],
                "final_state": "seed创作的稳定终态",
            }
            assert "ending_spec" not in payload
            return _function_constraints()
        if output_schema is state.ScenePlanDraft:
            assert payload["function_constraints"]["segments"][0]["function_name"] == "F1"
            assert payload["narrative_plan"]["steps"][0]["genre_realization"]
            assert payload["narrative_plan"]["ending"]["final_state"] == "P1安全"
            assert payload["literary_design"]["global_design"]["tone"] == "克制"
            assert payload["literary_design"]["literary_ending"]["sensory_anchor"] == "潮湿墙面"
            assert payload["allowed_character_ids"] == ["P1"]
            return _scene_plan_draft()
        if output_schema is state.SceneDevelopmentPlan:
            assert payload["scene_plan"]["scenes"][0]["scene_id"] == "S1"
            assert payload["scene_plan"]["scenes"][-1]["is_ending"] is True
            assert "mechanism_plan" not in payload
            assert payload["literary_design"]["steps"][0]["delivery_mode"] == "DEVELOP"
            assert payload["literary_design"]["literary_ending"]["delivery_mode"] == "DEVELOP"
            return _scene_developments()
        if output_schema is state.StoryDraft:
            assert _kwargs["reasoning_effort"] == "medium"
            assert sum("保留原始创作要求" in message["content"] for message in messages) == 1
            assert not any(
                message["content"].startswith("补充创作要求：")
                for message in messages
            )
            assert "story" not in payload["function_constraints"]
            assert "mechanism_plan" not in payload
            assert "narrative_plan" not in payload
            assert payload["literary_design"]["global_design"]["tone"] == "克制"
            assert payload["literary_design"]["literary_ending"]["closing_action_or_image"] == "P1收起工具"
            assert [item["scene_id"] for item in payload["scene_developments"]["developments"]] == ["S1", "S2", "S3"]
            assert "writing_requirements" not in payload
            short_text = "他在仓库里解决了危险。"
            return state.StoryDraft(title="雾中灯塔", character_names={"P1": "林晚"}, scenes=[
                state.StoryScene(scene_id="S2", text=short_text),
                state.StoryScene(scene_id="S1", text=short_text),
                state.StoryScene(scene_id="S3", text=short_text),
            ])
        if output_schema is state.StoryValidation:
            assert "min_chinese_chars" not in payload
            assert payload["chinese_char_count"] < 10000
            return _story_validation()
        raise AssertionError(output_schema)

    monkeypatch.setattr(app, "chat_structured", fake_chat)
    result = app._build_graph().invoke({
        "outline_id": "OUT_TEST", "knowledge_db": "knowledge.db",
        "user_request": "保留原始创作要求", "out_dir": str(tmp_path / "stories"),
        "outline_data": None, "function_constraints": None,
        "scene_plan": None, "scene_developments": None,
        "story": None, "story_validation": None,
        "first_story_validation": None, "story_revalidation": None,
        "story_repair_count": 0, "result_path": "",
    })
    with open(result["result_path"], encoding="utf-8") as f:
        exported = json.load(f)
    assert [scene["scene_id"] for scene in exported["story"]["scenes"]] == ["S1", "S2", "S3"]
    assert [item["scene_id"] for item in exported["scene_developments"]["developments"]] == ["S1", "S2", "S3"]
    assert calls == [
        state.FunctionConstraintPlan,
        state.ScenePlanDraft,
        state.SceneDevelopmentPlan,
        state.StoryDraft,
        state.StoryValidation,
    ]
    assert [item["segment_index"] for item in exported["function_constraints"]["segments"]] == [1, 2]
    assert exported["source_outline"]["contract_ledger"]["enabled"] is False
    assert exported["source_outline"]["literary_design"]["global_design"]["tone"] == "克制"
    assert exported["source_outline"]["validation"]["overall_ok"] is True
    assert exported["source_outline_id"] == "OUT_TEST"
    assert exported["story"]["character_names"] == {"P1": "林晚"}
    assert exported["story_status"] == "accepted"
    assert exported["chinese_char_count"] < 10000
    assert "length_ok" not in exported
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
            long_text = "他在仓库里解决了危险。" * 340
            return state.StoryDraft(
                title="雾中灯塔", character_names={"P1": "林晚"}, scenes=[
                    state.StoryScene(scene_id="S1", text=long_text),
                    state.StoryScene(scene_id="S2", text=long_text),
                    state.StoryScene(scene_id="S3", text=long_text),
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


def test_story_validator_rewrites_after_function_execution_failure(tmp_path, monkeypatch):
    failed = _story_validation(
        overall_ok=False,
        repairable=True,
        causal_constraints_ok=False,
        issues=["第 2 段 Function 正文执行缺失"],
        function_execution_evidence=[
            {
                "segment_index": 1, "function_name": "F1", "scene_id": "S1",
                "evidence": "P1发现符号并确认危险",
                "status": "PASS",
            },
            {
                "segment_index": 2, "function_name": "F2", "scene_id": "S2",
                "evidence": "正文没有写出关闭危险源或危险消失",
                "status": "MISSING",
            },
        ],
    )
    exported, calls, _ = _run_story_graph(
        tmp_path, monkeypatch, [failed, _story_validation()],
    )

    assert calls.count(state.StoryDraft) == 2
    assert exported["story_status"] == "rewritten"
    assert exported["first_story_validation"]["causal_constraints_ok"] is False
    assert exported["story_revalidation"]["overall_ok"] is True


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
