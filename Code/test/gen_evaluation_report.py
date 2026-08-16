"""生成三题材并集 Evaluator_v0 评估报告（可复现）。

合并 data/genre_functions/ 三份题材快照（functions + bank）为并集，
用 evaluation_context 指向并集与 manifest，调用 evaluator_node，
报告落盘 data/evaluation/evaluation_report.json（并集文件保留以便复现）。
"""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Agent.Evaluator.evaluator import evaluator_node

BASE = os.path.join(os.path.dirname(__file__), "..", "data", "genre_functions")
EVAL_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "evaluation")
MANIFEST = os.path.join(os.path.dirname(__file__), "..", "zhihu_story_subset_120_20260815_clean", "manifest.json")


def _merge(prefix: str) -> list:
    merged = []
    for name in sorted(os.listdir(BASE)):
        if not name.startswith(prefix):
            continue
        with open(os.path.join(BASE, name), "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    merged.append(json.loads(line))
    return merged


def main() -> None:
    functions = _merge("functions_")
    all_obs = _merge("bank_")
    os.makedirs(EVAL_DIR, exist_ok=True)
    reg_path = os.path.join(EVAL_DIR, "union_functions.jsonl")
    bank_path = os.path.join(EVAL_DIR, "union_obs.jsonl")
    with open(reg_path, "w", encoding="utf-8") as f:
        for func in functions:
            f.write(json.dumps(func, ensure_ascii=False) + "\n")
    with open(bank_path, "w", encoding="utf-8") as f:
        for o in all_obs:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print(f"[gen_evaluation_report] 并集: {len(functions)} funcs / {len(all_obs)} obs")
    result = evaluator_node({
        "messages": [],
        "evaluation_context": {
            "registry_file": reg_path,
            "bank_file": bank_path,
            "manifest_path": MANIFEST,
            "report_path": os.path.join(EVAL_DIR, "evaluation_report.json"),
        },
    })
    print(f"[gen_evaluation_report] 判定: {result['evaluator_decision']}")


if __name__ == "__main__":
    main()