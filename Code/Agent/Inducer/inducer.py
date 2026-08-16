"""
Inducer Node - 从相似 Observations 归纳 Candidate Function
逻辑：先收集候选 → 循环算分（bootstrap 可豁免 confusable）→ upsert 写 Registry
（同名或 definition 相似度 > 0.85 视为重复，仅保留置信度最高者）
"""

from pydantic import AliasChoices, BaseModel, Field

from Agent.llm import chat_structured
from Agent.state import NarrativePipelineState
from Agent.Inducer.confidence import (
    calculate_confidence_detailed,
    max_definition_similarity,
    NEAR_DUP_THRESHOLD,
)
from Agent.Registry.registry import get_active_store
from Prompt.Inducer_prompt import INDUCER_SYSTEM_PROMPT


# ========== Pydantic Schema ==========

class CandidateFunction(BaseModel):
    function_name: str = Field(description="函数名（英文大写下划线，如 CAPABILITY_REVELATION）")
    definition: str = Field(description="定义（中文1句，简明扼要）")
    realization_patterns: list[str] = Field(
        validation_alias=AliasChoices("realization_patterns", "surface_forms"),
        description="去除专名和具体道具、但保留动作机制的中间粒度实现模式，2-4个",
    )
    hard_negatives: list[str] = Field(description="1-2个反例")
    confusable_functions: list[str] = Field(description="易混淆的Function，1-2个")
    supporting_obs_ids: list[str] = Field(description="支持此Function的obs_id")


class InducerResponse(BaseModel):
    candidate_functions: list[CandidateFunction] = Field(description="候选 Function 列表")


# ========== Registry ==========

# bootstrap 阶段豁免 confusable 软惩罚（run_bootstrap.py 启动时置为 False）
APPLY_CONFUSABLE = True


def merge_candidates(
    live: list[dict],
    candidates: list[dict],
    embedder,
    threshold: float = NEAR_DUP_THRESHOLD,
) -> tuple[list[dict], list[dict]]:
    """
    把候选依次并入 live（live = 已有 Registry + 本轮已写入候选）。

    - 同名 function_name，或 definition 余弦相似度 > threshold，视为重复；
    - 重复时只保留置信度最高者：新候选置信度更高才替换，否则跳过。

    返回 (更新后的 live, 实际写入的候选列表)。
    """
    live = list(live)
    written = []
    for cand in candidates:
        cand_name = cand.get("function_name", "")
        cand_def = cand.get("definition", "")
        conflicts = [
            entry for entry in live
            if entry.get("function_name") == cand_name
            or max_definition_similarity(cand_def, [entry], embedder) > threshold
        ]
        if not conflicts:
            live.append(cand)
            written.append(cand)
            continue
        best = max(conflicts, key=lambda e: e.get("confidence", 0.0))
        if cand.get("confidence", 0.0) <= best.get("confidence", 0.0):
            continue
        for entry in conflicts:
            live.remove(entry)
        live.append(cand)
        written.append(cand)
    return live, written


def _upsert_registry(candidates: list[dict], embedder) -> list[dict]:
    """合并候选到当前活跃 Registry（去重后）并整体重写该命名空间"""
    store = get_active_store()
    updated, written = merge_candidates(store.load_all(), candidates, embedder)
    store.replace_all(updated)
    return written


# ========== Obs Cluster ==========

def _build_obs_cluster(similar_observations: list[dict]) -> list[dict]:
    """去重 obs，校验跨故事"""
    seen = {}
    for pair in similar_observations:
        for role in ("reference", "retrieved"):
            obs = pair.get(role)
            if obs and (oid := obs.get("obs_id", "")) and oid not in seen:
                seen[oid] = obs
    if not seen:
        return []
    if len(set(o.get("story_id", "") for o in seen.values())) < 2:
        return []
    return list(seen.values())


def _format_obs_for_prompt(obs_list: list[dict]) -> str:
    return "\n".join(
        f"""Obs ID: {obs.get("obs_id", "N/A")}
  故事 ID: {obs.get("story_id", "N/A")}
  事件: {obs.get("event", "")}
  参与者: {obs.get("participants", [])}
  前置状态: {obs.get("before_state", "")}
  后置状态: {obs.get("after_state", "")}
  受影响方面: {obs.get("affected_aspect", "")}
  叙事效果: {obs.get("narrative_effect", "")}
  表层实现: {obs.get("surface_form", "")}
"""
        for obs in obs_list
    )


# ========== Inducer Node ==========

def inducer_node(state: NarrativePipelineState) -> NarrativePipelineState:
    """先收集候选 → 循环算分 → upsert 写 Registry"""
    similar = state.get("similar_observations", [])
    if not similar:
        return {"induced_functions": [], "messages": [{"role": "system", "content": "[Inducer] 无相似对，跳过归纳"}]}

    obs_cluster = _build_obs_cluster(similar)
    if not obs_cluster:
        return {"induced_functions": [], "messages": [{"role": "system", "content": "[Inducer] 无跨故事证据，跳过"}]}

    result = chat_structured([
        {"role": "system", "content": INDUCER_SYSTEM_PROMPT},
        {"role": "user", "content": f"请分析以下来自不同故事的相似 Observations，归纳候选 Function：\n\n{_format_obs_for_prompt(obs_cluster)}"},
    ], InducerResponse)

    # 1) 收集 + 算分
    from Agent.app import get_bank
    bank = get_bank()
    scored = []
    for func in result.candidate_functions:
        detail = calculate_confidence_detailed(
            supporting_obs_ids=func.supporting_obs_ids,
            candidate_def=func.definition,
            bank=bank,
            apply_confusable=APPLY_CONFUSABLE,
        )
        confidence = detail["confidence"]
        print(f"\n[Inducer DEBUG] 候选: {func.function_name}")
        print(f"  definition: {func.definition[:50]}...")
        print(f"  因子得分: {detail['factors']}")
        print(f"  最终置信度: {confidence:.3f}")
        if confidence < 0.5:
            print(f"  → 跳过 (confidence={confidence:.3f} < 0.5)")
            continue
        scored.append({
            "schema_version": 2,
            "function_name": func.function_name,
            "definition": func.definition,
            "realization_patterns": func.realization_patterns,
            "hard_negatives": func.hard_negatives,
            "confusable_functions": func.confusable_functions,
            "supporting_obs_ids": func.supporting_obs_ids,
            "confidence": confidence,
        })

    # 2) upsert（去重：同名/近义只保留置信度最高者）
    induced = _upsert_registry(scored, bank.embedder)

    return {
        "induced_functions": induced,
        "messages": [{"role": "system", "content": f"[Inducer] 归纳完成（候选={len(result.candidate_functions)}, 写入={len(induced)}）"}],
    }