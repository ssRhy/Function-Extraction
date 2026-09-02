"""一键生成：Outline_Agent → Story_Agent。"""

import argparse
import json
import os
import time

from langgraph.graph import END, START, StateGraph

from Outline_Agent import app as outline_app
from Story_Agent import app as story_app
from Pipeline_Agent.state import PipelineState


def generate_outline_node(state):
    genre = outline_app.normalize_genre(state["genre"])
    outline_dir = os.path.join(state["out_dir"], "outline")
    result = outline_app._build_graph().invoke({
        "snapshot_id": state["snapshot_id"],
        "knowledge_db": state["knowledge_db"],
        "genre": genre,
        "out_dir": outline_dir,
        "pattern_request": state.get("pattern_request"),
        "user_request": None,
        "pattern_id": None,
        "pattern_name": "",
        "ending_spec": None,
        "chain": [],
        "seed": None,
        "mechanism": None,
        "narrative": None,
        "contract_ledger": None,
        "outline": None,
        "validation": None,
        "outline_id": "",
        "result_path": "",
    })
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
    story_dir = os.path.join(state["out_dir"], "story")
    result = story_app._build_graph().invoke({
        "outline_id": state["outline_id"],
        "knowledge_db": state["knowledge_db"],
        "user_request": None,
        "out_dir": story_dir,
        "outline_data": None,
        "function_constraints": None,
        "scene_plan": None,
        "scene_developments": None,
        "story": None,
        "result_path": "",
    })
    print(f"[Pipeline] story={result['result_path']}")
    return {"story_path": result["result_path"]}


def export_node(state):
    story_markdown = os.path.splitext(state["story_path"])[0] + ".md"
    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "genre": state["genre"],
        "snapshot_id": state["snapshot_id"],
        "pattern_request": state.get("pattern_request"),
        "pattern_name": state["outline_result"]["pattern_name"],
        "outline_id": state["outline_id"],
        "outline_json": os.path.abspath(state["outline_path"]),
        "story_json": os.path.abspath(state["story_path"]),
        "story_markdown": os.path.abspath(story_markdown),
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
