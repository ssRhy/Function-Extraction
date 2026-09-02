"""
Observer Node - 从句子中提取 Narrative Observations
LangGraph 范式
"""

from typing import TypedDict
from pydantic import BaseModel, Field

from FunctionExtract_Agent.llm import chat_structured
from FunctionExtract_Agent.Prompt.Observer_prompt import OBSERVATION_SYSTEM_PROMPT
from Contracts.versioning import observation_id, observation_version_id


# ========== Pydantic Schema ==========

class ObservationItem(BaseModel):
    before_state: str = Field(description="事件之前的情况/背景")
    event: str = Field(description="具体发生了什么事")
    participants: list[str] = Field(description="参与事件的角色类型，如['英雄','受害者']，不要写具体人名")
    after_state: str = Field(description="事件之后发生了什么变化")
    affected_aspect: str = Field(description="影响的是角色的哪个方面（能力/身份/关系/资源等）")
    narrative_effect: str = Field(description="事件对故事发展的影响")
    surface_form: str = Field(description="表层实现（具体动作，如'比武获胜''治病救人'）")
    source_sentence_indices: list[int] = Field(
        default_factory=list,
        description="支撑此观察的句子在 normalized_story.sentences 中的下标（可追溯；缺失时为空列表）",
    )


class ObservationResponse(BaseModel):
    observations: list[ObservationItem] = Field(description="观察到的叙事事件列表")


class NarrativeObservation(TypedDict):
    obs_id: str
    observation_version_id: str
    observation_order: int
    story_version_id: str
    before_state: str
    event: str
    participants: list[str]
    after_state: str
    affected_aspect: str
    narrative_effect: str
    surface_form: str
    source_sentence_indices: list[int]
    source_text: str
    story_id: str


# ============================================================
# 从 pre_processor 导入统一 State
# ============================================================
from FunctionExtract_Agent.state import NarrativePipelineState


def observer_node(state: NarrativePipelineState) -> NarrativePipelineState:
    """
    Observer 节点

    输入: normalized_story
    输出: observations

    直接读取父状态，LangGraph 自动传递 normalized_story
    """
    normalized = state.get("normalized_story")
    if not normalized:
        return {
            "observations": [],
            "messages": [{
                "role": "system",
                "content": "[Observer] 警告：normalized_story 为空"
            }]
        }

    story_id = normalized["metadata"]["story_id"]
    story_version = normalized["metadata"]["story_version_id"]
    sentences = normalized["sentences"]

    # 构建发送给 LLM 的句子列表
    sentences_text = "\n".join([f"[{i}] {s}" for i, s in enumerate(sentences)])

    result = chat_structured(
        [
            {"role": "system", "content": OBSERVATION_SYSTEM_PROMPT},
            {"role": "user", "content": f"故事句子列表：\n{sentences_text}"}
        ],
        ObservationResponse
    )

    observations = []
    for i, obs in enumerate(result.observations):
        indices = tuple(sorted({
            int(index) for index in (obs.source_sentence_indices or [])
            if isinstance(index, int) and 0 <= index < len(sentences)
        }))
        observation = {
            "story_version_id": story_version,
            "observation_order": i + 1,
            "before_state": obs.before_state,
            "event": obs.event,
            "participants": obs.participants,
            "after_state": obs.after_state,
            "affected_aspect": obs.affected_aspect,
            "narrative_effect": obs.narrative_effect,
            "surface_form": obs.surface_form,
            "source_sentence_indices": list(indices),
            "source_text": "".join(sentences[index] for index in indices),
            "story_id": story_id,
        }
        observation["obs_id"] = observation_id(story_id, observation)
        observation["observation_version_id"] = observation_version_id(story_version, observation)
        observations.append(observation)

    return {
        "observations": observations,
        "messages": [{
            "role": "system",
            "content": f"[Observer] 完成 (ID={story_id}, 观察到={len(observations)})"
        }]
    }
