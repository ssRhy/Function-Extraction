"""
统一全流程 Agent：一次运行完成 Bootstrap 全流程（唯一推荐入口）。

流程：
  清空 Bank/Registry → 阶段1 全量提取 obs（extract_app，逐篇入库并累计跨故事相似对）
  → 阶段2 跨题材统一聚类归纳（cluster + inducer，≥2 故事分量）
  → 阶段3 六维评估 + 自动修订闭环（curate_app）→ 单一命名空间 + 快照。

不再按题材分批、也不再需要并集合并：跨题材 obs 直接一起归纳，函数天然题材无关。

用法:
    python run_bootstrap.py                                     # 全量（缺省 clean 语料 120 篇）
    python run_bootstrap.py --limit 5                           # 试跑前 5 篇
    python run_bootstrap.py --stories "01_悬疑惊悚/a.txt,03_现代情感家庭/b.txt"
    python run_bootstrap.py --no-revise                         # 仅评估，不进入修订闭环
    python run_bootstrap.py --namespace o0 --out-dir data/o0    # 自定义命名空间/快照目录
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from Agent.state import NarrativePipelineState
from Agent.app import extract_app, get_bank
from Agent.Inducer.cluster import cluster_similar_pairs, split_oversized
from Agent.Inducer import inducer as inducer_module
from Agent.Registry.registry import RegistryStore, set_active_store

DEFAULT_CORPUS = "zhihu_story_subset_120_20260815_clean"

parser = argparse.ArgumentParser(description="Bootstrap 统一全流程：全量提取 → 统一归纳 → 评估修订 → 单一命名空间")
parser.add_argument("--corpus", type=str, default=None, help=f"语料目录（缺省 = 仓库下 {DEFAULT_CORPUS}）")
parser.add_argument("--namespace", type=str, default="bootstrap", help="Registry 命名空间（缺省 bootstrap）")
parser.add_argument("--out-dir", type=str, default="data/bootstrap", help="快照输出目录（缺省 data/bootstrap）")
parser.add_argument("--limit", type=int, default=None, help="只处理前 N 个故事（未指定 --stories 时生效）")
parser.add_argument("--stories", type=str, default=None, help="仅处理指定文件（逗号分隔，相对语料路径），优先于 --limit")
parser.add_argument("--no-revise", action="store_true", help="仅评估，不进入修订闭环")
parser.add_argument("--evaluate-only", action="store_true", help="仅评估现有快照（不清空/不提取/不归纳/不修订）")
parser.add_argument("--curate-only", action="store_true", help="在现有命名空间上跑评估+修订闭环（不清空/不提取/不归纳）")
args = parser.parse_args()


def natural_key(name: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def _print_dimensions(report: dict) -> None:
    for name, d in report.get("dimensions", {}).items():
        extra = ""
        if name == "coverage":
            extra = f" (covered={d.get('covered_obs')}/{d.get('total_obs')})"
        elif name == "evidence_count":
            extra = f" (mean_stories={d.get('mean_stories')}, mean_obs={d.get('mean_obs')})"
        elif name == "diversity":
            extra = f" (categories={d.get('categories')}, stories={d.get('stories')})"
        print(f"    {name}: score={d.get('score')} pass={d.get('pass')}{extra}")


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


# ---- 语料与 manifest ----
root = os.path.dirname(os.path.abspath(__file__))
stories_dir = args.corpus if args.corpus else os.path.join(root, DEFAULT_CORPUS)
if not os.path.isdir(stories_dir):
    print(f"语料目录不存在: {stories_dir}")
    print(f"请用 --corpus 指定语料目录，或先用 clean_corpus.py 生成缺省语料 {DEFAULT_CORPUS}。")
    sys.exit(1)

manifest_path = os.path.join(stories_dir, "manifest.json")
corpus_mode = args.corpus is not None or os.path.exists(manifest_path)
manifest: dict = {}
if os.path.exists(manifest_path):
    with open(manifest_path, "r", encoding="utf-8") as f:
        for entry in json.load(f):
            manifest[entry["txt_file"].replace("\\", "/")] = entry

# ---- --evaluate-only：非破坏性评估现有快照（不清空/不提取/不归纳/不修订） ----
if args.evaluate_only:
    from Agent.Evaluator.evaluator import evaluator_node

    dst_f = os.path.join(args.out_dir, f"functions_{args.namespace}.jsonl")
    dst_b = os.path.join(args.out_dir, f"bank_{args.namespace}.jsonl")
    if not os.path.exists(dst_f):
        print(f"快照不存在: {dst_f}（请先运行完整流程生成快照）")
        sys.exit(1)
    eval_context: dict = {"registry_file": os.path.abspath(dst_f), "bank_file": os.path.abspath(dst_b)}
    if os.path.exists(manifest_path):
        eval_context["manifest_path"] = os.path.abspath(manifest_path)
    result = evaluator_node({"messages": [], "evaluation_context": eval_context})
    decision = result.get("evaluator_decision")
    report = result.get("evaluation_report", {})
    print(f"判定: {decision}（达标 {len(report.get('passed_dimensions', []))}/6）")
    _print_dimensions(report)
    print("评估报告: data/evaluation/evaluation_report.json")
    sys.exit(0)

# ---- --curate-only：在现有命名空间上跑评估+修订闭环（不清空/不提取/不归纳） ----
if args.curate_only:
    from Agent.app import curate_app

    registry_store = RegistryStore(namespace=args.namespace)
    if registry_store.count() == 0:
        print(f"命名空间 {args.namespace} 为空，请先运行完整流程（run_bootstrap.py）生成 O_0")
        sys.exit(1)
    set_active_store(registry_store)
    eval_context: dict = {}
    if os.path.exists(manifest_path):
        eval_context["manifest_path"] = os.path.abspath(manifest_path)
    result = curate_app.invoke(
        {"messages": [], "evaluation_context": eval_context, "evaluation_round": 0},
        config={"configurable": {"thread_id": f"curate-only-{args.namespace}"}},
    )
    decision = result.get("evaluator_decision")
    report = result.get("evaluation_report", {})
    rev = result.get("revise_report") or {}
    print(f"判定: {decision}（达标 {len(report.get('passed_dimensions', []))}/6，修订轮数 {result.get('evaluation_round', 0)}）")
    _print_dimensions(report)
    if rev.get("merged") or rev.get("revised") or rev.get("split") or rev.get("removed"):
        print(f"修订动作: 合并 {len(rev.get('merged', []))} / 修订 {len(rev.get('revised', []))} "
              f"/ 拆分 {len(rev.get('split', []))} / 移除 {len(rev.get('removed', []))}")
    os.makedirs(args.out_dir, exist_ok=True)
    dst_f = os.path.join(args.out_dir, f"functions_{args.namespace}.jsonl")
    registry_store.export_jsonl(dst_f)
    print(f"快照已同步 → {dst_f}（{registry_store.count()} 条）")
    sys.exit(0)

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

# ---- 清空 Bank / Registry（只清本命名空间，保留其他历史命名空间） ----
print("=== 清理 Bank / Registry ===")
bank = get_bank()
bank.clear()
registry_store = RegistryStore(namespace=args.namespace)
registry_store.clear()
set_active_store(registry_store)
print(f"  清空 Registry 命名空间: {args.namespace}（DB: {registry_store.db_path}）")
print(f"  Bank 已清空 (count={bank.count()})")
print()

# bootstrap 阶段豁免 confusable 软惩罚（近义由 Registry 硬去重处理）
inducer_module.APPLY_CONFUSABLE = False

total = len(story_files)
start_time = time.time()
print(f"发现 {total} 个故事文件，开始批量处理...\n")

# ---- 阶段 1：逐篇提取 obs（extract_app，Function=0），累计跨故事相似对 ----
all_pairs: list[dict] = []
for idx, filename in enumerate(story_files, start=1):
    path = os.path.join(stories_dir, filename)
    with open(path, "r", encoding="utf-8") as f:
        raw_text = f.read().strip()
    if not raw_text:
        print(f"[{idx}/{total}] {filename}: 空文件，跳过")
        continue

    story_id = os.path.splitext(os.path.basename(filename))[0]
    tag = f" [{manifest[filename]['category']}]" if filename in manifest else ""
    print(f"[{idx}/{total}] {filename} (ID={story_id}{tag}, {len(raw_text)} 字)")

    story_config = {"source_file": filename, "story_id": story_id}
    if filename in manifest:
        story_config["story_type"] = manifest[filename]["category"]
        story_config["title"] = manifest[filename]["question_title"]

    initial_state: NarrativePipelineState = {
        "messages": [],
        "raw_text": raw_text,
        "story_config": story_config,
        "normalized_story": None,
        "observations": [],
        "added_obs_ids": [],
        "similar_observations": [],
        "induced_functions": [],
        "current_story_index": idx,
        "total_stories": total,
    }
    try:
        result = extract_app.invoke(
            initial_state,
            config={"configurable": {"thread_id": f"batch-{idx}"}},
        )
        all_pairs.extend(result["similar_observations"])
        print(
            f"  → 句子={len(result['normalized_story']['sentences'])}, "
            f"obs={len(result['observations'])}, "
            f"新增={len(result['added_obs_ids'])}, "
            f"相似对={len(result['similar_observations'])}, Function=0"
        )
    except Exception as e:
        print(f"  ✗ 失败: {e}")
    print()

# ---- 阶段 2：跨题材统一聚类归纳 ----
print("=== 阶段 2: 跨题材统一归纳 ===")
induced_batch = []
components = cluster_similar_pairs(all_pairs)
print(f"  相似对 {len(all_pairs)} 条 → {len(components)} 个分量")
for component in components:
    for sub in split_oversized(component):
        stories = {p["reference"]["story_id"] for p in sub} | {p["retrieved"]["story_id"] for p in sub}
        if len(stories) < 2:
            continue
        n_obs = len({p["reference"]["obs_id"] for p in sub} | {p["retrieved"]["obs_id"] for p in sub})
        print(f"\n[批后归纳] {n_obs} obs / {len(stories)} 故事 / {len(sub)} 对")
        try:
            res = inducer_module.inducer_node({"similar_observations": sub})
            written = res.get("induced_functions", [])
            induced_batch.extend(written)
            print(f"  → 写入 {len(written)} 个 Function")
        except Exception as e:
            print(f"  ✗ 分量归纳失败: {e}")
print(f"阶段 2 共写入 {len(induced_batch)} 个 Function")

# ---- 阶段 3：六维评估 + 自动修订闭环（--no-revise 仅评估） ----
print("\n=== Evaluator_v0: 批后六维评估" + ("" if args.no_revise else " + 自动修订闭环") + " ===")
eval_context: dict = {}
if os.path.exists(manifest_path):
    eval_context["manifest_path"] = os.path.abspath(manifest_path)
try:
    if args.no_revise:
        from Agent.Evaluator.evaluator import evaluator_node
        result = evaluator_node({"messages": [], "evaluation_context": eval_context})
    else:
        from Agent.app import curate_app
        result = curate_app.invoke(
            {"messages": [], "evaluation_context": eval_context, "evaluation_round": 0},
            config={"configurable": {"thread_id": "curate-batch"}},
        )
    decision = result.get("evaluator_decision")
    report = result.get("evaluation_report", {})
    rev = result.get("revise_report") or {}
    print(f"判定: {decision}（达标 {len(report.get('passed_dimensions', []))}/6，修订轮数 {result.get('evaluation_round', 0)}）")
    for name, d in report.get("dimensions", {}).items():
        extra = ""
        if name == "coverage":
            extra = f" (covered={d.get('covered_obs')}/{d.get('total_obs')})"
        elif name == "evidence_count":
            extra = f" (mean_stories={d.get('mean_stories')}, mean_obs={d.get('mean_obs')})"
        elif name == "diversity":
            extra = f" (categories={d.get('categories')}, stories={d.get('stories')})"
        print(f"    {name}: score={d.get('score')} pass={d.get('pass')}{extra}")
    if decision == "FAIL":
        print("建议清单:")
        for k, v in report.get("recommendations", {}).items():
            print(f"  - {k}: {v}")
    if rev.get("merged") or rev.get("revised") or rev.get("split") or rev.get("removed"):
        print(f"修订动作: 合并 {len(rev.get('merged', []))} / 修订 {len(rev.get('revised', []))} "
              f"/ 拆分 {len(rev.get('split', []))} / 移除 {len(rev.get('removed', []))}（备份 {rev.get('backup', 'N/A')}）")
except Exception as e:
    print(f"  ✗ Evaluator 评估失败: {e}")

elapsed = time.time() - start_time
print(f"=== 运行耗时: {elapsed:.1f} 秒 ({elapsed / max(total, 1):.1f} 秒/篇) ===")

# ---- 收尾：Registry 统计 + 快照 ----
print("=== Registry 统计 ===")
funcs = registry_store.load_all()
if funcs:
    print(f"  共写入 Function: {len(funcs)}")
    for rec in funcs[:5]:
        print(f"    - {rec.get('function_name', 'N/A')} "
              f"(conf={rec.get('confidence', 0):.3f}, "
              f"supporting={len(rec.get('supporting_obs_ids', []))})")
    if len(funcs) > 5:
        print(f"    ... 还有 {len(funcs) - 5} 条")
else:
    print("  命名空间为空")

os.makedirs(args.out_dir, exist_ok=True)
dst_f = os.path.join(args.out_dir, f"functions_{args.namespace}.jsonl")
dst_b = os.path.join(args.out_dir, f"bank_{args.namespace}.jsonl")
registry_store.export_jsonl(dst_f)
print(f"  快照 Registry → {dst_f}（{registry_store.count()} 条）")
if os.path.exists(bank.jsonl_path):
    shutil.copyfile(bank.jsonl_path, dst_b)
    print(f"  快照 Bank → {dst_b}")

print(f"\nBank 总 obs 数: {bank.count()}")
print(f"全部 {total} 个故事处理完成")
