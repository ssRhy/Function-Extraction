"""
Evaluator_v0 节点 - 批后六维本体评估（Bootstrap → Evolve 入口）

在 batch 的 Inducer 阶段（bootstrap_app 阶段 2）归纳完全部候选 Function 后，
由本节点一次性评估初始本体 O_0：计算六维得分与 PASS/FAIL 判定（>=4/6 达标通过），
FAIL 时输出优化建议清单。不新增独立图链路，作为 bootstrap_app 单图的一个节点被调用。

评估对象 = 当次批次的完整 Registry + Bank；evaluation_context 可传
registry_file / bank_file / manifest_path / report_path 覆盖默认路径，便于对快照并集评估。
"""

import json
import os

from Agent.llm import chat_structured
from Agent.Registry.registry import get_active_store
from Agent.Evaluator.dimensions import (
    evaluate_function_set,
    detect_bidirectional_conflation,
)
from Prompt.Evaluator_prompt import (
    EVALUATOR_SYSTEM_PROMPT,
    EvaluatorReviewResponse,
)

_EVAL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "evaluation")
_DEFAULT_REPORT_PATH = os.path.join(_EVAL_DIR, "evaluation_report.json")
_REVIEW_BATCH_SIZE = 20  # 每次 LLM 复核最多容纳的函数数


def _load_functions(registry_file: str | None) -> list[dict]:
    if registry_file:
        if not os.path.exists(registry_file):
            return []
        funcs = []
        with open(registry_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    funcs.append(json.loads(line))
        return funcs
    return get_active_store().load_all()


def _load_obs(bank_file: str | None) -> list[dict]:
    if bank_file:
        if not os.path.exists(bank_file):
            return []
        obs = []
        with open(bank_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    obs.append(json.loads(line))
        return obs
    from Agent.app import get_bank
    return get_bank().get_all()


def _load_story_category_map(manifest_path: str | None) -> dict | None:
    """manifest 的 txt_file -> category，转成 story_id（文件名主干）-> category 映射。"""
    if not manifest_path or not os.path.exists(manifest_path):
        return None
    mapping = {}
    with open(manifest_path, "r", encoding="utf-8") as f:
        for entry in json.load(f):
            txt = entry.get("txt_file", "")
            cat = entry.get("category")
            if not txt or not cat:
                continue
            story_id = os.path.splitext(os.path.basename(txt.replace("\\", "/")))[0]
            mapping[story_id] = cat
    return mapping or None


def _function_genres(functions, obs_by_id, story_to_category) -> dict:
    """每个函数支持故事覆盖的题材（供报告展示）。"""
    if not story_to_category:
        return {}
    result = {}
    for f in functions:
        cats = set()
        for oid in f.get("supporting_obs_ids", []):
            o = obs_by_id.get(oid)
            if o and o.get("story_id") in story_to_category:
                cats.add(story_to_category[o["story_id"]])
        result[f.get("function_name")] = sorted(cats)
    return result


def _review_abstraction(
    functions: list[dict],
    review_targets: list[str] | None = None,
    prev_reviews: list[dict] | None = None,
) -> tuple[list[dict], list[str], int, int, list[list[str]]]:
    """LLM 逐批复核抽象质量；某批失败时退回规则预筛（该批缺失），记录错误。

    review_targets=None 时全量复核（首轮）；否则只复核变更集（review_targets
    命中的函数 + 缺少旧评审的函数），未变更函数沿用 prev_reviews（按 function_name 复用）。
    返回 (合并后评审列表, 错误, 本轮新评审数, 复用旧评审数, LLM 近义合并组)。
    """
    if review_targets is None:
        to_review = list(functions)
        prev_by_name = {}
    else:
        target_set = set(review_targets)
        prev_by_name = {r.get("function_name"): r for r in (prev_reviews or [])}
        to_review, seen = [], set()
        for f in functions:
            name = f.get("function_name")
            if name in target_set or name not in prev_by_name:
                if name not in seen:
                    seen.add(name)
                    to_review.append(f)
    reviews, errors, merge_groups = [], [], []
    valid_names = {f.get("function_name") for f in functions}
    for start in range(0, len(to_review), _REVIEW_BATCH_SIZE):
        batch = to_review[start:start + _REVIEW_BATCH_SIZE]
        hits = detect_bidirectional_conflation([f.get("definition", "") for f in batch])
        cards = []
        for f, hit in zip(batch, hits):
            cards.append({
                "function_name": f.get("function_name"),
                "definition": f.get("definition"),
                "realization_patterns": f.get("realization_patterns", []),
                "hard_negatives": f.get("hard_negatives", []),
                "confusable_functions": f.get("confusable_functions", []),
                "rule_prescreen_hits": hit,
            })
        user_content = "请评审以下 Function 的抽象质量（rule_prescreen_hits 是规则预筛命中的方向词对，仅供参考）：\n" + json.dumps(cards, ensure_ascii=False, indent=1)
        try:
            result = chat_structured([
                {"role": "system", "content": EVALUATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ], EvaluatorReviewResponse)
            reviews.extend(r.model_dump() for r in result.reviews)
            for g in result.merge_groups:
                names = [n for n in g if n in valid_names]
                if len(names) >= 2 and len(set(names)) == len(names):
                    merge_groups.append(names)
        except Exception as e:
            errors.append(f"batch@{start}: {e}")
    merged = dict(prev_by_name)
    for r in reviews:
        merged[r.get("function_name")] = r
    final_reviews = [merged[f.get("function_name")] for f in functions if f.get("function_name") in merged]
    new_names = {r.get("function_name") for r in reviews}
    reused = sum(
        1 for f in functions
        if f.get("function_name") in prev_by_name and f.get("function_name") not in new_names
    )
    return final_reviews, errors, len(reviews), reused, merge_groups


def _print_summary(report: dict) -> None:
    print(f"[Evaluator_v0] 判定: {report['verdict']}（达标 {len(report['passed_dimensions'])}/6）")
    print(f"  达标: {report['passed_dimensions']}")
    print(f"  未达标: {report['failed_dimensions']}")
    for name, d in report.get("dimensions", {}).items():
        extra = ""
        if name == "coverage":
            extra = f" (covered={d.get('covered_obs')}/{d.get('total_obs')})"
        elif name == "evidence_count":
            extra = f" (mean_stories={d.get('mean_stories')}, mean_obs={d.get('mean_obs')})"
        elif name == "diversity":
            extra = f" (categories={d.get('categories')}, stories={d.get('stories')})"
        print(f"    {name}: score={d.get('score')} pass={d.get('pass')}{extra}")
    rec = report.get("recommendations", {})
    if rec:
        print("  建议清单:")
        for k, v in rec.items():
            print(f"    - {k}: {v}")


def evaluator_node(state: dict) -> dict:
    """读取 Registry + Bank，计算六维评估，写报告文件，返回判定字段。"""
    context = state.get("evaluation_context") or {}
    functions = _load_functions(context.get("registry_file"))
    all_obs = _load_obs(context.get("bank_file"))

    if not functions:
        report = {
            "verdict": "FAIL",
            "passed_dimensions": [],
            "failed_dimensions": [],
            "dimensions": {},
            "recommendations": {"reason": "Registry 为空，无法评估"},
        }
        report_path = context.get("report_path") or _DEFAULT_REPORT_PATH
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print("[Evaluator_v0] Registry 为空，判定 FAIL")
        return {
            "evaluation_report": report,
            "evaluator_decision": "FAIL",
            "messages": [{"role": "system", "content": "[Evaluator_v0] FAIL（Registry 为空）"}],
        }

    if context.get("bank_file"):
        from Embedding.embedding import Embedder
        embedder = Embedder()
    else:
        from Agent.app import get_bank
        embedder = get_bank().embedder

    story_to_category = _load_story_category_map(context.get("manifest_path"))
    force_full = state.get("force_full_review")
    prev_report = state.get("evaluation_report") or {}
    prev_reviews = None if force_full else prev_report.get("abstraction_reviews")
    review_targets = None if force_full else state.get("review_targets")
    if review_targets is None and not force_full:
        review_targets = (state.get("revise_report") or {}).get("changed")
    reviews, review_errors, reviewed_n, reused_n, merge_groups = _review_abstraction(
        functions, review_targets=review_targets, prev_reviews=prev_reviews,
    )
    mode = "全量(最终)" if force_full else ("增量" if review_targets else "全量")
    print(f"[Evaluator_v0] Abstraction 复核: {mode} {reviewed_n} 个 / 复用 {reused_n} 个")
    report = evaluate_function_set(
        functions,
        all_obs,
        embedder,
        story_to_category=story_to_category,
        abstraction_reviews=reviews,
        merge_groups=merge_groups,
    )
    print(f"[Evaluator_v0] LLM 近义合并组: {len(merge_groups)} 组")
    if reviews:
        report["abstraction_reviews"] = reviews
    report["abstraction_reviewed"] = reviewed_n
    report["abstraction_reused"] = reused_n
    if review_errors:
        report["review_errors"] = review_errors
    obs_by_id = {o.get("obs_id"): o for o in all_obs}
    report["function_genres"] = _function_genres(functions, obs_by_id, story_to_category)

    report_path = context.get("report_path") or _DEFAULT_REPORT_PATH
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    verdict = report["verdict"]
    _print_summary(report)
    return {
        "evaluation_report": report,
        "evaluator_decision": verdict,
        "review_targets": None,
        "messages": [{"role": "system", "content": f"[Evaluator_v0] {verdict}（达标 {len(report['passed_dimensions'])}/6）"}],
    }
