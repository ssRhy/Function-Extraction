"""Pipeline Agent 的 LangGraph 状态。"""

from typing import TypedDict


class PipelineState(TypedDict):
    genre: str
    snapshot_id: str
    knowledge_db: str
    pattern_request: str | None
    user_request: str | None
    planner_mode: str
    best_of: int
    out_dir: str
    outline_id: str | None
    outline_path: str | None
    outline_result: dict | None
    outline_results: list[dict]
    story_path: str | None
    candidate_results: list[dict]
    selection: dict | None
    manifest_path: str
