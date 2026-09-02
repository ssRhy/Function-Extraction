"""Story Pattern Agent 精确 motif 候选提取测试。"""

from copy import deepcopy
from collections import Counter
import os
from pathlib import Path

import pytest

from story_pattern_loader import inputs, sequences


def _functions(count=6):
    return {
        f"F_{index}": {
            "function_id": f"F_{index}",
            "function_name": f"FUNCTION_{index}",
        }
        for index in range(1, count + 1)
    }


def _segment(ids, start=1, repeats=None):
    repeats = repeats or [1] * len(ids)
    return [{
        "function_id": function_id,
        "function_name": f"FUNCTION_{function_id.split('_')[1]}",
        "repeat_count": repeat_count,
        "structural_order": start + index,
        "occurrence_ids": [
            f"obs_{start + index}_{item}" for item in range(1, repeat_count + 1)
        ],
    } for index, (function_id, repeat_count) in enumerate(zip(ids, repeats))]


def _context(story_id, segment, anchor_index=0, category="悬疑"):
    anchor = segment[anchor_index]
    return {
        "story_id": story_id,
        "category": category,
        "structural_order": anchor["structural_order"],
        "anchor_index": anchor_index,
        "repeat_count": anchor["repeat_count"],
        "occurrence_ids": list(anchor["occurrence_ids"]),
        "segment": deepcopy(segment),
    }


def _state(contexts, functions=None):
    return {
        "snapshot_manifest": {"snapshot_id": "snapshot_test"},
        "function_by_id": functions or _functions(),
        "function_contexts": contexts,
    }


def _candidate(result, ids):
    return next(
        item for item in result["motif_candidates"]
        if item["function_ids"] == ids
    )


def test_extracts_all_contiguous_windows_of_lengths_three_to_six():
    segment = _segment([f"F_{index}" for index in range(1, 7)])
    result = sequences.extract_motif_candidates(_state({"F_1": [_context("s1", segment)]}))

    assert len(result["motif_candidates"]) == 10
    assert {length: sum(item["length"] == length for item in result["motif_candidates"])
            for length in range(3, 7)} == {3: 4, 4: 3, 5: 2, 6: 1}


def test_short_segment_produces_no_candidates():
    segment = _segment(["F_1", "F_2"])
    result = sequences.extract_motif_candidates(_state({"F_1": [_context("s1", segment)]}))
    assert result["motif_candidates"] == []


def test_scans_only_zero_anchor_context():
    segment = _segment(["F_1", "F_2", "F_3"])
    contexts = {
        "F_1": [_context("s1", segment, 0)],
        "F_2": [_context("s1", segment, 1)],
        "F_3": [_context("s1", segment, 2)],
    }
    candidate = sequences.extract_motif_candidates(_state(contexts))["motif_candidates"][0]
    assert candidate["evidence_count"] == 1


def test_cross_story_support_and_same_story_evidence_are_distinct():
    segment = _segment(["F_1", "F_2", "F_3"])
    contexts = {"F_1": [
        _context("s1", segment),
        _context("s1", _segment(["F_1", "F_2", "F_3"], start=10)),
        _context("s2", _segment(["F_1", "F_2", "F_3"]), category="情感"),
    ]}
    candidate = sequences.extract_motif_candidates(_state(contexts))["motif_candidates"][0]

    assert candidate["tier"] == "REPEATED"
    assert candidate["story_support"] == 2
    assert candidate["evidence_count"] == 3
    assert candidate["category_counts"] == {"情感": 1, "悬疑": 2}


def test_same_story_duplicate_stays_single_story():
    contexts = {"F_1": [
        _context("s1", _segment(["F_1", "F_2", "F_3"])),
        _context("s1", _segment(["F_1", "F_2", "F_3"], start=10)),
    ]}
    candidate = sequences.extract_motif_candidates(_state(contexts))["motif_candidates"][0]
    assert (candidate["tier"], candidate["story_support"], candidate["evidence_count"]) == (
        "SINGLE_STORY", 1, 2,
    )


def test_repetition_is_variant_not_motif_identity_and_keeps_evidence():
    contexts = {"F_1": [
        _context("s1", _segment(["F_1", "F_2", "F_3"])),
        _context("s2", _segment(["F_1", "F_2", "F_3"], repeats=[1, 2, 1])),
    ]}
    candidate = sequences.extract_motif_candidates(_state(contexts))["motif_candidates"][0]

    assert len(candidate["repeat_variants"]) == 2
    assert candidate["evidence"][1]["repeat_counts"] == [1, 2, 1]
    assert len(candidate["evidence"][1]["occurrence_ids"]) == 4
    assert candidate["evidence"][0]["structural_orders"] == [1, 2, 3]


def test_order_changes_identity_and_output_is_deterministic():
    forward = _context("s2", _segment(["F_1", "F_2", "F_3"]))
    reverse = _context("s1", _segment(["F_3", "F_2", "F_1"]))
    state = _state({"F_1": [forward], "F_3": [reverse]})
    before = deepcopy(state)
    first = sequences.extract_motif_candidates(state)
    second = sequences.extract_motif_candidates(state)

    assert len({item["motif_id"] for item in first["motif_candidates"]}) == 2
    assert first == second
    assert state == before


@pytest.mark.parametrize("change, message", [
    ({"snapshot_manifest": None}, "Snapshot ID"),
    ({"function_contexts": {}}, "非空 function_contexts"),
    ({"function_by_id": {}}, "function_by_id"),
])
def test_requires_complete_inputs(change, message):
    segment = _segment(["F_1", "F_2", "F_3"])
    state = _state({"F_1": [_context("s1", segment)]})
    state.update(change)
    with pytest.raises(ValueError, match=message):
        sequences.extract_motif_candidates(state)


@pytest.mark.parametrize("mutate, message", [
    (lambda context: context.update(anchor_index=4), "anchor_index"),
    (lambda context: context["segment"][0].update(function_id="F_UNKNOWN"), "未知 Function"),
    (lambda context: context["segment"][0].update(function_name="WRONG"), "ID/名称不一致"),
    (lambda context: context["segment"][0].pop("structural_order"), "结构无效"),
])
def test_rejects_invalid_context_or_segment(mutate, message):
    context = _context("s1", _segment(["F_1", "F_2", "F_3"]))
    mutate(context)
    with pytest.raises(ValueError, match=message):
        sequences.extract_motif_candidates(_state({"F_1": [context]}))


def test_real_data_candidate_distribution():
    code_root = Path(__file__).resolve().parents[1]
    snapshot_id = os.environ.get("FUNCTION_SNAPSHOT_ID")
    if not snapshot_id:
        pytest.skip("真实 Snapshot 测试需显式设置 FUNCTION_SNAPSHOT_ID")
    state = {
        "knowledge_db": str(code_root / "data/knowledge/story_knowledge.db"),
        "snapshot_id": snapshot_id,
        "messages": [],
    }
    try:
        state.update(inputs.load_inputs(state))
    except ValueError as exc:
        if "Snapshot" in str(exc):
            pytest.skip("历史 evolve_250 Snapshot 不属于当前全新 DB 验收数据")
        raise
    state.update(sequences.load_occurrences_node(state))
    for index in range(len(state["story_ids"])):
        state["current_story_index"] = index
        story_id = state["story_ids"][index]
        state["current_story_id"] = story_id
        state["current_metadata"] = state["story_metadata"][story_id]
        state["current_observations"] = state["observations_by_story"][story_id]
        state["current_occurrences"] = []
        state["current_structural_sequence"] = []
        state.update(sequences.build_story_sequences(state))
        state.update(sequences.annotate_repetitions(state))
    state.update(sequences.index_function_contexts(state))
    result = sequences.extract_motif_candidates(state)
    candidates = result["motif_candidates"]

    assert sum(
        context["anchor_index"] == 0
        for contexts in state["function_contexts"].values()
        for context in contexts
    ) == 451
    assert len(candidates) == 1904
    assert Counter(item["length"] for item in candidates) == {3: 744, 4: 539, 5: 371, 6: 250}
    assert Counter(item["tier"] for item in candidates) == {"REPEATED": 17, "SINGLE_STORY": 1887}
    assert all(item["story_support"] == len(set(item["story_ids"])) for item in candidates)
