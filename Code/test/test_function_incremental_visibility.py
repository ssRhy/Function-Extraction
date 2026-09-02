"""Function Evolve 的 Run 可见性与 Snapshot 不可变性。"""

import hashlib
import json

from Contracts.occurrence import align_occurrences
from Contracts.snapshot import publish_snapshot
from Contracts.versioning import observation_version_id, story_version_id
from KnowledgeBase import StoryKnowledgeStore


FUNCTION = {
    "function_id": "F_TEST",
    "function_name": "TEST",
    "definition": "测试功能",
    "status": "stable",
    "supporting_obs_ids": ["story_obs_001"],
}


def _story(text):
    version_id = story_version_id("story", text)
    return {
        "raw_text": text,
        "metadata": {
            "story_id": "story",
            "story_version_id": version_id,
            "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "title": "Story",
            "story_type": "test",
        },
    }


def _observation(text):
    version_id = story_version_id("story", text)
    item = {
        "obs_id": "story_obs_001",
        "story_id": "story",
        "story_version_id": version_id,
        "observation_order": 1,
        "before_state": "before",
        "event": text,
        "after_state": "after",
    }
    item["observation_version_id"] = observation_version_id(version_id, item)
    return item


def _commit(store, root, run_id, workflow, text, parent=None):
    store.begin_function_run(run_id, workflow, "test", parent)
    observations = store.stage_story_observations(
        run_id, _story(text), {"source_file": "story.txt"}, [_observation(text)], 1,
    )
    snapshot = publish_snapshot(
        [FUNCTION], {"verdict": "PASS"}, workflow, "test", str(root),
        align_occurrences([FUNCTION], observations),
        parent_snapshot_id=parent, run_id=run_id,
    )
    return store.commit_function_run(snapshot, run_id)["snapshot_id"]


def test_run_overlay_snapshot_immutability_and_failure_cleanup(tmp_path):
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    parent = _commit(store, tmp_path / "snapshots", "R1", "bootstrap", "old")
    child = _commit(store, tmp_path / "snapshots", "R2", "evolve", "new", parent)

    assert store.load_story_pattern_inputs(parent)["observations"][0]["event"] == "old"
    assert store.load_story_pattern_inputs(child)["observations"][0]["event"] == "new"

    store.begin_function_run("R3", "evolve", "test", child)
    store.stage_story_observations(
        "R3", _story("failed"), {"source_file": "story.txt"}, [_observation("failed")], 1,
    )
    store.fail_function_run("R3", {"reason": "test"})

    assert store.load_run_observation_view(child, "R3")[0]["event"] == "new"
    with store.connect() as conn:
        assert conn.execute("SELECT status FROM pipeline_runs WHERE run_id='R3'").fetchone()[0] == "FAIL"
        assert conn.execute(
            "SELECT COUNT(*) FROM story_versions WHERE created_by_run_id='R3'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM observations WHERE obs_id='story_obs_001'"
        ).fetchone()[0] == 1


def test_new_run_recovers_interrupted_unpublished_run(tmp_path):
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    store.begin_function_run("R1", "bootstrap", "test", None)
    store.stage_story_observations(
        "R1", _story("interrupted"), {"source_file": "story.txt"},
        [_observation("interrupted")], 1,
    )

    store.begin_function_run("R2", "bootstrap", "test", None)

    with store.connect() as conn:
        row = conn.execute(
            "SELECT status, snapshot_id, payload_json FROM pipeline_runs WHERE run_id='R1'"
        ).fetchone()
        assert row["status"] == "FAIL"
        assert row["snapshot_id"] is None
    payload = json.loads(row["payload_json"])
    assert payload["status"] == "FAILED"
    assert payload["stage"] == "bootstrap"
    assert payload["error_code"] == "INTERRUPTED_BEFORE_SNAPSHOT"
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM run_stories WHERE run_id='R1'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM run_observations WHERE run_id='R1'").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM story_versions WHERE created_by_run_id='R1'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM observation_versions WHERE created_by_run_id='R1'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM observations"
        ).fetchone()[0] == 0
        assert conn.execute("SELECT status FROM pipeline_runs WHERE run_id='R2'").fetchone()[0] == "RUNNING"
