"""
Revise Node - bootstrap 内嵌 Curator-lite：消费 Evaluator 报告，全自动修订 O_0 并写回。

动作：近义 MERGE / 定义 REVISE / SPLIT 拆分（obs 按向量确定性分配）/ weak-fit 剔除 / 低证据移除。
与 evaluator_node 同模式：由 curate_app 闭环图或入口脚本直接调用，不新增逐篇 pipeline 链路。
"""

import json
import os
import shutil
import types

from Agent.llm import chat_structured
from Agent.Inducer.confidence import calculate_confidence_detailed
from Agent.Evaluator import evaluator as ev
from Agent.Evaluator.dimensions import _obs_text, _cosine
from Prompt.Merge_prompt import MERGE_SYSTEM_PROMPT, MergeResponse
from Prompt.Revise_prompt import REVISE_SYSTEM_PROMPT, ReviseResponse

MAX_EVAL_ROUNDS = 3        # 最大修订轮数（curate_run --max-rounds 可覆盖）
SPLIT_OBS_MIN_SIM = 0.40   # SPLIT 分配：obs 与子函数定义余弦低于该值不归属任何子函数
LLM_RETRY = 1              # 单次 LLM 动作失败重试次数
_OBS_POSITIVE_LIMIT = 4


def _default_registry_file() -> str:
    from Agent.Inducer.inducer import _REGISTRY_FILE
    return _REGISTRY_FILE


def _load_report(report_path: str) -> dict | None:
    if not os.path.exists(report_path):
        return None
    with open(report_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _story_count(supporting_ids: list[str], obs_by_id: dict) -> int:
    return len({obs_by_id[oid].get("story_id") for oid in supporting_ids if oid in obs_by_id})


def _recalc_confidence(func: dict, obs_by_id: dict, embedder) -> dict:
    """用 bootstrap 豁免口径重算置信度（不信任 LLM 输出分数）。"""
    bank_stub = types.SimpleNamespace(embedder=embedder, get=obs_by_id.get)
    try:
        detail = calculate_confidence_detailed(
            func.get("supporting_obs_ids", []),
            func.get("definition", ""),
            bank_stub,
            apply_confusable=False,
        )
        func["confidence"] = detail["confidence"]
        func["confidence_factors"] = detail["factors"]
    except Exception:
        pass
    return func


def _build_positive_examples(supporting_obs_ids: list[str], obs_by_id: dict, limit: int = _OBS_POSITIVE_LIMIT) -> list[dict]:
    examples, seen_stories = [], set()
    for oid in supporting_obs_ids:
        o = obs_by_id.get(oid)
        if not o:
            continue
        sid = o.get("story_id", "")
        if sid in seen_stories:
            continue
        seen_stories.add(sid)
        examples.append({
            "obs_id": oid,
            "story_id": sid,
            "raw_surface_form": o.get("surface_form", ""),
            "event": o.get("event", ""),
        })
        if len(examples) >= limit:
            break
    return examples


def _union_supporting(members: list[dict]) -> list[str]:
    merged = []
    for m in members:
        for oid in m.get("supporting_obs_ids", []):
            if oid not in merged:
                merged.append(oid)
    return merged


def _llm_merge(members: list[dict], obs_by_id: dict) -> tuple[dict | None, str | None]:
    cards = []
    for m in members:
        events = []
        for oid in m.get("supporting_obs_ids", [])[:6]:
            o = obs_by_id.get(oid)
            if o:
                events.append(o.get("event", ""))
        cards.append({
            "function_name": m.get("function_name"),
            "definition": m.get("definition"),
            "realization_patterns": m.get("realization_patterns", []),
            "hard_negatives": m.get("hard_negatives", []),
            "confusable_functions": m.get("confusable_functions", []),
            "supporting_events": events,
        })
    user_content = "请合并以下近义 Function：\n" + json.dumps(cards, ensure_ascii=False, indent=1)
    last_err = None
    for _ in range(LLM_RETRY + 1):
        try:
            result = chat_structured([
                {"role": "system", "content": MERGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ], MergeResponse)
            merged_list = [m.model_dump() for m in result.merged_functions]
            if not merged_list:
                raise ValueError("LLM 未返回合并函数")
            merged = merged_list[0]
            merged["supporting_obs_ids"] = _union_supporting(members)
            merged["positive_examples"] = _build_positive_examples(merged["supporting_obs_ids"], obs_by_id)
            return merged, None
        except Exception as e:
            last_err = str(e)
    return None, last_err


def _llm_revise(func: dict, reasons: dict) -> tuple[list[dict] | None, str | None]:
    card = {
        "function_name": func.get("function_name"),
        "definition": func.get("definition"),
        "realization_patterns": func.get("realization_patterns", []),
        "hard_negatives": func.get("hard_negatives", []),
        "confusable_functions": func.get("confusable_functions", []),
    }
    user_content = "请修订以下 Function，质量问题如下：\n" + json.dumps(
        {"function": card, "issues": reasons}, ensure_ascii=False, indent=1
    )
    last_err = None
    for _ in range(LLM_RETRY + 1):
        try:
            result = chat_structured([
                {"role": "system", "content": REVISE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ], ReviseResponse)
            out = [r.model_dump() for r in result.revised_functions]
            if not out:
                raise ValueError("LLM 未返回修订函数")
            return out, None
        except Exception as e:
            last_err = str(e)
    return None, last_err


def _assign_split_obs(supporting_ids, obs_by_id, sub_funcs, embedder, min_sim: float = SPLIT_OBS_MIN_SIM):
    """obs 按文本 vs 子函数定义余弦确定性分配；无归属 obs 丢弃，无 obs 的子函数丢弃。"""
    if len(sub_funcs) < 2:
        for f in sub_funcs:
            f["supporting_obs_ids"] = list(supporting_ids)
        return sub_funcs, []
    def_vecs = embedder.encode([f["definition"] for f in sub_funcs])
    assigned: list[list[str]] = [[] for _ in sub_funcs]
    dropped_obs = []
    for oid in supporting_ids:
        o = obs_by_id.get(oid)
        if not o:
            continue
        obs_vec = embedder.encode([_obs_text(o)])[0]
        sims = [_cosine(obs_vec, def_vecs[i]) for i in range(len(sub_funcs))]
        best = max(range(len(sub_funcs)), key=lambda i: sims[i])
        if sims[best] >= min_sim:
            assigned[best].append(oid)
        else:
            dropped_obs.append(oid)
    kept = []
    for f, ids in zip(sub_funcs, assigned):
        f["supporting_obs_ids"] = ids
        if ids:
            f["positive_examples"] = _build_positive_examples(ids, obs_by_id)
            _recalc_confidence(f, obs_by_id, embedder)
            kept.append(f)
    return kept, dropped_obs


def _collect_revise_targets(report: dict) -> dict:
    """name -> reasons（issue 原因 + recommendation）。"""
    targets: dict[str, dict] = {}
    issues = report.get("dimensions", {}).get("abstraction_quality", {}).get("issues", {})
    for item in issues.get("conflation", []):
        targets.setdefault(item.get("function_name"), {})["双向混叠"] = item.get("reason", "")
    for item in issues.get("genre_bound", []):
        targets.setdefault(item.get("function_name"), {})["题材表层绑定"] = item.get("reason", "")
    for n in issues.get("too_specific", []):
        targets.setdefault(n, {})["粒度过细"] = "too_specific"
    for n in issues.get("too_broad", []):
        targets.setdefault(n, {})["粒度过宽"] = "too_broad"
    for r in report.get("abstraction_reviews", []):
        name = r.get("function_name")
        if r.get("recommendation") in ("REVISE", "SPLIT") and name:
            targets.setdefault(name, {})["recommendation"] = r.get("recommendation")
    return targets


def revise_node(state: dict) -> dict:
    """消费评估报告，全自动修订并写回 Registry（O_0 数据源）。"""
    context = state.get("evaluation_context") or {}
    registry_file = context.get("registry_file") or _default_registry_file()
    bank_file = context.get("bank_file")
    report_path = context.get("report_path") or ev._DEFAULT_REPORT_PATH

    functions = ev._load_functions(context.get("registry_file"))
    all_obs = ev._load_obs(bank_file)
    obs_by_id = {o.get("obs_id"): o for o in all_obs}

    if bank_file:
        from Embedding.embedding import Embedder
        embedder = Embedder()
    else:
        from Agent.app import get_bank
        embedder = get_bank().embedder

    report = _load_report(report_path)
    if report is None:
        return {
            "revise_report": {"error": "评估报告不存在，跳过修订"},
            "evaluation_round": state.get("evaluation_round", 0) + 1,
            "messages": [{"role": "system", "content": "[Revise] 评估报告缺失，跳过修订"}],
        }

    by_name: dict[str, dict] = {}
    for f in functions:
        by_name.setdefault(f.get("function_name", ""), f)

    weak_fit_by_name: dict[str, set] = {}
    for w in report.get("recommendations", {}).get("weak_fit_obs", []):
        weak_fit_by_name.setdefault(w.get("function_name"), set()).add(w.get("obs_id"))

    removed_names = {e.get("function_name") for e in report.get("recommendations", {}).get("low_evidence_functions", [])}
    merge_groups = report.get("recommendations", {}).get("merge_groups", [])
    targets = _collect_revise_targets(report)

    consumed: set[str] = set()
    new_funcs: list[dict] = []
    actions = {
        "merged": [], "revised": [], "split": [], "removed": [],
        "failed": [], "weak_fit_removed": 0, "backup": None,
    }

    # 1) 近义合并
    for group in merge_groups:
        members = [by_name[n] for n in group if n in by_name]
        if len(members) < 2:
            actions["failed"].append({"action": "merge", "group": group, "reason": "组内可用成员不足"})
            continue
        merged, err = _llm_merge(members, obs_by_id)
        if merged is None:
            actions["failed"].append({"action": "merge", "group": group, "reason": err})
            continue
        _recalc_confidence(merged, obs_by_id, embedder)
        new_funcs.append(merged)
        names = [m.get("function_name") for m in members]
        consumed.update(names)
        actions["merged"].append({"group": names, "merged_as": merged.get("function_name")})

    # 2) 定义 REVISE / SPLIT（跳过已合并/已移除函数）
    for name, reasons in targets.items():
        if name in consumed or name in removed_names or name not in by_name:
            continue
        func = dict(by_name[name])
        out, err = _llm_revise(func, reasons)
        if out is None:
            actions["failed"].append({"action": "revise", "function_name": name, "reason": err})
            continue
        base_sup = [oid for oid in func.get("supporting_obs_ids", []) if oid not in weak_fit_by_name.get(name, set())]
        if len(out) == 1:
            revised = out[0]
            revised["supporting_obs_ids"] = base_sup
            revised["positive_examples"] = _build_positive_examples(base_sup, obs_by_id)
            _recalc_confidence(revised, obs_by_id, embedder)
            new_funcs.append(revised)
            actions["revised"].append({"function_name": name, "revised_as": revised.get("function_name")})
        else:
            kept, dropped = _assign_split_obs(base_sup, obs_by_id, out, embedder)
            if not kept:
                actions["failed"].append({"action": "split", "function_name": name, "reason": "子函数均无匹配 obs，保留原函数"})
                continue
            new_funcs.extend(kept)
            actions["split"].append({
                "function_name": name,
                "split_into": [f.get("function_name") for f in kept],
                "dropped_obs": dropped,
            })
        consumed.add(name)
        actions["weak_fit_removed"] += len(weak_fit_by_name.get(name, set()))

    # 3) 低证据移除
    for name in sorted(removed_names):
        if name in consumed or name not in by_name:
            continue
        actions["removed"].append({"function_name": name, "reason": "支持故事 <2"})
        consumed.add(name)

    # 4) 保留函数：weak-fit 剔除
    for f in functions:
        name = f.get("function_name", "")
        if name in consumed:
            continue
        kept_f = dict(f)
        wf = weak_fit_by_name.get(name, set())
        if wf:
            kept_f["supporting_obs_ids"] = [oid for oid in kept_f.get("supporting_obs_ids", []) if oid not in wf]
            actions["weak_fit_removed"] += len(wf)
        new_funcs.append(kept_f)

    # 5) 修订后低证据复查：<2 故事的函数移出
    final, recheck = [], []
    for f in new_funcs:
        if _story_count(f.get("supporting_obs_ids", []), obs_by_id) < 2:
            recheck.append(f.get("function_name"))
            actions["removed"].append({"function_name": f.get("function_name"), "reason": "修订后支持故事 <2"})
        else:
            final.append(f)
    actions["recheck_removed"] = recheck
    actions["before_count"] = len(functions)
    actions["after_count"] = len(final)

    changed = bool(
        actions["merged"] or actions["revised"] or actions["split"]
        or actions["removed"] or actions["weak_fit_removed"] > 0
    )
    if changed and registry_file and os.path.exists(registry_file):
        backup = f"{registry_file}.pre_revise.jsonl"
        if not os.path.exists(backup):
            shutil.copyfile(registry_file, backup)
        with open(registry_file, "w", encoding="utf-8") as f:
            for func in final:
                f.write(json.dumps(func, ensure_ascii=False) + "\n")
        actions["backup"] = backup

    return {
        "revise_report": actions,
        "evaluation_round": state.get("evaluation_round", 0) + 1,
        "messages": [{
            "role": "system",
            "content": f"[Revise] 合并 {len(actions['merged'])} / 修订 {len(actions['revised'])} "
                       f"/ 拆分 {len(actions['split'])} / 移除 {len(actions['removed'])}",
        }],
    }