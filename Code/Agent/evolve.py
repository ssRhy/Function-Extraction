"""Evolve App - evolve_app 单图 + CLI（python -m Agent.evolve）

新文本目录 → 复用 story_loader/preprocessor/observer/bank_adder 提取并写入 Bank
→ Matcher（top-k 召回 + LLM 五分类）→ MATCH/EXTEND 直写 Registry exemplars、
NOVEL→novelty_pool、CONFLICT/UNCERTAIN→challenge_pool → FunctionOccurrence + 匹配报告。

用法:
    python -m Agent.evolve --corpus <新文本目录>
    python -m Agent.evolve --corpus <dir> --namespace smoke --out-dir data/evolve_smoke
    python -m Agent.evolve --corpus <dir> --stories "a.txt,b.txt" --limit 5
"""

import argparse
import json
import os
import sys
import time
from collections import Counter

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT_DIR = os.path.join(_ROOT, "data", "evolve")
MID_OBS_THRESHOLD = 20  # 累计处理多少个新 obs 触发一次 Evaluator_mid 周期体检（滚动重置）
_VENDOR = os.path.join(_ROOT, "vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

from langgraph.graph import StateGraph, START, END

from Agent.state import NarrativePipelineState
from Agent.app import story_loader_node, bank_adder_node, natural_key, get_bank
from Agent.Pre_pro.pre_processor import preprocessor_node
from Agent.Observer.observer import observer_node
from Agent.Matcher import matcher as matcher_module
from Agent.Matcher.matcher import matcher_node
from Agent.Registry.registry import RegistryStore, set_active_store, get_active_store
from Agent.Evaluator.evaluator import evaluator_node
from Agent.Critic.critic import critic_node
from Agent.Curator.curator import curator_node


def _collect_txt(root: str) -> list[str]:
    """递归收集目录下全部 .txt（不限文件名模式，供新文本语料）。"""
    files = []
    for dirpath, _dirs, fns in os.walk(root):
        for fn in fns:
            if fn.endswith(".txt"):
                files.append(os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/"))
    return sorted(files, key=natural_key)


def _write_jsonl(path: str, items: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def continue_evolve(state: NarrativePipelineState) -> str:
    """story_loader 后路由：全部处理完 → report；有故事 → preprocessor；空文件已跳过 → 继续 loader。"""
    if state.get("current_story_index", 0) >= state.get("total_stories", 0):
        return "report"
    if state.get("raw_text"):
        return "preprocessor"
    return "skip"


def collector_node(state: NarrativePipelineState) -> dict:
    """累积 occurrence、打印逐篇摘要、推进 story 下标、清空临时字段。"""
    occurrences = list(state.get("occurrences", []))
    occurrences.extend(state.get("match_occurrences", []))
    pending_evidence = list(state.get("pending_evidence", []))
    pending_evidence.extend(state.get("match_pending", []))
    labels = Counter(o.get("label") for o in state.get("match_occurrences", []))
    ns = state.get("normalized_story") or {}
    print(f"  → 句子={len(ns.get('sentences', []))}, obs={len(state.get('observations', []))}, "
          f"判定={dict(labels)}, 累计 occurrence={len(occurrences)}")
    obs_since_eval = state.get("obs_since_eval", 0) + len(state.get("match_occurrences", []))
    return {
        "occurrences": occurrences,
        "pending_evidence": pending_evidence,
        "match_pending": [],
        "obs_since_eval": obs_since_eval,
        "current_story_index": state.get("current_story_index", 0) + 1,
        "raw_text": None,
        "story_config": None,
        "normalized_story": None,
        "observations": [],
        "added_obs_ids": [],
        "match_decisions": [],
        "match_occurrences": [],
    }


def check_mid(state: NarrativePipelineState) -> str:
    """collector 后路由：自上次体检累计 >= MID_OBS_THRESHOLD 个 obs → 体检；否则继续下一篇。"""
    if state.get("obs_since_eval", 0) >= MID_OBS_THRESHOLD:
        return "evaluator_mid"
    return "story_loader"


def evaluator_mid_node(state: NarrativePipelineState) -> dict:
    """Evaluator_mid 周期体检：复用 evaluator_node 六维评估当前 Registry+Bank，只记录不修订。"""
    mid_reports = list(state.get("mid_reports", []))
    n = len(mid_reports) + 1
    out_dir = state.get("out_dir", DEFAULT_OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    report_path = os.path.join(out_dir, f"evaluation_mid_{n}.json")
    st = dict(state)
    pending = state.get("pending_evidence", [])
    if pending:
        by_name = {}
        for f in get_active_store().load_all():
            by_name.setdefault(f.get("function_name"), dict(f))
        for p in pending:
            f = by_name.get(p.get("function_name"))
            if f:
                sup = list(f.get("supporting_obs_ids", []))
                if p.get("obs_id") and p["obs_id"] not in sup:
                    sup.append(p["obs_id"])
                    f["supporting_obs_ids"] = sup
        tmp_registry = os.path.join(out_dir, f"registry_pending_{n}.jsonl")
        _write_jsonl(tmp_registry, list(by_name.values()))
        st["evaluation_context"] = {"registry_file": tmp_registry, "report_path": report_path}
    else:
        st["evaluation_context"] = {"report_path": report_path}
    result = evaluator_node(st)
    report = result.get("evaluation_report") or {}
    dims = report.get("dimensions", {})
    rec = report.get("recommendations") or {}
    summary = {
        "round": n,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "verdict": result.get("evaluator_decision"),
        "passed_dimensions": report.get("passed_dimensions", []),
        "failed_dimensions": report.get("failed_dimensions", []),
        "dimensions": {k: {"score": d.get("score"), "pass": d.get("pass")} for k, d in dims.items()},
        "pending_applied": len(state.get("pending_evidence", [])),
        "recommendations": report.get("recommendations", {}),
        "issue_counts": {
            "merge_groups": len(rec.get("merge_groups", [])),
            "revise": len(rec.get("revise_definitions", [])),
            "low_evidence": len(rec.get("low_evidence_functions", [])),
            "weak_fit": len(rec.get("weak_fit_obs", [])),
        },
    }
    mid_reports.append(summary)
    passed = len(summary["passed_dimensions"])
    print(f"  [Evaluator_mid] 第 {n} 次体检: {summary['verdict']}（达标 {passed}/6）→ {report_path}")
    return {
        "mid_reports": mid_reports,
        "obs_since_eval": 0,
        "messages": [{"role": "system", "content": f"[Evaluator_mid] 第 {n} 次体检 {summary['verdict']}（{passed}/6）"}],
    }


def report_node(state: NarrativePipelineState) -> dict:
    """写 occurrences / novelty_pool / challenge_pool / match_report，打印统计。"""
    occs = state.get("occurrences", [])
    counts = Counter(o.get("label") for o in occs)
    total = len(occs)
    coverage = (counts.get("MATCH", 0) + counts.get("EXTEND", 0)) / total if total else 0.0
    novelty = counts.get("NOVEL", 0) / total if total else 0.0
    report = {
        "total_obs": total,
        "counts": dict(counts),
        "coverage": round(coverage, 4),
        "novelty_rate": round(novelty, 4),
        "occurrences": occs,
        "mid_evaluations": state.get("mid_reports", []),
    }
    out_dir = state.get("out_dir", DEFAULT_OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    _write_jsonl(os.path.join(out_dir, "occurrences.jsonl"), occs)
    _write_jsonl(os.path.join(out_dir, "novelty_pool.jsonl"), [o for o in occs if o.get("label") == "NOVEL"])
    _write_jsonl(
        os.path.join(out_dir, "challenge_pool.jsonl"),
        [o for o in occs if o.get("label") in ("CONFLICT", "UNCERTAIN", "RESOLVED")],
    )
    _write_jsonl(os.path.join(out_dir, "pending_evidence.jsonl"), state.get("pending_evidence", []))
    with open(os.path.join(out_dir, "match_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("\n=== Evolve 匹配报告 ===")
    print(f"  总 obs: {total}")
    for label in ("MATCH", "EXTEND", "CONFLICT", "UNCERTAIN", "NOVEL"):
        print(f"    {label}: {counts.get(label, 0)}")
    print(f"  coverage={report['coverage']:.3f} (MATCH+EXTEND) / novelty_rate={report['novelty_rate']:.3f} (NOVEL)")
    mids = state.get("mid_reports", [])
    if mids:
        print("  Evaluator_mid 体检:")
        for m in mids:
            print(f"    第 {m['round']} 次: {m['verdict']}（达标 {len(m['passed_dimensions'])}/6）"
                  f" 问题={m['issue_counts']}")
    print(f"  输出目录 → {out_dir}")
    return {"match_report": report}


def _build_evolve_graph() -> StateGraph:
    """构建 evolve_app 拓扑（条件边循环，逐篇处理）。"""
    graph = StateGraph(NarrativePipelineState)
    graph.add_node("story_loader", story_loader_node)
    graph.add_node("preprocessor", preprocessor_node)
    graph.add_node("observer", observer_node)
    graph.add_node("bank_adder", bank_adder_node)
    graph.add_node("matcher", matcher_node)
    graph.add_node("critic", critic_node)
    graph.add_node("collector", collector_node)
    graph.add_node("evaluator_mid", evaluator_mid_node)
    graph.add_node("report", report_node)
    graph.add_node("curator", curator_node)

    graph.add_edge(START, "story_loader")
    graph.add_conditional_edges(
        "story_loader",
        continue_evolve,
        {"preprocessor": "preprocessor", "skip": "story_loader", "report": "report"},
    )
    graph.add_edge("preprocessor", "observer")
    graph.add_edge("observer", "bank_adder")
    graph.add_edge("bank_adder", "matcher")
    graph.add_edge("matcher", "critic")
    graph.add_edge("critic", "collector")
    graph.add_conditional_edges(
        "collector",
        check_mid,
        {"evaluator_mid": "evaluator_mid", "story_loader": "story_loader"},
    )
    graph.add_edge("evaluator_mid", "story_loader")
    graph.add_edge("report", "curator")
    graph.add_edge("curator", END)
    return graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Evolve 单图：新文本 → 提取 obs → Matcher 五分类 → 直写/Pools/报告")
    parser.add_argument("--corpus", type=str, required=True, help="新文本语料目录（含 .txt，递归收集）")
    parser.add_argument("--namespace", type=str, default="bootstrap",
                        help="Registry 命名空间（读函数库 + MATCH/EXTEND 直写目标，缺省 bootstrap）")
    parser.add_argument("--out-dir", type=str, default=None, help="输出目录（缺省 data/evolve）")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 个故事")
    parser.add_argument("--stories", type=str, default=None, help="仅处理指定文件（逗号分隔，优先于 --limit）")
    parser.add_argument("--batch-size", type=int, default=matcher_module.MATCH_BATCH_SIZE, help="Matcher 每批 obs 数")
    parser.add_argument("--top-k", type=int, default=matcher_module.TOP_K, help="每 obs 召回候选函数数")
    args = parser.parse_args()

    stories_dir = os.path.abspath(args.corpus)
    if not os.path.isdir(stories_dir):
        print(f"语料目录不存在: {stories_dir}")
        sys.exit(1)

    manifest_path = os.path.join(stories_dir, "manifest.json")
    story_meta: dict = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            for entry in json.load(f):
                story_meta[entry["txt_file"].replace("\\", "/")] = entry

    story_files = _collect_txt(stories_dir)
    if args.stories:
        wanted = [s.strip() for s in args.stories.split(",") if s.strip()]
        selected, missing = [], []
        for s in wanted:
            if s in story_files:
                selected.append(s)
            else:
                matches = [f for f in story_files if os.path.basename(f) == os.path.basename(s)]
                if matches:
                    selected.append(matches[0])
                else:
                    missing.append(s)
        story_files = selected
        if missing:
            print(f"警告: --stories 中 {len(missing)} 个文件未找到: {missing}")
    elif args.limit is not None:
        story_files = story_files[: args.limit]
    if not story_files:
        print(f"目录 {stories_dir} 中没有可处理的 .txt 文件")
        sys.exit(1)

    matcher_module.MATCH_BATCH_SIZE = args.batch_size
    matcher_module.TOP_K = args.top_k
    store = RegistryStore(namespace=args.namespace)
    set_active_store(store)
    n_funcs = store.count()
    print(f"=== Evolve 启动：函数库 namespace={args.namespace}（{n_funcs} 个 Function），"
          f"语料 {len(story_files)} 篇 ===")

    total = len(story_files)
    initial: NarrativePipelineState = {
        "messages": [],
        "raw_text": None,
        "story_config": None,
        "normalized_story": None,
        "observations": [],
        "added_obs_ids": [],
        "similar_observations": [],
        "match_decisions": [],
        "match_occurrences": [],
        "occurrences": [],
        "match_report": None,
        "obs_since_eval": 0,
        "mid_reports": [],
        "pending_evidence": [],
        "match_pending": [],
        "curator_plan": [],
        "current_story_index": 0,
        "total_stories": total,
        "story_files": story_files,
        "corpus_dir": stories_dir,
        "story_meta": story_meta,
        "errors": [],
        "namespace": args.namespace,
        "out_dir": os.path.abspath(args.out_dir) if args.out_dir else DEFAULT_OUT_DIR,
    }
    app = _build_evolve_graph().compile()
    start_time = time.time()
    result = app.invoke(initial)
    elapsed = time.time() - start_time
    report = result.get("match_report") or {}
    print(f"\n=== Evolve 完成: {elapsed:.1f}s ({elapsed / max(total, 1):.1f}s/篇) ===")
    print(f"  最终: {total} 篇 / {report.get('total_obs', 0)} obs / "
          f"coverage={report.get('coverage')} / novelty_rate={report.get('novelty_rate')}")
    if result.get("errors"):
        print(f"  失败记录 {len(result['errors'])} 条（不中断）")


if __name__ == "__main__":
    main()
