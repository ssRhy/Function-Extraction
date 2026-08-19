"""
全量抽象归并 - export 前单轮识别近义组并复用 revise._llm_merge 重新归纳统一函数
"""

import json

from Agent.llm import chat_structured
from Agent.Inducer.confidence import calculate_confidence_detailed
from Agent.Evaluator import revise as revise_module
from Prompt.Abstract_merge_prompt import (
    ABSTRACT_MERGE_SYSTEM_PROMPT,
    AbstractMergeResponse,
)

# 粒度上限：合并后 supporting obs 数超过该值视为超大类，跳过（避免迭代无限上卷成超大类）
MAX_MERGE_OBS = 20


def abstract_merge(funcs: list[dict], bank) -> list[dict]:
    """全量抽象归并：单轮识别近义组，逐组复用 revise._llm_merge 重新归纳为一个新的统一函数。

    粒度守卫：成员 supporting 并集 > MAX_MERGE_OBS 的组跳过（宁少勿滥，阻止超大类）。
    """
    if len(funcs) < 2:
        return funcs
    by_name = {f.get("function_name"): f for f in funcs}
    cards = [{
        "function_name": f.get("function_name"),
        "definition": f.get("definition"),
        "realization_patterns": f.get("realization_patterns", []),
    } for f in funcs]
    user_content = "请识别承担同一结构作用、应归并为一个新函数的函数组：\n" + json.dumps(cards, ensure_ascii=False, indent=1)
    try:
        result = chat_structured([
            {"role": "system", "content": ABSTRACT_MERGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ], AbstractMergeResponse)
    except Exception as e:
        print(f"  [AbstractMerge] 近义组识别失败，保持原样: {e}")
        return funcs

    obs_by_id = {o.get("obs_id"): o for o in bank.get_all()}
    consumed: set[str] = set()
    new_funcs: list[dict] = []
    for group in result.merge_groups:
        members = [by_name[n] for n in group if n in by_name and n not in consumed]
        if len(members) < 2:
            continue
        union_obs = {oid for m in members for oid in m.get("supporting_obs_ids", [])}
        if len(union_obs) > MAX_MERGE_OBS:
            print(f"  [AbstractMerge] 组 {[m['function_name'] for m in members]} 合并后 "
                  f"{len(union_obs)} obs 超过粒度上限 {MAX_MERGE_OBS}，跳过（宁少勿滥）")
            continue
        merged, err = revise_module._llm_merge(members, obs_by_id)
        if merged is None:
            print(f"  [AbstractMerge] 组 {[m['function_name'] for m in members]} 合并失败: {err}（保持原样）")
            continue
        consumed.update(m.get("function_name") for m in members)
        merged["schema_version"] = 2
        try:
            detail = calculate_confidence_detailed(
                merged["supporting_obs_ids"], merged["definition"], bank, apply_confusable=False,
            )
            merged["confidence"] = detail["confidence"]
            merged["confidence_factors"] = detail["factors"]
        except Exception:
            merged["confidence"] = 0.5
        new_funcs.append(merged)

    out = [f for f in funcs if f.get("function_name") not in consumed]
    out.extend(new_funcs)
    # 新函数与存量重名时加 _N 后缀，保证 O_0 函数名唯一
    seen = {f.get("function_name") for f in funcs if f.get("function_name") not in consumed}
    for f in new_funcs:
        name = f["function_name"]
        base, i = name, 1
        while name in seen:
            i += 1
            name = f"{base}_{i}"
        seen.add(name)
        f["function_name"] = name
    if consumed:
        print(f"  [AbstractMerge] 归并 {len(consumed)} 个函数 → {len(new_funcs)} 个新函数")
    return out
