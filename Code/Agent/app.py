"""
Narrative Pipeline App - LangGraph 图连接定义
    START → preprocessor → observer → bank_adder → retrieval → inducer → END
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from Agent.state import NarrativePipelineState
from Agent.Pre_pro.pre_processor import preprocessor_node
from Agent.Observer.observer import observer_node
from Agent.Inducer.inducer import inducer_node
from Bank.bank import ObservationBank
from Retrieval.retrieval import Retriever


_bank_instance = None


def get_bank() -> ObservationBank:
    global _bank_instance
    if _bank_instance is None:
        _bank_instance = ObservationBank()
    return _bank_instance


def bank_adder_node(state: NarrativePipelineState) -> NarrativePipelineState:
    """将新提取的 Observations 存入 Bank"""
    observations = state.get("observations", [])
    if not observations:
        return {"added_obs_ids": [], "messages": [{"role": "system", "content": "[BankAdder] 无 observations，跳过"}]}
    added_ids = get_bank().add(observations)
    return {"added_obs_ids": added_ids, "messages": [{"role": "system", "content": f"[BankAdder] 添加 {len(added_ids)} 条"}]}


def retrieval_node(state: NarrativePipelineState) -> NarrativePipelineState:
    """增量检索：仅比较本轮新增 Observation 与历史 Observation。"""
    bank = get_bank()
    added_ids = state.get("added_obs_ids", [])
    if not added_ids:
        return {"similar_observations": [], "messages": [{"role": "system", "content": "[Retrieval] 无新增 Observation，跳过"}]}

    added_set = set(added_ids)
    new_observations = [bank.get(obs_id) for obs_id in added_ids]
    new_observations = [obs for obs in new_observations if obs]
    if bank.count() <= len(new_observations):
        return {"similar_observations": [], "messages": [{"role": "system", "content": "[Retrieval] 无历史 Observation，跳过"}]}

    retriever = Retriever(bank)
    similar, seen = [], set()
    for obs in new_observations:
        for r in retriever.query_by_observation(
            obs,
            top_k=5,
            exclude_obs_ids=list(added_set),
        ):
            if obs["obs_id"] == r.obs["obs_id"] or obs.get("story_id") == r.obs.get("story_id"):
                continue
            pair = tuple(sorted([obs["obs_id"], r.obs["obs_id"]]))
            if pair in seen:
                continue
            seen.add(pair)
            similar.append({"reference": obs, "retrieved": r.obs, "similarity": r.similarity})

    return {"similar_observations": similar, "messages": [{"role": "system", "content": f"[Retrieval] 新增 {len(new_observations)} 条，找到 {len(similar)} 个历史相似对"}]}


def build_pipeline_graph(include_inducer: bool = True) -> StateGraph:
    graph = StateGraph(NarrativePipelineState)
    graph.add_node("preprocessor", preprocessor_node)
    graph.add_node("observer", observer_node)
    graph.add_node("bank_adder", bank_adder_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_edge(START, "preprocessor")
    graph.add_edge("preprocessor", "observer")
    graph.add_edge("observer", "bank_adder")
    graph.add_edge("bank_adder", "retrieval")
    if include_inducer:
        graph.add_node("inducer", inducer_node)
        graph.add_edge("retrieval", "inducer")
        graph.add_edge("inducer", END)
    else:
        graph.add_edge("retrieval", END)
    return graph


from Agent.Evaluator.evaluator import evaluator_node
from Agent.Evaluator import revise as revise_module
from Agent.Evaluator.revise import revise_node


def should_continue(state: NarrativePipelineState) -> str:
    """curate_app 循环路由：PASS 或达修订轮数上限则结束，否则进入修订。"""
    if state.get("evaluator_decision") == "PASS":
        return "end"
    if state.get("evaluation_round", 0) >= revise_module.MAX_EVAL_ROUNDS:
        return "end"
    return "revise"


def build_curate_graph() -> StateGraph:
    """闭环图：评估 →（FAIL 且未达上限）→ 修订 → 再评估 → …→ END。"""
    graph = StateGraph(NarrativePipelineState)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("revise", revise_node)
    graph.add_edge(START, "evaluator")
    graph.add_conditional_edges(
        "evaluator",
        should_continue,
        {"end": END, "revise": "revise"},
    )
    graph.add_edge("revise", "evaluator")
    return graph


pipeline_app = build_pipeline_graph().compile(checkpointer=MemorySaver())
extract_app = build_pipeline_graph(include_inducer=False).compile(checkpointer=MemorySaver())
curate_app = build_curate_graph().compile(checkpointer=MemorySaver())
