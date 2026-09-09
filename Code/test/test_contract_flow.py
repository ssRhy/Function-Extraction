"""验证 FunctionContract 从 Pattern 输入穿透到 Outline 账本。"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Contracts.ledger import build_contract_ledger, normalize_relationship_befores
from Contracts.state_vocabulary import StateVocabulary, canonical_id
from Outline_Agent import app as outline
from Outline_Agent import state as outline_state


def _contract(function_id, name, before, after, *, opens=None, resolves=None):
    return {
        "function_id": function_id,
        "function_name": name,
        "role_slots": ["actor"],
        "preconditions": [{"role_slots": ["actor"], "aspect": "MISSION", "state": before}],
        "effects": [{
            "role_slots": ["actor"], "aspect": "MISSION",
            "before": before, "after": after,
        }],
        "obligation_effects": {
            "opens": opens or [], "advances": [], "resolves": resolves or [],
        },
    }


def _mechanism(name):
    return {
        "function_name": name,
        "role_bindings": {"actor": "P1"},
        "state_change": "推进状态",
    }


def test_contract_ledger_applies_effects_and_resolves_obligation():
    opening = {"key": "REPAIR_TRUST", "role_slots": ["actor"], "description": "修复信任", "satisfied_when": "信任恢复"}
    chain = [
        {"function_name": "OPEN", "contract": _contract("F1", "OPEN", "UNKNOWN", "ACTIVE", opens=[opening])},
        {"function_name": "CLOSE", "contract": _contract("F2", "CLOSE", "ACTIVE", "RESOLVED", resolves=[opening])},
    ]
    ledger = build_contract_ledger(
        chain,
        [_mechanism("OPEN"), _mechanism("CLOSE")],
        {"characters": [{"id": "P1"}]},
    )

    assert ledger["enabled"] is True
    assert ledger["issues"] == []
    assert ledger["obligations"] == []
    assert ledger["states"] == [{"role": "P1", "aspect": "MISSION", "state": "RESOLVED"}]


def test_contract_ledger_keeps_repeated_function_steps_by_segment_index():
    contract = _contract("F1", "REPEAT", "UNKNOWN", "KNOWN")
    chain = [
        {"segment_index": 1, "function_name": "REPEAT", "contract": contract},
        {"segment_index": 2, "function_name": "REPEAT", "contract": contract},
    ]
    steps = [
        {
            "segment_index": 1, "function_name": "REPEAT",
            "role_bindings": {"actor": "P1"}, "state_change": "P1完成变化",
        },
        {
            "segment_index": 2, "function_name": "REPEAT",
            "role_bindings": {"actor": "P2"}, "state_change": "P2完成变化",
        },
    ]

    ledger = build_contract_ledger(
        chain, steps, {"characters": [{"id": "P1"}, {"id": "P2"}]},
    )

    assert [item["segment_index"] for item in ledger["transitions"]] == [1, 2]
    assert [item["role_bindings"] for item in ledger["transitions"]] == [
        {"actor": "P1"}, {"actor": "P2"},
    ]


def test_relationship_before_is_inherited_across_repeated_steps():
    relation_contract = {
        "role_slots": ["actor", "affected"],
        "preconditions": [],
        "effects": [{
            "aspect": "RELATIONSHIP_STATUS", "role_slots": ["actor", "affected"],
            "before": "未建立", "after": "已建立",
        }],
        "obligation_effects": {},
    }
    chain = [
        {"segment_index": 1, "function_name": "RELATE", "contract": relation_contract},
        {"segment_index": 2, "function_name": "RELATE", "contract": relation_contract},
    ]
    steps = [
        {
            "segment_index": 1, "function_name": "RELATE",
            "role_bindings": {"actor": "P1", "affected": "P2"},
            "state_change": "建立关系", "character_state_changes": {"P1": "a", "P2": "b"},
            "relationship_changes": [{
                "source_id": "P1", "target_id": "P2", "dimension": "trust",
                "before": "模型猜测", "after": "初步信任", "evidence": "P1承担代价",
            }],
        },
        {
            "segment_index": 2, "function_name": "RELATE",
            "role_bindings": {"actor": "P1", "affected": "P2"},
            "state_change": "加深关系", "character_state_changes": {"P1": "c", "P2": "d"},
            "relationship_changes": [{
                "source_id": "P1", "target_id": "P2", "dimension": "trust",
                "before": "仍然猜测", "after": "稳定信任", "evidence": "P2回报承诺",
            }],
        },
    ]
    normalized = normalize_relationship_befores(
        chain, steps, {"characters": [{"id": "P1"}, {"id": "P2"}]},
    )
    assert normalized[0]["relationship_changes"][0]["before"] == "未建立"
    assert normalized[1]["relationship_changes"][0]["before"] == "初步信任"
    assert build_contract_ledger(
        chain, normalized, {"characters": [{"id": "P1"}, {"id": "P2"}]},
    )["relationship_ledger"]["issues"] == []


def test_contract_ledger_reports_binding_and_transition_breaks():
    chain = [
        {"function_name": "OPEN", "contract": _contract("F1", "OPEN", "UNKNOWN", "ACTIVE")},
        {"function_name": "CLOSE", "contract": _contract("F2", "CLOSE", "MISSING", "RESOLVED")},
    ]
    ledger = build_contract_ledger(
        chain,
        [{"function_name": "OPEN", "role_bindings": {}, "state_change": ""}, _mechanism("CLOSE")],
        {"characters": [{"id": "P1"}]},
    )

    assert any("缺少角色绑定" in issue for issue in ledger["issues"])
    assert any("前置状态" in warning for warning in ledger["warnings"])


def test_state_vocabulary_is_deterministic_and_keeps_raw_evidence():
    contracts = [_contract("F1", "OPEN", "关系紧张", "关系缓和")]
    vocabulary = StateVocabulary.from_contracts(contracts)
    assert vocabulary.canonical("aspect", " MISSION ") == "MISSION"
    assert vocabulary.canonical("state", "关系紧张") == canonical_id("state", "关系紧张")
    entry = next(item for item in vocabulary.entries if item["canonical_id"] == canonical_id("state", "关系紧张"))
    assert entry["aliases"] == ["关系紧张"]
    assert entry["raw_evidence"] == ["关系紧张"]


def test_contract_ledger_exposes_state_vocabulary_without_changing_raw_states():
    contract = _contract("F1", "OPEN", "UNKNOWN", "KNOWN")
    ledger = build_contract_ledger(
        [{"function_name": "OPEN", "contract": contract}],
        [_mechanism("OPEN")],
        {"characters": [{"id": "P1"}]},
    )
    assert ledger["states"] == [{"role": "P1", "aspect": "MISSION", "state": "KNOWN"}]
    assert ledger["state_vocabulary"]["schema_version"] == 1


def test_planner_uses_snapshot_contracts_over_pattern_contract():
    contract = _contract("F1", "A", "UNKNOWN", "KNOWN")
    catalog = {"published_patterns": [{
        "pattern_id": "PAT_P",
        "pattern_name": "P",
        "story_support": 2,
        "category_counts": {"01_悬疑惊悚": 1},
        "core_function_chain": [{"function_id": "F1", "function_name": "A", "definition": "d"}],
    }]}
    pattern, chain = outline.planner(
        catalog,
        "01_悬疑惊悚",
        contracts={"F1": contract},
    )

    assert pattern["pattern_name"] == "P"
    assert chain[0]["contract"] == contract
    assert chain[0]["preconditions"] == contract["preconditions"]
    assert chain[0]["role_slots"] == contract["role_slots"]


def test_outline_graph_consumes_contract_and_exports_closed_ledger(tmp_path, monkeypatch):
    contract = _contract("F1", "A", "UNKNOWN", "KNOWN")
    catalog = {"published_patterns": [{
        "pattern_id": "PAT_P",
        "pattern_name": "P",
        "story_support": 2,
        "category_counts": {"01_悬疑惊悚": 1},
        "core_function_chain": [{"function_id": "F1", "function_name": "A", "definition": "d"}],
    }]}
    monkeypatch.setattr(outline, "load_catalog", lambda *_args: catalog)
    monkeypatch.setattr(outline, "load_contracts", lambda *_args: {"F1": contract})
    monkeypatch.setattr(outline, "load_planner_references", lambda *_args: {
        "motifs": [], "transitions": {}, "instance_cases": {},
    })

    def fake_chat(_messages, output_schema, **_kwargs):
        if output_schema is outline.StorySeed:
            return outline.StorySeed(
                genre="悬疑惊悚", world_setting="w",
                characters=[outline_state.SeedCharacter(
                    id="P1", label="主角", role="hero", goal="g",
                    motivation="m", relationships={}, stance_toward_protagonist="self",
                )],
                core_conflict="c", ending_direction="e",
                ending_requirements=["完成c的可观察结果"],
            )
        if output_schema is outline.MechanismPlan:
            return outline.MechanismPlan(steps=[outline_state.MechanismStep(
                segment_index=1, function_name="A", role_bindings={"actor": "P1"},
                who_does_what="P1行动", why="c", state_change="UNKNOWN变为KNOWN",
                character_state_changes={"P1": "未知 → 行动证据 → 已知"}, connects_to_next="结束",
            )])
        if output_schema is outline.NarrativePlan:
            return outline.NarrativePlan(steps=[outline_state.NarrativeStep(
                segment_index=1, function_name="A", genre_realization="P1执行题材化行动",
                connective_event="进入结局",
            )])
        if output_schema is outline.OutlineRealization:
            return outline.OutlineRealization(
                segments=[outline_state.OutlineSegment(segment_index=1, function_name="A", beats=["完成变化"], link="进入结局收束")],
                final_ledger=["目标已处理"],
                ending=outline_state.EndingRealization(
                    resolution_actions=["完成解决"],
                    conflict_resolution="核心冲突已解决",
                    final_state="达到稳定终态",
                ),
            )
        if output_schema is outline.OutlineValidation:
            assert "warnings" not in json.loads(_messages[-1]["content"])["contract_ledger"]
            return outline.OutlineValidation(
                segment_checks=[outline_state.SegmentCheck(segment_index=1, function_name="A", recoverable=True, issue="")],
                overall_ok=True, issues=[],
            )
        raise AssertionError(output_schema)

    monkeypatch.setattr(outline, "chat_structured", fake_chat)
    class FakeStore:
        def __init__(self, _path):
            pass

        def load_pattern_feedback(self, _snapshot_id):
            return {}

        def used_pattern_ids(self):
            return set()

        def claim_pattern(self, snapshot_id, pattern_id):
            assert snapshot_id == "contract-snapshot"
            assert pattern_id == "PAT_P"

        def record_outline(self, _document, _markdown):
            return "OUT_CONTRACT"

        def record_generation_outcome(self, *args, **kwargs):
            assert args[2] == "OUT_CONTRACT"

    monkeypatch.setattr(outline, "StoryKnowledgeStore", FakeStore)
    result = outline._build_graph().invoke({
        "snapshot_id": "contract-snapshot", "genre": "01_悬疑惊悚", "out_dir": str(tmp_path),
        "knowledge_db": str(tmp_path / "knowledge.db"),
        "pattern_request": None, "user_request": None, "pattern_id": None,
        "pattern_name": "", "chain": [],
        "seed": None, "mechanism": None, "narrative": None, "contract_ledger": None,
        "outline": None, "validation": None, "outline_id": "", "result_path": "",
    })

    assert result["chain"][0]["contract"] == contract
    assert result["contract_ledger"]["enabled"] is True
    assert result["contract_ledger"]["issues"] == []
    assert result["validation"]["contract_issues"] == []
    assert result["validation"]["overall_ok"] is True
    exported = json.loads(open(result["result_path"], encoding="utf-8").read())
    assert exported["contract_ledger"]["states"][0]["state"] == "KNOWN"
    assert exported["narrative_plan"]["steps"][0]["function_name"] == "A"
