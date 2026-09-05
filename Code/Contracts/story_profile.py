"""故事级人物、关系与 Function 实例角色位置。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ROLE_POSITIONS = (
    "actor",
    "affected",
    "information_provider",
    "resource_provider",
    "beneficiary",
    "obstacle",
)
ROLE_POSITION_SET = set(ROLE_POSITIONS)
Stance = Literal["support", "obstruct", "mixed", "neutral"]


class StoryCharacter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    structural_role: str = Field(min_length=1, description="主人公/反派/帮助者等结构角色")
    long_term_goal: str = Field(min_length=1)
    motivation: str = Field(min_length=1)
    evidence_sentence_indices: list[int] = Field(default_factory=list)


class StoryRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relation_type: str = Field(min_length=1)
    stance_toward_protagonist: Stance
    description: str = Field(min_length=1)
    evidence_sentence_indices: list[int] = Field(default_factory=list)


class RelationshipDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    dimension: str = Field(min_length=1)
    before: str = Field(min_length=1)
    after: str = Field(min_length=1)
    evidence_sentence_indices: list[int] = Field(default_factory=list, min_length=1)

    @model_validator(mode="after")
    def validate_edge(self):
        if self.source_id == self.target_id:
            raise ValueError("关系变化不能连接同一人物")
        if self.before == self.after:
            raise ValueError("关系变化的前后状态不能相同")
        return self


class EventRoleBindings(BaseModel):
    """Function 实例所需的标准角色位置到人物 ID 的绑定。"""

    model_config = ConfigDict(extra="forbid")

    actor: list[str] = Field(default_factory=list)
    affected: list[str] = Field(default_factory=list)
    information_provider: list[str] = Field(default_factory=list)
    resource_provider: list[str] = Field(default_factory=list)
    beneficiary: list[str] = Field(default_factory=list)
    obstacle: list[str] = Field(default_factory=list)


class StoryProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world_setting: str = Field(default="")
    protagonist_id: str = Field(min_length=1)
    characters: list[StoryCharacter] = Field(min_length=1)
    relationships: list[StoryRelationship] = Field(default_factory=list)
    core_conflict: str = Field(min_length=1)
    ending_state: str = Field(default="")

    @model_validator(mode="after")
    def validate_graph(self):
        ids = [character.id for character in self.characters]
        if len(ids) != len(set(ids)):
            raise ValueError("StoryProfile 人物 ID 必须唯一")
        known = set(ids)
        if self.protagonist_id not in known:
            raise ValueError("StoryProfile protagonist_id 必须引用已声明人物")
        for relationship in self.relationships:
            if relationship.source_id not in known or relationship.target_id not in known:
                raise ValueError("StoryProfile 关系边引用了未知人物")
            if relationship.source_id == relationship.target_id:
                raise ValueError("StoryProfile 关系边不能连接同一人物")
        edges = [
            (item.source_id, item.target_id, item.relation_type)
            for item in self.relationships
        ]
        if len(edges) != len(set(edges)):
            raise ValueError("StoryProfile 关系边不能重复")
        for character in self.characters:
            if any(index < 0 for index in character.evidence_sentence_indices):
                raise ValueError("人物证据句子下标不能为负数")
        for relationship in self.relationships:
            if any(index < 0 for index in relationship.evidence_sentence_indices):
                raise ValueError("关系证据句子下标不能为负数")
        return self


class StoryProfileRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str = Field(min_length=1)
    story_version_id: str = Field(min_length=1)
    profile: StoryProfile


def validate_event_roles(
    profile: StoryProfile,
    participant_ids: list[str],
    role_bindings: EventRoleBindings | dict,
    relationship_deltas: list[RelationshipDelta | dict],
    sentence_count: int | None = None,
) -> None:
    """校验一次 Observation 的人物 ID、角色位置和关系边。"""
    bindings = (
        role_bindings
        if isinstance(role_bindings, EventRoleBindings)
        else EventRoleBindings.model_validate(role_bindings)
    )
    deltas = [
        item if isinstance(item, RelationshipDelta) else RelationshipDelta.model_validate(item)
        for item in relationship_deltas
    ]
    known = {character.id for character in profile.characters}
    participants = set(participant_ids)
    if not participants.issubset(known):
        raise ValueError("Observation participant_ids 引用了未知人物")
    bound_ids = {
        person_id
        for position in ROLE_POSITIONS
        for person_id in getattr(bindings, position)
    }
    if not bound_ids.issubset(known):
        raise ValueError("Observation role_bindings 引用了未知人物")
    if not bound_ids.issubset(participants):
        raise ValueError("Observation participant_ids 必须包含所有角色绑定人物")
    for delta in deltas:
        if delta.source_id not in known or delta.target_id not in known:
            raise ValueError("Observation relationship_deltas 引用了未知人物")
        if not {delta.source_id, delta.target_id}.issubset(participants):
            raise ValueError("Observation participant_ids 必须包含关系变化双方")
        if sentence_count is not None and any(
            index >= sentence_count for index in delta.evidence_sentence_indices
        ):
            raise ValueError("关系变化证据句子下标超出故事范围")
