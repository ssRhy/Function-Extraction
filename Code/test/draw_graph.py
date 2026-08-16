"""
可视化当前 LangGraph 图：生成 Mermaid 源码(.mmd)、PNG 图片和 ASCII 图
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Agent.app import pipeline_app

out_dir = os.path.dirname(os.path.abspath(__file__))
g = pipeline_app.get_graph()
with open(os.path.join(out_dir, "langgraph_pipeline.mmd"), "w", encoding="utf-8") as f:
    f.write(g.draw_mermaid())
with open(os.path.join(out_dir, "langgraph_pipeline.png"), "wb") as f:
    f.write(g.draw_mermaid_png())
print(g.draw_ascii())
print(f"\n已生成 langgraph_pipeline.mmd / .png")