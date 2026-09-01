"""Curator Node - 收尾维护（Evolve 阶段）

整合 pending_evidence / novelty_pool / challenge_pool / 最新 evaluation_mid 问题，
按动作分门槛执行完整维护：应用 exemplars、跨故事 novel 归纳新函数、挑战/体检问题修订。
方案写 curator_plan.jsonl（Human Review 自动留档）后自动 Apply 写回 Registry（追加 version_history），
并清空已消费的 pending；不满足门槛的动作记 SKIP_SMALL_SAMPLE 保留累积。
"""

import json
import os
import time

import numpy as np
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import pdist

from Agent.app import get_bank
from Agent.Registry.registry import get_active_store
from Agent.Matcher.matcher import _apply_evidence
from Agent.Inducer.cluster import cluster_similar_pairs
from Agent.Inducer.inducer import inducer_node
from Agent.Evaluator import revise as rev
from Agent.llm import chat_structured
from Prompt.Abstract_merge_prompt import ABSTRACT_MERGE_SYSTEM_PROMPT, AbstractMergeResponse

# ---- 动作分门槛（可调）----
ADD_MIN_NOVEL = 3            # 归纳新函数的最小 novel obs 数（另需跨故事 >= 2，文档 §9）
REVISE_MIN_SUPPORTING = 3    # 修订/合并涉及函数的最小 supporting obs 数
NOVEL_SIM_THRESHOLD = 0.60   # novel obs 聚类边阈值（与 bootstrap 聚类一致）

_ACTIONABLE_KEYS = ("merge_groups", "revise_definitions", "genre_bound_functions",
                    "low_evidence_functions", "weak_fit_obs")
AGGLOMERATIVE_SIM_THRESHOLD = 0.75   # 近义候选拎组阈值：definition 余弦 >= 该值视为候选（complete 链接防链式串簇；LLM 确认后合并）


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _bump_version(func: dict, action: str) -> None:
    vh = list(func.get("version_history", []))
    vh.append({"version": len(vh) + 1, "action": action, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
    func["version_history"] = vh


def _plan_record(action, target, **extra):
    rec = {"action": action, "target": target, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    rec.update(extra)
    return rec


def _has_accumulation(state: dict) -> bool:
    pending = state.get("pending_evidence", [])
    occs = state.get("occurrences", [])
    novel = [o for o in occs if o.get("label") == "NOVEL"]
    boundary = [o for o in occs if o.get("label") in ("CONFLICT", "UNCERTAIN", "RESOLVED")]
    mid = (state.get("mid_reports") or [{}])[-1]
    rec = (mid.get("recommendations") or {}) if mid else {}
    has_issues = any(rec.get(k) for k in _ACTIONABLE_KEYS)
    return bool(pending or novel or boundary or has_issues)


def _apply_pending(pending: list[dict], func_map: dict, bank, plan: list[dict]) -> list[str]:
    matched = [(p.get("function_name"), {"obs_id": p.get("obs_id")})
               for p in pending if p.get("function_name") and p.get("obs_id")]
    if not matched:
        return []
    changed = _apply_evidence(func_map, matched, bank)
    for name in set(changed):
        _bump_version(func_map[name], "APPLY_EVIDENCE")
    for p in pending:
        plan.append(_plan_record(
            "APPLY_EVIDENCE", p.get("function_name"),
            obs_id=p.get("obs_id"), source=p.get("source"),
            applied=p.get("function_name") in changed,
        ))
    return changed


def _induce_novelty(novel_occs: list[dict], bank, plan: list[dict]) -> int:
    novel_obs = [bank.get(o.get("occurrence_id")) for o in novel_occs]
    novel_obs = [o for o in novel_obs if o]
    if len(novel_obs) < 2:
        return 0
    embedder = bank.embedder
    pairs = []
    for i in range(len(novel_obs)):
        vi = embedder.encode_observation(novel_obs[i])
        for j in range(i + 1, len(novel_obs)):
            if novel_obs[i].get("story_id") == novel_obs[j].get("story_id"):
                continue
            sim = _cosine(vi, embedder.encode_observation(novel_obs[j]))
            if sim >= NOVEL_SIM_THRESHOLD:
                pairs.append({"reference": novel_obs[i], "retrieved": novel_obs[j], "similarity": round(sim, 3)})
    added = 0
    for comp in cluster_similar_pairs(pairs) if pairs else []:
        ids = {p["reference"]["obs_id"] for p in comp} | {p["retrieved"]["obs_id"] for p in comp}
        stories = {p["reference"]["story_id"] for p in comp} | {p["retrieved"]["story_id"] for p in comp}
        if len(stories) < 2 or len(ids) < ADD_MIN_NOVEL:
            plan.append(_plan_record(
                "SKIP_SMALL_SAMPLE", "NOVEL_CLUSTER",
                obs_ids=sorted(ids),
                reason=f"跨故事 {len(stories)} / novel obs {len(ids)}（需 ≥2 故事且 ≥{ADD_MIN_NOVEL} obs）",
            ))
            continue
        result = inducer_node({"similar_observations": comp})
        for f in result.get("induced_functions", []):
            added += 1
            plan.append(_plan_record("ADD_FUNCTION", f.get("function_name"),
                                     obs_ids=f.get("supporting_obs_ids", [])))
    return added


def _agglomerative_candidates(names: list[str], funcs_by_name: dict, embedder) -> list[list[str]]:
    """Agglomerative 拎候选近义组：definition 向量余弦距离，complete 链接防链式串簇。

    返回簇内 >=2 个函数的候选组；complete 链接要求组内最远两点也在阈值内，
    避免"A-B 近、B-C 近但 A-C 远"被链式并成一组。
    """
    vecs = embedder.encode_cached([funcs_by_name[n].get("definition", "") for n in names])
    vecs = vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)
    dist = pdist(vecs, metric="cosine")
    Z = linkage(dist, method="complete")
    labels = fcluster(Z, t=1 - AGGLOMERATIVE_SIM_THRESHOLD, criterion="distance")
    groups: dict[int, list[str]] = {}
    for name, lab in zip(names, labels):
        groups.setdefault(int(lab), []).append(name)
    return [g for g in groups.values() if len(g) >= 2]


def _full_merge_scan(funcs_by_name: dict, obs_by_id: dict, embedder, plan: list[dict], consumed: set) -> bool:
    """近义收敛：Agglomerative 拎候选（definition 向量、complete 链接防链式串簇）
    → LLM 确认（Abstract_merge_prompt 宁少勿滥）→ 确认组 _llm_merge 重新归纳。"""
    names = [n for n in funcs_by_name if n not in consumed]
    if len(names) < 2:
        return False
    # ① 拎候选：Agglomerative（complete 链接防链式串簇）
    candidate_groups = _agglomerative_candidates(names, funcs_by_name, embedder)
    if not candidate_groups:
        return False

    # ② LLM 确认：从候选组里挑真正同一结构作用的组
    cards = [{
        "group": members,
        "functions": [{
            "function_name": funcs_by_name[m].get("function_name"),
            "definition": funcs_by_name[m].get("definition", ""),
            "realization_patterns": funcs_by_name[m].get("realization_patterns", []),
        } for m in members],
    } for members in candidate_groups]
    user_content = "请从以下候选近义组中，确认真正承担同一结构作用、应合并为一组的函数：\n" + \
        json.dumps(cards, ensure_ascii=False, indent=1)
    try:
        result = chat_structured([
            {"role": "system", "content": ABSTRACT_MERGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ], AbstractMergeResponse)
        confirmed = [g for g in result.merge_groups if isinstance(g, list) and len(g) >= 2]
    except Exception as e:
        plan.append(_plan_record("SKIP_SMALL_SAMPLE", "FULL_MERGE_SCAN", reason=f"近义确认失败：{e}"))
        return False
    if not confirmed:
        return False

    changed = False
    for members in confirmed:
        valid = [m for m in members if m in funcs_by_name and m not in consumed]
        if len(valid) < 2:
            continue
        if any(len(funcs_by_name[m].get("supporting_obs_ids", [])) < REVISE_MIN_SUPPORTING for m in valid):
            plan.append(_plan_record(
                "SKIP_SMALL_SAMPLE", "+".join(valid),
                reason=f"近义收敛：成员 supporting < {REVISE_MIN_SUPPORTING}",
            ))
            continue
        merged, err = rev._llm_merge([funcs_by_name[m] for m in valid], obs_by_id)
        if merged is None:
            plan.append(_plan_record("SKIP_SMALL_SAMPLE", "+".join(valid), reason=f"近义合并失败：{err}"))
            continue
        rev._recalc_confidence(merged, obs_by_id, embedder)
        _bump_version(merged, "MERGE")
        for m in valid:
            consumed.add(m)
            del funcs_by_name[m]
        funcs_by_name[merged["function_name"]] = merged
        changed = True
        plan.append(_plan_record("MERGE", merged["function_name"], members=valid, source="agglomerative+confirm"))
    return changed


def _revise_from_report(report: dict, store, bank, plan: list[dict]) -> bool:
    rec = (report or {}).get("recommendations") or {}
    funcs = store.load_all()
    by_name = {f["function_name"]: dict(f) for f in funcs}
    obs_by_id = {o.get("obs_id"): o for o in bank.get_all()}
    embedder = bank.embedder
    consumed = set()
    changed = _full_merge_scan(by_name, obs_by_id, embedder, plan, consumed)
    if not any(rec.get(k) for k in _ACTIONABLE_KEYS):
        if changed:
            store.replace_all(list(by_name.values()))
        return changed

    for group in rec.get("merge_groups", []):
        members = [by_name[n] for n in group if n in by_name and n not in consumed]
        if len(members) < 2:
            continue
        if any(len(m.get("supporting_obs_ids", [])) < REVISE_MIN_SUPPORTING for m in members):
            plan.append(_plan_record(
                "SKIP_SMALL_SAMPLE", "+".join(m["function_name"] for m in members),
                reason=f"成员 supporting < {REVISE_MIN_SUPPORTING}",
            ))
            continue
        merged, err = rev._llm_merge(members, obs_by_id)
        if merged is None:
            plan.append(_plan_record("SKIP_SMALL_SAMPLE", "+".join(m["function_name"] for m in members),
                                     reason=f"合并失败：{err}"))
            continue
        rev._recalc_confidence(merged, obs_by_id, embedder)
        _bump_version(merged, "MERGE")
        for m in members:
            consumed.add(m["function_name"])
            del by_name[m["function_name"]]
        by_name[merged["function_name"]] = merged
        changed = True
        plan.append(_plan_record("MERGE", merged["function_name"],
                                 members=[m["function_name"] for m in members]))

    revise_items = []
    for e in rec.get("revise_definitions", []):
        revise_items.append((e.get("function_name"), {"双向混叠": e.get("reason", "")}))
    for e in rec.get("genre_bound_functions", []):
        revise_items.append((e.get("function_name"), {"题材表层绑定": e.get("reason", "")}))
    for name, reasons in revise_items:
        if name in consumed or name not in by_name:
            continue
        f = by_name[name]
        if len(f.get("supporting_obs_ids", [])) < REVISE_MIN_SUPPORTING:
            plan.append(_plan_record("SKIP_SMALL_SAMPLE", name,
                                     reason=f"supporting < {REVISE_MIN_SUPPORTING}"))
            continue
        out, err = rev._llm_revise(f, reasons)
        if out is None:
            plan.append(_plan_record("SKIP_SMALL_SAMPLE", name, reason=f"修订失败：{err}"))
            continue
        if len(out) == 1:
            revised = out[0]
            revised["function_id"] = f.get("function_id")
            revised["version_history"] = list(f.get("version_history", []))
            revised["supporting_obs_ids"] = f.get("supporting_obs_ids", [])
            rev._recalc_confidence(revised, obs_by_id, embedder)
            _bump_version(revised, "REVISE")
            del by_name[name]
            by_name[revised["function_name"]] = revised
            consumed.add(name)
            changed = True
            plan.append(_plan_record("REVISE", revised["function_name"], from_name=name))
        else:
            kept, dropped = rev._assign_split_obs(f.get("supporting_obs_ids", []), obs_by_id, out, embedder)
            if not kept:
                plan.append(_plan_record("SKIP_SMALL_SAMPLE", name, reason="SPLIT 子函数均无匹配 obs"))
                continue
            for sub in kept:
                _bump_version(sub, "SPLIT")
                by_name[sub["function_name"]] = sub
            del by_name[name]
            consumed.add(name)
            changed = True
            plan.append(_plan_record("SPLIT", name,
                                     split_into=[s["function_name"] for s in kept],
                                     dropped_obs=dropped))

    for e in rec.get("low_evidence_functions", []):
        name = e.get("function_name")
        if name in consumed or name not in by_name:
            continue
        del by_name[name]
        consumed.add(name)
        changed = True
        plan.append(_plan_record("REMOVE", name, reason="支持故事 <2"))

    for w in rec.get("weak_fit_obs", []):
        f = by_name.get(w.get("function_name"))
        if not f or w.get("obs_id") not in f.get("supporting_obs_ids", []):
            continue
        f["supporting_obs_ids"] = [oid for oid in f["supporting_obs_ids"] if oid != w.get("obs_id")]
        _bump_version(f, "WEAK_FIT_REMOVE")
        changed = True
        plan.append(_plan_record("WEAK_FIT_REMOVE", w.get("function_name"), obs_id=w.get("obs_id")))

    if changed:
        store.replace_all(list(by_name.values()))
    return changed


def curator_node(state: dict) -> dict:
    """收尾维护：应用 pending + novelty 归纳 + 挑战/体检修订；方案留档后 Apply 并清空 pending。"""
    if not _has_accumulation(state):
        print("[Curator] 无累积（pending/pools/体检问题均空），跳过维护")
        return {
            "curator_plan": [],
            "pending_evidence": [],
            "messages": [{"role": "system", "content": "[Curator] 无累积，跳过维护"}],
        }

    plan: list[dict] = []
    out_dir = state.get("out_dir", "data/evolve")
    os.makedirs(out_dir, exist_ok=True)
    store = get_active_store()
    bank = get_bank()

    pending = state.get("pending_evidence", [])
    if pending:
        func_map = {f["function_name"]: dict(f) for f in store.load_all()}
        changed = _apply_pending(pending, func_map, bank, plan)
        store.replace_all(list(func_map.values()))
        print(f"  [Curator] 应用 pending {len(pending)} 条（{len(changed)} 个函数证据更新）")

    occs = state.get("occurrences", [])
    novel_occs = [o for o in occs if o.get("label") == "NOVEL"]
    if novel_occs:
        added = _induce_novelty(novel_occs, bank, plan)
        print(f"  [Curator] novelty 归纳：新增 {added} 个函数（{len(novel_occs)} 个 novel obs 参与聚类）")

    mid = (state.get("mid_reports") or [{}])[-1]
    revised = _revise_from_report(mid, store, bank, plan)
    if revised:
        print("  [Curator] 挑战/体检修订完成")

    plan_path = os.path.join(out_dir, "curator_plan.jsonl")
    with open(plan_path, "a", encoding="utf-8") as f:
        for item in plan:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"  [Curator] 方案留档 → {plan_path}（{len(plan)} 个动作）")

    report_path = os.path.join(out_dir, "match_report.json")
    if os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            mr = json.load(f)
        mr["curator"] = {
            "actions": len(plan),
            "summary": [p.get("action") for p in plan],
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(mr, f, ensure_ascii=False, indent=2)

    return {
        "curator_plan": plan,
        "pending_evidence": [],
        "messages": [{"role": "system", "content": f"[Curator] 维护完成（{len(plan)} 个动作）"}],
    }
