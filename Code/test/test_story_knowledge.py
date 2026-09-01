"""统一知识库的证据链、版本和幂等测试。"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Contracts.snapshot import publish_snapshot
from Contracts.function_contract import definition_sha256
from KnowledgeBase import StoryKnowledgeStore


def _function(definition="结构变化", version=1):
    return {
        "function_id": "F_TEST",
        "function_name": "TEST_FUNCTION",
        "definition": definition,
        "status": "stable",
        "version": version,
        "supporting_obs_ids": ["story_obs_001"],
        "version_history": [
            {"version": value, "action": "CREATE" if value == 1 else "REVISE", "ts": f"2026-01-0{value}"}
            for value in range(1, version + 1)
        ],
    }


def _snapshot(tmp_path, function, contracts=None):
    occurrence = {
        "occurrence_id": "story_obs_001",
        "obs_id": "story_obs_001",
        "story_id": "story",
        "function_id": "F_TEST",
        "function_name": "TEST_FUNCTION",
        "status": "MATCHED",
        "source_sentence_indices": [0],
    }
    return publish_snapshot(
        [function],
        {"verdict": "PASS"},
        "evolve",
        "test_namespace",
        str(tmp_path / "snapshots"),
        [occurrence],
        contracts,
    )


def _corpus(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "story.txt").write_text("一个真实故事。", encoding="utf-8")
    meta = {"story.txt": {"txt_file": "story.txt", "category": "测试"}}
    observation = {
        "obs_id": "story_obs_001",
        "story_id": "story",
        "before_state": "之前",
        "event": "事件",
        "after_state": "之后",
    }
    return corpus, meta, [observation]


def test_function_run_records_story_to_occurrence_chain(tmp_path):
    snapshot = _snapshot(tmp_path, _function())
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")

    store.record_function_run(snapshot, corpus, ["story.txt"], meta, observations)

    status = store.status()
    assert status["counts"] == {
        "pipeline_runs": 1,
        "stories": 1,
        "observations": 1,
        "observation_versions": 1,
        "functions": 1,
        "function_versions": 1,
        "function_evolution_events": 1,
        "snapshots": 1,
        "function_occurrences": 1,
        "function_contracts": 0,
        "patterns": 0,
        "pattern_versions": 0,
        "pattern_runs": 0,
        "pattern_story_sequences": 0,
        "motif_evidence": 0,
        "motif_pair_reviews": 0,
        "motif_clusters": 0,
        "snapshot_patterns": 0,
        "outlines": 0,
        "pattern_usage": 0,
    }
    with store.connect() as conn:
        assert conn.execute("SELECT text_content FROM stories").fetchone()[0] == "一个真实故事。"
        row = conn.execute(
            """SELECT o.obs_id, f.function_name
               FROM function_occurrences o
               JOIN functions f ON f.function_id=o.function_id"""
        ).fetchone()
        assert tuple(row) == ("story_obs_001", "TEST_FUNCTION")


def test_snapshot_versions_accumulate_and_link_parent(tmp_path):
    first = _snapshot(tmp_path, _function())
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    store.record_function_run(first, corpus, ["story.txt"], meta, observations)

    second = _snapshot(tmp_path, _function("修订后的结构变化", 2))
    store.record_function_run(second, corpus, ["story.txt"], meta, observations)
    store.record_function_run(second, corpus, ["story.txt"], meta, observations)
    store.record_function_run(first, corpus, ["story.txt"], meta, observations)

    status = store.status()
    assert status["counts"]["snapshots"] == 2
    assert status["counts"]["function_versions"] == 2
    assert status["counts"]["function_evolution_events"] == 2
    assert status["counts"]["observation_versions"] == 2
    with store.connect() as conn:
        row = conn.execute(
            "SELECT parent_snapshot_id FROM snapshots WHERE snapshot_id=?", (os.path.basename(second),)
        ).fetchone()
        assert row[0] == os.path.basename(first)
        assert conn.execute("SELECT definition FROM functions").fetchone()[0] == "修订后的结构变化"


def test_pattern_versions_keep_changed_publications(tmp_path):
    snapshot = _snapshot(tmp_path, _function())
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    store.record_function_run(snapshot, corpus, ["story.txt"], meta, observations)
    snapshot_id = os.path.basename(snapshot)
    catalog_path = tmp_path / "pattern_catalog.json"

    def write(name):
        catalog_path.write_text(json.dumps({
            "snapshot_id": snapshot_id,
            "published_patterns": [{
                "pattern_id": "PAT_1",
                "snapshot_id": snapshot_id,
                "pattern_name": name,
                "story_ids": ["story"],
            }],
            "rejected_patterns": [],
            "manual_review_patterns": [],
        }, ensure_ascii=False), encoding="utf-8")

    write("模式一")
    store.record_pattern_catalog(catalog_path)
    store.record_pattern_catalog(catalog_path)
    write("模式一修订")
    store.record_pattern_catalog(catalog_path)

    status = store.status()
    assert status["counts"]["patterns"] == 1
    assert status["counts"]["pattern_versions"] == 2
    with store.connect() as conn:
        assert conn.execute("SELECT pattern_name FROM patterns").fetchone()[0] == "模式一修订"
        assert conn.execute("SELECT COUNT(*) FROM pattern_evidence").fetchone()[0] == 2


def test_outline_round_trip_is_idempotent(tmp_path):
    snapshot = _snapshot(tmp_path, _function())
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    store.record_function_run(snapshot, corpus, ["story.txt"], meta, observations)
    snapshot_id = os.path.basename(snapshot)
    catalog_path = tmp_path / "pattern_catalog.json"
    catalog_path.write_text(json.dumps({
        "snapshot_id": snapshot_id,
        "published_patterns": [{
            "pattern_id": "PAT_1", "pattern_name": "模式一", "story_ids": ["story"],
        }],
        "rejected_patterns": [], "manual_review_patterns": [],
    }, ensure_ascii=False), encoding="utf-8")
    store.record_pattern_catalog(catalog_path)
    outline = {
        "snapshot_id": snapshot_id, "pattern_id": "PAT_1", "pattern_name": "模式一",
        "genre": "03_现代情感", "generated_at": "2026-08-30T10:00:00",
        "validation": {"overall_ok": True}, "outline": {"segments": []},
    }

    store.claim_pattern(snapshot_id, "PAT_1")
    outline_id = store.record_outline(outline, "# 大纲\n")
    assert store.record_outline(outline, "# 大纲\n") == outline_id
    assert store.load_outline(outline_id)["outline_id"] == outline_id
    assert store.status()["counts"]["outlines"] == 1


def test_pattern_claim_is_global_and_idempotency_is_rejected(tmp_path):
    snapshot = _snapshot(tmp_path, _function())
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    store.record_function_run(snapshot, corpus, ["story.txt"], meta, observations)
    snapshot_id = os.path.basename(snapshot)
    catalog_path = tmp_path / "pattern_catalog.json"
    catalog_path.write_text(json.dumps({
        "snapshot_id": snapshot_id,
        "published_patterns": [{"pattern_id": "PAT_1", "pattern_name": "模式一"}],
        "rejected_patterns": [], "manual_review_patterns": [],
    }, ensure_ascii=False), encoding="utf-8")
    store.record_pattern_catalog(catalog_path)

    store.claim_pattern(snapshot_id, "PAT_1")
    assert store.used_pattern_ids() == {"PAT_1"}
    try:
        store.claim_pattern(snapshot_id, "PAT_1")
    except ValueError as exc:
        assert "已使用" in str(exc)
    else:
        raise AssertionError("同一 Pattern 不应重复领取")


def test_failed_outline_consumes_pattern(tmp_path):
    snapshot = _snapshot(tmp_path, _function())
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    store.record_function_run(snapshot, corpus, ["story.txt"], meta, observations)
    snapshot_id = os.path.basename(snapshot)
    catalog_path = tmp_path / "pattern_catalog.json"
    catalog_path.write_text(json.dumps({
        "snapshot_id": snapshot_id,
        "published_patterns": [{"pattern_id": "PAT_1", "pattern_name": "模式一"}],
        "rejected_patterns": [], "manual_review_patterns": [],
    }, ensure_ascii=False), encoding="utf-8")
    store.record_pattern_catalog(catalog_path)
    outline = {
        "snapshot_id": snapshot_id, "pattern_id": "PAT_1", "pattern_name": "模式一",
        "genre": "03_现代情感", "generated_at": "2026-08-30T10:00:00",
        "validation": {"overall_ok": False, "issues": ["测试失败"]},
        "outline": {"segments": []},
    }

    store.claim_pattern(snapshot_id, "PAT_1")
    store.record_outline(outline, "# 失败大纲\n")
    try:
        store.claim_pattern(snapshot_id, "PAT_1")
    except ValueError as exc:
        assert "已使用" in str(exc)
    else:
        raise AssertionError("校验失败的大纲也应消耗 Pattern")


def test_old_pattern_snapshot_can_read_latest_contract_by_function(tmp_path):
    function = _function()
    pattern_snapshot = _snapshot(tmp_path, function)
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    store.record_function_run(pattern_snapshot, corpus, ["story.txt"], meta, observations)
    contract = {
        "function_id": "F_TEST",
        "function_name": "TEST_FUNCTION",
        "definition_sha256": definition_sha256(function),
        "evidence_refs": ["story_obs_001"],
        "role_slots": ["行动者"],
        "preconditions": [{
            "role_slots": ["行动者"], "aspect": "TASK", "state": "OPEN",
        }],
        "effects": [{
            "role_slots": ["行动者"], "aspect": "TASK",
            "before": "OPEN", "after": "RESOLVED",
        }],
        "obligation_effects": {"opens": [], "advances": [], "resolves": []},
    }
    contract_snapshot = _snapshot(tmp_path, function, [contract])
    store.record_snapshot(contract_snapshot, os.path.basename(pattern_snapshot))

    assert store.load_contracts(os.path.basename(pattern_snapshot)) == []
    assert store.load_contracts(
        os.path.basename(pattern_snapshot), latest_by_function=True,
    )[0]["function_id"] == "F_TEST"
