"""
Inducer Node - 从相似 Observations 归纳 Candidate Function
逻辑：先收集候选 → 循环算分 → 循环结束统一写 Registry（按 supporting_obs_ids 查重）
"""

import json
import os

from pydantic import AliasChoices, BaseModel, Field

from Agent.llm import chat_structured
from Agent.state import NarrativePipelineState
from Agent.Inducer.confidence import calculate_confidence_detailed
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

_REGISTRY_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "registry")
_REGISTRY_FILE = os.path.join(_REGISTRY_DIR, "functions.jsonl")


def _key_of(func: dict) -> tuple:
    return tuple(sorted(func.get("supporting_obs_ids", [])))


def _load_existing_keys() -> set:
    if not os.path.exists(_REGISTRY_FILE):
        return set()
    keys = set()
    with open(_REGISTRY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                keys.add(_key_of(json.loads(line)))
            except json.JSONDecodeError:
                pass
    return keys


def _append_to_registry(func: dict, existing_keys: set) -> bool:
    key = _key_of(func)
    if key in existing_keys:
        return False
    os.makedirs(_REGISTRY_DIR, exist_ok=True)
    with open(_REGISTRY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(func, ensure_ascii=False) + "\n")
    existing_keys.add(key)
    return True


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


def _build_positive_examples(
    supporting_obs_ids: list[str],
    bank,
    limit: int = 4,
) -> list[dict]:
    """从 Bank 回填原始证据，避免让 LLM 编造或改写正例。"""
    available = []
    for obs_id in supporting_obs_ids:
        obs = bank.get(obs_id)
        if not obs:
            continue
        available.append({
            "obs_id": obs_id,
            "story_id": obs.get("story_id", ""),
            "raw_surface_form": obs.get("surface_form", ""),
            "event": obs.get("event", ""),
        })

    examples = []
    selected_ids = set()
    seen_stories = set()
    for example in available:
        story_id = example["story_id"]
        if story_id in seen_stories:
            continue
        examples.append(example)
        selected_ids.add(example["obs_id"])
        seen_stories.add(story_id)
        if len(examples) >= limit:
            return examples

    for example in available:
        if example["obs_id"] in selected_ids:
            continue
        examples.append(example)
        if len(examples) >= limit:
            break
    return examples


# ========== Inducer Node ==========

def inducer_node(state: NarrativePipelineState) -> NarrativePipelineState:
    """先收集候选 → 循环算分 → 循环结束统一写 Registry"""
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

    # 1) 收集 + 算分（一次性算两个版本，避免重复计算）
    from Agent.app import get_bank
    bank = get_bank()
    scored = []
    for func in result.candidate_functions:
        detail = calculate_confidence_detailed(
            supporting_obs_ids=func.supporting_obs_ids,
            candidate_def=func.definition,
            bank=bank,
            obs_cluster=obs_cluster,
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
            "positive_examples": _build_positive_examples(
                func.supporting_obs_ids, bank
            ),
            "hard_negatives": func.hard_negatives,
            "confusable_functions": func.confusable_functions,
            "supporting_obs_ids": func.supporting_obs_ids,
            "confidence": confidence,
        })

    # 2) 循环结束统一写盘
    existing_keys = _load_existing_keys()
    induced = [cand for cand in scored if _append_to_registry(cand, existing_keys)]

    return {
        "induced_functions": induced,
        "messages": [{"role": "system", "content": f"[Inducer] 归纳完成（候选={len(result.candidate_functions)}, 写入={len(induced)}）"}],
    }
