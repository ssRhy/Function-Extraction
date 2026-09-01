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
    prior = [{
        "occurrence_id": "story_1_obs_001",
        "story_id": "story_1",
        "function_name": "OLD_FUNCTION",
        "label": "MATCH",
        "reason": "旧 Matcher 结果",
    }]

    result = align_occurrences(functions, [_observation("story_1_obs_001")], prior)

    assert result[0]["status"] == "MATCHED"
    assert result[0]["function_id"] == "F_FINAL"
    assert result[0]["function_name"] == "FINAL_FUNCTION"
    assert result[0]["reason"] == "旧 Matcher 结果"


def test_align_preserves_novel_as_other_and_unbound_as_uncertain():
    observations = [_observation("story_1_obs_001"), _observation("story_1_obs_002")]
    prior = [{
        "occurrence_id": "story_1_obs_001",
        "story_id": "story_1",
        "label": "NOVEL",
    }]

    result = align_occurrences([], observations, prior)

    assert result[0]["status"] == "OTHER"
    assert result[0]["function_name"] == "OTHER"
    assert result[1]["status"] == "UNCERTAIN"
    assert result[1]["function_name"] is None


def test_multiple_final_supports_remain_uncertain():
    functions = [
        {"function_id": "F_1", "function_name": "A", "supporting_obs_ids": ["story_1_obs_001"]},
        {"function_id": "F_2", "function_name": "B", "supporting_obs_ids": ["story_1_obs_001"]},
    ]

    occurrence = align_occurrences(functions, [_observation("story_1_obs_001")])[0]

    assert occurrence["status"] == "UNCERTAIN"
    assert occurrence["candidate_functions"] == ["A", "B"]
