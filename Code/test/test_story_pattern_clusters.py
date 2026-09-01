"""Story Pattern motif cluster 构建测试。"""

from copy import deepcopy

import pytest

from story_pattern_loader import clusters


def _candidate(motif_id, story_id, category="悬疑", occurrence_id=None):
    occurrence_id = occurrence_id or f"{story_id}_obs_001"
    return {
        "motif_id": motif_id,
        "snapshot_id": "snapshot_test",
        "story_ids": [story_id],
        "story_support": 1,
        "evidence": [{
            "story_id": story_id,
            "category": category,
            "structural_orders": [1, 2, 3],
            "repeat_counts": [1, 1, 1],
            "occurrence_ids": [occurrence_id],
        }],
    }


def _review(pair_id, left, right, verdict="SAME_PATTERN", order_conflicts=None):
    return {
        "variant_pair_id": pair_id,
        "snapshot_id": "snapshot_test",
        "member_motif_ids": [left, right],
        "verdict": verdict,
        "core_alignment": ["核心链一致"],
        "optional_steps": [],
        "order_conflicts": order_conflicts or [],
        "reason": "测试",
    }


def _state(candidates=None, reviews=None):
    return {
        "snapshot_manifest": {"snapshot_id": "snapshot_test"},
        "motif_candidates": candidates or [
            _candidate("MC_A", "s1"),
            _candidate("MC_B", "s2", "情感"),
        ],
        "motif_pair_reviews": reviews or [_review("MV_AB", "MC_A", "MC_B")],
    }


def test_builds_cluster_and_recomputes_story_evidence_and_categories():
    state = _state()
    before = deepcopy(state)
    result = clusters.build_motif_clusters(state)
    cluster = result["motif_clusters"][0]

    assert cluster["member_motif_ids"] == ["MC_A", "MC_B"]
    assert cluster["story_support"] == 2
    assert cluster["category_counts"] == {"悬疑": 1, "情感": 1}
    assert cluster["evidence_count"] == 2
    assert cluster["same_pattern_edge_ids"] == ["MV_AB"]
    assert cluster["review_edges"][0]["core_alignment"] == ["核心链一致"]
    assert cluster["needs_review"] is False
    assert state == before


def test_deduplicates_shared_evidence_and_keeps_source_motifs():
    candidates = [
        _candidate("MC_A", "s1", occurrence_id="occ_1"),
        _candidate("MC_B", "s1", occurrence_id="occ_1"),
    ]
    cluster = clusters.build_motif_clusters(_state(candidates))["motif_clusters"][0]

    assert cluster["story_support"] == 1
    assert cluster["evidence_count"] == 1
    assert cluster["evidence"][0]["source_motif_ids"] == ["MC_A", "MC_B"]


def test_marks_transitive_chain_as_incomplete_not_conflict():
    candidates = [
        _candidate("MC_A", "s1"),
        _candidate("MC_B", "s2"),
        _candidate("MC_C", "s3"),
    ]
    reviews = [
        _review("MV_AB", "MC_A", "MC_B"),
        _review("MV_BC", "MC_B", "MC_C"),
    ]
    state = _state(candidates, reviews)
    state["motif_variant_pairs"] = [
        {"variant_pair_id": "MV_AB", "snapshot_id": "snapshot_test", "member_motif_ids": ["MC_A", "MC_B"]},
        {"variant_pair_id": "MV_BC", "snapshot_id": "snapshot_test", "member_motif_ids": ["MC_B", "MC_C"]},
        {"variant_pair_id": "MV_AC", "snapshot_id": "snapshot_test", "member_motif_ids": ["MC_A", "MC_C"]},
    ]
    cluster = clusters.build_motif_clusters(state)["motif_clusters"][0]

    assert cluster["member_count"] == 3
    assert cluster["needs_review"] is False
    assert cluster["review_incomplete"] is True
    assert cluster["review_status"] == "INCOMPLETE"
    assert cluster["unreviewed_pair_ids"] == ["MV_AC"]


def test_marks_internal_non_same_and_order_conflicts():
    candidates = [
        _candidate("MC_A", "s1"),
        _candidate("MC_B", "s2"),
        _candidate("MC_C", "s3"),
    ]
    reviews = [
        _review("MV_AB", "MC_A", "MC_B"),
        _review("MV_BC", "MC_B", "MC_C", order_conflicts=["顺序相反"]),
        _review("MV_AC", "MC_A", "MC_C", verdict="DIFFERENT"),
    ]
    cluster = clusters.build_motif_clusters(_state(candidates, reviews))["motif_clusters"][0]
    reason_types = [item["type"] for item in cluster["review_reasons"]]

    assert cluster["needs_review"] is True
    assert "ORDER_CONFLICT" in reason_types
    assert "INTERNAL_REVIEW_CONFLICT" in reason_types


def test_only_same_pattern_reviews_create_clusters():
    reviews = [_review("MV_AB", "MC_A", "MC_B", verdict="RELATED")]
    result = clusters.build_motif_clusters(_state(reviews=reviews))["motif_clusters"]
    assert {tuple(item["member_motif_ids"]) for item in result} == {("MC_A",), ("MC_B",)}


@pytest.mark.parametrize("mutate, message", [
    (lambda state: state.update(snapshot_manifest=None), "Snapshot ID"),
    (lambda state: state.update(motif_candidates=[]), "motif_candidates"),
    (lambda state: state["motif_candidates"][0].update(snapshot_id="wrong"), "candidate 结构"),
    (lambda state: state["motif_pair_reviews"][0].update(snapshot_id="wrong"), "review 结构"),
    (lambda state: state["motif_pair_reviews"][0].update(member_motif_ids=["MC_A", "UNKNOWN"]), "review 结构"),
])
def test_rejects_invalid_inputs(mutate, message):
    state = _state()
    mutate(state)
    with pytest.raises(ValueError, match=message):
        clusters.build_motif_clusters(state)
