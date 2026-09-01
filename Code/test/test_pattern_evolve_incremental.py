"""Pattern Evolve 的 DB 增量、幂等和失败原子性测试。"""

from pathlib import Path

import pytest

from Contracts.snapshot import publish_snapshot
from KnowledgeBase import StoryKnowledgeStore
from StoryPattern_Agent import app


def _functions():
    return [{
        "function_id": f"F_{index}",
        "function_name": f"FUNCTION_{index}",
        "definition": f"状态变化 {index}",
        "status": "stable",
        "version": 1,
        "supporting_obs_ids": [],
        "version_history": [],
    } for index in range(4)]


def _record_snapshot(store, root, stories, workflow, parent=None):
    corpus = root / f"corpus_{len(stories)}"
    corpus.mkdir(exist_ok=True)
    files, metadata, observations, occurrences = [], {}, [], []
    for story_id in stories:
        filename = f"{story_id}.txt"
        files.append(filename)
        (corpus / filename).write_text("真实故事", encoding="utf-8")
        metadata[filename] = {"txt_file": filename, "category": "测试"}
        for index in range(4):
            obs_id = f"{story_id}_obs_{index + 1:03d}"
            observations.append({
                "obs_id": obs_id, "story_id": story_id, "event": f"事件 {index}",
                "before_state": "之前", "after_state": "之后",
            })
            occurrences.append({
                "occurrence_id": obs_id, "obs_id": obs_id, "story_id": story_id,
                "function_id": f"F_{index}", "function_name": f"FUNCTION_{index}",
                "status": "MATCHED", "source_sentence_indices": [index],
            })
    snapshot = publish_snapshot(
        _functions(), {"verdict": "PASS"}, workflow, "pattern_test",
        str(root / "snapshots"), occurrences,
    )
    store.record_function_run(snapshot, corpus, files, metadata, observations, parent)
    return Path(snapshot).name


def _no_pairs(_state):
    return {"motif_variant_pairs": [], "messages": []}


def _summary(state):
    cluster = state["motif_clusters"][0]
    motif = next(
        item for item in state["motif_candidates"]
        if item["motif_id"] == cluster["anchor_motif_id"]
    )
    return {"pattern_summaries": [{
        "pattern_id": cluster["pattern_id"],
        "snapshot_id": state["snapshot_id"],
        "cluster_id": cluster["cluster_id"],
        "pattern_name": "测试模式",
        "abstract_definition": "四步状态变化",
        "core_function_chain": [{
            "function_id": function_id,
            "function_name": state["function_by_id"][function_id]["function_name"],
            "definition": state["function_by_id"][function_id]["definition"],
        } for function_id in motif["function_ids"]],
        "optional_steps": [], "applicability_conditions": [],
        "counterexamples_limitations": [], "ending_spec": None,
        "story_ids": cluster["story_ids"], "story_support": cluster["story_support"],
        "category_counts": cluster["category_counts"], "evidence": cluster["evidence"],
        "evidence_count": cluster["evidence_count"],
        "member_motif_ids": cluster["member_motif_ids"], "review_edge_ids": [],
    }], "skipped_clusters": [], "messages": []}


def test_bootstrap_then_evolve_inherits_sequences_and_extends_evidence(tmp_path, monkeypatch):
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    monkeypatch.setattr(app, "retrieve_variant_pairs", _no_pairs)
    monkeypatch.setattr(app, "summarize_story_patterns", _summary)
    bootstrap = _record_snapshot(store, tmp_path, ["story_a", "story_b"], "bootstrap")
    first = app.run_pattern_evolve(bootstrap, store.db_path)
    evolve = _record_snapshot(
        store, tmp_path, ["story_a", "story_b", "story_c"], "evolve", bootstrap,
    )
    second = app.run_pattern_evolve(evolve, store.db_path)

    assert first["new_pattern_ids"]
    assert second["new_pattern_ids"] == []
    assert second["story_delta"] == {
        "new": ["story_c"], "changed": [],
        "unchanged": ["story_a", "story_b"], "removed": [],
    }
    assert second["updated_pattern_ids"] == first["new_pattern_ids"]
    with store.connect() as conn:
        actions = [row[0] for row in conn.execute(
            "SELECT action FROM pattern_versions ORDER BY rowid"
        )]
        inherited = conn.execute(
            """SELECT COUNT(*) FROM pattern_story_sequences
               WHERE snapshot_id=? AND inherited_from_snapshot_id=?""",
            (evolve, bootstrap),
        ).fetchone()[0]
    assert actions == ["CREATE", "EVIDENCE_EXTENDED"]
    assert inherited == 2


def test_delta_evolve_snapshot_merges_parent_story_inputs(tmp_path, monkeypatch):
    """子 Function Snapshot 只含本批故事时，Pattern 仍从 DB 继承父故事与 Motif。"""
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    monkeypatch.setattr(app, "retrieve_variant_pairs", _no_pairs)
    monkeypatch.setattr(app, "summarize_story_patterns", _summary)
    bootstrap = _record_snapshot(store, tmp_path, ["story_a", "story_b"], "bootstrap")
    first = app.run_pattern_evolve(bootstrap, store.db_path)
    delta = _record_snapshot(store, tmp_path, ["story_c"], "evolve", bootstrap)
    second = app.run_pattern_evolve(delta, store.db_path)

    assert second["story_delta"] == {
        "new": ["story_c"], "changed": [],
        "unchanged": ["story_a", "story_b"], "removed": [],
    }
    assert second["new_pattern_ids"] == []
    assert second["updated_pattern_ids"] == first["new_pattern_ids"]
    with store.connect() as conn:
        inherited = conn.execute(
            """SELECT COUNT(*) FROM pattern_story_sequences
               WHERE snapshot_id=? AND inherited_from_snapshot_id=?""",
            (delta, bootstrap),
        ).fetchone()[0]
        motif_rows = conn.execute(
            "SELECT COUNT(*) FROM motif_evidence WHERE snapshot_id=?", (delta,)
        ).fetchone()[0]
    assert inherited == 2
    assert motif_rows > 0


def test_same_snapshot_is_idempotent(tmp_path, monkeypatch):
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    monkeypatch.setattr(app, "retrieve_variant_pairs", _no_pairs)
    monkeypatch.setattr(app, "summarize_story_patterns", _summary)
    snapshot = _record_snapshot(store, tmp_path, ["story_a", "story_b"], "bootstrap")
    first = app.run_pattern_evolve(snapshot, store.db_path)
    before = store.status()["counts"]
    second = app.run_pattern_evolve(snapshot, store.db_path)
    assert second == first
    assert store.status()["counts"] == before


def test_rebuild_explicitly_replaces_incomplete_pattern_snapshot(tmp_path, monkeypatch):
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    monkeypatch.setattr(app, "retrieve_variant_pairs", _no_pairs)
    monkeypatch.setattr(app, "summarize_story_patterns", _summary)
    snapshot = _record_snapshot(store, tmp_path, ["story_a", "story_b"], "bootstrap")
    first = app.run_pattern_evolve(snapshot, store.db_path)
    rebuilt = app.run_pattern_evolve(snapshot, store.db_path, rebuild=True)

    assert rebuilt["run_id"] == first["run_id"]
    assert rebuilt["counts"] == first["counts"]
    assert store.load_pattern_run(snapshot)["status"] == "SUCCESS"


def test_node_failure_marks_run_failed_without_partial_pattern_data(tmp_path, monkeypatch):
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    snapshot = _record_snapshot(store, tmp_path, ["story_a", "story_b"], "bootstrap")
    monkeypatch.setattr(
        app, "retrieve_variant_pairs",
        lambda _state: (_ for _ in ()).throw(ValueError("LLM 前置失败")),
    )
    with pytest.raises(ValueError, match="LLM 前置失败"):
        app.run_pattern_evolve(snapshot, store.db_path)
    assert store.load_pattern_run(snapshot)["status"] == "FAILED"
    counts = store.status()["counts"]
    assert counts["pattern_story_sequences"] == 0
    assert counts["motif_evidence"] == 0
    assert counts["patterns"] == 0


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
