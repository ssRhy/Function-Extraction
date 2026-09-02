"""Matcher Node - 新 Observation 与现有 Function Registry 五分类匹配（Evolve 阶段）。

输入：当前故事新增 observations；输出五分类判定 + FunctionOccurrence（NOVEL=OTHER），
MATCH/EXTEND 直写 Registry exemplars（append supporting_obs_ids + 重算 confidence）。
"""

import json
import time

import numpy as np

from FunctionExtract_Agent.llm import chat_structured
from FunctionExtract_Agent.Registry.registry import get_active_store
from FunctionExtract_Agent.Inducer.confidence import calculate_confidence_detailed
from FunctionExtract_Agent.Prompt.Matcher_prompt import MATCHER_SYSTEM_PROMPT, MatchResponse, MatchDecision

MATCH_BATCH_SIZE = 10
TOP_K = 5


def _cosine_sims(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-9)
    b = b / np.maximum(np.linalg.norm(b, axis=1, keepdims=True), 1e-9)
    return a @ b.T


def recall_candidates(observations: list[dict], funcs: list[dict], embedder, top_k: int = TOP_K) -> list[list[dict]]:
    """每 obs 结构化向量 vs 函数 definition 向量余弦，返回 top-k 候选（函数名+相似度）。"""
    if not funcs:
        return [[] for _ in observations]
    obs_vecs = embedder.encode_observations(observations)
    def_vecs = embedder.encode_cached([f.get("definition", "") for f in funcs])
    sims = _cosine_sims(obs_vecs, def_vecs)
    out = []
    for i in range(len(observations)):
        order = np.argsort(-sims[i])[:top_k]
        out.append([
            {"function_name": funcs[j]["function_name"], "similarity": round(float(sims[i][j]), 3)}
            for j in order if sims[i][j] > 0
        ])
    return out


def _story_stage(source_indices: list[int], n_sentences: int | None) -> str | None:
    """按句子下标占比确定性划分故事阶段（无下标/无句数时 None）。"""
    if not source_indices or not n_sentences:
        return None
    mid = sorted(source_indices)[len(source_indices) // 2]
    ratio = mid / n_sentences
    if ratio < 0.33:
        return "beginning"
    if ratio < 0.66:
        return "middle"
    return "end"


def _make_occurrence(obs: dict, decision: MatchDecision, candidates: list[dict], category, stage) -> dict:
    """组装 FunctionOccurrence（NOVEL → function_name=OTHER，不强行分类）。"""
    return {
        "occurrence_id": obs.get("obs_id"),
        "obs_id": obs.get("obs_id"),
        "observation_version_id": obs.get("observation_version_id"),
        "function_name": "OTHER" if decision.label == "NOVEL" else (decision.matched_function or ""),
        "label": decision.label,
        "story_id": obs.get("story_id"),
        "category": category,
        "event": obs.get("event", ""),
        "participants": obs.get("participants", []),
        "before_state": obs.get("before_state", ""),
        "after_state": obs.get("after_state", ""),
        "surface_form": obs.get("surface_form", ""),
        "source_sentence_indices": obs.get("source_sentence_indices", []),
        "story_stage": stage,
        "matched_function": decision.matched_function or "",
        "candidate_functions": decision.candidate_functions or [],
        "top_candidates": candidates,
        "reason": decision.reason or "",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _apply_evidence(func_map: dict, matched: list[tuple[str, dict]], bank) -> list[str]:
    """MATCH/EXTEND 直写：append obs_id（幂等）到命中函数 supporting_obs_ids，重算 confidence。"""
    changed = []
    for func_name, obs in matched:
        f = func_map.get(func_name)
        if not f:
            continue
        oid = obs.get("obs_id")
        sup = list(f.get("supporting_obs_ids", []))
        if oid in sup:
            continue
        sup.append(oid)
        f["supporting_obs_ids"] = sup
        try:
            detail = calculate_confidence_detailed(sup, f.get("definition", ""), bank, apply_confusable=True)
            f["confidence"] = detail["confidence"]
            f["confidence_factors"] = detail["factors"]
        except Exception:
            pass
        changed.append(func_name)
    return changed


def _build_batch_input(batch: list[dict], candidates: list[list[dict]]) -> str:
    lines = []
    for o, cand in zip(batch, candidates):
        lines.append(json.dumps({
            "obs_id": o.get("obs_id"),
            "event": o.get("event", ""),
            "participants": o.get("participants", []),
            "before_state": o.get("before_state", ""),
            "after_state": o.get("after_state", ""),
            "surface_form": o.get("surface_form", ""),
            "top_candidates": cand,
        }, ensure_ascii=False))
    return "\n".join(lines)


def match_observations(
    observations: list[dict],
    funcs: list[dict],
    embedder,
    candidates: list[list[dict]] | None = None,
) -> tuple[list[MatchDecision], list[list[dict]], list[str]]:
    """对一批 Observation 做召回和五分类，供新故事与旧未决回看共用。"""
    if not observations:
        return [], [], []
    if not funcs:
        return [
            MatchDecision(obs_id=o.get("obs_id", ""), label="NOVEL", reason="函数库为空，无候选可匹配")
            for o in observations
        ], [[] for _ in observations], []

    candidates = candidates if candidates is not None else recall_candidates(observations, funcs, embedder)
    cards = [{
        "function_name": f["function_name"],
        "definition": f.get("definition", ""),
        "realization_patterns": f.get("realization_patterns", []),
    } for f in funcs]
    system = MATCHER_SYSTEM_PROMPT + "\n\n## 现有 Function 卡片\n" + json.dumps(cards, ensure_ascii=False, indent=1)
    decisions, errors = [], []
    for start in range(0, len(observations), MATCH_BATCH_SIZE):
        batch = observations[start:start + MATCH_BATCH_SIZE]
        user = "请对以下 Observations 做五分类判定：\n" + _build_batch_input(
            batch, candidates[start:start + MATCH_BATCH_SIZE]
        )
        try:
            result = chat_structured([
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ], MatchResponse)
            decisions.extend(result.decisions)
        except Exception as e:
            errors.append(f"batch@{start}: {e}")
            decisions.extend(
                MatchDecision(obs_id=o.get("obs_id", ""), label="UNCERTAIN", reason=f"LLM 判定失败：{e}")
                for o in batch
            )
    # 按 obs_id 对齐（LLM 可能乱序/漏项），缺失项补 UNCERTAIN。
    by_id = {d.obs_id: d for d in decisions if d.obs_id}
    decisions = [
        by_id.get(o.get("obs_id", "")) or MatchDecision(
            obs_id=o.get("obs_id", ""), label="UNCERTAIN", reason="LLM 未返回该 obs 判定"
        )
        for o in observations
    ]
    return decisions, candidates, errors


def matcher_node(state: dict) -> dict:
    """对当前故事新增 obs：召回 top-k → LLM 五分类 → 生成 occurrences。"""
    observations = state.get("observations", [])
    if not observations:
        return {
            "match_decisions": [],
            "match_occurrences": [],
            "errors": [],
            "messages": [{"role": "system", "content": "[Matcher] 无 observations，跳过"}],
        }

    from FunctionExtract_Agent.app import get_bank
    bank = get_bank()
    funcs = get_active_store().load_all()
    decisions, candidates, errors = match_observations(observations, funcs, bank.embedder)

    # MATCH/EXTEND 证据进待应用区（不直写 Registry，由 Curator 统一应用 exemplars）
    match_pending = [
        {"function_name": d.matched_function, "obs_id": o.get("obs_id"), "source": "matcher"}
        for o, d in zip(observations, decisions)
        if d.label in ("MATCH", "EXTEND") and d.matched_function
    ]
    if match_pending:
        print(f"  [Matcher] {len(match_pending)} 条 MATCH/EXTEND 证据进入待应用区")

    # occurrences
    n_sentences = len((state.get("normalized_story") or {}).get("sentences", [])) or None
    category = (state.get("story_config") or {}).get("story_type")
    occs = [
        _make_occurrence(o, d, cand, category, _story_stage(o.get("source_sentence_indices", []), n_sentences))
        for o, d, cand in zip(observations, decisions, candidates)
    ]
    summary = " ".join(f"{d.label}:{d.matched_function or '-'}" for d in decisions[:8])
    print(f"  [Matcher] {len(occs)} obs 判定 → {summary}")
    return {
        "match_decisions": [d.model_dump() for d in decisions],
        "match_occurrences": occs,
        "match_pending": match_pending,
        "errors": errors,
        "messages": [{"role": "system", "content": f"[Matcher] {len(occs)} obs 五分类完成"}],
    }
