"""
Evaluator_v0 六维评估纯函数模块（无 LLM、可复现）

六维：
1. coverage            覆盖率：能被 >=1 个 Function 解释的 obs 占比
2. cohesion            内聚度：supporting obs 与其 centroid 的余弦均值；弱贴合 obs 标记
3. separation          分离度：definition 两两余弦 >= 阈值的近义组数（=0 达标，抓近义碎片化）
4. abstraction_quality 抽象质量：LLM 复核聚合（OK 比例）；规则预筛仅作兜底/种子
5. evidence_count      证据量：跨故事证据数量与分布
6. diversity           语料多样性：支持故事覆盖题材数（无题材信息时回退去重故事数）
"""

import numpy as np

# ---- 阈值（集中可调，集成验收时按真实分布校准）----
COVERAGE_SIM_THRESHOLD = 0.65   # obs 文本向量与任一 definition 余弦 >= 该值视为可解释（MiniLM 中文基线 ~0.5-0.6）
COVERAGE_PASS = 0.60            # 覆盖率达标线
COHESION_PASS = 0.60            # 内聚度达标线（MiniLM 中文同质 obs ~0.97、无关 ~0.57）
OBS_FIT_THRESHOLD = 0.70        # 单 obs 与函数 centroid 余弦低于该值标记 weak-fit（0.80 在真实数据标记 49 条过噪，<0.70 仅 5 条为真离群）
SEP_NEAR_DUP_THRESHOLD = 0.85   # 近义组阈值（对齐 NEAR_DUP_THRESHOLD；0.78 会串出巨型连通分量不可用，漏检的弱近义由 LLM 抽象复核补）
ABSTRACTION_PASS = 0.80         # 抽象质量 OK 比例达标线
EVIDENCE_MIN_STORIES = 2        # 每个函数至少覆盖的故事数
EVIDENCE_MEAN_STORIES = 2.5     # 全体函数平均支持故事数（120 篇实测 2.892、中位数 3，按真实分布校准）
EVIDENCE_MEAN_OBS = 3           # 全体函数平均支持 obs 数（120 篇实测 3.048、中位数 3，按真实分布校准）
DIVERSITY_GENRE_PASS = 2        # 支持故事覆盖题材数达标线
DIVERSITY_STORY_PASS = 20       # 无题材信息时的去重故事数达标线
PASS_MIN_DIMENSIONS = 4         # 通过判定：>= 4/6 维度达标
SEP_REVIEW_THRESHOLD = 0.78     # 复核候选对阈值（低于分组阈值，仅作建议列表）
SEP_REVIEW_CAP = 60             # 复核候选对数量上限（按相似度降序取前 N）

# 双向混叠方向词对（规则预筛，供 LLM 复核作种子；形如"揭露或掩盖/建立或恶化"）
OPPOSITION_PAIRS = [
    ("揭露", "掩盖"), ("揭示", "掩盖"), ("转变", "揭示"), ("建立", "恶化"),
    ("建立", "破裂"), ("改善", "恶化"), ("得到", "失去"), ("获得", "失去"),
    ("成功", "失败"), ("开始", "结束"), ("上升", "下降"), ("出现", "消失"),
    ("加强", "削弱"), ("亲近", "疏远"), ("接受", "反抗"), ("增加", "减少"),
]


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    dot = float(np.dot(a, b))
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _obs_text(obs: dict) -> str:
    return " | ".join(x for x in (
        obs.get("before_state", ""),
        obs.get("event", ""),
        obs.get("after_state", ""),
    ) if x) or obs.get("surface_form", "")


# ========== 1. Coverage 覆盖率 ==========

def compute_coverage(functions, all_obs, embedder, sim_threshold: float = COVERAGE_SIM_THRESHOLD) -> dict:
    """能被 >=1 个 Function 解释的 obs 占比（obs 属于 supporting 集，或与任一 definition 相似）。"""
    if not functions or not all_obs:
        return {"score": 0.0, "pass": False, "total_obs": len(all_obs), "covered_obs": 0}
    supporting_ids = set()
    for f in functions:
        supporting_ids.update(f.get("supporting_obs_ids", []))
    def_vecs = embedder.encode([f.get("definition", "") for f in functions])
    obs_vecs = embedder.encode([_obs_text(o) for o in all_obs])
    def_norm = def_vecs / np.maximum(np.linalg.norm(def_vecs, axis=1, keepdims=True), 1e-9)
    obs_norm = obs_vecs / np.maximum(np.linalg.norm(obs_vecs, axis=1, keepdims=True), 1e-9)
    sims = obs_norm @ def_norm.T
    covered = 0
    for i, o in enumerate(all_obs):
        if o.get("obs_id") in supporting_ids:
            covered += 1
            continue
        if sims.shape[1] and float(sims[i].max()) >= sim_threshold:
            covered += 1
    score = covered / len(all_obs)
    return {"score": round(score, 4), "pass": score >= COVERAGE_PASS, "total_obs": len(all_obs), "covered_obs": covered}


# ========== 2. Cohesion 内聚度 ==========

def compute_cohesion(functions, obs_by_id, embedder, fit_threshold: float = OBS_FIT_THRESHOLD) -> dict:
    """supporting obs 与其 centroid 余弦的总体均值；单 obs 低于阈值标记 weak-fit。"""
    per_function, weak_fit_obs = [], []
    for f in functions:
        sup = [obs_by_id[oid] for oid in f.get("supporting_obs_ids", []) if oid in obs_by_id]
        if len(sup) < 2:
            continue
        vecs = embedder.encode([_obs_text(o) for o in sup])
        centroid = vecs.mean(axis=0)
        sims = [_cosine(vecs[i], centroid) for i in range(len(vecs))]
        per_function.append(sum(sims) / len(sims))
        for i, o in enumerate(sup):
            if sims[i] < fit_threshold:
                weak_fit_obs.append({
                    "obs_id": o.get("obs_id"),
                    "function_name": f.get("function_name"),
                    "similarity": round(sims[i], 3),
                })
    score = float(np.mean(per_function)) if per_function else 0.0
    return {
        "score": round(score, 4),
        "pass": score >= COHESION_PASS,
        "weak_fit_obs": weak_fit_obs,
    }


# ========== 3. Separation 分离度 ==========

def compute_separation(functions, embedder, threshold: float = SEP_NEAR_DUP_THRESHOLD) -> dict:
    """definition 两两余弦 >= 阈值的并查集近义组；达标 = 0 组。

    低于分组阈值但 >= SEP_REVIEW_THRESHOLD 的对子进 review_pairs（建议复核列表，
    仅作建议，不参与达标判定；避免低阈值串出巨型连通分量）。
    """
    n = len(functions)
    if n == 0:
        return {"score": 0, "pass": True, "groups": [], "pairs": [], "review_pairs": []}
    vecs = embedder.encode([f.get("definition", "") for f in functions])
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    pairs, review_pairs = [], []
    for i in range(n):
        for j in range(i + 1, n):
            sim = _cosine(vecs[i], vecs[j])
            if sim >= threshold:
                union(i, j)
                pairs.append({
                    "a": functions[i].get("function_name"),
                    "b": functions[j].get("function_name"),
                    "similarity": round(sim, 3),
                })
            elif sim >= SEP_REVIEW_THRESHOLD:
                review_pairs.append({
                    "a": functions[i].get("function_name"),
                    "b": functions[j].get("function_name"),
                    "similarity": round(sim, 3),
                })
    groups_map = {}
    for i in range(n):
        groups_map.setdefault(find(i), []).append(i)
    groups = [sorted(g) for g in groups_map.values() if len(g) > 1]
    group_names = [[functions[i].get("function_name") for i in g] for g in groups]
    review_pairs.sort(key=lambda p: p["similarity"], reverse=True)
    return {
        "score": len(group_names),
        "pass": len(group_names) == 0,
        "groups": group_names,
        "pairs": pairs,
        "review_pairs": review_pairs[:SEP_REVIEW_CAP],
    }


# ========== 4. Abstraction Quality 抽象质量 ==========

def detect_bidirectional_conflation(definitions) -> list:
    """规则预筛：定义中同时出现成对方向词，返回每定义的命中词对列表。"""
    hits = []
    for d in definitions:
        pairs = [f"{a}↔{b}" for a, b in OPPOSITION_PAIRS if a in d and b in d]
        hits.append(pairs)
    return hits


def compute_abstraction(functions, abstraction_reviews=None) -> dict:
    """LLM 复核聚合；无复核时退回规则预筛（仅双向混叠）。"""
    issues = {"conflation": [], "genre_bound": [], "too_specific": [], "too_broad": []}
    if not abstraction_reviews:
        hits = detect_bidirectional_conflation([f.get("definition", "") for f in functions])
        ok = sum(1 for h in hits if not h)
        for f, h in zip(functions, hits):
            if h:
                issues["conflation"].append({"function_name": f.get("function_name"), "reason": "；".join(h)})
        score = ok / len(functions) if functions else 0.0
        return {
            "score": round(score, 4), "pass": score >= ABSTRACTION_PASS,
            "ok_count": ok, "total": len(functions), "reviewed": False, "issues": issues,
        }
    by_name = {r.get("function_name"): r for r in abstraction_reviews}
    ok_count, total = 0, 0
    for f in functions:
        r = by_name.get(f.get("function_name"))
        if not r:
            continue
        total += 1
        if r.get("recommendation") == "OK":
            ok_count += 1
        if r.get("bidirectional_conflation"):
            issues["conflation"].append({"function_name": f.get("function_name"), "reason": r.get("conflation_reason", "")})
        if r.get("genre_surface_binding"):
            issues["genre_bound"].append({"function_name": f.get("function_name"), "reason": r.get("binding_reason", "")})
        if r.get("granularity") == "too_specific":
            issues["too_specific"].append(f.get("function_name"))
        elif r.get("granularity") == "too_broad":
            issues["too_broad"].append(f.get("function_name"))
    score = ok_count / total if total else 0.0
    return {
        "score": round(score, 4), "pass": score >= ABSTRACTION_PASS,
        "ok_count": ok_count, "total": total, "reviewed": True, "issues": issues,
    }


# ========== 5. Evidence Count 证据量 ==========

def compute_evidence(functions, obs_by_id) -> dict:
    """无 <2 故事函数、平均支持故事 >=2.5、平均 obs >=3 方达标；不足者标记待复核。"""
    story_counts, obs_counts, low_evidence = [], [], []
    for f in functions:
        sup_ids = [oid for oid in f.get("supporting_obs_ids", []) if oid in obs_by_id]
        stories = len({obs_by_id[oid].get("story_id") for oid in sup_ids})
        story_counts.append(stories)
        obs_counts.append(len(sup_ids))
        if stories < EVIDENCE_MIN_STORIES:
            low_evidence.append({"function_name": f.get("function_name"), "stories": stories})
    mean_stories = float(np.mean(story_counts)) if story_counts else 0.0
    mean_obs = float(np.mean(obs_counts)) if obs_counts else 0.0
    ok = (
        all(s >= EVIDENCE_MIN_STORIES for s in story_counts)
        and mean_stories >= EVIDENCE_MEAN_STORIES
        and mean_obs >= EVIDENCE_MEAN_OBS
    )
    return {
        "score": round(mean_stories, 3), "pass": ok,
        "mean_stories": round(mean_stories, 3), "mean_obs": round(mean_obs, 3),
        "low_evidence": low_evidence,
    }


# ========== 6. Diversity 语料多样性 ==========

def compute_diversity(functions, obs_by_id, story_to_category=None) -> dict:
    """支持故事覆盖题材数达标（>=2）；无题材映射时回退去重故事数（>=20）。"""
    stories = set()
    for f in functions:
        for oid in f.get("supporting_obs_ids", []):
            o = obs_by_id.get(oid)
            if o:
                stories.add(o.get("story_id"))
    if story_to_category:
        categories = {story_to_category[s] for s in stories if s in story_to_category}
        return {
            "score": len(categories), "pass": len(categories) >= DIVERSITY_GENRE_PASS,
            "categories": sorted(categories), "stories": len(stories),
        }
    return {
        "score": len(stories), "pass": len(stories) >= DIVERSITY_STORY_PASS,
        "categories": None, "stories": len(stories),
    }


# ========== 聚合 ==========

def generate_recommendations(functions, dims: dict) -> dict:
    """把各维问题整理为可执行建议清单。"""
    sep, coh, evi, abq = dims["separation"], dims["cohesion"], dims["evidence_count"], dims["abstraction_quality"]
    rec = {
        "merge_groups": sep.get("groups", []),
        "near_dup_pairs": sep.get("pairs", []),
        "near_dup_review_pairs": sep.get("review_pairs", []),
        "revise_definitions": abq.get("issues", {}).get("conflation", []),
        "genre_bound_functions": abq.get("issues", {}).get("genre_bound", []),
        "granularity_issues": {
            k: v for k, v in abq.get("issues", {}).items()
            if k in ("too_specific", "too_broad") and v
        },
        "weak_fit_obs": coh.get("weak_fit_obs", []),
        "low_evidence_functions": evi.get("low_evidence", []),
    }
    return {k: v for k, v in rec.items() if v}


def evaluate_function_set(functions, all_obs, embedder, story_to_category=None, abstraction_reviews=None) -> dict:
    """六维评估总入口：返回判定、各维得分、达标位与建议。"""
    obs_by_id = {o.get("obs_id"): o for o in all_obs}
    dims = {
        "coverage": compute_coverage(functions, all_obs, embedder),
        "cohesion": compute_cohesion(functions, obs_by_id, embedder),
        "separation": compute_separation(functions, embedder),
        "abstraction_quality": compute_abstraction(functions, abstraction_reviews),
        "evidence_count": compute_evidence(functions, obs_by_id),
        "diversity": compute_diversity(functions, obs_by_id, story_to_category),
    }
    passed = [name for name, d in dims.items() if d["pass"]]
    failed = [name for name, d in dims.items() if not d["pass"]]
    verdict = "PASS" if len(passed) >= PASS_MIN_DIMENSIONS else "FAIL"
    return {
        "verdict": verdict,
        "passed_dimensions": passed,
        "failed_dimensions": failed,
        "dimensions": dims,
        "recommendations": generate_recommendations(functions, dims),
    }