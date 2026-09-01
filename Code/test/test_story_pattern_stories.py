"""Story Pattern Agent select_story 节点测试。"""

from copy import deepcopy

import pytest

from story_pattern_loader import stories

has_next_story = stories.has_next_story
select_story = stories.select_story


def _state(index=0):
    observations = {
        "s1": [{"obs_id": "s1_obs_001"}, {"obs_id": "s1_obs_002"}],
        "s2": [{"obs_id": "s2_obs_001"}],
    }
    return {
        "messages": [],
        "story_ids": ["s1", "s2"],
        "story_metadata": {
            "s1": {"story_id": "s1", "question_title": "故事一"},
            "s2": {"story_id": "s2", "question_title": "故事二"},
        },
        "observations_by_story": observations,
        "current_story_index": index,
        "current_story_id": "old",
        "current_metadata": {"story_id": "old"},
        "current_observations": [{"obs_id": "old_obs_001"}],
        "current_occurrences": [{"occurrence_id": "old_obs_001"}],
        "current_structural_sequence": [{"function_id": "F_OLD"}],
    }


def test_select_story_uses_current_index_without_mutating_source():
    state = _state(index=1)
    before = deepcopy(state)
    result = select_story(state)

    assert state == before
    assert result["current_story_id"] == "s2"
    assert result["current_metadata"] is state["story_metadata"]["s2"]
    assert result["current_observations"] is state["observations_by_story"]["s2"]
    assert [o["obs_id"] for o in result["current_observations"]] == ["s2_obs_001"]
    assert result["current_occurrences"] == []
    assert result["current_structural_sequence"] == []
    assert "current_story_index" not in result


def test_select_story_preserves_observation_order():
    result = select_story(_state())
    assert [o["obs_id"] for o in result["current_observations"]] == [
        "s1_obs_001", "s1_obs_002",
    ]


@pytest.mark.parametrize("index, expected", [(0, True), (1, True), (2, False), (3, False)])
def test_has_next_story(index, expected):
    assert has_next_story(_state(index)) is expected


def test_negative_index_rejected():
    with pytest.raises(IndexError, match="不能为负数"):
        has_next_story(_state(-1))


def test_select_story_out_of_range_rejected():
    with pytest.raises(IndexError, match="越界"):
        select_story(_state(2))


def test_missing_metadata_rejected():
    state = _state()
    del state["story_metadata"]["s1"]
    with pytest.raises(ValueError, match="缺少 metadata"):
        select_story(state)


@pytest.mark.parametrize("observations", [None, []])
def test_missing_observations_rejected(observations):
    state = _state()
    if observations is None:
        del state["observations_by_story"]["s1"]
    else:
        state["observations_by_story"]["s1"] = observations
    with pytest.raises(ValueError, match="缺少 Observations"):
        select_story(state)
