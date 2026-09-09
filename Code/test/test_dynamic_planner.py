"""动态 Planner：操作扩展、硬校验、去重分类和 Outline 图分支。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import Outline_Agent.app as outline
import Outline_Agent.dynamic_planner as dynamic
from KnowledgeBase import StoryKnowledgeStore


def _contract(function_id, name, before="UNKNOWN", after="KNOWN"):
    return {
        "function_id": function_id,
        "function_name": name,
        "role_slots": ["actor"],
        "preconditions": [{
            "role_slots": ["actor"], "aspect": "MISSION", "state": before,
        }],
        "effects": [{
            "role_slots": ["actor"], "aspect": "MISSION",
            "before": before, "after": after,
        }],
        "obligation_effects": {"opens": [], "advances": [], "resolves": []},
    }


def _references():
    functions = [
        {"function_id": f"F{i}", "function_name": f"F{i}", "definition": f"d{i}"}
        for i in range(1, 5)
    ]
    contracts = {
        f"F{i}": _contract(f"F{i}", f"F{i}") for i in range(1, 5)
    }
    return {
        "functions": functions,
        "contracts": contracts,
        "state_vocabulary": {"schema_version": 1, "entries": []},
        "transitions": {"F1": [{"to": "F2", "count": 3, "support_stories": 2}]},
        "instance_cases": {},
        "motifs": [
            {"motif_id": "M1", "function_ids": ["F1", "F2"],
             "function_names": ["F1", "F2"], "story_support": 3},
            {"motif_id": "M2", "function_ids": ["F3", "F4"],
             "function_names": ["F3", "F4"], "story_support": 2},
        ],
        "published_patterns": [{"pattern_id": "P1", "function_ids": ["F1", "F2"]}],
    }


def _seed():
    return {"characters": [{"id": "P1"}], "core_conflict": "c"}


def test_beam_prompt_omits_raw_role_and_relationship_blocks():
    references = _references()
    references["role_stats"] = {"F1": {"positions": {"actor": {"binding_count": 4}}}}
    references["relationship_cases"] = {"F1": [{"dimension": "trust"}]}

    prompt = dynamic._planner_prompt(_seed(), "目标", [], references)

    assert '"role_stats"' not in prompt
    assert '"relationship_cases"' not in prompt
    assert '"transitions"' in prompt
    assert '"motif_menu"' in prompt


def test_dynamic_operations_expand_only_declared_motifs_and_functions():
    references = _references()
    cases = [
        ("REUSE_MOTIF", ["F1", "F2"], ["M1"]),
        ("COMPOSE_MOTIFS", ["F1", "F2", "F3", "F4"], ["M1", "M2"]),
        ("MUTATE_MOTIF", ["F1", "F3"], ["M1"]),
        ("BRIDGE", ["F3"], []),
        ("EXPLORE", ["F4"], []),
    ]
    for operation, function_ids, motif_ids in cases:
        extension = dynamic.DynamicExtension(
            operation=operation, function_ids=function_ids, motif_ids=motif_ids,
            reason="满足目标", expected_state="状态推进", complete=True,
        )
        assert dynamic._expanded_function_ids(extension, references) == function_ids


def test_composition_merges_motif_boundary_overlap():
    references = _references()
    references["motifs"] = [
        {"motif_id": "M1", "function_ids": ["F1", "F2"], "function_names": ["F1", "F2"]},
        {"motif_id": "M2", "function_ids": ["F2", "F3"], "function_names": ["F2", "F3"]},
    ]
    extension = dynamic.DynamicExtension(
        operation="COMPOSE_MOTIFS", motif_ids=["M1", "M2"],
        function_ids=["F1", "F2", "F3"], overlap_sizes=[1],
        reason="合并重复边界", expected_state="形成新转移", novelty_reason="F2只保留一次",
    )
    assert dynamic._expanded_function_ids(extension, references) == ["F1", "F2", "F3"]
    repaired = dynamic.DynamicExtension(
        operation="COMPOSE_MOTIFS", motif_ids=["M1", "M2"],
        function_ids=["F1", "F4"], overlap_sizes=[2],
        reason="模型给出不合法重叠", expected_state="程序修正",
    )
    assert dynamic._expanded_function_ids(repaired, references) == ["F1", "F2", "F3"]
    report = dynamic._structure_novelty(
        ["F1", "F2", "F3"],
        [{"motif_ids": ["M1", "M2"], "boundary_overlap": 0, "internal_overlap_sizes": [1],
          "novelty_reason": "F2只保留一次"}],
        references,
    )
    assert report["overlap_count"] == 1
    assert report["novelty_score"] > 0


def test_cross_extension_repeat_is_rejected_but_motif_internal_repeat_is_allowed():
    references = _references()
    references["motifs"] = [{
        "motif_id": "M_LOOP", "function_ids": ["F1", "F2", "F1"],
        "function_names": ["F1", "F2", "F1"],
    }]
    extension = dynamic.DynamicExtension(
        operation="REUSE_MOTIF", motif_ids=["M_LOOP"],
        function_ids=["F1", "F2", "F1"], reason="保留 motif 内部回环",
        expected_state="回环后继续推进", complete=True,
    )
    assert dynamic.validate_dynamic_chain(
        ["F1", "F2", "F1"], references, _seed(), allowed_repeat_ids={"F1"}
    )["valid"]
    with pytest.raises(ValueError, match="跨段重复"):
        dynamic._extension_append(["F1"], extension, references)


def test_dynamic_hard_validation_rejects_unknown_ids_contracts_and_order():
    references = _references()
    invalid = dynamic.validate_dynamic_chain(["F1", "UNKNOWN"], references, _seed())
    assert invalid["valid"] is False
    assert any("Function ID" in issue for issue in invalid["hard_issues"])

    missing_contract = {**references, "contracts": {"F1": references["contracts"]["F1"]}}
    invalid = dynamic.validate_dynamic_chain(["F1", "F2"], missing_contract, _seed())
    assert invalid["valid"] is False
    assert any("FunctionContract" in issue for issue in invalid["hard_issues"])

    invalid = dynamic.validate_dynamic_chain(["F1", "F1"], references, _seed())
    assert invalid["valid"] is False
    assert any("重复 Function" in issue for issue in invalid["hard_issues"])


def test_dynamic_beam_deduplicates_and_classifies_reuse_variant_novel():
    extensions = [
        dynamic.DynamicExtension(
            operation="REUSE_MOTIF", motif_ids=["M1"], function_ids=["F1", "F2"],
            reason="复用成熟结构", expected_state="已知", goal_fit=0.9, complete=True,
        ),
        dynamic.DynamicExtension(
            operation="COMPOSE_MOTIFS", motif_ids=["M1", "M2"],
            function_ids=["F1", "F2", "F3", "F4"],
            reason="拼接两段结构", expected_state="危机升级", goal_fit=0.8, complete=True,
        ),
        dynamic.DynamicExtension(
            operation="EXPLORE", function_ids=["F3", "F4"], motif_ids=[],
            reason="从 Function 探索", expected_state="关系改变", goal_fit=0.7, complete=True,
        ),
    ]

    def fake_llm(_messages, output_schema, **_kwargs):
        assert output_schema is dynamic.DynamicPlanResponse
        return dynamic.DynamicPlanResponse(extensions=extensions)

    candidates = dynamic.generate_dynamic_candidates(
        _seed(), _references(), "目标", llm=fake_llm,
    )
    assert len(candidates) == 3
    assert len({tuple(item["function_ids"]) for item in candidates}) == 3
    assert {item["classification"] for item in candidates} == {"REUSE", "VARIANT", "NOVEL"}
    assert all(item["pattern_id"] is None for item in candidates)
    assert all(item["validation"]["valid"] for item in candidates)


def test_beam_retention_uses_quality_and_removes_near_duplicate_paths():
    references = _references()

    def beam(function_ids):
        names = {item["function_id"]: item["function_name"] for item in references["functions"]}
        steps = [{
            "function_id": function_id, "function_name": names[function_id],
            "motif_ids": [], "boundary_overlap": 0,
            "internal_overlap_sizes": [], "novelty_reason": "新结构",
        } for function_id in function_ids]
        return {
            "steps": steps,
            "score_parts": [0.8] * len(steps),
            "operations": ["EXPLORE"],
            "validation": dynamic.validate_dynamic_chain(
                function_ids, references, _seed(),
            ),
        }

    selected = dynamic._select_diverse_beams([
        beam(["F1", "F2", "F3"]),
        beam(["F1", "F2", "F3", "F4"]),
        beam(["F3", "F4"]),
    ], references, 2)
    assert [tuple(step["function_id"] for step in item["steps"]) for item in selected] == [
        ("F1", "F2", "F3"), ("F3", "F4"),
    ]


def test_stalled_beam_is_completed_without_llm_complete_flag():
    calls = []

    def fake_llm(_messages, _output_schema, **_kwargs):
        calls.append(1)
        function_id = "F1" if len(calls) == 1 else "F2" if len(calls) == 2 else "F1"
        return dynamic.DynamicPlanResponse(extensions=[dynamic.DynamicExtension(
            operation="EXPLORE", function_ids=[function_id],
            reason="继续推进", expected_state="状态推进", complete=False,
        )])

    candidates = dynamic.generate_dynamic_candidates(
        _seed(), _references(), "目标", llm=fake_llm,
    )
    assert [item["function_ids"] for item in candidates] == [["F1", "F2"]]


def test_build_dynamic_references_reads_snapshot_inputs(monkeypatch):
    class FakeStore:
        def __init__(self, _path):
            pass

        def load_functions(self, snapshot_id):
            assert snapshot_id == "snapshot_x"
            return [{"function_id": "F1", "function_name": "A", "definition": "d"}]

        def load_contracts(self, _snapshot_id):
            return [_contract("F1", "A")]

        def load_occurrences(self, _snapshot_id):
            return [{
                "occurrence_id": "o1", "story_id": "s1", "status": "MATCHED",
                "function_name": "A", "observation_order": 1,
                "surface_form": "一次行动",
                "participant_ids": ["P1"],
                "role_bindings": {"actor": ["P1"]},
                "relationship_deltas": [],
            }]

        def load_story_profiles(self, _snapshot_id):
            return [{
                "story_id": "s1", "story_version_id": "SV1", "profile": {
                    "world_setting": "w", "protagonist_id": "P1",
                    "characters": [{
                        "id": "P1", "label": "主角", "structural_role": "protagonist",
                        "long_term_goal": "g", "motivation": "m",
                    }], "relationships": [], "core_conflict": "c", "ending_state": "e",
                },
            }]

        def load_pattern_catalog(self, _snapshot_id):
            return {"published_patterns": [{
                "pattern_id": "P1", "pattern_name": "P",
                "member_motif_ids": ["M1"],
                "core_function_chain": [{"function_id": "F1", "function_name": "A"}],
            }]}

        def load_motif_evidence(self, _snapshot_id):
            return [{
                "motif_id": "M1", "function_ids": ["F1"],
                "function_names": ["A"], "length": 1,
                "evidence": {"story_id": "s1"},
            }]

    monkeypatch.setattr(dynamic, "StoryKnowledgeStore", FakeStore)
    references = dynamic.build_dynamic_references("snapshot_x", "knowledge.db")
    assert references["snapshot_id"] == "snapshot_x"
    assert list(references["contracts"]) == ["F1"]
    assert references["motifs"][0]["motif_id"] == "M1"
    assert references["instance_cases"]["A"][0]["surface_form"] == "一次行动"
    assert references["state_vocabulary"]["schema_version"] == 1


def test_dynamic_graph_keeps_candidate_in_memory_and_exports_null_pattern_id(tmp_path, monkeypatch):
    contract = _contract("F1", "A")
    contract["preconditions"] = []
    references = {
        "motifs": [], "transitions": {}, "instance_cases": {},
    }
    selected = {
        "candidate_id": "DYN_TEST", "classification": "NOVEL", "pattern_id": None,
        "chain": [{
            "segment_index": 1, "function_id": "F1", "function_name": "A",
            "definition": "d", "preconditions": [], "role_slots": ["actor"],
            "contract": contract,
        }],
    }
    monkeypatch.setattr(outline, "plan_dynamic_outline", lambda *_args: (
        references, [selected], selected,
    ))

    def fake_chat(_messages, output_schema, **_kwargs):
        if output_schema is outline.StorySeed:
            return outline.StorySeed(
                genre="现代情感", world_setting="w", characters=[{
                        "id": "P1", "label": "主角", "role": "hero", "goal": "g",
                        "motivation": "m", "relationships": {}, "stance_toward_protagonist": "self",
                }], core_conflict="c", ending_direction="e",
                ending_requirements=["完成c的可观察结果"],
            )
        if output_schema is outline.MechanismPlan:
            return outline.MechanismPlan(steps=[{
                "segment_index": 1, "function_name": "A",
                "role_bindings": {"actor": "P1"}, "who_does_what": "P1行动",
                "why": "c", "state_change": "推进", "character_state_changes": {"P1": "变化"},
                "connects_to_next": "结束",
            }])
        if output_schema is outline.NarrativePlan:
            return outline.NarrativePlan(steps=[{
                "segment_index": 1, "function_name": "A", "genre_realization": "行动",
            }])
        if output_schema is outline.OutlineRealization:
            return outline.OutlineRealization(
                segments=[{"segment_index": 1, "function_name": "A", "beats": ["完成"], "link": ""}],
                final_ledger=["c"], ending={
                    "resolution_actions": ["解决"], "conflict_resolution": "完成",
                    "final_state": "稳定",
                },
            )
        if output_schema is outline.OutlineValidation:
            return outline.OutlineValidation(
                segment_checks=[{"segment_index": 1, "function_name": "A", "recoverable": True, "issue": ""}],
                overall_ok=True, issues=[],
            )
        raise AssertionError(output_schema)

    monkeypatch.setattr(outline, "chat_structured", fake_chat)

    class FakeStore:
        def __init__(self, _path):
            pass

        def record_outline(self, document, _markdown):
            assert document["pattern_source"] == "dynamic"
            assert document["pattern_id"] is None
            assert document["dynamic_candidate"]["candidate_id"] == "DYN_TEST"
            return "OUT_DYNAMIC"

        def record_generation_outcome(self, *args, **kwargs):
            assert args[2] == "OUT_DYNAMIC"

    monkeypatch.setattr(outline, "StoryKnowledgeStore", FakeStore)
    result = outline._build_graph().invoke({
        "snapshot_id": "snapshot_x", "knowledge_db": str(tmp_path / "knowledge.db"),
        "genre": "03_现代情感", "out_dir": str(tmp_path),
        "pattern_request": None, "user_request": "目标", "planner_mode": "dynamic",
        "pattern_id": None, "pattern_name": "", "pattern_source": "dynamic",
        "pattern_selection": None, "ending_spec": None, "chain": [],
        "planner_references": None, "dynamic_candidates": [], "dynamic_candidate": None,
        "seed": None, "mechanism": None, "narrative": None, "contract_ledger": None,
        "outline": None, "validation": None, "outline_id": "", "result_path": "",
    })
    assert result["pattern_id"] is None
    assert result["pattern_source"] == "dynamic"
    assert result["dynamic_candidate"]["candidate_id"] == "DYN_TEST"


def test_dynamic_graph_reuses_preplanned_candidate(monkeypatch):
    selected = {
        "candidate_id": "DYN_SECOND",
        "chain": [{"function_id": "F1", "function_name": "A"}],
    }
    seed = {"core_conflict": "同一 Seed"}
    monkeypatch.setattr(
        outline,
        "plan_dynamic_outline",
        lambda *_args: pytest.fail("不应再次运行动态 Planner"),
    )
    monkeypatch.setattr(
        outline,
        "build_dynamic_references",
        lambda snapshot_id, knowledge_db: {
            "snapshot_id": snapshot_id, "knowledge_db": knowledge_db,
        },
    )

    result = outline.dynamic_planner_node({
        "snapshot_id": "snapshot_x",
        "knowledge_db": "knowledge.db",
        "dynamic_candidates": [selected],
        "dynamic_candidate": selected,
    })

    assert result["dynamic_candidate"] == selected
    assert result["dynamic_candidates"] == [selected]
    assert result["chain"] == selected["chain"]
    monkeypatch.setattr(
        outline,
        "chat_structured",
        lambda *_args: pytest.fail("预置 Seed 不应再次生成"),
    )
    assert outline.seed_node({"seed": seed}) == {"seed": seed}


def test_dynamic_outline_record_does_not_claim_pattern(tmp_path):
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    store.initialize()
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO snapshots(snapshot_id, schema_version, source_workflow, namespace, created_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("snapshot_x", 1, "bootstrap", "test", "2026-01-01T00:00:00Z", "{}"),
        )
    document = {
        "schema_version": 1, "snapshot_id": "snapshot_x", "pattern_id": None,
        "pattern_source": "dynamic", "pattern_name": "DYN_TEST", "genre": "03_现代情感",
        "generated_at": "2026-01-01T00:00:00", "validation": {"overall_ok": True},
        "outline": {"segments": []},
    }
    store.record_outline(document, "# 动态\n")
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pattern_usage").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM snapshot_patterns").fetchone()[0] == 0
