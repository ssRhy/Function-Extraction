"""
Narrative Pipeline App - LangGraph 图连接定义
Bootstrap 完整链路：
    START → preprocessor → observer → bank_adder → retrieval → END
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from Agent.state import NarrativePipelineState
from Agent.pre_processor import preprocessor_node
from Agent.observer import observer_node
from Bank.bank import ObservationBank
from Retrieval.retrieval import Retriever


# ============================================================
# Bank 单例（避免每个节点重复初始化 Embedder）
# ============================================================
_bank_instance = None

def _get_bank() -> ObservationBank:
    global _bank_instance
    if _bank_instance is None:
        _bank_instance = ObservationBank()
    return _bank_instance


# ============================================================
# LangGraph Nodes
# ============================================================

def bank_adder_node(state: NarrativePipelineState) -> NarrativePipelineState:
    """将新提取的 Observations 存入 Bank"""
    observations = state.get("observations", [])
    if not observations:
        return {
            "added_obs_ids": [],
            "messages": [{"role": "system", "content": "[BankAdder] 无 observations，跳过"}]
        }
    bank = _get_bank()
    added_ids = bank.add(observations)
    return {
        "added_obs_ids": added_ids,
        "messages": [{"role": "system", "content": f"[BankAdder] 添加 {len(added_ids)} 条"}]
    }


def retrieval_node(state: NarrativePipelineState) -> NarrativePipelineState:
    """对新提取的每个 Observation 检索 Bank 中跨故事的相似对"""
    observations = state.get("observations", [])
    if not observations:
        return {"similar_observations": [], "messages": []}

    bank = _get_bank()
    if bank.count() <= len(observations):
        return {
            "similar_observations": [],
            "messages": [{"role": "system", "content": "[Retrieval] Bank 数据不足，跳过"}]
        }

    retriever = Retriever(bank)
    similar = []
    for obs in observations:
        results = retriever.query_by_observation(obs, top_k=5)
        for r in results:
            similar.append({
                "reference": obs,
                "retrieved": r.obs,
                "similarity": r.similarity
            })

    return {
        "similar_observations": similar,
        "messages": [{"role": "system", "content": f"[Retrieval] 找到 {len(similar)} 个相似对"}]
    }


# ============================================================
# 图构建
# ============================================================

def build_pipeline_graph() -> StateGraph:
    """
    构建 Bootstrap 完整 LangGraph

    边连接设计：
        START → preprocessor → observer → bank_adder → retrieval → END

    State 流动：
        raw_text + story_config
          → preprocessor: normalized_story
          → observer: observations
          → bank_adder: added_obs_ids
          → retrieval: similar_observations
    """
    graph = StateGraph(NarrativePipelineState)

    # 添加节点
    graph.add_node("preprocessor", preprocessor_node)
    graph.add_node("observer", observer_node)
    graph.add_node("bank_adder", bank_adder_node)
    graph.add_node("retrieval", retrieval_node)

    # 添加边
    graph.add_edge(START, "preprocessor")
    graph.add_edge("preprocessor", "observer")
    graph.add_edge("observer", "bank_adder")
    graph.add_edge("bank_adder", "retrieval")
    graph.add_edge("retrieval", END)

    return graph


# 编译：支持 checkpointer 实现状态持久化
checkpointer = MemorySaver()
pipeline_app = build_pipeline_graph().compile(checkpointer=checkpointer)
