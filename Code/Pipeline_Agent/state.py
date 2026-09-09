"""Pipeline Agent 的 LangGraph 状态。"""

from typing import TypedDict


class PipelineState(TypedDict):
    genre: str
    snapshot_id: str
    knowledge_db: str
    pattern_request: str | None
    user_request: str | None
    planner_mode: str
    out_dir: str
    outline_id: str | None
    outline_path: str | None
    outline_result: dict | None
    story_path: str | None
    manifest_path: str
