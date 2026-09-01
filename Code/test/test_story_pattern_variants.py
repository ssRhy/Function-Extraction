"""Story Pattern Agent motif 语义变体召回测试。"""

from copy import deepcopy

import numpy as np
import pytest

from story_pattern_loader import variants


class _FakeEmbedder:
    vectors = {}

    def encode_cached(self, texts):
        return np.array([self.vectors[text] for text in texts])


def _functions():
    return {
        f"F_{index}": {
            "function_id": f"F_{index}",
            "function_name": f"FUNCTION_{index}",
            "definition": f"definition_{index}",
        }
        for index in range(1, 8)
    }


def _candidate(motif_id, function_ids, story_id, tier="SINGLE_STORY"):
    return {
        "motif_id": motif_id,
        "snapshot_id": "snapshot_test",
        "function_ids": function_ids,
        "function_names": [f"FUNCTION_{item.split('_')[1]}" for item in function_ids],
        "length": len(function_ids),
        "tier": tier,
        "story_support": 1 if tier == "SINGLE_STORY" else 2,
        "story_ids": [story_id] if tier == "SINGLE_STORY" else [story_id, "s9"],
    }


def _state(candidates):
    return {
        "snapshot_manifest": {"snapshot_id": "snapshot_test"},
        "function_by_id": _functions(),
        "motif_candidates": candidates,
    }


def _install_vectors(monkeypatch, vectors):
    functions = _functions()
    _FakeEmbedder.vectors = {
        f"{functions[function_id]['function_name']}。{functions[function_id]['definition']}": vector
        for function_id, vector in vectors.items()
    }
    monkeypatch.setattr(variants, "Embedder", _FakeEmbedder)


def test_retrieves_position_aligned_cross_story_pair(monkeypatch):
    _install_vectors(monkeypatch, {
        "F_1": [1, 0, 0], "F_2": [0, 1, 0], "F_3": [0, 0, 1],
        "F_4": [1, 0, 0], "F_5": [0, 1, 0], "F_6": [0, 0, 1],
    })
    state = _state([
        _candidate("MC_A", ["F_1", "F_2", "F_3"], "s1"),
        _candidate("MC_B", ["F_4", "F_5", "F_6"], "s2"),
    ])
    pair = variants.retrieve_motif_variants(state)["motif_variant_pairs"][0]

    assert pair["member_motif_ids"] == ["MC_A", "MC_B"]
    assert pair["similarity"] == 1.0
    assert pair["recall_tier"] == "HIGH"
    assert pair["length_difference"] == 0
    assert pair["story_ids"] == ["s1", "s2"]
    assert [item["similarity"] for item in pair["alignment"]] == [1.0, 1.0, 1.0]


def test_length_difference_one_uses_best_ordered_gap(monkeypatch):
    _install_vectors(monkeypatch, {
        "F_1": [1, 0, 0], "F_2": [0, 1, 0], "F_3": [0, 0, 1],
        "F_4": [1, 0, 0], "F_5": [1, 1, 1], "F_6": [0, 1, 0], "F_7": [0, 0, 1],
    })
    state = _state([
        _candidate("MC_A", ["F_1", "F_2", "F_3"], "s1"),
        _candidate("MC_B", ["F_4", "F_5", "F_6", "F_7"], "s2"),
    ])
    pair = variants.retrieve_motif_variants(state)["motif_variant_pairs"][0]

    assert pair["similarity"] == 0.9375
    assert pair["recall_tier"] == "HIGH"
    assert pair["length_difference"] == 1
    assert pair["alignment"][1]["left_function_id"] is None
    assert pair["alignment"][1]["right_function_id"] == "F_5"


def test_ordered_gap_can_be_at_sequence_end(monkeypatch):
    _install_vectors(monkeypatch, {
        "F_1": [1, 0, 0], "F_2": [0, 1, 0], "F_3": [0, 0, 1],
        "F_4": [1, 0, 0], "F_5": [0, 1, 0], "F_6": [0, 0, 1], "F_7": [1, 1, 1],
    })
    state = _state([
        _candidate("MC_A", ["F_1", "F_2", "F_3"], "s1"),
        _candidate("MC_B", ["F_4", "F_5", "F_6", "F_7"], "s2"),
    ])
    pair = variants.retrieve_motif_variants(state)["motif_variant_pairs"][0]

    assert pair["alignment"][-1]["left_function_id"] is None
    assert pair["alignment"][-1]["right_function_id"] == "F_7"


def test_filters_weak_and_same_story_but_includes_repeated_candidates(monkeypatch):
    _install_vectors(monkeypatch, {
        "F_1": [1, 0, 0], "F_2": [0, 1, 0], "F_3": [0, 0, 1],
        "F_4": [0, 1, 0], "F_5": [0, 0, 1], "F_6": [1, 0, 0],
    })
    candidates = [
        _candidate("MC_A", ["F_1", "F_2", "F_3"], "s1"),
        _candidate("MC_B", ["F_1", "F_2", "F_3"], "s1"),
        _candidate("MC_C", ["F_4", "F_5", "F_6"], "s2"),
        _candidate("MC_D", ["F_1", "F_2", "F_3"], "s3", tier="REPEATED"),
    ]
    pairs = variants.retrieve_motif_variants(_state(candidates))["motif_variant_pairs"]
    assert {tuple(pair["member_motif_ids"]) for pair in pairs} == {
        ("MC_A", "MC_D"), ("MC_B", "MC_D"),
    }


def test_allows_multiple_ordered_gaps(monkeypatch):
    _install_vectors(monkeypatch, {
        "F_1": [1, 0, 0], "F_2": [0, 1, 0], "F_3": [0, 0, 1],
        "F_4": [1, 0, 0], "F_5": [1, 1, 0], "F_6": [0, 1, 0],
        "F_7": [0, 0, 1],
    })
    state = _state([
        _candidate("MC_A", ["F_1", "F_2", "F_3"], "s1"),
        _candidate("MC_B", ["F_4", "F_5", "F_6", "F_5", "F_7"], "s2"),
    ])
    pair = variants.retrieve_motif_variants(state)["motif_variant_pairs"][0]

    assert pair["length_difference"] == 2
    assert sum(item["left_function_id"] is None for item in pair["alignment"]) == 2
    assert pair["similarity"] == 0.9


def test_similarity_between_thresholds_is_expanded(monkeypatch):
    _install_vectors(monkeypatch, {
        "F_1": [1, 0], "F_2": [1, 0], "F_3": [1, 0],
        "F_4": [0.8, 0.6], "F_5": [0.8, 0.6], "F_6": [0.8, 0.6],
    })
    state = _state([
        _candidate("MC_A", ["F_1", "F_2", "F_3"], "s1"),
        _candidate("MC_B", ["F_4", "F_5", "F_6"], "s2"),
    ])
    pair = variants.retrieve_motif_variants(state)["motif_variant_pairs"][0]

    assert pair["similarity"] == 0.8
    assert pair["recall_tier"] == "EXPANDED"


def test_top_five_is_selected_per_candidate_then_deduplicated(monkeypatch):
    functions = _functions()
    monkeypatch.setattr(variants, "Embedder", _FakeEmbedder)
    _FakeEmbedder.vectors = {
        f"{function['function_name']}。{function['definition']}": [1, 0]
        for function in functions.values()
    }
    candidates = [
        _candidate(f"MC_{index}", ["F_1", "F_2", "F_3"], f"s{index}")
        for index in range(7)
    ]
    pairs = variants.retrieve_motif_variants(_state(candidates))["motif_variant_pairs"]

    selected_counts = {candidate["motif_id"]: 0 for candidate in candidates}
    for pair in pairs:
        for selection in pair["selected_by"]:
            selected_counts[selection["motif_id"]] += 1
            assert 1 <= selection["rank"] <= 5
    assert all(count == 5 for count in selected_counts.values())
    assert len(pairs) < 7 * 5


def test_output_is_deterministic_and_does_not_mutate_input(monkeypatch):
    _install_vectors(monkeypatch, {
        "F_1": [1, 0], "F_2": [0, 1], "F_3": [1, 1],
        "F_4": [1, 0], "F_5": [0, 1], "F_6": [1, 1],
    })
    state = _state([
        _candidate("MC_B", ["F_4", "F_5", "F_6"], "s2"),
        _candidate("MC_A", ["F_1", "F_2", "F_3"], "s1"),
    ])
    before = deepcopy(state)
    first = variants.retrieve_motif_variants(state)
    second = variants.retrieve_motif_variants(state)

    assert first == second
    assert state == before
    assert first["motif_variant_pairs"][0]["variant_pair_id"].startswith("MV_")


@pytest.mark.parametrize("change, message", [
    ({"snapshot_manifest": None}, "Snapshot ID"),
    ({"function_by_id": {}}, "function_by_id"),
    ({"motif_candidates": []}, "motif_candidates"),
])
def test_requires_complete_inputs(change, message):
    state = _state([
        _candidate("MC_A", ["F_1", "F_2", "F_3"], "s1"),
        _candidate("MC_B", ["F_4", "F_5", "F_6"], "s2"),
    ])
    state.update(change)
    with pytest.raises(ValueError, match=message):
        variants.retrieve_motif_variants(state)


@pytest.mark.parametrize("mutate, message", [
    (lambda item: item.update(snapshot_id="wrong"), "Snapshot ID 不匹配"),
    (lambda item: item.update(function_ids=["F_1", "F_2", "UNKNOWN"]), "未知 Function"),
    (lambda item: item["function_names"].__setitem__(0, "WRONG"), "ID/名称不一致"),
    (lambda item: item.update(story_support=2), "支持数无效"),
])
def test_rejects_invalid_candidate(monkeypatch, mutate, message):
    first = _candidate("MC_A", ["F_1", "F_2", "F_3"], "s1")
    mutate(first)
    state = _state([first, _candidate("MC_B", ["F_4", "F_5", "F_6"], "s2")])
    with pytest.raises(ValueError, match=message):
        variants.retrieve_motif_variants(state)
