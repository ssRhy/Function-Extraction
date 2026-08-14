"""
Observer Node - 从句子中提取 Narrative Observations
LangGraph 范式
"""

from typing import TypedDict, Annotated
from langgraph.graph import add_messages
from pydantic import BaseModel, Field

from Agent.llm import chat_structured
from Prompt.Observer_prompt import OBSERVATION_SYSTEM_PROMPT


# ========== Pydantic Schema ==========

class ObservationItem(BaseModel):
    before_state: str = Field(description="事件之前的情况/背景")
    event: str = Field(description="具体发生了什么事")
    participants: list[str] = Field(description="参与事件的角色类型，如['英雄','受害者']，不要写具体人名")
    after_state: str = Field(description="事件之后发生了什么变化")
    affected_aspect: str = Field(description="影响的是角色的哪个方面（能力/身份/关系/资源等）")
    narrative_effect: str = Field(description="事件对故事发展的影响")
    surface_form: str = Field(description="表层实现（具体动作，如'比武获胜''治病救人'）")


class ObservationResponse(BaseModel):
    observations: list[ObservationItem] = Field(description="观察到的叙事事件列表")


class NarrativeObservation(TypedDict):
    obs_id: str
    before_state: str
    event: str
    participants: list[str]
    after_state: str
    affected_aspect: str
    narrative_effect: str
    surface_form: str
    story_id: str


# ============================================================
# 从 pre_processor 导入统一 State
# ============================================================
from Agent.state import NarrativePipelineState


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
        observation = {
            "obs_id": f"{story_id}_obs_{i+1:03d}",
            "before_state": obs.before_state,
            "event": obs.event,
            "participants": obs.participants,
            "after_state": obs.after_state,
            "affected_aspect": obs.affected_aspect,
            "narrative_effect": obs.narrative_effect,
            "surface_form": obs.surface_form,
            "story_id": story_id,
        }
        observations.append(observation)

    return {
        "observations": observations,
        "messages": [{
            "role": "system",
            "content": f"[Observer] 完成 (ID={story_id}, 观察到={len(observations)})"
        }]
    }
