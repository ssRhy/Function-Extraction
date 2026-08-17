"""
Bootstrap App - 唯一编译图 bootstrap_app + CLI 入口（python -m Agent.app）

单图全流程：
  START → story_loader →[continue_extraction]→(preprocessor→observer→bank_adder→retrieval→pairs_collector→story_loader 循环)
  → cluster_node →[continue_induction]→(induce_step 循环)→ evaluator
  →[route_after_evaluator]→(revise 循环 / final_review)→[route_after_final]→ export_node → END

持久化：SqliteSaver（data/checkpoints/bootstrap-<ns>.sqlite3），thread_id=bootstrap-<ns>；
无 --resume 时 fresh（清空 Bank/Registry/checkpoint）；--resume 跳过清理、从同一 thread 续跑。

用法:
    python -m Agent.app                                        # 全量（缺省 clean 语料 120 篇）
    python -m Agent.app --limit 5                              # 试跑前 5 篇
    python -m Agent.app --stories "01_悬疑惊悚/a.txt,03_现代情感家庭/b.txt"
    python -m Agent.app --no-revise                            # 仅评估，不进入修订闭环
    python -m Agent.app --resume                               # 从 checkpoint 续跑（不清空）
    python -m Agent.app --namespace o0 --out-dir data/o0       # 自定义命名空间/快照目录
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import time


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VENDOR = os.path.join(_ROOT, "vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

from Agent.state import NarrativePipelineState
from Agent.Pre_pro.pre_processor import preprocessor_node
from Agent.Observer.observer import observer_node
from Agent.Inducer.cluster import cluster_similar_pairs, split_oversized
from Agent.Inducer import inducer as inducer_module
from Agent.Inducer.inducer import inducer_node
from Agent.Evaluator.evaluator import evaluator_node
from Agent.Evaluator import revise as revise_module
from Agent.Evaluator.revise import revise_node
from Agent.Registry.registry import RegistryStore, get_active_store, set_active_store
from Bank.bank import ObservationBank
from Retrieval.retrieval import Retriever

DEFAULT_CORPUS = "zhihu_story_subset_120_20260815_clean"
CHECKPOINT_DIR = os.path.join(_ROOT, "data", "checkpoints")


_bank_instance = None


def get_bank() -> ObservationBank:
    global _bank_instance
    if _bank_instance is None:
        _bank_instance = ObservationBank()
    return _bank_instance


def bank_adder_node(state: NarrativePipelineState) -> dict:
    """将新提取的 Observations 存入 Bank"""
    observations = state.get("observations", [])
    if not observations:
        return {"added_obs_ids": [], "messages": [{"role": "system", "content": "[BankAdder] 无 observations，跳过"}]}
    added_ids = get_bank().add(observations)
    return {"added_obs_ids": added_ids, "messages": [{"role": "system", "content": f"[BankAdder] 添加 {len(added_ids)} 条"}]}


def retrieval_node(state: NarrativePipelineState) -> dict:
    """增量检索：仅比较本轮新增 Observation 与历史 Observation。"""
    bank = get_bank()
    added_ids = state.get("added_obs_ids", [])
    if not added_ids:
        return {"similar_observations": [], "messages": [{"role": "system", "content": "[Retrieval] 无新增 Observation，跳过"}]}

    added_set = set(added_ids)
    new_observations = [obs for obs in (bank.get(obs_id) for obs_id in added_ids) if obs]
    if bank.count() <= len(new_observations):
        return {"similar_observations": [], "messages": [{"role": "system", "content": "[Retrieval] 无历史 Observation，跳过"}]}

    retriever = Retriever(bank)
    similar, seen = [], set()
    for obs in new_observations:
        for r in retriever.query_by_observation(obs, top_k=5, exclude_obs_ids=list(added_set)):
            if obs["obs_id"] == r.obs["obs_id"] or obs.get("story_id") == r.obs.get("story_id"):
                continue
            pair = tuple(sorted([obs["obs_id"], r.obs["obs_id"]]))
            if pair in seen:
                continue
            seen.add(pair)
            similar.append({"reference": obs, "retrieved": r.obs, "similarity": r.similarity})

    return {"similar_observations": similar, "messages": [{"role": "system", "content": f"[Retrieval] 新增 {len(new_observations)} 条，找到 {len(similar)} 个历史相似对"}]}


# ========== 阶段 1：逐篇提取（story 循环） ==========

def story_loader_node(state: NarrativePipelineState) -> dict:
    """加载 story_files[current_story_index]；空文件/读失败记 errors 并自增跳过。"""
    idx = state.get("current_story_index", 0)
    total = state.get("total_stories", 0)
    if idx >= total:
        return {}
    filename = state["story_files"][idx]
    path = os.path.join(state["corpus_dir"], filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_text = f.read().strip()
    except Exception:
        raw_text = ""
    if not raw_text:
        errors = list(state.get("errors", []))
        errors.append(f"[{idx + 1}/{total}] {filename}: 空文件或读取失败，跳过")
        return {
            "current_story_index": idx + 1,
            "raw_text": None,
            "story_config": None,
            "normalized_story": None,
            "observations": [],
            "added_obs_ids": [],
            "similar_observations": [],
            "errors": errors,
        }
    story_id = os.path.splitext(os.path.basename(filename))[0]
    story_config = {"source_file": filename, "story_id": story_id}
    meta = state.get("story_meta") or {}
    if filename in meta:
        story_config["story_type"] = meta[filename].get("category")
        story_config["title"] = meta[filename].get("question_title")
    tag = f" [{story_config['story_type']}]" if story_config.get("story_type") else ""
    print(f"[{idx + 1}/{total}] {filename} (ID={story_id}{tag}, {len(raw_text)} 字)")
    return {
        "raw_text": raw_text,
        "story_config": story_config,
        "normalized_story": None,
        "observations": [],
        "added_obs_ids": [],
        "similar_observations": [],
    }


def continue_extraction(state: NarrativePipelineState) -> str:
    """story_loader 后路由：全部处理完 → cluster；有当前故事 → preprocessor；空文件已跳过 → 继续 loader。"""
    if state.get("current_story_index", 0) >= state.get("total_stories", 0):
        return "cluster"
    if state.get("raw_text"):
        return "preprocessor"
    return "skip"


def pairs_collector_node(state: NarrativePipelineState) -> dict:
    """累计相似对（存 obs_id 三元组，避免 checkpoint 随全量 obs 膨胀）、打印逐篇摘要、推进 story 下标。"""
    all_pairs = list(state.get("all_pairs", []))
    all_pairs.extend({
        "ref_obs_id": p["reference"]["obs_id"],
        "ret_obs_id": p["retrieved"]["obs_id"],
        "similarity": p["similarity"],
    } for p in state.get("similar_observations", []))
    ns = state.get("normalized_story") or {}
    print(f"  → 句子={len(ns.get('sentences', []))}, obs={len(state.get('observations', []))}, "
          f"新增={len(state.get('added_obs_ids', []))}, "
          f"相似对={len(state.get('similar_observations', []))}, Function=0")
    return {
        "all_pairs": all_pairs,
        "current_story_index": state.get("current_story_index", 0) + 1,
        "raw_text": None,
        "story_config": None,
        "normalized_story": None,
        "observations": [],
        "added_obs_ids": [],
        "similar_observations": [],
    }


# ========== 阶段 2：跨题材统一聚类归纳 ==========

def cluster_node(state: NarrativePipelineState) -> dict:
    """相似对聚类 → 拆超大分量 → 过滤 <2 故事分量。"""
    bank = get_bank()
    full_pairs = []
    for pair in state.get("all_pairs", []):
        ref = bank.get(pair["ref_obs_id"])
        ret = bank.get(pair["ret_obs_id"])
        if ref is not None and ret is not None:
            full_pairs.append({"reference": ref, "retrieved": ret, "similarity": pair["similarity"]})
    components = []
    for component in cluster_similar_pairs(full_pairs):
        for sub in split_oversized(component):
            stories = {p["reference"]["story_id"] for p in sub} | {p["retrieved"]["story_id"] for p in sub}
            if len(stories) >= 2:
                components.append(sub)
    print(f"  相似对 {len(full_pairs)} 条 → {len(components)} 个可归纳分量（≥2 故事）")
    return {"induction_components": components, "induction_index": 0}


def continue_induction(state: NarrativePipelineState) -> str:
    """cluster / induce_step 后路由：还有分量 → induce_step；否则 → evaluator。"""
    if state.get("induction_index", 0) >= len(state.get("induction_components", [])):
        return "evaluator"
    return "induce_step"


def induce_step_node(state: NarrativePipelineState) -> dict:
    """对单个分量调用 inducer_node（复用现有归纳/算分/upsert），推进分量下标。"""
    idx = state.get("induction_index", 0)
    sub = state["induction_components"][idx]
    stories = {p["reference"]["story_id"] for p in sub} | {p["retrieved"]["story_id"] for p in sub}
    n_obs = len({p["reference"]["obs_id"] for p in sub} | {p["retrieved"]["obs_id"] for p in sub})
    print(f"\n[批后归纳] {n_obs} obs / {len(stories)} 故事 / {len(sub)} 对")
    errors = list(state.get("errors", []))
    written = []
    try:
        written = inducer_node({"similar_observations": sub}).get("induced_functions", [])
        print(f"  → 写入 {len(written)} 个 Function")
    except Exception as e:
        errors.append(f"分量归纳失败（{n_obs} obs / {len(stories)} 故事）: {e}")
        print(f"  ✗ 分量归纳失败: {e}")
    return {"induction_index": idx + 1, "induced_functions": written, "errors": errors}


# ========== 阶段 3：六维评估 + 修订闭环 ==========

_ACTIONABLE_KEYS = (
    "merge_groups",
    "revise_definitions",
    "genre_bound_functions",
    "granularity_issues",
    "weak_fit_obs",
    "low_evidence_functions",
)


def _has_actionable_issues(report) -> bool:
    """报告里还有可执行的修订动作（近义组/待修订/题材绑定/粒度/weak-fit/低证据）。"""
    if not report:
        return False
    rec = report.get("recommendations") or {}
    return any(rec.get(k) for k in _ACTIONABLE_KEYS)


def route_after_evaluator(state: NarrativePipelineState) -> str:
    """evaluator 后路由：no_revise / 达轮数上限 / PASS 且无问题 → final_review；否则 revise。"""
    if state.get("no_revise"):
        return "final_review"
    if state.get("evaluation_round", 0) >= revise_module.MAX_EVAL_ROUNDS:
        return "final_review"
    if state.get("evaluator_decision") == "FAIL":
        return "revise"
    if _has_actionable_issues(state.get("evaluation_report")):
        return "revise"
    return "final_review"


def route_after_final(state: NarrativePipelineState) -> str:
    """final_review 后路由：no_revise / 达上限 / PASS 且无问题 → export；否则再修订。"""
    if state.get("no_revise"):
        return "export"
    if state.get("evaluation_round", 0) >= revise_module.MAX_EVAL_ROUNDS:
        return "export"
    if state.get("evaluator_decision") == "FAIL":
        return "revise"
    if _has_actionable_issues(state.get("evaluation_report")):
        return "revise"
    return "export"


def final_review_node(state: NarrativePipelineState) -> dict:
    """最终评估轮：强制全新全量 Abstraction 复核（不增量复用），保证判定基于真实测量。"""
    st = dict(state)
    st["force_full_review"] = True
    return evaluator_node(st)


# ========== 收尾：快照导出 ==========

def _discard_set(report, funcs) -> set:
    """final_review 标记的不达标函数名集合（merge 组保留支持证据最多者）。"""
    rec = (report or {}).get("recommendations") or {}
    discard = set()
    for e in rec.get("revise_definitions", []):
        discard.add(e.get("function_name"))
    for e in rec.get("genre_bound_functions", []):
        discard.add(e.get("function_name"))
    for cat in ("too_specific", "too_broad"):
        discard.update(rec.get("granularity_issues", {}).get(cat, []))
    for e in rec.get("low_evidence_functions", []):
        discard.add(e.get("function_name"))
    by_name = {f.get("function_name"): f for f in funcs}
    for group in rec.get("merge_groups", []):
        members = [n for n in group if n in by_name]
        if len(members) >= 2:
            def _key(n):
                f = by_name[n]
                return (len(f.get("supporting_obs_ids", [])), f.get("confidence", 0.0), n)
            best = max(members, key=_key)
            discard.update(m for m in members if m != best)
    return {n for n in discard if n in by_name}


def export_node(state: NarrativePipelineState) -> dict:
    """收尾节点：按 final_review 报告逐函数舍弃标记函数，幸存者导出为 O_0（无幸存者 → discarded）。"""
    store = get_active_store()
    ns = state.get("namespace", "bootstrap")
    out_dir = state.get("out_dir", "data/bootstrap")
    funcs = store.load_all()
    discard_names = _discard_set(state.get("evaluation_report"), funcs)
    removed = [f for f in funcs if f.get("function_name") in discard_names]
    survivors = [f for f in funcs if f.get("function_name") not in discard_names]
    store.replace_all(survivors)
    if removed:
        os.makedirs(out_dir, exist_ok=True)
        dst_d = os.path.join(out_dir, f"discarded_{ns}.jsonl")
        with open(dst_d, "w", encoding="utf-8") as f:
            for func in removed:
                f.write(json.dumps(func, ensure_ascii=False) + "\n")
        print(f"=== 逐函数舍弃 {len(removed)} 个：{', '.join(sorted(r['function_name'] for r in removed))} ===")
        print(f"  被舍弃函数已留档 → {dst_d}")
    if not survivors:
        print(f"=== 无达标函数，O_0 为空（命名空间 {ns} 已清空，未导出快照）===")
        return {
            "discarded": True,
            "messages": [{"role": "system", "content": "[Finalize] 无达标函数，O_0 为空"}],
        }
    print("=== Registry 统计 ===")
    print(f"  共写入 Function: {len(survivors)}")
    for rec in survivors[:5]:
        print(f"    - {rec.get('function_name', 'N/A')} "
              f"(conf={rec.get('confidence', 0):.3f}, "
              f"supporting={len(rec.get('supporting_obs_ids', []))})")
    if len(survivors) > 5:
        print(f"    ... 还有 {len(survivors) - 5} 条")
    os.makedirs(out_dir, exist_ok=True)
    dst_f = os.path.join(out_dir, f"functions_{ns}.jsonl")
    dst_b = os.path.join(out_dir, f"bank_{ns}.jsonl")
    store.export_jsonl(dst_f)
    print(f"  快照 Registry → {dst_f}（{store.count()} 条）")
    if _bank_instance is not None:
        if os.path.exists(_bank_instance.jsonl_path):
            shutil.copyfile(_bank_instance.jsonl_path, dst_b)
            print(f"  快照 Bank → {dst_b}")
        print(f"\nBank 总 obs 数: {_bank_instance.count()}")
    print(f"全部 {state.get('total_stories', 0)} 个故事处理完成")
    return {}


# ========== 图构建 ==========

def _build_bootstrap_graph() -> StateGraph:
    """构建 bootstrap_app 拓扑（不编译，便于测试用临时 checkpointer 编译）。"""
    graph = StateGraph(NarrativePipelineState)
    graph.add_node("story_loader", story_loader_node)
    graph.add_node("preprocessor", preprocessor_node)
    graph.add_node("observer", observer_node)
    graph.add_node("bank_adder", bank_adder_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("pairs_collector", pairs_collector_node)
    graph.add_node("cluster", cluster_node)
    graph.add_node("induce_step", induce_step_node)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("final_review", final_review_node)
    graph.add_node("revise", revise_node)
    graph.add_node("export", export_node)

    graph.add_edge(START, "story_loader")
    graph.add_conditional_edges(
        "story_loader",
        continue_extraction,
        {"preprocessor": "preprocessor", "skip": "story_loader", "cluster": "cluster"},
    )
    graph.add_edge("preprocessor", "observer")
    graph.add_edge("observer", "bank_adder")
    graph.add_edge("bank_adder", "retrieval")
    graph.add_edge("retrieval", "pairs_collector")
    graph.add_edge("pairs_collector", "story_loader")

    graph.add_conditional_edges(
        "cluster",
        continue_induction,
        {"induce_step": "induce_step", "evaluator": "evaluator"},
    )
    graph.add_conditional_edges(
        "induce_step",
        continue_induction,
        {"induce_step": "induce_step", "evaluator": "evaluator"},
    )

    graph.add_conditional_edges(
        "evaluator",
        route_after_evaluator,
        {"revise": "revise", "final_review": "final_review"},
    )
    graph.add_edge("revise", "evaluator")
    graph.add_conditional_edges(
        "final_review",
        route_after_final,
        {"revise": "revise", "export": "export"},
    )
    graph.add_edge("export", END)
    return graph


def _make_checkpointer(db_path: str) -> SqliteSaver:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    saver = SqliteSaver(sqlite3.connect(db_path, check_same_thread=False))
    saver.setup()
    return saver


def _new_app(namespace: str):
    """按命名空间编译 bootstrap_app（checkpoint DB 隔离：data/checkpoints/bootstrap-<ns>.sqlite3）。"""
    db_path = os.path.join(CHECKPOINT_DIR, f"bootstrap-{namespace}.sqlite3")
    return _build_bootstrap_graph().compile(checkpointer=_make_checkpointer(db_path))


# ========== CLI（python -m Agent.app） ==========

def natural_key(name: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def collect_story_files(root: str, recursive: bool) -> list[str]:
    """corpus 模式递归收集 <answer_id>_<question_id>.txt，否则取目录顶层 .txt"""
    if recursive:
        files = []
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if re.fullmatch(r"\d+_\d+\.txt", fn):
                    files.append(os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/"))
    else:
        files = [f for f in os.listdir(root) if f.endswith(".txt")]
    return sorted(files, key=natural_key)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap 单图全流程：全量提取 → 统一归纳 → 评估修订 → 快照")
    parser.add_argument("--corpus", type=str, default=None, help=f"语料目录（缺省 = 仓库下 {DEFAULT_CORPUS}）")
    parser.add_argument("--namespace", type=str, default="bootstrap", help="Registry 命名空间（缺省 bootstrap）")
    parser.add_argument("--out-dir", type=str, default=None, help="快照输出目录（缺省 data/bootstrap）")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 个故事（未指定 --stories 时生效）")
    parser.add_argument("--stories", type=str, default=None, help="仅处理指定文件（逗号分隔，相对语料路径），优先于 --limit")
    parser.add_argument("--no-revise", action="store_true", help="仅评估，不进入修订闭环")
    parser.add_argument("--resume", action="store_true", help="跳过清空，从同一 checkpoint 续跑")
    args = parser.parse_args()

    stories_dir = os.path.abspath(args.corpus) if args.corpus else os.path.join(_ROOT, DEFAULT_CORPUS)
    if not os.path.isdir(stories_dir):
        print(f"语料目录不存在: {stories_dir}")
        print(f"请用 --corpus 指定语料目录，或先用 clean_corpus.py 生成缺省语料 {DEFAULT_CORPUS}。")
        sys.exit(1)

    manifest_path = os.path.join(stories_dir, "manifest.json")
    corpus_mode = args.corpus is not None or os.path.exists(manifest_path)
    story_meta: dict = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            for entry in json.load(f):
                story_meta[entry["txt_file"].replace("\\", "/")] = entry

    story_files = collect_story_files(stories_dir, corpus_mode)
    if args.stories:
        # 支持相对路径或纯文件名（文件名便于命令行直接传参，避开中文路径编码问题）
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

    bank = get_bank()
    registry_store = RegistryStore(namespace=args.namespace)
    set_active_store(registry_store)
    inducer_module.APPLY_CONFUSABLE = False  # bootstrap 豁免 confusable 软惩罚（近义由 Registry 硬去重处理）

    app = _new_app(args.namespace)
    thread_id = f"bootstrap-{args.namespace}"
    if args.resume:
        if app.checkpointer.get_tuple({"configurable": {"thread_id": thread_id}}) is None:
            print(f"--resume：thread {thread_id} 无 checkpoint，请先运行完整流程（不带 --resume）。")
            sys.exit(1)
        print(f"=== --resume：跳过清理，从 checkpoint 续跑（{thread_id}） ===")
    else:
        print("=== 清理 Bank / Registry / Checkpoint ===")
        bank.clear()
        registry_store.clear()
        app.checkpointer.delete_thread(thread_id)
        print(f"  清空 Registry 命名空间: {args.namespace}（DB: {registry_store.db_path}）")
        print(f"  Bank 已清空 (count={bank.count()})")
    print()

    evaluation_context: dict = {}
    if os.path.exists(manifest_path):
        evaluation_context["manifest_path"] = os.path.abspath(manifest_path)

    total = len(story_files)
    print(f"发现 {total} 个故事文件，开始批量处理...\n")
    start_time = time.time()
    if args.resume:
        result = app.invoke({"messages": []}, config={"configurable": {"thread_id": thread_id}})
    else:
        initial: NarrativePipelineState = {
            "messages": [],
            "raw_text": None,
            "story_config": None,
            "normalized_story": None,
            "observations": [],
            "added_obs_ids": [],
            "similar_observations": [],
            "induced_functions": [],
            "evaluation_round": 0,
            "current_story_index": 0,
            "total_stories": total,
            "story_files": story_files,
            "corpus_dir": stories_dir,
            "story_meta": story_meta,
            "all_pairs": [],
            "induction_components": [],
            "induction_index": 0,
            "errors": [],
            "no_revise": args.no_revise,
            "namespace": args.namespace,
            "out_dir": os.path.abspath(args.out_dir) if args.out_dir else os.path.join(_ROOT, "data", "bootstrap"),
            "evaluation_context": evaluation_context,
        }
        result = app.invoke(initial, config={"configurable": {"thread_id": thread_id}})
    elapsed = time.time() - start_time

    decision = result.get("evaluator_decision")
    report = result.get("evaluation_report", {})
    rev = result.get("revise_report") or {}
    print(f"判定: {decision}（达标 {len(report.get('passed_dimensions', []))}/6，修订轮数 {result.get('evaluation_round', 0)}）")
    if decision == "FAIL":
        print("建议清单:")
        for k, v in report.get("recommendations", {}).items():
            print(f"  - {k}: {v}")
    if rev.get("merged") or rev.get("revised") or rev.get("split") or rev.get("removed"):
        print(f"修订动作: 合并 {len(rev.get('merged', []))} / 修订 {len(rev.get('revised', []))} "
              f"/ 拆分 {len(rev.get('split', []))} / 移除 {len(rev.get('removed', []))}（备份 {rev.get('backup', 'N/A')}）")
    print(f"=== 运行耗时: {elapsed:.1f} 秒 ({elapsed / max(total, 1):.1f} 秒/篇) ===")
    if result.get("discarded"):
        print("=== 无达标函数，O_0 为空，未导出快照 ===")
        sys.exit(1)


if __name__ == "__main__":
    main()
