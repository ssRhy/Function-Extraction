"""Story Pattern Agent 当前故事选择节点。"""

from .state import StoryPatternState


def has_next_story(state: StoryPatternState) -> bool:
    """判断是否还有待处理故事；负下标视为非法状态。"""
    index = state["current_story_index"]
    if index < 0:
        raise IndexError(f"current_story_index 不能为负数: {index}")
    return index < len(state["story_ids"])


def select_story(state: StoryPatternState) -> dict:
    """选择当前故事并清空上一篇故事的临时 occurrence。"""
    index = state["current_story_index"]
    if not has_next_story(state):
        raise IndexError(f"current_story_index 越界: {index}")

    story_id = state["story_ids"][index]
    metadata = state["story_metadata"].get(story_id)
    observations = state["observations_by_story"].get(story_id)
    if metadata is None:
        raise ValueError(f"故事缺少 metadata: {story_id}")
    if not observations:
        raise ValueError(f"故事缺少 Observations: {story_id}")

    return {
        "current_story_id": story_id,
        "current_metadata": metadata,
        "current_observations": observations,
        "current_occurrences": [],
        "current_structural_sequence": [],
        "messages": [{
            "role": "system",
            "content": f"[StoryPattern.select_story] {story_id}，Observation={len(observations)}",
        }],
    }
