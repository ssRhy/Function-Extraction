"""
NarrativePipelineState - LangGraph 统一状态定义
所有节点共享的 State，按数据生命周期分节
"""

from typing import TypedDict, Annotated
from langgraph.graph import add_messages


class NarrativePipelineState(TypedDict):
    """统一状态，所有节点共享"""

    # LangGraph 规范：自动处理消息追加
    messages: Annotated[list, add_messages]

    # ---- 故事输入 ----
    raw_text: str | None
    story_config: dict | None  # story_id, title, story_type

    # ---- Pre-Processor 输出 ----
    normalized_story: dict | None  # NormalizedStory

    # ---- Observer 输出 ----
    observations: list[dict]  # NarrativeObservation 列表

    # ---- Bank 输出 ----
    added_obs_ids: list[str]  # bank_adder 输出

    # ---- Retrieval 输出 ----
    similar_observations: list[dict]  # 跨故事相似 obs 对

    # ---- 流程控制 ----
    current_phase: str  # "bootstrap" | "evolve"
    current_story_index: int
    total_stories: int
