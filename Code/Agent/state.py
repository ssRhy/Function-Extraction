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

    # ---- Inducer 输出 ----
    induced_functions: list[dict]  # 归纳出的候选 Function

    # ---- Evaluator 输出 ----
    evaluation_report: dict | None  # 六维评估报告
    evaluator_decision: str | None  # PASS / FAIL
    evaluation_context: dict | None  # 评估上下文（registry_file/bank_file/manifest_path/report_path）
    revise_report: dict | None  # 修订节点输出（合并/修订/拆分/移除清单）
    evaluation_round: int  # bootstrap_app 修订轮次计数
    review_targets: list[str] | None  # 下一轮 Abstraction 复核目标（修订变更集；None=全量复核）
    force_full_review: bool | None  # 最终评估轮强制全新全量 Abstraction 复核（不增量复用）

    # ---- 流程控制 ----
    current_story_index: int
    total_stories: int

    # ---- 批处理编排（bootstrap_app 单图）----
    story_files: list[str]      # 待处理故事相对路径（自然排序）
    corpus_dir: str             # 语料根目录
    story_meta: dict            # manifest: txt_file -> entry（category/question_title）
    all_pairs: list[dict]       # 累计跨故事相似 obs 对
    induction_components: list[list[dict]]  # cluster 后的可归纳分量（≥2 故事）
    induction_index: int        # 当前分量下标
    errors: list[str]           # 逐篇/每分量失败记录（不中断）
    no_revise: bool             # 仅评估，跳过修订闭环
    namespace: str              # Registry 命名空间
    out_dir: str                # 快照输出目录
    discarded: bool             # 逐函数舍弃后无幸存者（O_0 为空）时置 True
