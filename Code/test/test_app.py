"""
测试：从 story.txt 读取文本，运行 pipeline + 可视化
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Agent.app import pipeline_app

# 读取 story.txt
story_path = os.path.join(os.path.dirname(__file__), "story.txt")
with open(story_path, "r", encoding="utf-8") as f:
    raw_text = f.read().strip()

print(f"故事文本 ({len(raw_text)} 字)")

# 初始状态
initial_state = {
    "messages": [],
    "raw_text": raw_text,
    "story_config": {"story_type": "default"},
    "normalized_story": None,
    "observations": [],
    "current_phase": "bootstrap",
    "current_story_index": 0,
    "total_stories": 1
}

config = {"configurable": {"thread_id": "test-run-1"}}

print("运行 Pipeline...")
result = pipeline_app.invoke(initial_state, config=config)

print("\n[OK] Pipeline 完成!")
print(f"故事: {result['normalized_story']['metadata']['title']}")
print(f"句子数: {len(result['normalized_story']['sentences'])}")
print(f"观察到: {len(result['observations'])} 个事件")

for obs in result["observations"]:
    print(f"\n[{obs['obs_id']}] {obs['event']}")
    print(f"  前因: {obs['prior_context']}")
    print(f"  结果: {obs['after_state']}")

# 可视化
test_dir = os.path.dirname(os.path.abspath(__file__))
mermaid_code = pipeline_app.get_graph().draw_mermaid()

mmd_path = os.path.join(test_dir, "langgraph_graph.mmd")
with open(mmd_path, "w", encoding="utf-8") as f:
    f.write(mermaid_code)
print(f"已生成: {mmd_path}")

print("\n" + "=" * 50)
print("ASCII 图")
print("=" * 50)
print(pipeline_app.get_graph().draw_ascii())
