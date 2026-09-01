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
import uuid
from collections import Counter

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT_DIR = os.path.join(_ROOT, "data", "evolve")
MID_OBS_THRESHOLD = 20  # 累计处理多少个新 obs 触发一次 Evaluator_mid 周期体检（滚动重置）
_VENDOR = os.path.join(_ROOT, "vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

from langgraph.graph import StateGraph, START, END

from Agent.state import NarrativePipelineState
from Agent.app import story_loader_node, natural_key, get_bank, set_bank
from Bank.bank import ScopedObservationBank
from Agent.Pre_pro.pre_processor import preprocessor_node
from Agent.Observer.observer import observer_node
from Agent.Matcher import matcher as matcher_module
from Agent.Matcher.matcher import matcher_node
from Agent.Registry.registry import RegistryStore, set_active_store, get_active_store
from Agent.Evaluator.evaluator import evaluator_node
from Agent.Critic.critic import critic_node
from Agent.Curator.curator import curator_node
from Agent.Contract.contract import build_function_contracts
from Contracts.snapshot import DEFAULT_SNAPSHOT_ROOT, publish_snapshot
from Contracts.occurrence import align_occurrences
from KnowledgeBase import DEFAULT_DB_PATH, StoryKnowledgeStore


def _collect_txt(root: str) -> list[str]:
    """递归收集目录下全部 .txt（不限文件名模式，供新文本语料）。"""
    files = []
    for dirpath, _dirs, fns in os.walk(root):
        for fn in fns:
            if fn.endswith(".txt"):
                files.append(os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/"))
    return sorted(files, key=natural_key)


def initialize_registry_from_knowledge(
    store: RegistryStore,
    knowledge_db: str,
    base_snapshot_id: str | None = None,
) -> str:
    """用统一知识库中的正式 Snapshot 初始化本次 Evolve 工作区。"""
    knowledge = StoryKnowledgeStore(knowledge_db)
    snapshot_id = base_snapshot_id or knowledge.latest_snapshot_id()
    store.replace_all(knowledge.load_functions(snapshot_id))
    return snapshot_id


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


def evolve_bank_adder_node(state: NarrativePipelineState) -> dict:
    """暂存当前故事，并刷新“父 Snapshot + 当前 Run”Bank 视图。"""
    observations = state.get("observations", [])
    normalized = state.get("normalized_story")
    if not normalized:
        return {"added_obs_ids": []}
    staged = StoryKnowledgeStore(state["knowledge_db"]).stage_story_observations(
        state["run_id"], normalized, state.get("story_config") or {}, observations,
        state.get("current_story_index", 0) + 1,
    )
    story_id = normalized["metadata"]["story_id"]
    bank = get_bank()
    bank.replace_story(story_id, staged)
    # 旧版本 Observation 已不在本轮 Bank 视图中，不能继续作为 Function 证据。
    store = get_active_store()
    current_functions = store.load_all()
    changed = False
    for function in current_functions:
        support = function.get("supporting_obs_ids", [])
        filtered = [obs_id for obs_id in support if bank.get(obs_id) is not None]
        if filtered != support:
            function["supporting_obs_ids"] = filtered
            changed = True
    if changed:
        store.replace_all(current_functions)
    added_ids = [item["obs_id"] for item in staged]
    return {"observations": staged, "added_obs_ids": added_ids}


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
    context = dict(state.get("evaluation_context") or {})
    context["report_path"] = report_path
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
        context["registry_file"] = tmp_registry
    st["evaluation_context"] = context
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


def _load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _compare_ontologies(baseline: list[dict], final: list[dict]) -> dict:
    """演化前后对比：函数增删改、supporting/confidence 分布。"""
    def identity(function: dict) -> str:
        return str(function.get("function_id") or f"name:{function.get('function_name')}")

    base_by_id = {identity(f): f for f in baseline}
    final_by_id = {identity(f): f for f in final}
    kept = sorted(final_by_id[key].get("function_name") for key in set(base_by_id) & set(final_by_id))
    added = sorted(final_by_id[key].get("function_name") for key in set(final_by_id) - set(base_by_id))
    removed = sorted(base_by_id[key].get("function_name") for key in set(base_by_id) - set(final_by_id))

    def _dist(funcs, key, transform=lambda v: v):
        vals = [transform(f.get(key)) for f in funcs if f.get(key) is not None]
        if not vals:
            return None
        return {"mean": round(sum(vals) / len(vals), 3), "min": round(min(vals), 3), "max": round(max(vals), 3)}

    return {
        "baseline_count": len(baseline),
        "final_count": len(final),
        "kept": kept,
        "added": added,
        "removed": removed,
        "supporting": {
            "baseline": _dist(baseline, "supporting_obs_ids", len),
            "final": _dist(final, "supporting_obs_ids", len),
        },
        "confidence": {
            "baseline": _dist(baseline, "confidence"),
            "final": _dist(final, "confidence"),
        },
    }


def evaluator_final_node(state: dict) -> dict:
    """终期评估：六维终评（force_full_review）+ 演化前后对比 + 导出最终 Ontology 快照。"""
    out_dir = state.get("out_dir", DEFAULT_OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    ns = state.get("namespace", "bootstrap")
    report_path = os.path.join(out_dir, "evaluation_final.json")
    st = dict(state)
    ctx = dict(state.get("evaluation_context") or {})
    ctx["report_path"] = report_path
    st["evaluation_context"] = ctx
    st["force_full_review"] = True
    result = evaluator_node(st)
    report = result.get("evaluation_report") or {}

    final_funcs = get_active_store().load_all()
    baseline = _load_jsonl(os.path.join(out_dir, f"functions_{ns}_start.jsonl"))
    comparison = _compare_ontologies(baseline, final_funcs)
    final_report = {
        "verdict": result.get("evaluator_decision"),
        "passed_dimensions": report.get("passed_dimensions", []),
        "failed_dimensions": report.get("failed_dimensions", []),
        "dimensions": {k: {"score": d.get("score"), "pass": d.get("pass")}
                       for k, d in (report.get("dimensions") or {}).items()},
        "recommendations": report.get("recommendations", {}),
        "comparison": comparison,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(final_report, f, ensure_ascii=False, indent=2)

    get_active_store().export_jsonl(os.path.join(out_dir, f"functions_{ns}.jsonl"))
    bank = get_bank()
    _write_jsonl(os.path.join(out_dir, f"bank_{ns}.jsonl"), bank.get_all())
    print(f"[Evaluator_final] 判定: {final_report['verdict']}（达标 {len(final_report['passed_dimensions'])}/6）")
    c = comparison
    print(f"  comparison: 基线 {c['baseline_count']} → 最终 {c['final_count']} "
          f"（新增 {len(c['added'])} / 移除 {len(c['removed'])} / 保留 {len(c['kept'])}）")
    print(f"  Final Report → {report_path}")

    mr_path = os.path.join(out_dir, "match_report.json")
    if os.path.exists(mr_path):
        with open(mr_path, "r", encoding="utf-8") as f:
            mr = json.load(f)
        mr["final_evaluation"] = {
            "verdict": final_report["verdict"],
            "passed_dimensions": final_report["passed_dimensions"],
            "failed_dimensions": final_report["failed_dimensions"],
            "comparison": comparison,
        }
        with open(mr_path, "w", encoding="utf-8") as f:
            json.dump(mr, f, ensure_ascii=False, indent=2)

    observations = bank.get_all()
    final_occurrences = align_occurrences(final_funcs, observations)
    _write_jsonl(os.path.join(out_dir, "occurrences_final.jsonl"), final_occurrences)
    function_contracts = []
    if final_report.get("verdict") == "PASS":
        function_contracts = build_function_contracts(final_funcs, observations, out_dir)

    run_id = state.get("run_id")
    if not run_id:
        raise ValueError("evaluator_final_node 需要 run_id")
    snapshot_path = publish_snapshot(
        final_funcs,
        final_report,
        source_workflow="evolve",
        namespace=ns,
        snapshots_root=state.get("snapshot_root") or DEFAULT_SNAPSHOT_ROOT,
        occurrences=final_occurrences,
        function_contracts=function_contracts,
        parent_snapshot_id=state.get("base_snapshot_id"),
        run_id=run_id,
    )
    if snapshot_path:
        print(f"  OntologySnapshot → {snapshot_path}")
        knowledge_db = state.get("knowledge_db")
        if knowledge_db:
            StoryKnowledgeStore(knowledge_db).commit_function_run(snapshot_path, run_id)
            print(f"  KnowledgeBase → {knowledge_db}")
    else:
        if state.get("knowledge_db"):
            StoryKnowledgeStore(state["knowledge_db"]).fail_function_run(
                run_id, final_report,
            )
        print("  最终终评未通过，不发布 OntologySnapshot")

    return {
        "final_report": final_report,
        "occurrences": final_occurrences,
        "function_contracts": function_contracts,
        "ontology_snapshot": snapshot_path,
        "messages": [{"role": "system", "content": f"[Evaluator_final] {final_report['verdict']}（{len(final_report['passed_dimensions'])}/6）"}],
    }


def _build_evolve_graph() -> StateGraph:
    """构建 evolve_app 拓扑（条件边循环，逐篇处理）。"""
    graph = StateGraph(NarrativePipelineState)
    graph.add_node("story_loader", story_loader_node)
    graph.add_node("preprocessor", preprocessor_node)
    graph.add_node("observer", observer_node)
    graph.add_node("bank_adder", evolve_bank_adder_node)
    graph.add_node("matcher", matcher_node)
    graph.add_node("critic", critic_node)
    graph.add_node("collector", collector_node)
    graph.add_node("evaluator_mid", evaluator_mid_node)
    graph.add_node("report", report_node)
    graph.add_node("curator", curator_node)
    graph.add_node("evaluator_final", evaluator_final_node)

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
    graph.add_edge("curator", "evaluator_final")
    graph.add_edge("evaluator_final", END)
    return graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Evolve 单图：新文本 → 提取 obs → Matcher 五分类 → 直写/Pools/报告")
    parser.add_argument("--corpus", type=str, required=True, help="新文本语料目录（含 .txt，递归收集）")
    parser.add_argument("--namespace", type=str, default="evolve_work",
                        help="本次 Evolve 的可变工作命名空间")
    parser.add_argument("--base-snapshot", type=str, default=None,
                        help="基础 Snapshot ID；缺省读取统一库最新正式 Snapshot")
    parser.add_argument("--knowledge-db", type=str, default=str(DEFAULT_DB_PATH))
    parser.add_argument("--out-dir", type=str, default=None, help="输出目录（缺省 data/evolve）")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 个故事")
    parser.add_argument("--stories", type=str, default=None, help="仅处理指定文件（逗号分隔，优先于 --limit）")
    parser.add_argument("--batch-size", type=int, default=matcher_module.MATCH_BATCH_SIZE, help="Matcher 每批 obs 数")
    parser.add_argument("--top-k", type=int, default=matcher_module.TOP_K, help="每 obs 召回候选函数数")
    args = parser.parse_args()

    matcher_module.MATCH_BATCH_SIZE = args.batch_size
    matcher_module.TOP_K = args.top_k
    store = RegistryStore(namespace=args.namespace)
    set_active_store(store)
    out_dir = os.path.abspath(args.out_dir) if args.out_dir else DEFAULT_OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    base_snapshot_id = initialize_registry_from_knowledge(
        store, args.knowledge_db, args.base_snapshot,
    )
    print(f"=== Evolve 基础：KnowledgeBase Snapshot={base_snapshot_id}，Function={store.count()} ===")
    # 导出演化前基线（供 Evaluator_final 前后对比）
    store.export_jsonl(os.path.join(out_dir, f"functions_{args.namespace}_start.jsonl"))

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

    n_funcs = store.count()
    print(f"=== Evolve 启动：函数库 namespace={args.namespace}（{n_funcs} 个 Function），"
          f"语料 {len(story_files)} 篇 ===")

    total = len(story_files)
    run_id = "FR_" + uuid.uuid4().hex[:16]
    knowledge = StoryKnowledgeStore(args.knowledge_db)
    knowledge.begin_function_run(
        run_id, "evolve", args.namespace, base_snapshot_id, stories_dir,
    )
    set_bank(ScopedObservationBank(knowledge.load_run_observation_view(base_snapshot_id, run_id)))
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
        "snapshot_root": DEFAULT_SNAPSHOT_ROOT,
        "function_contracts": [],
        "ontology_snapshot": None,
        "knowledge_db": args.knowledge_db,
        "run_id": run_id,
        "base_snapshot_id": base_snapshot_id,
        "evaluation_context": {
            "manifest_path": os.path.abspath(manifest_path),
        } if os.path.exists(manifest_path) else {},
        "current_story_index": 0,
        "total_stories": total,
        "story_files": story_files,
        "corpus_dir": stories_dir,
        "story_meta": story_meta,
        "errors": [],
        "namespace": args.namespace,
        "out_dir": out_dir,
    }
    app = _build_evolve_graph().compile()
    start_time = time.time()
    try:
        result = app.invoke(initial)
    except Exception as exc:
        knowledge.fail_function_run(run_id, {"error": str(exc)})
        raise
    elapsed = time.time() - start_time
    report = result.get("match_report") or {}
    print(f"\n=== Evolve 完成: {elapsed:.1f}s ({elapsed / max(total, 1):.1f}s/篇) ===")
    print(f"  最终: {total} 篇 / {report.get('total_obs', 0)} obs / "
          f"coverage={report.get('coverage')} / novelty_rate={report.get('novelty_rate')}")
    if result.get("errors"):
        print(f"  失败记录 {len(result['errors'])} 条（不中断）")


if __name__ == "__main__":
    main()
