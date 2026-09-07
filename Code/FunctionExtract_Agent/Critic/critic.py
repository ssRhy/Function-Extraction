"""Critic Node - 边界复检器（Evolve 阶段）

对 Matcher 判为 CONFLICT/UNCERTAIN 的 obs 做二次校验，输出四类最终判定：
match/extend → 归函数（进 pending_evidence）；novel → novelty_pool；resolved → challenge_pool。
"""

import json

from FunctionExtract_Agent.llm import chat_structured
from FunctionExtract_Agent.Registry.registry import get_active_store
from FunctionExtract_Agent.Prompt.Critic_prompt import CRITIC_SYSTEM_PROMPT, CriticResponse

CRITIC_BATCH_SIZE = 10


def _build_batch_input(batch: list[dict]) -> str:
    lines = []
    for occ in batch:
        lines.append(json.dumps({
            "obs_id": occ.get("occurrence_id"),
            "label": occ.get("label"),
            "event": occ.get("event", ""),
            "participants": occ.get("participants", []),
            "before_state": occ.get("before_state", ""),
            "after_state": occ.get("after_state", ""),
            "surface_form": occ.get("surface_form", ""),
            "matched_function": occ.get("matched_function", ""),
            "candidate_functions": occ.get("candidate_functions", []),
            "top_candidates": occ.get("top_candidates", []),
            "matcher_reason": occ.get("reason", ""),
        }, ensure_ascii=False))
    return "\n".join(lines)


def critic_node(state: dict) -> dict:
    """复检本故事 CONFLICT/UNCERTAIN obs；返回更新后的 occurrences + 追加的 pending。"""
    occs = list(state.get("match_occurrences", []))
    targets = [o for o in occs if o.get("label") in ("CONFLICT", "UNCERTAIN")]
    if not targets:
        return {
            "match_occurrences": occs,
            "match_pending": state.get("match_pending", []),
            "errors": [],
            "messages": [{"role": "system", "content": "[Critic] 无边界观测，跳过复检"}],
        }

    funcs = get_active_store().load_all()
    cards = [{
        "function_name": f.get("function_name"),
        "definition": f.get("definition", ""),
        "realization_patterns": f.get("realization_patterns", []),
        "hard_negatives": f.get("hard_negatives", []),
    } for f in funcs]
    system = CRITIC_SYSTEM_PROMPT + "\n\n## 现有 Function 卡片（含 hard_negatives 边界反例）\n" + \
        json.dumps(cards, ensure_ascii=False, indent=1)

    decisions, errors, failed_ids = [], [], set()
    for start in range(0, len(targets), CRITIC_BATCH_SIZE):
        batch = targets[start:start + CRITIC_BATCH_SIZE]
        user = "请复检以下边界观测：\n" + _build_batch_input(batch)
        try:
            result = chat_structured([
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ], CriticResponse)
            decisions.extend(result.decisions)
        except Exception as e:
            errors.append(f"critic batch@{start}: {e}")
            failed_ids.update(o.get("occurrence_id") for o in batch)

    by_id = {d.obs_id: d for d in decisions if d.obs_id}
    pending = list(state.get("match_pending", []))
    updated = []
    n_match = n_extend = n_novel = n_resolved = 0
    for o in occs:
        if o.get("label") not in ("CONFLICT", "UNCERTAIN") or o.get("occurrence_id") in failed_ids:
            updated.append(o)  # 非边界或复检失败：保持原始 label
            continue
        d = by_id.get(o.get("occurrence_id"))
        if d is None:
            updated.append(o)  # LLM 漏输出：保持原始 label
            continue
        new_occ = dict(o)
        new_occ["resolved_by"] = "critic"
        new_occ["critic_reason"] = d.reason or ""
        if d.final_label in ("match", "extend") and d.matched_function:
            new_occ["label"] = "MATCH" if d.final_label == "match" else "EXTEND"
            new_occ["function_name"] = d.matched_function
            new_occ["matched_function"] = d.matched_function
            pending.append({
                "function_name": d.matched_function,
                "obs_id": o.get("occurrence_id"),
                "source": "critic",
            })
            if d.final_label == "match":
                n_match += 1
            else:
                n_extend += 1
        elif d.final_label == "novel":
            new_occ["label"] = "NOVEL"
            new_occ["function_name"] = "OTHER"
            n_novel += 1
        else:  # resolved
            new_occ["label"] = "RESOLVED"
            new_occ["matched_function"] = d.matched_function or new_occ.get("matched_function", "")
            n_resolved += 1
        updated.append(new_occ)

    print(f"  [Critic] 复检 {len(targets)} 个边界 obs → match={n_match} extend={n_extend} "
          f"novel={n_novel} resolved={n_resolved} 失败={len(failed_ids)}")
    return {
        "match_occurrences": updated,
        "match_pending": pending,
        "errors": errors,
        "messages": [{"role": "system", "content": f"[Critic] 复检 {len(targets)} 个边界 obs 完成"}],
    }
