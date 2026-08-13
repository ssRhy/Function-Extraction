"""
Narrative Pipeline App - LangGraph 图连接定义
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from Agent.pre_processor import NarrativePipelineState, preprocessor_node
from Agent.observer import observer_node


def build_pipeline_graph() -> StateGraph:
    """
    构建 Pre-Processor → Observer 的 LangGraph

    边连接设计：
        START → preprocessor → observer → END

    State 流动：
        raw_text + story_config → preprocessor → normalized_story → observer → observations
    """
    graph = StateGraph(NarrativePipelineState)

    # 添加节点
    graph.add_node("preprocessor", preprocessor_node)
    graph.add_node("observer", observer_node)

    # 添加边
    graph.add_edge(START, "preprocessor")
    graph.add_edge("preprocessor", "observer")
    graph.add_edge("observer", END)

    return graph


# 编译：支持 checkpointer 实现状态持久化
checkpointer = MemorySaver()
pipeline_app = build_pipeline_graph().compile(checkpointer=checkpointer)

