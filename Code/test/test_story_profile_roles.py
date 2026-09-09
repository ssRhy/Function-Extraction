"""StoryProfile、实例角色、关系投影与关系账本的边界测试。"""

import pytest

from Contracts.ledger import build_contract_ledger
from Contracts.occurrence import align_occurrences
from Contracts.role_projection import project_role_references
from Contracts.snapshot import publish_snapshot, validate_snapshot
from Contracts.versioning import observation_version_id
from FunctionExtract_Agent.Observer import observer as observer_module
from FunctionExtract_Agent.Observer.observer import ObservationResponse, observer_node


def _profile():
    return {
        "world_setting": "城邦",
        "protagonist_id": "P1",
        "characters": [
            {
                "id": "P1", "label": "主角", "structural_role": "protagonist",
                "long_term_goal": "保护家人", "motivation": "不愿重蹈覆辙",
                "evidence_sentence_indices": [0],
            },
            {
                "id": "P2", "label": "对手", "structural_role": "opponent",
                "long_term_goal": "夺取权力", "motivation": "害怕失去地位",
                "evidence_sentence_indices": [1],
            },
        ],
        "relationships": [{
            "source_id": "P2", "target_id": "P1", "relation_type": "opposition",
            "stance_toward_protagonist": "obstruct", "description": "阻碍主角",
            "evidence_sentence_indices": [1],
        }],
        "core_conflict": "权力争夺",
        "ending_state": "主角保住家人",
    }


def _observation(story_version_id="SV_1"):
    item = {
        "obs_id": "s1_obs_1", "story_id": "s1", "story_version_id": story_version_id,
        "observation_order": 1, "before_state": "双方对立", "event": "主角公开反击",
        "participants": ["主角", "对手"], "participant_ids": ["P1", "P2"],
        "role_bindings": {
            "actor": ["P1"], "affected": ["P2"], "information_provider": [],
            "resource_provider": [], "beneficiary": ["P1"], "obstacle": ["P2"],
        },
        "relationship_deltas": [{
            "source_id": "P1", "target_id": "P2", "dimension": "trust",
            "before": "低", "after": "更低", "evidence_sentence_indices": [1],
        }],
        "after_state": "对手失去优势", "affected_aspect": "RELATIONSHIP_STATUS",
        "narrative_effect": "冲突升级", "surface_form": "反击", "source_sentence_indices": [1],
    }
    item["observation_version_id"] = observation_version_id(story_version_id, item)
    return item


def test_observer_returns_profile_and_bound_observation(monkeypatch):
    response = ObservationResponse(
        story_profile=_profile(),
        observations=[_observation()],
    )
    monkeypatch.setattr(observer_module, "chat_structured", lambda *args, **kwargs: response)
    result = observer_node({
        "normalized_story": {
            "metadata": {"story_id": "s1", "story_version_id": "SV_1"},
            "sentences": ["主角想保护家人。", "对手阻碍主角。"],
        },
    })
    assert result["story_profile"]["protagonist_id"] == "P1"
    assert result["observations"][0]["role_bindings"]["actor"] == ["P1"]
    assert result["observations"][0]["relationship_deltas"][0]["target_id"] == "P2"


def test_observer_drops_out_of_range_profile_evidence(monkeypatch):
    profile = _profile()
    profile["characters"][0]["evidence_sentence_indices"] = [0, 9]
    profile["relationships"][0]["evidence_sentence_indices"] = [1, 9]
    response = ObservationResponse(story_profile=profile, observations=[])
    monkeypatch.setattr(observer_module, "chat_structured", lambda *args, **kwargs: response)

    result = observer_node({
        "normalized_story": {
            "metadata": {"story_id": "s1", "story_version_id": "SV_1"},
            "sentences": ["冲突开始。", "结局动作完成。"],
        },
    })

    output = result["story_profile"]
    assert output["characters"][0]["evidence_sentence_indices"] == [0]
    assert output["relationships"][0]["evidence_sentence_indices"] == [1]
    assert "丢弃" in result["messages"][0]["content"]


def test_snapshot_rejects_unknown_person_and_accepts_profile(tmp_path):
    profile = {"story_id": "s1", "story_version_id": "SV_1", "profile": _profile()}
    function = {
        "function_id": "F1", "function_name": "CONFRONTATION", "definition": "对抗阻碍",
        "supporting_obs_ids": ["s1_obs_1"],
    }
    occurrence = align_occurrences([function], [_observation()])[0]
    path = publish_snapshot(
        [function], {"verdict": "PASS"}, "bootstrap", "test", str(tmp_path),
        [occurrence], story_profiles=[profile],
    )
    assert validate_snapshot(path)["schema_version"] == 5
    occurrence["participant_ids"] = ["P999"]
    with pytest.raises(ValueError, match="未知人物"):
        publish_snapshot(
            [function], {"verdict": "PASS"}, "bootstrap", "test2", str(tmp_path),
            [occurrence], story_profiles=[profile],
        )


def test_role_projection_includes_goal_stance_and_relationship_case():
    occurrence = _observation()
    occurrence.update({"status": "MATCHED", "function_name": "CONFRONTATION", "function_id": "F1"})
    projection = project_role_references(
        [{"function_id": "F1", "function_name": "CONFRONTATION"}],
        [{"function_id": "F1", "function_name": "CONFRONTATION", "role_slots": ["actor", "affected"]}],
        [occurrence], [{"story_id": "s1", "story_version_id": "SV_1", "profile": _profile()}],
    )
    assert projection["role_stats"]["CONFRONTATION"]["positions"]["actor"]["protagonist_count"] == 1
    case = projection["relationship_cases"]["CONFRONTATION"][0]
    assert case["role_context"]["affected"][0]["stance_toward_protagonist"] == "obstruct"
    assert case["relationship_deltas"][0]["source_role"] == "protagonist"


def test_relationship_ledger_requires_contract_and_evidence():
    chain = [{
        "segment_index": 1, "function_name": "CONFRONTATION",
        "contract": {"role_slots": ["actor", "affected"], "preconditions": [], "effects": [{
            "aspect": "RELATIONSHIP_STATUS", "role_slots": ["actor", "affected"],
            "before": "low", "after": "high",
        }], "obligation_effects": {}},
    }]
    seed = {"characters": [
        {"id": "P1", "relationships": {"P2": "opposition"}},
        {"id": "P2", "relationships": {}},
    ]}
    steps = [{
        "segment_index": 1, "function_name": "CONFRONTATION",
        "role_bindings": {"actor": "P1", "affected": "P2"},
        "state_change": "对抗结果改变双方关系",
        "character_state_changes": {"P1": "changed", "P2": "changed"},
        "relationship_changes": [{
            "source_id": "P1", "target_id": "P2", "dimension": "trust",
            "before": "opposition", "after": "lower", "evidence": "当众拒绝援助",
        }],
    }]
    ledger = build_contract_ledger(chain, steps, seed)
    assert ledger["relationship_ledger"]["issues"] == []


def test_relationship_ledger_rejects_pair_from_different_role_slots():
    chain = [{
        "segment_index": 1, "function_name": "CONFRONTATION",
        "contract": {"role_slots": ["actor", "affected"], "preconditions": [], "effects": [{
            "aspect": "RELATIONSHIP_STATUS", "role_slots": ["actor", "affected"],
            "before": "low", "after": "high",
        }], "obligation_effects": {}},
    }]
    steps = [{
        "segment_index": 1, "function_name": "CONFRONTATION",
        "role_bindings": {"actor": "P1", "affected": "P2", "obstacle": "P3"},
        "state_change": "对抗结果改变关系",
        "character_state_changes": {"P1": "changed", "P3": "changed"},
        "relationship_changes": [{
            "source_id": "P1", "target_id": "P3", "dimension": "trust",
            "before": "low", "after": "lower", "evidence": "当众拒绝援助",
        }],
    }]
    ledger = build_contract_ledger(
        chain, steps, {"characters": [{"id": "P1"}, {"id": "P2"}, {"id": "P3"}]},
    )
    assert any("同一关系效果" in issue for issue in ledger["relationship_ledger"]["issues"])
