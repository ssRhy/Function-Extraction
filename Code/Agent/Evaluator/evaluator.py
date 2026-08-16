"""
Evaluator_v0 节点 - 批后六维本体评估（Bootstrap → Evolve 入口）

在 batch 的 Inducer 阶段（--batch-induction 阶段 2）归纳完全部候选 Function 后，
由本节点一次性评估初始本体 O_0：计算六维得分与 PASS/FAIL 判定（>=4/6 达标通过），
FAIL 时输出优化建议清单。不新增图链路，由 batch_run 归纳循环结束后直接调用本节点
（与现有直接调用 inducer_node 的模式一致）。

评估对象 = 当次批次的完整 Registry + Bank；evaluation_context 可传
registry_file / bank_file / manifest_path / report_path 覆盖默认路径，便于对快照并集评估。
"""

import json
import os

from Agent.llm import chat_structured
from Agent.Inducer.confidence import load_registry_functions
from Agent.Evaluator.dimensions import (
    evaluate_function_set,
    detect_bidirectional_conflation,
)
from Prompt.Evaluator_prompt import (
    EVALUATOR_SYSTEM_PROMPT,
    EvaluatorReviewResponse,
)

_EVAL_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "evaluation")
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
    return load_registry_functions()


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


def _review_abstraction(functions: list[dict]) -> tuple[list[dict], list[str]]:
    """LLM 逐批复核抽象质量；某批失败时退回规则预筛（该批缺失），记录错误。"""
    reviews, errors = [], []
    for start in range(0, len(functions), _REVIEW_BATCH_SIZE):
        batch = functions[start:start + _REVIEW_BATCH_SIZE]
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
        except Exception as e:
            errors.append(f"batch@{start}: {e}")
    return reviews, errors


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
            "next_node": "inducer_retry",
            "messages": [{"role": "system", "content": "[Evaluator_v0] FAIL（Registry 为空）"}],
        }

    if context.get("bank_file"):
        from Embedding.embedding import Embedder
        embedder = Embedder()
    else:
        from Agent.app import get_bank
        embedder = get_bank().embedder

    story_to_category = _load_story_category_map(context.get("manifest_path"))
    reviews, review_errors = _review_abstraction(functions)
    report = evaluate_function_set(
        functions,
        all_obs,
        embedder,
        story_to_category=story_to_category,
        abstraction_reviews=reviews,
    )
    if reviews:
        report["abstraction_reviews"] = reviews
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
        "next_node": "registry_init" if verdict == "PASS" else "inducer_retry",
        "messages": [{"role": "system", "content": f"[Evaluator_v0] {verdict}（达标 {len(report['passed_dimensions'])}/6）"}],
    }