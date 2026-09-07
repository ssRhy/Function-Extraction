"""统一知识库的证据链、版本和幂等测试。"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Contracts.snapshot import publish_snapshot
from Contracts.versioning import observation_version_id, story_version_id
from KnowledgeBase import StoryKnowledgeStore


STORY_TEXT = "一个真实故事。"


def _profile():
    return {
        "world_setting": "测试世界", "protagonist_id": "P1",
        "characters": [{
            "id": "P1", "label": "主角", "structural_role": "protagonist",
            "long_term_goal": "完成任务", "motivation": "避免失败",
        }], "relationships": [], "core_conflict": "任务受阻", "ending_state": "任务完成",
    }


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
        "participant_ids": ["P1"],
        "role_bindings": {"actor": ["P1"]},
        "relationship_deltas": [],
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


def _snapshot(tmp_path, function, contracts=None, parent=None, workflow="evolve", namespace="test_namespace"):
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
        "participant_ids": ["P1"],
        "role_bindings": {"actor": ["P1"]},
        "relationship_deltas": [],
    }
    return publish_snapshot(
        [function],
        {"verdict": "PASS"},
        workflow,
        namespace,
        str(tmp_path / "snapshots"),
        [occurrence],
        contracts,
        story_profiles=[{"story_id": "story", "story_version_id": observation["story_version_id"], "profile": _profile()}],
        parent_snapshot_id=parent,
    )


def _corpus(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "story.txt").write_text(STORY_TEXT, encoding="utf-8")
    meta = {"story.txt": {"txt_file": "story.txt", "category": "测试"}}
    return corpus, meta, [_observation()]


def _commit_function_snapshot(store, snapshot, corpus, story_meta, observations):
    with open(os.path.join(snapshot, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    existing = store.load_function_run(manifest["run_id"])
    if existing and existing["status"] == "PASS":
        return manifest
    store.begin_function_run(
        manifest["run_id"], manifest["source_workflow"], manifest["namespace"],
        manifest.get("parent_snapshot_id"), str(corpus),
    )
    by_story = {}
    for observation in observations:
        by_story.setdefault(observation["story_id"], []).append(observation)
    for position, filename in enumerate(story_meta, 1):
        meta = story_meta[filename]
        story_id = meta.get("story_id") or os.path.splitext(filename)[0]
        text = (corpus / filename).read_text(encoding="utf-8")
        version_id = story_version_id(story_id, text)
        store.stage_story_observations(
            manifest["run_id"],
            {"raw_text": text, "metadata": {
                "story_id": story_id,
                "story_version_id": version_id,
            }},
            {**meta, "source_file": filename},
            by_story.get(story_id, []), position,
            _profile(),
        )
    return store.commit_function_run(snapshot, manifest["run_id"])


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

    _commit_function_snapshot(store, snapshot, corpus, meta, observations)

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
    _commit_function_snapshot(store, first, corpus, meta, observations)

    second = _snapshot(
        tmp_path, _function("修订后的结构变化", 2),
        parent=os.path.basename(first),
    )
    _commit_function_snapshot(store, second, corpus, meta, observations)
    _commit_function_snapshot(store, second, corpus, meta, observations)
    _commit_function_snapshot(store, first, corpus, meta, observations)

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


def test_run_profile_view_inherits_parent_and_overrides_current_story(tmp_path):
    first = _snapshot(tmp_path, _function())
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    _commit_function_snapshot(store, first, corpus, meta, observations)

    run_id = "FR_PROFILE_OVERRIDE"
    parent_id = os.path.basename(first)
    store.begin_function_run(run_id, "evolve", "profile_override", parent_id, str(corpus))
    changed_text = "一个更新后的真实故事。"
    changed_profile = _profile()
    changed_profile["characters"][0]["long_term_goal"] = "完成新的任务"
    store.stage_story_observations(
        run_id,
        {"raw_text": changed_text, "metadata": {
            "story_id": "story",
            "story_version_id": story_version_id("story", changed_text),
        }},
        {"source_file": "story.txt"},
        [], 1, changed_profile,
    )

    view = store.load_run_story_profile_view(parent_id, run_id)
    assert len(view) == 1
    assert view[0]["story_id"] == "story"
    assert view[0]["profile"]["characters"][0]["long_term_goal"] == "完成新的任务"


def test_lineage_event_payload_round_trip(tmp_path):
    function = _function()
    function["version_history"].append({
        "version": 2,
        "action": "MERGE",
        "source_function_ids": ["F_A", "F_B"],
        "target_function_ids": ["F_TEST"],
        "ts": "2026-01-02",
    })
    snapshot = _snapshot(tmp_path, function)
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    _commit_function_snapshot(store, snapshot, corpus, meta, observations)

    with store.connect() as conn:
        row = conn.execute(
            "SELECT payload_json FROM function_evolution_events WHERE action='MERGE'"
        ).fetchone()
    payload = json.loads(row[0])
    assert payload["source_function_ids"] == ["F_A", "F_B"]
    assert payload["target_function_ids"] == ["F_TEST"]


def test_pattern_start_recovers_interrupted_run(tmp_path):
    first = _snapshot(
        tmp_path, _function(), workflow="bootstrap", namespace="pattern_first",
    )
    second = _snapshot(
        tmp_path, _function("另一种结构变化"), workflow="bootstrap", namespace="pattern_second",
    )
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    _commit_function_snapshot(store, first, corpus, meta, observations)
    _commit_function_snapshot(store, second, corpus, meta, observations)

    first_id = os.path.basename(first)
    second_id = os.path.basename(second)
    store.begin_pattern_run(first_id, "first")
    store.begin_pattern_run(second_id, "second")

    recovered = store.load_pattern_run(first_id)
    assert recovered["status"] == "FAILED"
    assert recovered["payload"]["status"] == "FAILED"
    assert recovered["payload"]["stage"] == "pattern"
    assert recovered["payload"]["error_code"] == "INTERRUPTED_BEFORE_PATTERN_COMMIT"
    assert recovered["payload"]["error"] == "进程在 Pattern 提交前中断"
    assert store.load_pattern_run(second_id)["status"] == "RUNNING"


def test_outline_round_trip_is_idempotent(tmp_path):
    snapshot = _snapshot(tmp_path, _function())
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    _commit_function_snapshot(store, snapshot, corpus, meta, observations)
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


def test_generation_outcome_feedback_is_snapshot_scoped(tmp_path):
    snapshot = _snapshot(tmp_path, _function())
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    _commit_function_snapshot(store, snapshot, corpus, meta, observations)
    snapshot_id = os.path.basename(snapshot)
    _insert_pattern(store, snapshot_id)
    outline = {
        "snapshot_id": snapshot_id, "pattern_id": "PAT_1", "pattern_name": "模式一",
        "genre": "03_现代情感", "generated_at": "2026-08-30T10:00:00",
        "validation": {"overall_ok": True}, "outline": {"segments": []},
    }
    outline_id = store.record_outline(outline, "# 大纲\n")

    for attempt in (1, 2):
        store.record_generation_outcome(
            snapshot_id, "PAT_1", outline_id, "published", False, False,
            "semantic", "rejected", {"attempt": attempt},
        )

    outcomes = store.load_generation_outcomes(snapshot_id)
    assert len(outcomes) == 2
    assert outcomes[0]["outline_id"] == outline_id
    assert outcomes[0]["validation_ok"] is False
    feedback = store.load_pattern_feedback(snapshot_id)
    assert feedback["PAT_1"]["failure_count"] == 2
    assert feedback["PAT_1"]["priority_delta"] == -1
    assert store.status()["counts"]["generation_outcomes"] == 2


def test_record_outline_claims_pattern(tmp_path):
    snapshot = _snapshot(tmp_path, _function())
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    _commit_function_snapshot(store, snapshot, corpus, meta, observations)
    snapshot_id = os.path.basename(snapshot)
    _insert_pattern(store, snapshot_id)
    outline = {
        "snapshot_id": snapshot_id, "pattern_id": "PAT_1", "pattern_name": "模式一",
        "genre": "03_现代情感", "generated_at": "2026-08-30T10:00:00",
        "validation": {"overall_ok": True}, "outline": {"segments": []},
    }

    outline_id = store.record_outline(outline, "# 大纲\n")
    with store.connect() as conn:
        usage = conn.execute(
            "SELECT outline_id FROM pattern_usage WHERE pattern_id='PAT_1'"
        ).fetchone()
    assert usage["outline_id"] == outline_id


def test_pattern_claim_is_global_and_idempotency_is_rejected(tmp_path):
    snapshot = _snapshot(tmp_path, _function())
    corpus, meta, observations = _corpus(tmp_path)
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    _commit_function_snapshot(store, snapshot, corpus, meta, observations)
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
    _commit_function_snapshot(store, snapshot, corpus, meta, observations)
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
