"""一键生成：Outline_Agent → Story_Agent。"""

import argparse
import json
import os
import time

from langgraph.graph import END, START, StateGraph

from Outline_Agent import app as outline_app
from Story_Agent import app as story_app
from Pipeline_Agent.state import PipelineState


def _outline_input(state, out_dir, **overrides):
    payload = {
        "snapshot_id": state["snapshot_id"],
        "knowledge_db": state["knowledge_db"],
        "genre": outline_app.normalize_genre(state["genre"]),
        "out_dir": out_dir,
        "pattern_request": state.get("pattern_request"),
        "user_request": state.get("user_request"),
        "planner_mode": state.get("planner_mode", "published"),
        "pattern_id": None,
        "pattern_name": "",
        "pattern_source": state.get("planner_mode", "published"),
        "pattern_selection": None,
        "ending_spec": None,
        "chain": [],
        "planner_references": None,
        "dynamic_candidates": [],
        "dynamic_candidate": None,
        "seed": None,
        "mechanism": None,
        "narrative": None,
        "contract_ledger": None,
        "outline": None,
        "validation": None,
        "realize_retry_count": 0,
        "outline_id": "",
        "result_path": "",
    }
    payload.update(overrides)
    return payload


def _run_outline(state, out_dir, **overrides):
    return outline_app._build_graph().invoke(_outline_input(state, out_dir, **overrides))


def generate_outline_node(state):
    genre = outline_app.normalize_genre(state["genre"])
    result = _run_outline(state, os.path.join(state["out_dir"], "outline"))
    validation = result["validation"] or {}
    if not validation.get("overall_ok"):
        raise ValueError(f"大纲校验未通过，正文未启动: {result['result_path']}")
    print(f"[Pipeline] outline={result['result_path']}")
    print(f"[Pipeline] pattern={result['pattern_name']}")
    return {
        "genre": genre,
        "outline_id": result["outline_id"],
        "outline_path": result["result_path"],
        "outline_result": result,
    }


def generate_story_node(state):
    result = story_app._build_graph().invoke({
        "outline_id": state["outline_id"],
        "knowledge_db": state["knowledge_db"],
        "user_request": state.get("user_request"),
        "out_dir": os.path.join(state["out_dir"], "story"),
        "outline_data": None,
        "function_constraints": None,
        "scene_plan": None,
        "scene_developments": None,
        "story": None,
        "result_path": "",
    })
    print(f"[Pipeline] story={result['result_path']}")
    return {
        "story_path": result["result_path"],
    }


def export_node(state):
    story_path = state.get("story_path")
    story_markdown = os.path.splitext(story_path)[0] + ".md" if story_path else None
    outline_result = state.get("outline_result") or {}
    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "genre": state["genre"],
        "snapshot_id": state["snapshot_id"],
        "pattern_request": state.get("pattern_request"),
        "user_request": state.get("user_request"),
        "planner_mode": state.get("planner_mode", "published"),
        "pattern_name": outline_result.get("pattern_name"),
        "outline_id": state["outline_id"],
        "outline_json": os.path.abspath(state["outline_path"]) if state.get("outline_path") else None,
        "story_json": os.path.abspath(story_path) if story_path else None,
        "story_markdown": os.path.abspath(story_markdown) if story_markdown else None,
    }
    os.makedirs(state["out_dir"], exist_ok=True)
    path = os.path.join(state["out_dir"], "pipeline_manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[Pipeline] manifest={path}")
    return {"manifest_path": path}


def _build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("generate_outline", generate_outline_node)
    graph.add_node("generate_story", generate_story_node)
    graph.add_node("export", export_node)
    graph.add_edge(START, "generate_outline")
    graph.add_edge("generate_outline", "generate_story")
    graph.add_edge("generate_story", "export")
    graph.add_edge("export", END)
    return graph.compile()


def main():
    parser = argparse.ArgumentParser(description="一键生成大纲和正文")
    parser.add_argument("--genre", required=True, help="题材，如 现代情感")
    parser.add_argument("--pattern", default=None, help="指定 Pattern 名称")
    parser.add_argument("--request", default=None, help="用户故事要求")
    parser.add_argument(
        "--planner-mode", choices=("published", "dynamic"), default="published",
        help="Planner 模式，默认使用已发布 Pattern",
    )
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--knowledge-db", default=str(outline_app.DEFAULT_DB_PATH))
    parser.add_argument("--out-dir", default=None, help="本次运行输出目录")
    args = parser.parse_args()
    out_dir = args.out_dir or os.path.join(
        outline_app._DATA, "pipeline_runs", time.strftime("%Y%m%dT%H%M%S"),
    )
    result = _build_graph().invoke({
        "genre": args.genre,
        "snapshot_id": args.snapshot_id,
        "knowledge_db": args.knowledge_db,
        "pattern_request": args.pattern,
        "user_request": args.request,
        "planner_mode": args.planner_mode,
        "out_dir": out_dir,
        "outline_id": None,
        "outline_path": None,
        "outline_result": None,
        "story_path": None,
        "manifest_path": "",
    })
    print(f"[Pipeline] completed={result['manifest_path']}")


if __name__ == "__main__":
    main()
