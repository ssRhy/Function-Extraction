"""Pattern Evolve 的 DB 增量、幂等和失败原子性测试。"""

import pytest

from StoryPattern_Agent import app


def _candidate(motif_id, stories):
    return {
        "motif_id": motif_id, "snapshot_id": "child",
        "function_ids": ["F_0", "F_1", "F_2", "F_3"],
        "function_names": [f"FUNCTION_{index}" for index in range(4)],
        "length": 4, "tier": "REPEATED", "story_ids": stories,
        "story_support": len(stories), "evidence_count": len(stories),
        "category_counts": {"测试": len(stories)},
        "evidence": [{
            "story_id": story_id, "category": "测试", "structural_orders": [1, 2, 3, 4],
            "repeat_counts": [1, 1, 1, 1],
            "occurrence_ids": [f"{story_id}_{index}" for index in range(4)],
        } for story_id in stories],
    }


def _lineage_state(candidates, reviews, parent_clusters, parent_patterns):
    return {
        "snapshot_id": "child", "snapshot_manifest": {
            "snapshot_id": "child", "schema_version": 2,
        },
        "motif_candidates": candidates, "motif_pair_reviews": reviews,
        "motif_variant_pairs": [], "function_contract_by_id": {},
        "parent_clusters": parent_clusters, "parent_patterns": parent_patterns,
    }


def test_merge_keeps_oldest_parent_pattern_id():
    candidates = [_candidate("MC_A", ["a1", "a2"]), _candidate("MC_B", ["b1", "b2"])]
    review = {
        "variant_pair_id": "MV_AB", "snapshot_id": "child",
        "member_motif_ids": ["MC_A", "MC_B"], "verdict": "SAME_PATTERN",
        "order_conflicts": [],
    }
    parents = [
        {"cluster_id": "C_A", "member_motif_ids": ["MC_A"], "pattern_id": "PAT_OLD"},
        {"cluster_id": "C_B", "member_motif_ids": ["MC_B"], "pattern_id": "PAT_NEW"},
    ]
    patterns = [
        {"pattern_id": "PAT_OLD", "born_at": "2026-01-01"},
        {"pattern_id": "PAT_NEW", "born_at": "2026-02-01"},
    ]
    result = app.rebuild_clusters(_lineage_state(candidates, [review], parents, patterns))
    cluster = result["motif_clusters"][0]
    assert cluster["pattern_id"] == "PAT_OLD"
    assert cluster["merged_pattern_ids"] == ["PAT_NEW"]


def test_split_anchor_keeps_parent_pattern_and_other_child_is_new():
    candidates = [_candidate("MC_A", ["a1", "a2"]), _candidate("MC_B", ["b1", "b2"])]
    parents = [{
        "cluster_id": "C_AB", "member_motif_ids": ["MC_A", "MC_B"],
        "anchor_motif_id": "MC_A", "pattern_id": "PAT_PARENT",
    }]
    patterns = [{"pattern_id": "PAT_PARENT", "born_at": "2026-01-01"}]
    result = app.rebuild_clusters(_lineage_state(candidates, [], parents, patterns))
    by_motif = {item["member_motif_ids"][0]: item for item in result["motif_clusters"]}
    assert by_motif["MC_A"]["pattern_id"] == "PAT_PARENT"
    assert by_motif["MC_B"]["pattern_id"].startswith("PAT_")
    assert by_motif["MC_B"]["pattern_id"] != "PAT_PARENT"


def test_empty_child_retires_parent_pattern():
    state = _lineage_state([], [], [{
        "cluster_id": "C_A", "member_motif_ids": ["MC_A"], "pattern_id": "PAT_PARENT",
    }], [{"pattern_id": "PAT_PARENT"}])
    assert app.rebuild_clusters(state)["retired_pattern_ids"] == ["PAT_PARENT"]


def test_update_story_sequences_keeps_zero_observation_story():
    result = app.update_story_sequences({
        "new_story_ids": ["empty_story"],
        "changed_story_ids": [],
        "unchanged_story_ids": [],
        "occurrences_by_story": {"empty_story": []},
        "occurrence_signatures": {"empty_story": "sig"},
        "parent_sequences": {},
        "parent_snapshot_id": None,
    })

    assert result["sequence_records"]["empty_story"]["payload"] == {
        "story_id": "empty_story",
        "raw_sequence": [],
        "structural_sequence": [],
    }


def test_update_motif_evidence_refreshes_inherited_function_names(monkeypatch):
    class FakeStore:
        def __init__(self, _path):
            pass

        def load_motif_evidence(self, _snapshot_id):
            return [{
                "motif_id": "MC_A",
                "function_ids": ["F_A", "F_B", "F_C"],
                "length": 3,
                "evidence": {
                    "story_id": "story_a", "category": "测试",
                    "structural_orders": [1, 2, 3], "occurrence_ids": ["o1"],
                },
            }]

    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    result = app.update_motif_evidence({
        "knowledge_db": "unused", "parent_snapshot_id": "parent",
        "snapshot_id": "child", "unchanged_story_ids": ["story_a"],
        "new_story_ids": [], "changed_story_ids": [],
        "function_by_id": {
            "F_A": {"function_name": "NEW_A"},
            "F_B": {"function_name": "NEW_B"},
            "F_C": {"function_name": "NEW_C"},
        },
    })

    assert result["motif_candidates"][0]["function_names"] == [
        "NEW_A", "NEW_B", "NEW_C",
    ]


def test_llm_review_failure_has_no_fallback(monkeypatch):
    pair = {
        "variant_pair_id": "MV_AB", "input_signature": "sig", "similarity": 0.9,
        "recall_tier": "HIGH", "member_motif_ids": ["MC_A", "MC_B"],
    }
    class EmptyStore:
        def __init__(self, _path):
            pass
        def load_motif_pair_review(self, *_args):
            return None
    monkeypatch.setattr(app, "StoryKnowledgeStore", EmptyStore)
    monkeypatch.setattr(
        app, "review_motif_pairs",
        lambda _state: (_ for _ in ()).throw(ValueError("LLM 失败")),
    )
    with pytest.raises(ValueError, match="LLM 失败"):
        app._review_selected({
            "knowledge_db": "unused", "snapshot_id": "child",
            "motif_pair_reviews": [],
        }, [pair])


def test_review_stage_timeout_stops_before_next_pair(monkeypatch):
    pair = {
        "variant_pair_id": "MV_AB", "input_signature": "sig", "similarity": 0.9,
        "recall_tier": "HIGH", "member_motif_ids": ["MC_A", "MC_B"],
    }

    class EmptyStore:
        def __init__(self, _path):
            pass

        def load_motif_pair_review(self, *_args):
            return {
                "variant_pair_id": "MV_AB", "verdict": "SAME_PATTERN",
            }

    ticks = iter((0.0, 2.0))
    monkeypatch.setattr(app, "StoryKnowledgeStore", EmptyStore)
    monkeypatch.setattr(app, "PATTERN_STAGE_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(app.time, "monotonic", lambda: next(ticks))

    with pytest.raises(TimeoutError, match="Pattern Motif Review 阶段超时"):
        app._review_selected({
            "knowledge_db": "unused", "snapshot_id": "child",
            "motif_pair_reviews": [],
        }, [pair])


def test_pattern_summary_stage_timeout(monkeypatch):
    monkeypatch.setattr(app, "PATTERN_STAGE_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(app.time, "monotonic", iter((0.0, 2.0)).__next__)
    monkeypatch.setattr(app, "summarize_story_patterns", lambda _state: {
        "pattern_summaries": [{"pattern_id": "PAT_NEW", "story_ids": ["s1", "s2"]}],
    })
    cluster = {
        "cluster_id": "MCL_NEW", "pattern_id": "PAT_NEW", "status": "published",
        "structure_signature": "structure", "summary_input_signature": "semantic",
        "story_ids": ["s1", "s2"], "story_support": 2, "category_counts": {},
        "evidence": [], "evidence_count": 0, "member_motif_ids": ["MC_A"],
    }

    with pytest.raises(TimeoutError, match="Pattern Pattern Summary 阶段超时"):
        app.summarize_changed_clusters({
            "snapshot_id": "child", "parent_patterns": [], "parent_clusters": [],
            "motif_clusters": [cluster], "retired_pattern_ids": [],
        })


def test_pattern_timeout_closes_run_as_failed(monkeypatch):
    calls = {}

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args):
            class Cursor:
                def fetchone(self):
                    return {"parent_snapshot_id": None}

            return Cursor()

    class FakeStore:
        def __init__(self, _path):
            pass

        def load_pattern_run(self, _snapshot_id):
            return None

        def load_snapshot_manifest(self, _snapshot_id):
            return {"namespace": "test", "parent_snapshot_id": None}

        def connect(self):
            return FakeConnection()

        def begin_pattern_run(self, *_args):
            calls["began"] = True
            return {
                "run_id": "PR_test", "workflow": "evolve", "namespace": "test",
                "parent_snapshot_id": None,
            }

        def fail_pattern_run(self, snapshot_id, error):
            calls["failed"] = (snapshot_id, error)

    class FailedGraph:
        def compile(self):
            return self

        def invoke(self, _state):
            raise TimeoutError("review stage timeout")

    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    monkeypatch.setattr(app, "_build_graph", lambda: FailedGraph())

    with pytest.raises(TimeoutError, match="review stage timeout"):
        app.run_pattern_evolve("snapshot_test", "unused.db")

    assert calls["began"] is True
    assert calls["failed"][0] == "snapshot_test"
    assert calls["failed"][1]["status"] == "FAILED"
    assert calls["failed"][1]["error_code"] == "PATTERN_RUN_FAILED"
    assert calls["failed"][1]["error"] == "review stage timeout"


def test_variant_review_keeps_only_mutual_top_two_publishable_pairs(monkeypatch):
    candidates = [
        _candidate("MC_A", ["a"]),
        _candidate("MC_B", ["b"]),
        {**_candidate("MC_C", ["c"]), "length": 3,
         "function_ids": ["F_0", "F_1", "F_2"],
         "function_names": ["FUNCTION_0", "FUNCTION_1", "FUNCTION_2"]},
    ]
    pairs = [
        {
            "variant_pair_id": "MV_KEEP", "member_motif_ids": ["MC_A", "MC_B"],
            "recall_tier": "HIGH", "selected_by": [
                {"motif_id": "MC_A", "rank": 1}, {"motif_id": "MC_B", "rank": 2},
            ],
        },
        {
            "variant_pair_id": "MV_ONE_SIDED", "member_motif_ids": ["MC_A", "MC_B"],
            "recall_tier": "HIGH", "selected_by": [{"motif_id": "MC_A", "rank": 1}],
        },
        {
            "variant_pair_id": "MV_SHORT", "member_motif_ids": ["MC_C", "MC_C"],
            "recall_tier": "HIGH", "selected_by": [
                {"motif_id": "MC_C", "rank": 1},
            ],
        },
    ]
    monkeypatch.setattr(app, "retrieve_motif_variants", lambda _state: {
        "motif_variant_pairs": pairs, "messages": [],
    })
    monkeypatch.setattr(app, "_pair_input_signature", lambda _state, pair: pair["variant_pair_id"])

    result = app.retrieve_variant_pairs({"motif_candidates": candidates})

    assert [item["variant_pair_id"] for item in result["motif_variant_pairs"]] == ["MV_KEEP"]


def test_summary_input_signature_uses_cluster_function_semantics():
    cluster = {"member_motif_ids": ["MC_A"]}
    state = {
        "motif_candidates": [{
            "motif_id": "MC_A", "function_ids": ["F_A"],
            "function_names": ["FUNCTION_A"],
        }],
        "function_by_id": {"F_A": {
            "function_id": "F_A", "function_name": "FUNCTION_A", "definition": "旧定义",
        }},
        "function_contract_by_id": {"F_A": {"effects": [{"after": "OPEN"}]}},
    }

    original = app._summary_input_signature(state, cluster)
    state["function_by_id"]["F_A"]["definition"] = "新定义"

    assert app._summary_input_signature(state, cluster) != original


def test_semantic_change_resummarizes_only_affected_cluster(monkeypatch):
    calls = []

    def fake_summary(state):
        cluster = state["motif_clusters"][0]
        calls.append(cluster["pattern_id"])
        return {"pattern_summaries": [{
            "pattern_id": cluster["pattern_id"],
            "story_ids": list(cluster["story_ids"]),
        }]}

    monkeypatch.setattr(app, "summarize_story_patterns", fake_summary)
    parent_patterns = [
        {
            "pattern_id": "PAT_KEEP", "pattern_version_id": "PV_KEEP",
            "structure_signature": "structure_keep", "pattern": {"story_ids": ["story_a"]},
        },
        {
            "pattern_id": "PAT_REVISE", "pattern_version_id": "PV_REVISE",
            "structure_signature": "structure_revise", "pattern": {"story_ids": ["story_b"]},
        },
    ]
    parent_clusters = [
        {"pattern_id": "PAT_KEEP", "summary_input_signature": "semantic_keep"},
        {"pattern_id": "PAT_REVISE", "summary_input_signature": "semantic_old"},
    ]
    clusters = [
        {
            "cluster_id": "MCL_KEEP", "pattern_id": "PAT_KEEP", "status": "published",
            "structure_signature": "structure_keep", "summary_input_signature": "semantic_keep",
            "story_ids": ["story_a"], "story_support": 1, "category_counts": {},
            "evidence": [], "evidence_count": 1, "member_motif_ids": ["MC_KEEP"],
        },
        {
            "cluster_id": "MCL_REVISE", "pattern_id": "PAT_REVISE", "status": "published",
            "structure_signature": "structure_revise", "summary_input_signature": "semantic_new",
            "story_ids": ["story_b"], "story_support": 1, "category_counts": {},
            "evidence": [], "evidence_count": 1, "member_motif_ids": ["MC_REVISE"],
        },
    ]

    result = app.summarize_changed_clusters({
        "snapshot_id": "child", "parent_patterns": parent_patterns,
        "parent_clusters": parent_clusters, "motif_clusters": clusters,
        "retired_pattern_ids": [],
    })
    records = {item["pattern_id"]: item for item in result["pattern_records"]}

    assert calls == ["PAT_REVISE"]
    assert records["PAT_KEEP"]["version"] is None
    assert records["PAT_REVISE"]["version"]["action"] == "SEMANTICS_REVISED"
