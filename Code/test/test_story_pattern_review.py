"""Story Pattern Agent motif 配对 LLM 审查测试。"""

import json
from copy import deepcopy

import pytest

from story_pattern_loader import review


def _candidate(motif_id, function_ids, story_id, occurrence_ids):
    return {
        "motif_id": motif_id,
        "snapshot_id": "snapshot_test",
        "function_ids": function_ids,
        "function_names": [f"FUNCTION_{item.split('_')[1]}" for item in function_ids],
        "length": len(function_ids),
        "tier": "SINGLE_STORY",
        "story_ids": [story_id],
        "evidence": [{
            "story_id": story_id,
            "category": "悬疑",
            "repeat_counts": [1] * len(function_ids),
            "occurrence_ids": occurrence_ids,
        }],
    }


def _state(index=0):
    functions = {
        f"F_{number}": {
            "function_id": f"F_{number}",
            "function_name": f"FUNCTION_{number}",
            "definition": f"定义_{number}",
        }
        for number in range(1, 7)
    }
    left_occurrences = [f"s1_occ_{number}" for number in range(1, 4)]
    right_occurrences = [f"s2_occ_{number}" for number in range(1, 4)]
    observations = {
        story_id: [{
            "obs_id": f"{story_id}_obs_{number}",
            "story_id": story_id,
            "event": f"事件_{story_id}_{number}",
            "before_state": "之前",
            "after_state": "之后",
            "narrative_effect": "推动结构",
            "surface_form": "表层动作",
        } for number in range(1, 4)]
        for story_id in ("s1", "s2")
    }
    all_occurrences = [{
        "occurrence_id": occurrence_id,
        "obs_id": f"{story_id}_obs_{number}",
        "story_id": story_id,
    } for story_id, occurrence_ids in (
        ("s1", left_occurrences), ("s2", right_occurrences),
    ) for number, occurrence_id in enumerate(occurrence_ids, 1)]
    return {
        "snapshot_manifest": {"snapshot_id": "snapshot_test"},
        "function_by_id": functions,
        "motif_candidates": [
            _candidate("MC_A", ["F_1", "F_2", "F_3"], "s1", left_occurrences),
            _candidate("MC_B", ["F_4", "F_5", "F_6"], "s2", right_occurrences),
        ],
        "motif_variant_pairs": [{
            "variant_pair_id": "MV_1",
            "snapshot_id": "snapshot_test",
            "member_motif_ids": ["MC_A", "MC_B"],
            "similarity": 0.9,
            "recall_tier": "HIGH",
            "story_ids": ["s1", "s2"],
            "alignment": [],
        }],
        "current_motif_pair_index": index,
        "motif_pair_reviews": [],
        "all_occurrences": all_occurrences,
        "observations_by_story": observations,
    }


def _mock_llm(monkeypatch, verdict="SAME_PATTERN"):
    captured = {}

    def fake_chat(messages, output_schema):
        captured["messages"] = messages
        return output_schema(
            verdict=verdict,
            confidence=0.91,
            core_alignment=["核心变化一致"],
            optional_steps=["右侧存在可选步骤"],
            order_conflicts=[],
            reason="核心功能及顺序一致",
        )

    monkeypatch.setattr(review, "chat_structured", fake_chat)
    return captured


def test_reviews_one_pair_with_function_and_observation_evidence(monkeypatch):
    captured = _mock_llm(monkeypatch)
    state = _state()
    before = deepcopy(state)
    result = review.review_motif_pairs(state)

    assert result["current_motif_pair_index"] == 1
    assert result["motif_pair_reviews"][0]["verdict"] == "SAME_PATTERN"
    assert result["motif_pair_reviews"][0]["embedding_similarity"] == 0.9
    assert state == before
    payload = json.loads(captured["messages"][1]["content"])
    assert payload["left_motif"]["sequence"][0]["definition"] == "定义_1"
    assert payload["left_motif"]["evidence"][0]["observations"][0]["event"] == "事件_s1_1"
    assert payload["variant_pair"]["variant_pair_id"] == "MV_1"


def test_prompt_separates_pair_equivalence_from_publication_support():
    assert "故事数量、样本数量、题材数量和当前支持度均不得影响 verdict" in review.REVIEW_SYSTEM_PROMPT
    assert "额外步骤写入 optional_steps" in review.REVIEW_SYSTEM_PROMPT
    assert "不得因为“故事支持不足”" in review.REVIEW_SYSTEM_PROMPT


@pytest.mark.parametrize("index, expected", [(0, True), (1, False), (2, False)])
def test_has_next_motif_pair(index, expected):
    assert review.has_next_motif_pair(_state(index)) is expected


def test_negative_index_is_rejected():
    with pytest.raises(IndexError, match="不能为负数"):
        review.has_next_motif_pair(_state(-1))


def test_out_of_range_does_not_call_llm(monkeypatch):
    called = _mock_llm(monkeypatch)
    with pytest.raises(IndexError, match="越界"):
        review.review_motif_pairs(_state(1))
    assert called == {}


def test_node_binds_pair_id_without_asking_llm_to_copy_it(monkeypatch):
    _mock_llm(monkeypatch)
    assert review.review_motif_pairs(_state())["motif_pair_reviews"][0]["variant_pair_id"] == "MV_1"


def test_rejects_already_reviewed_pair_before_llm(monkeypatch):
    captured = _mock_llm(monkeypatch)
    state = _state()
    state["motif_pair_reviews"] = [{"variant_pair_id": "MV_1"}]
    with pytest.raises(ValueError, match="已审查"):
        review.review_motif_pairs(state)
    assert captured == {}


@pytest.mark.parametrize("mutate, message", [
    (lambda state: state.update(snapshot_manifest=None), "Snapshot ID"),
    (lambda state: state.update(function_by_id={}), "function_by_id"),
    (lambda state: state["motif_variant_pairs"][0].update(snapshot_id="wrong"), "Snapshot ID"),
    (lambda state: state["motif_variant_pairs"][0].update(member_motif_ids=["MC_A", "UNKNOWN"]), "未知 candidate"),
    (lambda state: state["all_occurrences"].pop(), "未知 occurrence"),
    (lambda state: state["observations_by_story"]["s2"].pop(), "未知 Observation"),
    (lambda state: state["all_occurrences"][0].update(story_id="s2"), "故事归属不一致"),
])
def test_rejects_invalid_state_before_llm(monkeypatch, mutate, message):
    captured = _mock_llm(monkeypatch)
    state = _state()
    mutate(state)
    with pytest.raises(ValueError, match=message):
        review.review_motif_pairs(state)
    assert captured == {}
