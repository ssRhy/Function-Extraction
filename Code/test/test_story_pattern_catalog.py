"""PatternCatalog 发布节点测试。"""

from copy import deepcopy

import pytest

from story_pattern_loader import catalog


def _cluster(cluster_id, support, needs_review=False):
    return {
        "cluster_id": cluster_id,
        "snapshot_id": "snapshot_test",
        "member_motif_ids": [f"MC_{cluster_id}"],
        "needs_review": needs_review,
        "review_incomplete": False,
        "review_reasons": [{"type": "INTERNAL_REVIEW_CONFLICT"}] if needs_review else [],
        "story_ids": [f"s{index}" for index in range(support)],
        "story_support": support,
        "evidence": [{"story_id": f"s{index}"} for index in range(support)],
    }


def _summary(cluster_id, support):
    return {
        "pattern_id": f"PAT_{cluster_id}",
        "snapshot_id": "snapshot_test",
        "cluster_id": cluster_id,
        "pattern_name": f"模式 {cluster_id}",
        "abstract_definition": "抽象定义",
        "core_function_chain": [{"function_id": "F_1", "function_name": "F_1"}] * 3,
        "optional_steps": [],
        "applicability_conditions": [],
        "counterexamples_limitations": [],
        "story_ids": [f"s{index}" for index in range(support)],
        "story_support": support,
        "category_counts": {"悬疑": support},
        "evidence": [{"story_id": f"s{index}"} for index in range(support)],
        "evidence_count": support,
        "member_motif_ids": [f"MC_{cluster_id}"],
        "review_edge_ids": [],
    }


def _state():
    return {
        "snapshot_manifest": {"snapshot_id": "snapshot_test"},
        "motif_clusters": [
            _cluster("A", 2),
            _cluster("B", 1),
            _cluster("C", 3, needs_review=True),
            _cluster("D", 2),
        ],
        "pattern_summaries": [
            _summary("A", 2),
            _summary("B", 1),
            _summary("D", 2),
        ],
    }


def test_publishes_threshold_and_separates_rejected_and_manual_review():
    state = _state()
    before = deepcopy(state)
    result = catalog.publish_pattern_catalog(state)
    output = result["pattern_catalog"]

    assert output["publish_rules"]["minimum_story_support"] == 2
    assert [item["cluster_id"] for item in output["published_patterns"]] == ["A", "D"]
    assert output["published_patterns"][0]["publication_status"] == "PUBLISHED"
    assert output["rejected_patterns"][0]["reason"] == "INSUFFICIENT_STORY_SUPPORT"
    assert [item["cluster_id"] for item in output["manual_review_patterns"]] == ["C"]
    assert output["counts"] == {
        "candidates": 3, "published": 2, "rejected": 1, "manual_review": 1,
    }
    assert state == before


def test_missing_summary_is_rejected_and_manual_review_keeps_evidence():
    state = _state()
    state["pattern_summaries"] = [_summary("A", 2)]
    output = catalog.publish_pattern_catalog(state)["pattern_catalog"]

    rejected = {item["cluster_id"]: item for item in output["rejected_patterns"]}
    assert rejected["D"]["reason"] == "SUMMARY_MISSING"
    assert output["manual_review_patterns"][0]["evidence"] == state["motif_clusters"][2]["evidence"]


def test_incomplete_cluster_stays_in_manual_review():
    state = _state()
    state["motif_clusters"][0]["review_incomplete"] = True
    state["motif_clusters"][0]["unreviewed_pair_ids"] = ["MV_X"]
    output = catalog.publish_pattern_catalog(state)["pattern_catalog"]

    item = next(item for item in output["manual_review_patterns"] if item["cluster_id"] == "A")
    assert item["reason"] == "REVIEW_INCOMPLETE"
    assert item["unreviewed_pair_ids"] == ["MV_X"]


def test_v3_catalog_requires_contract_on_each_core_function():
    state = _state()
    state["snapshot_manifest"]["schema_version"] = 3
    state["pattern_summaries"] = [state["pattern_summaries"][0]]
    contract = {"function_id": "F_1", "function_name": "F_1"}
    state["function_contract_by_id"] = {"F_1": contract}
    state["pattern_summaries"][0]["core_function_chain"] = [
        {"function_id": "F_1", "function_name": "F_1", "contract": contract},
    ] * 3

    output = catalog.publish_pattern_catalog(state)["pattern_catalog"]

    assert output["publish_rules"]["requires_function_contract"] is True
    assert output["published_patterns"][0]["core_function_chain"][0]["contract"] == contract


@pytest.mark.parametrize("change, message", [
    ({"snapshot_manifest": None}, "Snapshot ID"),
    ({"motif_clusters": []}, "motif_clusters"),
    ({"pattern_summaries": None}, "pattern_summaries"),
    ({"pattern_summaries": [{"cluster_id": "UNKNOWN"}]}, "pattern summary 结构"),
])
def test_rejects_invalid_inputs(change, message):
    state = _state()
    state.update(change)
    with pytest.raises(ValueError, match=message):
        catalog.publish_pattern_catalog(state)
