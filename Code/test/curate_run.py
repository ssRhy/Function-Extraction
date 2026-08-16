"""独立入口：对任意快照/并集跑 Evaluator_v0 评估 + 自动修订闭环（curate_app）。

用法（在 Code/ 下）:
    python test/curate_run.py --registry data/evaluation/union_functions.jsonl \
        --bank data/evaluation/union_obs.jsonl \
        --manifest zhihu_story_subset_120_20260815_clean/manifest.json
    python test/curate_run.py --no-revise ...        # 仅评估（等价 gen_evaluation_report.py）
    python test/curate_run.py --max-rounds 2 ...     # 覆盖默认修订轮数

修订闭环采用"首轮全量 + 后续轮增量"Abstraction 复核（revise 记录变更集，
evaluator 只重评变更函数、其余沿用旧评审）；每轮修订动作追加落盘 revise_rounds.jsonl。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluator_v0 评估 + 自动修订闭环")
    parser.add_argument("--registry", type=str, default=None, help="Registry JSONL（缺省 = 默认 functions.jsonl）")
    parser.add_argument("--bank", type=str, default=None, help="Bank JSONL（缺省 = 当前 Bank）")
    parser.add_argument("--manifest", type=str, default=None, help="manifest.json 路径（Diversity 题材口径）")
    parser.add_argument("--report", type=str, default=None, help="评估报告输出路径（缺省 = data/evaluation/evaluation_report.json）")
    parser.add_argument("--max-rounds", type=int, default=None, help="最大修订轮数（缺省 3）")
    parser.add_argument("--no-revise", action="store_true", help="仅评估，不修订")
    args = parser.parse_args()

    if args.max_rounds is not None:
        from Agent.Evaluator import revise as revise_module
        revise_module.MAX_EVAL_ROUNDS = args.max_rounds

    eval_context = {}
    if args.registry:
        eval_context["registry_file"] = os.path.abspath(args.registry)
    if args.bank:
        eval_context["bank_file"] = os.path.abspath(args.bank)
    if args.manifest:
        eval_context["manifest_path"] = os.path.abspath(args.manifest)
    if args.report:
        eval_context["report_path"] = os.path.abspath(args.report)

    if args.no_revise:
        from Agent.Evaluator.evaluator import evaluator_node
        result = evaluator_node({"messages": [], "evaluation_context": eval_context})
        report = result.get("evaluation_report", {})
        print(f"[curate_run] 判定: {result.get('evaluator_decision')}（达标 {len(report.get('passed_dimensions', []))}/6）")
        return

    from Agent.app import curate_app
    state = {
        "messages": [],
        "evaluation_context": eval_context,
        "evaluation_round": 0,
    }
    config = {"configurable": {"thread_id": "curate-run"}}
    result = curate_app.invoke(state, config=config)
    report = result.get("evaluation_report", {})
    rev = result.get("revise_report") or {}
    print(f"[curate_run] 判定: {result.get('evaluator_decision')}（达标 {len(report.get('passed_dimensions', []))}/6，"
          f"修订轮数 {result.get('evaluation_round', 0)}）")
    print(f"[curate_run] 修订动作: 合并 {len(rev.get('merged', []))} / 修订 {len(rev.get('revised', []))} "
          f"/ 拆分 {len(rev.get('split', []))} / 移除 {len(rev.get('removed', []))}")
    if rev:
        rev_dir = os.path.dirname(args.report) if args.report else "data/evaluation"
        os.makedirs(rev_dir, exist_ok=True)
        with open(os.path.join(rev_dir, "revise_report.json"), "w", encoding="utf-8") as f:
            json.dump(rev, f, ensure_ascii=False, indent=2)
        print(f"[curate_run] 修订报告落盘: {os.path.join(rev_dir, 'revise_report.json')}")
    # 每轮修订动作追加落盘（回溯 checkpointer 历史，按时间序）
    rounds = []
    try:
        for snap in curate_app.get_state_history(config):
            vals = snap.values or {}
            rr = vals.get("revise_report")
            if rr and rr.get("before_count") is not None and rr not in rounds:
                rounds.append(rr)
    except Exception as e:
        print(f"[curate_run] 读取轮次历史失败: {e}")
    if rounds:
        rev_dir = os.path.dirname(args.report) if args.report else "data/evaluation"
        os.makedirs(rev_dir, exist_ok=True)
        rounds_path = os.path.join(rev_dir, "revise_rounds.jsonl")
        with open(rounds_path, "w", encoding="utf-8") as f:
            for rr in reversed(rounds):
                f.write(json.dumps(rr, ensure_ascii=False) + "\n")
        print(f"[curate_run] 每轮修订报告落盘: {rounds_path}（{len(rounds)} 轮）")


if __name__ == "__main__":
    main()