"""最终 FunctionOccurrence 对齐测试。"""

from Contracts.occurrence import align_occurrences


def _observation(obs_id: str) -> dict:
    return {
        "obs_id": obs_id,
        "story_id": "story_1",
        "event": "事件",
        "before_state": "之前",
        "after_state": "之后",
    }


def test_align_uses_final_supporting_function():
    functions = [{
        "function_id": "F_FINAL",
        "function_name": "FINAL_FUNCTION",
        "supporting_obs_ids": ["story_1_obs_001"],
    }]
    result = align_occurrences(functions, [_observation("story_1_obs_001")])

    assert result[0]["status"] == "MATCHED"
    assert result[0]["function_id"] == "F_FINAL"
    assert result[0]["function_name"] == "FINAL_FUNCTION"
    assert "reason" not in result[0]


def test_align_uses_only_current_observation_fields():
    functions = [{
        "function_id": "F_FINAL",
        "function_name": "FINAL_FUNCTION",
        "supporting_obs_ids": ["story_1_obs_001"],
    }]
    current = {
        **_observation("story_1_obs_001"),
        "event": "新事件",
        "observation_version_id": "OV_NEW",
    }

    result = align_occurrences(functions, [current])

    assert result[0]["event"] == "新事件"
    assert result[0]["observation_version_id"] == "OV_NEW"


def test_align_ignores_observations_not_in_current_version():
    observations = [_observation("story_1_obs_001"), _observation("story_1_obs_002")]

    result = align_occurrences([], observations)

    assert len(result) == 2
    assert all(item["status"] == "UNCERTAIN" for item in result)
    assert all(item["function_name"] is None for item in result)


def test_multiple_final_supports_remain_uncertain():
    functions = [
        {"function_id": "F_1", "function_name": "A", "supporting_obs_ids": ["story_1_obs_001"]},
        {"function_id": "F_2", "function_name": "B", "supporting_obs_ids": ["story_1_obs_001"]},
    ]

    occurrence = align_occurrences(functions, [_observation("story_1_obs_001")])[0]

    assert occurrence["status"] == "UNCERTAIN"
    assert occurrence["candidate_functions"] == ["A", "B"]
