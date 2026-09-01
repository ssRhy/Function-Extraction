"""统一知识库的证据链、版本和幂等测试。"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Contracts.snapshot import publish_snapshot
from Contracts.versioning import observation_version_id, story_version_id
from KnowledgeBase import StoryKnowledgeStore


STORY_TEXT = "一个真实故事。"


def _observation():
    version_id = story_version_id("story", STORY_TEXT)
    item = {
        "obs_id": "story_obs_001",
        "story_id": "story",
        "story_version_id": version_id,
        "observation_order": 1,
        "before_state": "之前",
        "event": "事件",
        "after_state": "之后",
    }
    item["observation_version_id"] = observation_version_id(version_id, item)
    return item


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


def _snapshot(tmp_path, function, contracts=None, parent=None):
    observation = _observation()
    occurrence = {
        "occurrence_id": "story_obs_001",
        "obs_id": "story_obs_001",
        "story_id": "story",
        "observation_version_id": observation["observation_version_id"],
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
        parent_snapshot_id=parent,
    )


def _corpus(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "story.txt").write_text(STORY_TEXT, encoding="utf-8")
    meta = {"story.txt": {"txt_file": "story.txt", "category": "测试"}}
    return corpus, meta, [_observation()]


def _insert_pattern(store, snapshot_id):
    pattern = {"pattern_id": "PAT_1", "pattern_name": "模式一", "story_ids": ["story"]}
    payload = json.dumps(pattern, ensure_ascii=False)
    version_id = f"PV_{snapshot_id}"
    with store.connect() as conn:
        conn.execute(
            """INSERT INTO patterns
               (snapshot_id, pattern_id, pattern_name, status, latest_version_id, payload_json)
               VALUES (?, 'PAT_1', '模式一', 'published', ?, ?)""",
            (snapshot_id, version_id, payload),
        )
        conn.execute(
            """INSERT INTO pattern_versions
               (pattern_version_id, snapshot_id, pattern_id, status, payload_json)
               VALUES (?, ?, 'PAT_1', 'published', ?)""",
            (version_id, snapshot_id, payload),
        )
        conn.execute(
            """INSERT INTO snapshot_patterns
               (snapshot_id, pattern_id, pattern_version_id, status, is_new)
               VALUES (?, 'PAT_1', ?, 'published', 1)""",
            (snapshot_id, version_id),
        )


def test_function_run_records_story_to_occurrence_chain(tmp_path):
    snapshot = _snapshot(tmp_path, _function())
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")

    store.record_function_run(snapshot, corpus, ["story.txt"], meta, observations)

    status = store.status()
    assert status["counts"]["story_versions"] == 1
    assert status["counts"]["snapshot_story_versions"] == 1
    assert status["counts"]["snapshot_observation_versions"] == 1
    with store.connect() as conn:
        assert conn.execute("SELECT text_content FROM story_versions").fetchone()[0] == STORY_TEXT
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

    second = _snapshot(
        tmp_path, _function("修订后的结构变化", 2),
        parent=os.path.basename(first),
    )
    store.record_function_run(second, corpus, ["story.txt"], meta, observations)
    store.record_function_run(second, corpus, ["story.txt"], meta, observations)
    store.record_function_run(first, corpus, ["story.txt"], meta, observations)

    status = store.status()
    assert status["counts"]["snapshots"] == 2
    assert status["counts"]["function_versions"] == 2
    assert status["counts"]["function_evolution_events"] == 2
    assert status["counts"]["observation_versions"] == 1
    with store.connect() as conn:
        row = conn.execute(
            "SELECT parent_snapshot_id FROM snapshots WHERE snapshot_id=?", (os.path.basename(second),)
        ).fetchone()
        assert row[0] == os.path.basename(first)
        assert conn.execute("SELECT definition FROM functions").fetchone()[0] == "修订后的结构变化"


def test_outline_round_trip_is_idempotent(tmp_path):
    snapshot = _snapshot(tmp_path, _function())
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    store.record_function_run(snapshot, corpus, ["story.txt"], meta, observations)
    snapshot_id = os.path.basename(snapshot)
    _insert_pattern(store, snapshot_id)
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
    _insert_pattern(store, snapshot_id)

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
    _insert_pattern(store, snapshot_id)
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
