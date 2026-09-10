"""Story Pattern Agent occurrence 加载与序列构建测试。"""

from copy import deepcopy

import pytest

from Contracts.snapshot import publish_snapshot
from KnowledgeBase import StoryKnowledgeStore
from story_pattern_loader import sequences


def _function():
    return [{
        "function_id": "F_1",
        "function_name": "FUNCTION_A",
        "definition": "定义",
    }]


PROFILE = {
    "world_setting": "测试世界", "protagonist_id": "P1",
    "characters": [{
        "id": "P1", "label": "主角", "structural_role": "protagonist",
        "long_term_goal": "完成任务", "motivation": "避免失败",
    }], "relationships": [], "core_conflict": "任务受阻", "ending_state": "任务完成",
}


def _occurrence(obs_id, source_indices, status="MATCHED"):
    return {
        "occurrence_id": obs_id,
        "obs_id": obs_id,
        "observation_version_id": f"OV_{obs_id}",
        "story_id": "s1",
        "status": status,
        "function_id": "F_1" if status == "MATCHED" else None,
        "function_name": "FUNCTION_A" if status == "MATCHED" else None,
        "source_sentence_indices": source_indices,
        "participant_ids": ["P1"],
        "role_bindings": {"actor": ["P1"]},
        "relationship_deltas": [],
    }


def _commit_snapshot(tmp_path, occurrences):
    store = StoryKnowledgeStore(tmp_path / "knowledge.db")
    store.begin_function_run("R_TEST", "bootstrap", "test", None)
    observations = [{
        "obs_id": item["obs_id"],
        "story_id": "s1",
        "before_state": "before",
        "event": item["obs_id"],
        "after_state": "after",
        "participant_ids": ["P1"],
        "role_bindings": {"actor": ["P1"]},
        "relationship_deltas": [],
    } for item in occurrences]
    staged = store.stage_story_observations(
        "R_TEST",
        {"raw_text": "story", "metadata": {"story_id": "s1", "title": "s1", "story_type": "test"}},
        {"source_file": "s1.txt"}, observations, 1, PROFILE,
    )
    versions = {item["obs_id"]: item["observation_version_id"] for item in staged}
    published = [dict(item, observation_version_id=versions[item["obs_id"]]) for item in occurrences]
    path = publish_snapshot(
        _function(), {"verdict": "PASS"}, "bootstrap", "test", str(tmp_path / "snapshots"),
        published, run_id="R_TEST",
        story_profiles=[{"story_id": "s1", "story_version_id": staged[0]["story_version_id"], "profile": PROFILE}],
    )
    manifest = store.commit_function_run(path, "R_TEST")
    return store.db_path, manifest


def _state(db_path, snapshot_id, occurrences):
    return {
        "knowledge_db": str(db_path),
        "snapshot_id": snapshot_id,
        "snapshot_manifest": {"snapshot_id": snapshot_id},
        "story_ids": ["s1"],
        "current_story_id": "s1",
        "occurrences_by_story": {},
        "story_sequences": {},
        "messages": [],
    }


def test_load_occurrences_groups_published_records(tmp_path):
    db, manifest = _commit_snapshot(tmp_path, [_occurrence("s1_obs_001", [1])])
    result = sequences.load_occurrences_node(_state(db, manifest["snapshot_id"], []))

    assert len(result["all_occurrences"]) == 1
    assert result["occurrences_by_story"]["s1"][0]["snapshot_id"] == manifest["snapshot_id"]


def test_build_story_sequences_orders_source_positions(tmp_path):
    path = publish_snapshot(
        _function(), {"verdict": "PASS"}, "evolve", "test", str(tmp_path),
        [_occurrence("s1_obs_002", [20]), _occurrence("s1_obs_001", [3])],
        story_profiles=[{"story_id": "s1", "story_version_id": "SV_s1", "profile": PROFILE}],
    )
    from Contracts.snapshot import validate_snapshot, load_occurrences
    manifest = validate_snapshot(path)
    occurrences = load_occurrences(path)
    state = _state(tmp_path / "unused.db", manifest["snapshot_id"], occurrences)
    state["occurrences_by_story"] = {"s1": occurrences}
    result = sequences.build_story_sequences(state)

    assert [item["occurrence_id"] for item in result["current_sequence"]] == [
        "s1_obs_001", "s1_obs_002",
    ]
    assert result["current_sequence"][0]["order"] == 1


def test_load_occurrences_keeps_story_without_records(tmp_path):
    db, manifest = _commit_snapshot(tmp_path, [_occurrence("s1_obs_001", [1])])
    state = _state(db, manifest["snapshot_id"], [])
    state["story_ids"] = ["s1", "s2"]
    result = sequences.load_occurrences_node(state)

    assert result["occurrences_by_story"]["s2"] == []


def test_build_story_sequences_requires_selected_story():
    with pytest.raises(ValueError, match="current_story_id"):
        sequences.build_story_sequences({"current_story_id": None})


def test_build_story_sequences_keeps_empty_story_sequence():
    result = sequences.build_story_sequences({
        "current_story_id": "s1",
        "occurrences_by_story": {"s1": []},
        "story_sequences": {},
    })

    assert result["story_sequences"]["s1"] == []
    assert result["current_sequence"] == []


def _sequence_item(order, function_id="F_1", status="MATCHED", name="FUNCTION_A"):
    return {
        "order": order,
        "occurrence_id": f"s1_obs_{order:03d}",
        "obs_id": f"s1_obs_{order:03d}",
        "function_id": function_id if status == "MATCHED" else None,
        "function_name": name if status == "MATCHED" else ("OTHER" if status == "OTHER" else None),
        "status": status,
    }


def test_annotate_repetitions_groups_consecutive_matched_function():
    state = {
        "current_story_id": "s1",
        "current_sequence": [_sequence_item(1), _sequence_item(2), _sequence_item(3)],
        "structural_sequences": {},
    }
    result = sequences.annotate_repetitions(state)
    run = result["current_structural_sequence"][0]

    assert run == {
        "order": 1,
        "function_id": "F_1",
        "function_name": "FUNCTION_A",
        "status": "MATCHED",
        "repeat_count": 3,
        "occurrence_ids": ["s1_obs_001", "s1_obs_002", "s1_obs_003"],
        "obs_ids": ["s1_obs_001", "s1_obs_002", "s1_obs_003"],
        "raw_orders": [1, 2, 3],
    }


def test_annotate_repetitions_keeps_non_consecutive_repeat():
    state = {
        "current_story_id": "s1",
        "current_sequence": [
            _sequence_item(1),
            _sequence_item(2, "F_2", name="FUNCTION_B"),
            _sequence_item(3),
        ],
        "structural_sequences": {},
    }
    result = sequences.annotate_repetitions(state)

    assert [run["function_id"] for run in result["current_structural_sequence"]] == [
        "F_1", "F_2", "F_1",
    ]


def test_annotate_repetitions_uses_function_id_not_name():
    state = {
        "current_story_id": "s1",
        "current_sequence": [
            _sequence_item(1, "F_1", name="SAME_NAME"),
            _sequence_item(2, "F_2", name="SAME_NAME"),
        ],
        "structural_sequences": {},
    }
    result = sequences.annotate_repetitions(state)

    assert len(result["current_structural_sequence"]) == 2


def test_unresolved_nodes_stay_separate_and_split_matched_runs():
    state = {
        "current_story_id": "s1",
        "current_sequence": [
            _sequence_item(1),
            _sequence_item(2, status="UNCERTAIN"),
            _sequence_item(3, status="UNCERTAIN"),
            _sequence_item(4, status="OTHER"),
            _sequence_item(5),
        ],
        "structural_sequences": {},
    }
    result = sequences.annotate_repetitions(state)
    runs = result["current_structural_sequence"]

    assert [run["status"] for run in runs] == [
        "MATCHED", "UNCERTAIN", "UNCERTAIN", "OTHER", "MATCHED",
    ]
    assert all(run["repeat_count"] == 1 for run in runs)


def test_annotate_repetitions_preserves_raw_sequence_and_singletons():
    state = {
        "current_story_id": "s1",
        "current_sequence": [
            _sequence_item(1),
            _sequence_item(2, "F_2", name="FUNCTION_B"),
        ],
        "structural_sequences": {},
    }
    before = deepcopy(state)
    result = sequences.annotate_repetitions(state)

    assert state == before
    assert [run["repeat_count"] for run in result["current_structural_sequence"]] == [1, 1]


def test_annotate_repetitions_requires_selected_story():
    state = {"current_story_id": None, "current_sequence": []}
    with pytest.raises(ValueError, match="current_story_id"):
        sequences.annotate_repetitions(state)


def test_annotate_repetitions_keeps_empty_story_sequence():
    result = sequences.annotate_repetitions({
        "current_story_id": "s1",
        "current_sequence": [],
        "structural_sequences": {},
    })

    assert result["structural_sequences"]["s1"] == []


def _run(order, function_id="F_1", name="FUNCTION_A", status="MATCHED", repeat_count=1):
    return {
        "order": order,
        "function_id": function_id if status == "MATCHED" else None,
        "function_name": name if status == "MATCHED" else ("OTHER" if status == "OTHER" else None),
        "status": status,
        "repeat_count": repeat_count,
        "occurrence_ids": [f"s_obs_{order}_{i}" for i in range(repeat_count)],
        "obs_ids": [f"s_obs_{order}_{i}" for i in range(repeat_count)],
        "raw_orders": list(range(order, order + repeat_count)),
    }


def _context_state(structural_sequences, story_ids=None):
    return {
        "story_ids": story_ids or ["s1"],
        "structural_sequences": structural_sequences,
        "function_by_id": {
            "F_1": {"function_id": "F_1", "function_name": "FUNCTION_A"},
            "F_2": {"function_id": "F_2", "function_name": "FUNCTION_B"},
            "F_3": {"function_id": "F_3", "function_name": "FUNCTION_C"},
            "F_EMPTY": {"function_id": "F_EMPTY", "function_name": "EMPTY"},
        },
        "story_metadata": {
            "s1": {"story_type": "悬疑"},
            "s2": {"story_type": "情感"},
        },
    }


def test_index_function_contexts_builds_anchor_for_each_function():
    state = _context_state({"s1": [
        _run(1),
        _run(2, "F_2", "FUNCTION_B"),
        _run(3, "F_3", "FUNCTION_C"),
    ]})
    result = sequences.index_function_contexts(state)

    assert [result["function_contexts"][fid][0]["anchor_index"] for fid in ("F_1", "F_2", "F_3")] == [0, 1, 2]
    assert [item["function_id"] for item in result["function_contexts"]["F_2"][0]["segment"]] == [
        "F_1", "F_2", "F_3",
    ]
    assert result["function_contexts"]["F_2"][0]["segment"][1]["structural_order"] == 2
    assert result["function_contexts"]["F_2"][0]["segment"][1]["occurrence_ids"] == ["s_obs_2_0"]
    assert result["function_contexts"]["F_2"][0]["category"] == "悬疑"
    assert result["function_contexts"]["F_EMPTY"] == []


@pytest.mark.parametrize("boundary", ["UNCERTAIN", "OTHER"])
def test_unresolved_boundary_splits_function_contexts(boundary):
    state = _context_state({"s1": [
        _run(1),
        _run(2, status=boundary),
        _run(3, "F_2", "FUNCTION_B"),
    ]})
    result = sequences.index_function_contexts(state)

    assert [item["function_id"] for item in result["function_contexts"]["F_1"][0]["segment"]] == ["F_1"]
    assert [item["function_id"] for item in result["function_contexts"]["F_2"][0]["segment"]] == ["F_2"]


def test_repetition_run_creates_one_context_with_all_evidence():
    state = _context_state({"s1": [_run(1, repeat_count=3)]})
    context = sequences.index_function_contexts(state)["function_contexts"]["F_1"][0]

    assert context["repeat_count"] == 3
    assert len(context["occurrence_ids"]) == 3
    assert len(state["structural_sequences"]["s1"]) == 1


def test_same_function_non_consecutive_creates_multiple_contexts():
    state = _context_state({"s1": [
        _run(1),
        _run(2, "F_2", "FUNCTION_B"),
        _run(3),
    ]})
    contexts = sequences.index_function_contexts(state)["function_contexts"]["F_1"]

    assert [context["anchor_index"] for context in contexts] == [0, 2]


def test_function_contexts_follow_manifest_story_order():
    state = _context_state(
        {"s2": [_run(1)], "s1": [_run(1)]},
        story_ids=["s1", "s2"],
    )
    contexts = sequences.index_function_contexts(state)["function_contexts"]["F_1"]

    assert [context["story_id"] for context in contexts] == ["s1", "s2"]


def test_index_function_contexts_does_not_mutate_state():
    state = _context_state({"s1": [_run(1)]})
    before = deepcopy(state)
    sequences.index_function_contexts(state)
    assert state == before


@pytest.mark.parametrize("state, message", [
    ({"story_ids": [], "structural_sequences": {}, "function_by_id": {}}, "story_ids"),
    ({"story_ids": ["s1"], "structural_sequences": {}, "function_by_id": {"F_1": {}}}, "缺少 structural_sequence"),
    ({"story_ids": ["s1"], "structural_sequences": {"s1": []}, "function_by_id": {}}, "function_by_id"),
])
def test_index_function_contexts_requires_complete_inputs(state, message):
    with pytest.raises(ValueError, match=message):
        sequences.index_function_contexts(state)


@pytest.mark.parametrize("change, message", [
    ({"function_id": "F_UNKNOWN"}, "未知 Function"),
    ({"function_name": "WRONG_NAME"}, "ID/名称不一致"),
    ({"status": "INVALID"}, "status 无效"),
])
def test_index_function_contexts_rejects_invalid_matched_run(change, message):
    run = _run(1)
    run.update(change)
    state = _context_state({"s1": [run]})
    with pytest.raises(ValueError, match=message):
        sequences.index_function_contexts(state)
