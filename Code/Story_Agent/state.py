"""Story Agent 的 LangGraph 状态与输出 schema。"""

from typing import Literal, TypedDict

from pydantic import BaseModel, Field, model_validator

from Outline_Agent.state import (
    GlobalLiteraryDesign,
    LiteraryDesign,
    LiteraryStep,
    MechanismPlan,
    NarrativePlan,
)


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
    story_validation: dict | None
    first_story_validation: dict | None
    story_revalidation: dict | None
    story_repair_count: int
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


class LegacyLiteraryDesign(BaseModel):
    """读取旧版 Outline 的文学设计；新生成仍使用完整 LiteraryDesign。"""

    global_design: GlobalLiteraryDesign
    steps: list[LiteraryStep]


class SourceOutlineDocument(BaseModel):
    outline_id: str
    snapshot_id: str
    pattern_id: str | None = None
    planner_mode: Literal["published", "dynamic"] = "published"
    pattern_name: str
    genre: str
    user_request: str | None = None
    seed: dict
    mechanism_plan: MechanismPlan
    narrative_plan: NarrativePlan
    literary_design: LiteraryDesign | LegacyLiteraryDesign | None = None
    contract_ledger: dict | None = None
    outline: SourceOutline
    ending_spec: dict | None = None
    ending_target: dict | None = None
    ending_budget: dict | None = None
    validation: dict | None = None

    @model_validator(mode="before")
    @classmethod
    def adapt_legacy_narrative_ending(cls, values):
        if not isinstance(values, dict):
            return values
        narrative = values.get("narrative_plan")
        outline = values.get("outline") or {}
        if isinstance(narrative, dict) and "ending" not in narrative and outline.get("ending"):
            narrative = dict(narrative)
            narrative["ending"] = outline["ending"]
            values = dict(values)
            values["narrative_plan"] = narrative
        return values


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


class FunctionConstraintPlan(BaseModel):
    segments: list[FunctionSegmentConstraint] = Field(min_length=1)


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
    ending: list[SceneDraft] = Field(min_length=1, max_length=3)


class SceneDevelopment(BaseModel):
    scene_id: str = Field(min_length=1)
    pacing_mode: Literal["DRAMATIZE", "DEVELOP", "COMPRESS"]
    expand_points: list[str]


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


class EndingEvidence(BaseModel):
    requirement_index: int = Field(ge=0)
    scene_id: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class FunctionExecutionEvidence(BaseModel):
    segment_index: int = Field(ge=1)
    function_name: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    status: Literal["PASS", "MISSING"]


class StoryValidation(BaseModel):
    user_request_ok: bool
    causal_constraints_ok: bool
    character_consistency_ok: bool
    ending_ok: bool
    unsupported_solution_ok: bool
    overall_ok: bool
    repairable: bool
    issues: list[str] = Field(default_factory=list)
    ending_evidence: list[EndingEvidence] = Field(default_factory=list)
    function_execution_evidence: list[FunctionExecutionEvidence] = Field(default_factory=list)
