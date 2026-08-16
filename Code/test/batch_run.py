"""
批量运行：从 stories/ 目录（或 --corpus 指定的语料目录）读取 .txt 文件，逐个运行 Pipeline
启动前清空 Bank 和 Registry。

用法:
    python test/batch_run.py            # 处理 test/stories/ 全部故事
    python test/batch_run.py --limit 10 # 只处理前 10 个（按自然序）
    python test/batch_run.py --corpus zhihu_story_subset_120_20260815 --limit 5
    python test/batch_run.py --corpus zhihu_story_subset_120_20260815 \
        --stories "01_悬疑惊悚/xxx.txt,02_古风穿越重生/yyy.txt,03_现代情感家庭/zzz.txt"
    python test/batch_run.py --corpus zhihu_story_subset_120_20260815 \
        --genre 01_悬疑惊悚 --batch-induction --out-dir data/genre_functions
"""
import sys, os, json, time, re, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Agent.state import NarrativePipelineState
from Agent.app import pipeline_app, extract_app, get_bank
from Agent.Inducer.cluster import cluster_similar_pairs, split_oversized
from Agent.Inducer import inducer as inducer_module

parser = argparse.ArgumentParser()
parser.add_argument("--limit", type=int, default=None, help="只处理前 N 个故事（未指定 --stories 时生效）")
parser.add_argument("--corpus", type=str, default=None, help="语料目录：递归收集 <answer_id>_<question_id>.txt")
parser.add_argument("--stories", type=str, default=None, help="仅处理指定文件（逗号分隔，相对语料/目录路径），优先于 --limit")
parser.add_argument("--genre", type=str, default=None, help="仅处理指定题材（manifest category，即语料顶层目录名）")
parser.add_argument("--batch-induction", action="store_true", help="批后统一归纳：先逐篇提取 obs，全部入库后统一归纳一次")
parser.add_argument("--out-dir", type=str, default=None, help="跑完后把 Registry/Bank 快照到该目录")
args = parser.parse_args()

stories_dir = args.corpus or os.path.join(os.path.dirname(__file__), "stories")
if not os.path.exists(stories_dir):
    os.makedirs(stories_dir)
    print(f"已创建目录: {stories_dir}")
    print("请把 .txt 文件放入此目录后重跑。")
    sys.exit(0)

# 1. 清空 Bank 和 Registry
print("=== 清理 Bank / Registry ===")
bank = get_bank()
bank.clear()
if os.path.exists(inducer_module._REGISTRY_FILE):
    os.remove(inducer_module._REGISTRY_FILE)
    print(f"  删除 Registry: {inducer_module._REGISTRY_FILE}")
print(f"  Bank 已清空 (count={bank.count()})")
print()

# bootstrap 阶段豁免 confusable 软惩罚（近义由 Registry 硬去重处理）
inducer_module.APPLY_CONFUSABLE = False


def natural_key(name: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def collect_story_files(root: str) -> list[str]:
    """收集 .txt：corpus 模式递归收集 <answer_id>_<question_id>.txt，否则取目录顶层 .txt"""
    if args.corpus:
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            for fn in filenames:
                if re.fullmatch(r"\d+_\d+\.txt", fn):
                    # 统一用正斜杠，与 manifest.txt_file 一致（Windows 下 relpath 是反斜杠）
                    files.append(os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/"))
    else:
        files = [f for f in os.listdir(root) if f.endswith(".txt")]
    return sorted(files, key=natural_key)


# 语料 manifest（若有）：提供 category / question_title 元数据
manifest = {}
manifest_path = os.path.join(stories_dir, "manifest.json")
if args.corpus and os.path.exists(manifest_path):
    with open(manifest_path, "r", encoding="utf-8") as f:
        for entry in json.load(f):
            # 归一化分隔符，避免 Windows 反斜杠 vs manifest 正斜杠不一致
            manifest[entry["txt_file"].replace("\\", "/")] = entry

story_files = collect_story_files(stories_dir)
if args.genre and args.corpus:
    prefix = args.genre.replace("\\", "/").rstrip("/") + "/"
    story_files = [f for f in story_files if f.startswith(prefix)]
    if not story_files:
        print(f"警告: 题材 {args.genre} 下没有可处理的 .txt 文件")
        sys.exit(0)
    print(f"题材过滤: {args.genre} → {len(story_files)} 篇")
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
    sys.exit(0)

total = len(story_files)
start_time = time.time()
print(f"发现 {total} 个故事文件，开始批量处理...\n")

app = extract_app if args.batch_induction else pipeline_app
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

    config = {"configurable": {"thread_id": f"batch-{idx}"}}

    try:
        result = app.invoke(initial_state, config=config)
        if args.batch_induction:
            all_pairs.extend(result["similar_observations"])
        print(
            f"  → 句子={len(result['normalized_story']['sentences'])}, "
            f"obs={len(result['observations'])}, "
            f"新增={len(result['added_obs_ids'])}, "
            f"相似对={len(result['similar_observations'])}, "
            f"Function={len(result['induced_functions'])}"
        )
    except Exception as e:
        print(f"  ✗ 失败: {e}")

    print()

# 阶段 2（--batch-induction）：把全部跨故事相似对聚类后统一归纳
if args.batch_induction:
    print("=== 阶段 2: 批后统一归纳 ===")
    induced_batch = []
    components = cluster_similar_pairs(all_pairs)
    print(f"  相似对 {len(all_pairs)} 条 → {len(components)} 个分量")
    for component in components:
        for sub in split_oversized(component):
            stories = {
                p["reference"]["story_id"] for p in sub
            } | {p["retrieved"]["story_id"] for p in sub}
            if len(stories) < 2:
                continue
            n_obs = len({
                p["reference"]["obs_id"] for p in sub
            } | {p["retrieved"]["obs_id"] for p in sub})
            print(f"\n[批后归纳] {n_obs} obs / {len(stories)} 故事 / {len(sub)} 对")
            try:
                res = inducer_module.inducer_node({"similar_observations": sub})
                written = res.get("induced_functions", [])
                induced_batch.extend(written)
                print(f"  → 写入 {len(written)} 个 Function")
            except Exception as e:
                print(f"  ✗ 分量归纳失败: {e}")
    print(f"阶段 2 共写入 {len(induced_batch)} 个 Function")
    # 阶段 3（--batch-induction）：Evaluator_v0 评估 + 自动修订闭环（curate_app）
    print("\n=== Evaluator_v0: 批后六维评估 + 自动修订闭环 ===")
    try:
        from Agent.app import curate_app
        eval_context = {}
        if args.corpus:
            manifest_abs = os.path.join(stories_dir, "manifest.json")
            if os.path.exists(manifest_abs):
                eval_context["manifest_path"] = manifest_abs
        result = curate_app.invoke({
            "messages": [],
            "evaluation_context": eval_context,
            "evaluation_round": 0,
        })
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

# 打印 Registry 统计
print("=== Registry 统计 ===")
if os.path.exists(inducer_module._REGISTRY_FILE):
    with open(inducer_module._REGISTRY_FILE, "r", encoding="utf-8") as f:
        funcs = [line for line in f if line.strip()]
    print(f"  共写入 Function: {len(funcs)}")
    for line in funcs[:5]:
        try:
            rec = json.loads(line)
            print(f"    - {rec.get('function_name', 'N/A')} "
                  f"(conf={rec.get('confidence', 0):.3f}, "
                  f"supporting={len(rec.get('supporting_obs_ids', []))})")
        except json.JSONDecodeError:
            pass
    if len(funcs) > 5:
        print(f"    ... 还有 {len(funcs) - 5} 条")
else:
    print("  Registry 文件不存在")

if args.out_dir:
    import shutil
    os.makedirs(args.out_dir, exist_ok=True)
    tag = args.genre or "all"
    dst_f = os.path.join(args.out_dir, f"functions_{tag}.jsonl")
    dst_b = os.path.join(args.out_dir, f"bank_{tag}.jsonl")
    if os.path.exists(inducer_module._REGISTRY_FILE):
        shutil.copyfile(inducer_module._REGISTRY_FILE, dst_f)
        print(f"  快照 Registry → {dst_f}")
    if os.path.exists(bank.jsonl_path):
        shutil.copyfile(bank.jsonl_path, dst_b)
        print(f"  快照 Bank → {dst_b}")

print(f"\nBank 总 obs 数: {bank.count()}")
print(f"全部 {total} 个故事处理完成")