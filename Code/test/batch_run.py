"""
批量运行：从 stories/ 目录读取所有 .txt 文件，逐个运行 Pipeline
启动前清空 Bank 和 Registry。
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Agent.state import NarrativePipelineState
from Agent.app import pipeline_app, get_bank
from Agent.Inducer import inducer as inducer_module

stories_dir = os.path.join(os.path.dirname(__file__), "stories")
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

story_files = sorted(
    f for f in os.listdir(stories_dir) if f.endswith(".txt")
)

if not story_files:
    print(f"目录 {stories_dir} 中没有 .txt 文件")
    sys.exit(0)

total = len(story_files)
print(f"发现 {total} 个故事文件，开始批量处理...\n")

for idx, filename in enumerate(story_files, start=1):
    path = os.path.join(stories_dir, filename)
    with open(path, "r", encoding="utf-8") as f:
        raw_text = f.read().strip()

    if not raw_text:
        print(f"[{idx}/{total}] {filename}: 空文件，跳过")
        continue

    print(f"[{idx}/{total}] {filename} ({len(raw_text)} 字)")

    initial_state: NarrativePipelineState = {
        "messages": [],
        "raw_text": raw_text,
        "story_config": {"source_file": filename},
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
        result = pipeline_app.invoke(initial_state, config=config)
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

print(f"\nBank 总 obs 数: {bank.count()}")
print(f"全部 {total} 个故事处理完成")
