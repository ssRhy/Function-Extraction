"""Outline Agent 的 LangGraph 状态与输出 schema。"""

from typing import TypedDict

from pydantic import BaseModel, Field


class OutlineState(TypedDict):
    snapshot_id: str
    knowledge_db: str
    genre: str
    out_dir: str
    pattern_request: str | None
    user_request: str | None
    pattern_id: str | None
    pattern_name: str
    pattern_selection: dict | None
    ending_spec: dict | None
    chain: list[dict]
    planner_references: dict | None
    seed: dict | None
    mechanism: dict | None
    narrative: dict | None
    contract_ledger: dict | None
    outline: dict | None
    validation: dict | None
    outline_id: str
    result_path: str


class SeedCharacter(BaseModel):
    id: str = Field(description="稳定人物 ID，如 P1")
    label: str = Field(description="身份标签，如 女主/对立方")
    role: str = Field(description="结构角色，如 hero/opponent/helper/love_interest")
    goal: str = Field(description="目标")
    motivation: str = Field(description="追求目标并参与核心冲突的内在原因")
    relationships: dict[str, str] = Field(description="其他人物 ID -> 故事开始时的关系与态度")


class StorySeed(BaseModel):
    genre: str
    world_setting: str
    characters: list[SeedCharacter]
    core_conflict: str
    ending_direction: str


class PatternSelection(BaseModel):
    candidate_index: int = Field(ge=1)
    reason: str = Field(min_length=1)


class MechanismStep(BaseModel):
    segment_index: int = Field(ge=1)
    function_name: str
    role_bindings: dict[str, str] = Field(description="role_slot -> 人物ID")
    who_does_what: str
    why: str
    state_change: str
    character_state_changes: dict[str, str] = Field(description="人物 ID -> 变化前、触发证据、变化后的状态")
    connects_to_next: str


class MechanismPlan(BaseModel):
    steps: list[MechanismStep]


class SetupPayoff(BaseModel):
    content: str = Field(min_length=1)
    payoff_segment_index: int | None = Field(default=None, ge=1)
    payoff: str = Field(min_length=1)


class NarrativeStep(BaseModel):
    segment_index: int = Field(ge=1)
    function_name: str
    genre_realization: str = Field(min_length=1)
    motivation_setup: str = ""
    connective_event: str = ""
    reaction_beat: str = ""
    setup_payoffs: list[SetupPayoff] = Field(default_factory=list, max_length=3)


class NarrativePlan(BaseModel):
    steps: list[NarrativeStep]


class OutlineSegment(BaseModel):
    segment_index: int = Field(ge=1)
    function_name: str
    beats: list[str]
    link: str = Field(default="", description="衔接：如何过渡到下一个 Function，最后一段为空")


class EndingRealization(BaseModel):
    resolution_actions: list[str] = Field(min_length=1)
    conflict_resolution: str = Field(min_length=1)
    final_state: str = Field(min_length=1)


class OutlineRealization(BaseModel):
    segments: list[OutlineSegment]
    final_ledger: list[str]
    ending: EndingRealization


class SegmentCheck(BaseModel):
    segment_index: int = Field(ge=1)
    function_name: str
    recoverable: bool
    issue: str


class OutlineValidation(BaseModel):
    segment_checks: list[SegmentCheck]
    overall_ok: bool
    issues: list[str]
    rule_issues: list[str] = Field(default_factory=list)
    contract_issues: list[str] = Field(default_factory=list)
    contract_warnings: list[str] = Field(default_factory=list)
