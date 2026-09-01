"""EXPANDED motif review queue 测试。"""

from story_pattern_loader import review_queue


def _pair(pair_id, left, right, tier="EXPANDED", similarity=0.8):
    return {
        "variant_pair_id": pair_id,
        "snapshot_id": "snapshot_test",
        "member_motif_ids": [left, right],
        "recall_tier": tier,
        "similarity": similarity,
    }


def test_prioritizes_internal_then_bridge_then_unconnected_and_skips_reviewed():
    state = {
        "snapshot_manifest": {"snapshot_id": "snapshot_test"},
        "motif_variant_pairs": [
            _pair("MV_INTERNAL", "MC_A", "MC_B", similarity=0.76),
            _pair("MV_BRIDGE", "MC_A", "MC_C", similarity=0.95),
            _pair("MV_UNCONNECTED", "MC_X", "MC_Y", similarity=0.99),
            _pair("MV_HIGH", "MC_A", "MC_C", tier="HIGH"),
            _pair("MV_REVIEWED", "MC_A", "MC_D"),
        ],
        "motif_pair_reviews": [{"member_motif_ids": ["MC_A", "MC_D"]}],
        "motif_clusters": [
            {"cluster_id": "MCL_1", "member_motif_ids": ["MC_A", "MC_B"]},
            {"cluster_id": "MCL_2", "member_motif_ids": ["MC_C"]},
        ],
    }

    queue = review_queue.build_expanded_review_queue(state)["motif_review_queue"]

    assert [item["variant_pair_id"] for item in queue] == [
        "MV_INTERNAL", "MV_BRIDGE", "MV_UNCONNECTED",
    ]
    assert [item["queue_reason"] for item in queue] == [
        "INTERNAL_CLUSTER_PAIR", "CLUSTER_BRIDGE_PAIR", "UNCONNECTED_PAIR",
    ]


def test_requires_snapshot_pairs_and_clusters():
    try:
        review_queue.build_expanded_review_queue({
            "snapshot_manifest": {"snapshot_id": "snapshot_test"},
            "motif_variant_pairs": [],
            "motif_clusters": [],
        })
    except ValueError as error:
        assert "motif_variant_pairs" in str(error)
    else:
        raise AssertionError("expected ValueError")
