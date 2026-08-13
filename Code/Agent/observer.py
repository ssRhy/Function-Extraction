"""
Observer Node - 从句子中提取 Narrative Observations
LangGraph 范式
"""

from typing import TypedDict, Annotated
from langgraph.graph import add_messages
from datetime import datetime
from pydantic import BaseModel, Field

from Agent.llm import chat_structured
from Agent.pre_processor import NormalizedStory
from Prompt.Observer_prompt import OBSERVATION_SYSTEM_PROMPT


# ========== Pydantic Schema ==========

class ObservationItem(BaseModel):
    prior_context: str = Field(description="事件之前的情况/背景")
    event: str = Field(description="具体发生了什么事")
    after_state: str = Field(description="事件之后发生了什么变化")
    narrative_effect: str = Field(description="事件对故事发展的影响")
    surface_form: str = Field(description="表层实现（具体动作）")
    affected_aspect: str = Field(description="影响的是角色的哪个方面")
    source_sentence_indices: list[int] = Field(description="来源句子索引列表")


class ObservationResponse(BaseModel):
    observations: list[ObservationItem] = Field(description="观察到的叙事事件列表")


class NarrativeObservation(TypedDict):
    obs_id: str
    prior_context: str
    event: str
    after_state: str
    narrative_effect: str
    surface_form: str
    affected_aspect: str
    source_sentence_indices: list[int]
    source_segment_id: str
    story_id: str
    extracted_at: str


# ============================================================
# 从 pre_processor 导入统一 State
# ============================================================
from Agent.pre_processor import NarrativePipelineState


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
    segments = normalized["segments"]

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
        source_indices = obs.source_sentence_indices
        source_segment_id = ""

        for seg in segments:
            if any(idx in seg.get("sentence_indices", []) for idx in source_indices):
                source_segment_id = seg["segment_id"]
                break

        observation = {
            "obs_id": f"{story_id}_obs_{i+1:03d}",
            "prior_context": obs.prior_context,
            "event": obs.event,
            "after_state": obs.after_state,
            "narrative_effect": obs.narrative_effect,
            "surface_form": obs.surface_form,
            "affected_aspect": obs.affected_aspect,
            "source_sentence_indices": source_indices,
            "source_segment_id": source_segment_id,
            "story_id": story_id,
            "extracted_at": datetime.now().isoformat()
        }
        observations.append(observation)

    return {
        "observations": observations,
        "messages": [{
            "role": "system",
            "content": f"[Observer] 完成 (ID={story_id}, 观察到={len(observations)})"
        }]
    }
