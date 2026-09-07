"""Story Agent 的 LangGraph 状态与输出 schema。"""

from typing import Literal, TypedDict

from pydantic import BaseModel, Field, field_validator

from Outline_Agent.state import MechanismPlan, NarrativePlan


class StoryState(TypedDict):
    outline_id: str
    knowledge_db: str
    user_request: str | None
    out_dir: str | None
    outline_data: dict | None
    function_constraints: dict | None
    scene_plan: dict | None
    scene_developments: dict | None
    story: dict | None
    result_path: str


class SourceSegment(BaseModel):
    function_name: str
    beats: list[str] = Field(min_length=1)
    link: str = ""


class SourceEnding(BaseModel):
    resolution_actions: list[str] = Field(min_length=1)
    conflict_resolution: str = Field(min_length=1)
    final_state: str = Field(min_length=1)


class SourceOutline(BaseModel):
    segments: list[SourceSegment] = Field(min_length=1)
    ending: SourceEnding


class SourceOutlineDocument(BaseModel):
    outline_id: str
    snapshot_id: str
    pattern_name: str
    genre: str
    seed: dict
    story_profile: dict | None = None  # 预留接口，当前不参与正文生成
    mechanism_plan: MechanismPlan
    narrative_plan: NarrativePlan
    contract_ledger: dict | None = None
    outline: SourceOutline
    ending_spec: dict | None = None
    ending_target: dict | None = None
    ending_budget: dict | None = None
    validation: dict | None = None


class FunctionSegmentConstraint(BaseModel):
    segment_index: int
    function_name: str = Field(min_length=1)
    role_bindings: dict[str, str]
    required_preconditions: list[str]
    required_effects: list[str] = Field(min_length=1)
    obligations_opened: list[str]
    obligations_advanced: list[str]
    obligations_resolved: list[str]
    required_action: str = Field(min_length=1)
    required_reason: str = Field(min_length=1)
    required_state_change: str = Field(min_length=1)
    relationship_changes: list[dict] = Field(
        default_factory=list,
        description="必须保持的有证据关系变化，来自 mechanism_plan",
    )
    causal_to_next: str


class StoryLevelConstraint(BaseModel):
    core_conflict: str = Field(min_length=1)
    ending_resolves: str = Field(min_length=1)
    ending_must_show: list[str] = Field(min_length=1)
    required_final_state: str = Field(min_length=1)
    resolution_actions: list[str] = Field(min_length=1)


class FunctionConstraintPlan(BaseModel):
    segments: list[FunctionSegmentConstraint] = Field(min_length=1)
    story: StoryLevelConstraint


class SceneDraft(BaseModel):
    characters: list[str] = Field(min_length=1)
    setting: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    conflict: str = Field(min_length=1)
    beats: list[str] = Field(min_length=1)
    state_change: str = Field(min_length=1)
    transition: str = ""


class SegmentScenePlan(BaseModel):
    segment_index: int
    scenes: list[SceneDraft] = Field(min_length=1, max_length=3)


class ScenePlanDraft(BaseModel):
    segments: list[SegmentScenePlan] = Field(min_length=1)


class ReactionDecision(BaseModel):
    stimulus: str = Field(min_length=1)
    reaction: str = Field(min_length=1)
    dilemma: str = Field(min_length=1)
    decision: str = Field(min_length=1)


class CausalMoment(BaseModel):
    stimulus: str = Field(min_length=1)
    interpretation: str = Field(min_length=1)
    response: str = Field(min_length=1)


class LiteraryPlan(BaseModel):
    environment_function: str = ""
    sensory_anchor: list[str] = Field(default_factory=list, max_length=3)
    image_or_motif: str = ""
    dialogue_subtext: str = ""
    rhetoric_focus: list[str] = Field(default_factory=list, max_length=2)
    sentence_rhythm: str = ""

    @field_validator(
        "environment_function", "image_or_motif", "dialogue_subtext", "sentence_rhythm",
        mode="before",
    )
    @classmethod
    def normalize_empty_text(cls, value):
        return "" if value is None else value

    @field_validator("sensory_anchor", "rhetoric_focus", mode="before")
    @classmethod
    def normalize_empty_list(cls, value):
        return [] if value is None else value


class SceneDevelopment(BaseModel):
    scene_id: str = Field(min_length=1)
    pacing_mode: Literal["DRAMATIZE", "DEVELOP", "COMPRESS"]
    expand_points: list[str]
    reaction_decision: ReactionDecision | None = None
    causal_moments: list[CausalMoment] = Field(default_factory=list, max_length=2)
    exit_aftereffect: str = ""
    literary_plan: LiteraryPlan

    @field_validator("causal_moments", mode="before")
    @classmethod
    def normalize_empty_causal_moments(cls, value):
        return [] if value is None else value

    @field_validator("exit_aftereffect", mode="before")
    @classmethod
    def normalize_empty_aftereffect(cls, value):
        return "" if value is None else value


class SceneDevelopmentPlan(BaseModel):
    developments: list[SceneDevelopment] = Field(min_length=1)


class StoryScene(BaseModel):
    scene_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class StoryDraft(BaseModel):
    title: str = Field(min_length=1)
    scenes: list[StoryScene] = Field(min_length=1)
    character_names: dict[str, str] = Field(
        default_factory=dict,
        description="故事内稳定人物 ID -> 正文使用的自然姓名",
    )
