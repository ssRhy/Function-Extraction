"""
可视化当前 LangGraph 整体图：pipeline（preprocessor→…→inducer）+ curate（evaluator→revise 闭环）
生成 Mermaid 源码(.mmd)、PNG 图片和 ASCII 图

用法：
  python Code/test/draw_graph.py             # 生成一次
  python Code/test/draw_graph.py --watch     # 监听 Code 下 .py 变化，实时重新生成
"""

import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def build_overall_graph():
    """整体图：pipeline 归纳 → curate 评估/修订闭环（仅用于可视化）。"""
    from langgraph.graph import StateGraph, START, END
    from Agent.state import NarrativePipelineState
    from Agent.app import (
        preprocessor_node,
        observer_node,
        bank_adder_node,
        retrieval_node,
        inducer_node,
        evaluator_node,
        revise_node,
        should_continue,
    )

    graph = StateGraph(NarrativePipelineState)
    graph.add_node("preprocessor", preprocessor_node)
    graph.add_node("observer", observer_node)
    graph.add_node("bank_adder", bank_adder_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("inducer", inducer_node)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("revise", revise_node)
    graph.add_edge(START, "preprocessor")
    graph.add_edge("preprocessor", "observer")
    graph.add_edge("observer", "bank_adder")
    graph.add_edge("bank_adder", "retrieval")
    graph.add_edge("retrieval", "inducer")
    graph.add_edge("inducer", "evaluator")
    graph.add_conditional_edges(
        "evaluator",
        should_continue,
        {"end": END, "revise": "revise"},
    )
    graph.add_edge("revise", "evaluator")
    return graph


def draw():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    g = build_overall_graph().compile().get_graph()
    with open(os.path.join(out_dir, "langgraph_overall.mmd"), "w", encoding="utf-8") as f:
        f.write(g.draw_mermaid())
    with open(os.path.join(out_dir, "langgraph_overall.png"), "wb") as f:
        f.write(g.draw_mermaid_png())
    print(g.draw_ascii())
    print(f"\n已生成 langgraph_overall.mmd / .png")


def _snapshot():
    files = {}
    for dirpath, _, filenames in os.walk(ROOT):
        if "__pycache__" in dirpath:
            continue
        for fn in filenames:
            if fn.endswith(".py"):
                p = os.path.join(dirpath, fn)
                try:
                    files[p] = os.path.getmtime(p)
                except OSError:
                    files[p] = 0.0
    return files


def watch():
    import subprocess, time

    sys.stdout.reconfigure(line_buffering=True)
    script = os.path.abspath(__file__)

    def rebuild(reason):
        print(f"\n[{reason}] 重新生成整体图...")
        subprocess.run([sys.executable, script])

    rebuild("启动")
    snap = _snapshot()
    print("监听中：Code 下任意 .py 变化将自动重新生成整体图（Ctrl+C 退出）")
    try:
        while True:
            time.sleep(2)
            cur = _snapshot()
            if cur != snap:
                changed = [os.path.relpath(p, ROOT) for p in cur if cur.get(p) != snap.get(p)]
                rebuild("检测到变化: " + ", ".join(changed))
                snap = _snapshot()
    except KeyboardInterrupt:
        print("\n已退出监听")


if __name__ == "__main__":
    if "--watch" in sys.argv:
        watch()
    else:
        draw()