"""
Observer Node - 从句子中提取 Narrative Observations
LangGraph 范式
"""

from pydantic import BaseModel, Field, model_validator

from FunctionExtract_Agent.llm import chat_structured
from FunctionExtract_Agent.Prompt.Observer_prompt import OBSERVATION_SYSTEM_PROMPT
from Contracts.versioning import observation_id, observation_version_id
from Contracts.story_profile import (
    EventRoleBindings,
    RelationshipDelta,
    ROLE_POSITIONS,
    StoryProfile,
    validate_event_roles,
)


# ========== Pydantic Schema ==========

class ObservationItem(BaseModel):
    before_state: str = Field(description="事件之前的情况/背景")
    event: str = Field(description="具体发生了什么事")
    participants: list[str] = Field(description="参与事件的角色类型，如['英雄','受害者']，不要写具体人名")
    participant_ids: list[str] = Field(default_factory=list, description="参与事件的人物稳定 ID")
    role_bindings: EventRoleBindings = Field(
        default_factory=EventRoleBindings,
        description="标准角色位置到人物 ID 的绑定；无证据的位置留空",
    )
    relationship_deltas: list[RelationshipDelta] = Field(
        default_factory=list,
        description="本事件明确造成的关系变化；没有关系证据时为空",
    )
    after_state: str = Field(description="事件之后发生了什么变化")
    affected_aspect: str = Field(description="影响的是角色的哪个方面（能力/身份/关系/资源等）")
    narrative_effect: str = Field(description="事件对故事发展的影响")
    surface_form: str = Field(description="表层实现（具体动作，如'比武获胜''治病救人'）")
    source_sentence_indices: list[int] = Field(
        default_factory=list,
        description="支撑此观察的句子在 normalized_story.sentences 中的下标（可追溯；缺失时为空列表）",
    )


class ObservationResponse(BaseModel):
    story_profile: StoryProfile
    observations: list[ObservationItem] = Field(description="观察到的叙事事件列表")

    @model_validator(mode="after")
    def validate_observation_roles(self):
        for observation in self.observations:
            bound_ids = []
            for position in ROLE_POSITIONS:
                for person_id in getattr(observation.role_bindings, position):
                    if person_id not in bound_ids:
                        bound_ids.append(person_id)
            for delta in observation.relationship_deltas:
                for person_id in (delta.source_id, delta.target_id):
                    if person_id not in bound_ids:
                        bound_ids.append(person_id)
            observation.participant_ids = list(dict.fromkeys(
                observation.participant_ids + bound_ids
            ))
            validate_event_roles(
                self.story_profile,
                observation.participant_ids,
                observation.role_bindings,
                observation.relationship_deltas,
            )
        return self


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
        ObservationResponse,
        max_retries=4,
    )

    profile = result.story_profile
    dropped_profile_indices = 0
    for item in [*profile.characters, *profile.relationships]:
        indices = item.evidence_sentence_indices
        valid = [index for index in indices if index < len(sentences)]
        dropped_profile_indices += len(indices) - len(valid)
        item.evidence_sentence_indices = valid

    observations = []
    for i, obs in enumerate(result.observations):
        evidence_indices = {
            index
            for delta in obs.relationship_deltas
            for index in delta.evidence_sentence_indices
        }
        indices = tuple(sorted({
            int(index) for index in (obs.source_sentence_indices or []) + list(evidence_indices)
            if isinstance(index, int) and 0 <= index < len(sentences)
        }))
        participant_ids = list(dict.fromkeys(obs.participant_ids))
        role_bindings = obs.role_bindings.model_dump()
        relationship_deltas = [item.model_dump() for item in obs.relationship_deltas]
        validate_event_roles(
            profile, participant_ids, obs.role_bindings, obs.relationship_deltas,
            sentence_count=len(sentences),
        )
        observation = {
            "story_version_id": story_version,
            "observation_order": i + 1,
            "before_state": obs.before_state,
            "event": obs.event,
            "participants": obs.participants,
            "participant_ids": participant_ids,
            "role_bindings": role_bindings,
            "relationship_deltas": relationship_deltas,
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

    message = f"[Observer] 完成 (ID={story_id}, 观察到={len(observations)})"
    if dropped_profile_indices:
        message += f"，丢弃越界 Profile 证据下标 {dropped_profile_indices} 个"
    return {
        "story_profile": profile.model_dump(),
        "observations": observations,
        "messages": [{
            "role": "system",
            "content": message,
        }]
    }
