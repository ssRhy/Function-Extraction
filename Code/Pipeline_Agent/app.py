"""一键生成：Outline_Agent → Story_Agent。"""

import argparse
import json
import os
import time

from langgraph.graph import END, START, StateGraph

from KnowledgeBase import StoryKnowledgeStore
from Outline_Agent import app as outline_app
from Pipeline_Agent.best_of import (
    _best_of,
    _candidate_summary,
    _dynamic_candidates,
    _select_best_of,
    _story_hard_gate,
)
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
    best_of = _best_of(state)
    if best_of == 1:
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
            "outline_results": [result],
        }

    first = _run_outline(
        state, os.path.join(state["out_dir"], "outline", "candidate_1"),
    )
    candidates = _dynamic_candidates(first.get("dynamic_candidates"))
    if len(candidates) < 2:
        raise ValueError("Best-of-2 需要至少两个有效且不同的动态 Function 候选")
    first_id = (first.get("dynamic_candidate") or {}).get("candidate_id")
    if first_id and first_id in {item.get("candidate_id") for item in candidates}:
        candidates.sort(key=lambda item: item.get("candidate_id") != first_id)

    outlines = [first]
    for index, candidate in enumerate(candidates[1:], 2):
        try:
            result = _run_outline(
                state,
                os.path.join(state["out_dir"], "outline", f"candidate_{index}"),
                seed=first.get("seed"),
                dynamic_candidates=candidates,
                dynamic_candidate=candidate,
            )
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            result = {
                "dynamic_candidate": candidate,
                "pattern_name": candidate.get("candidate_id", f"candidate_{index}"),
                "validation": {"overall_ok": False},
                "outline_error": str(exc),
            }
        outlines.append(result)

    for index, result in enumerate(outlines, 1):
        print(f"[Pipeline] candidate={index} outline={result.get('result_path') or 'failed'}")
        print(f"[Pipeline] candidate={index} pattern={result.get('pattern_name') or 'unknown'}")
    return {
        "genre": genre,
        "outline_id": first.get("outline_id"),
        "outline_path": first.get("result_path"),
        "outline_result": first,
        "outline_results": outlines,
    }


def generate_story_node(state):
    best_of = _best_of(state)
    if best_of == 1:
        story_dir = os.path.join(state["out_dir"], "story")
        result = story_app._build_graph().invoke({
            "outline_id": state["outline_id"],
            "knowledge_db": state["knowledge_db"],
            "user_request": state.get("user_request"),
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

    outlines = state.get("outline_results") or [state["outline_result"]]
    candidates = []
    for index, outline in enumerate(outlines, 1):
        candidate = _candidate_summary(index, outline)
        if outline.get("outline_error"):
            candidate["failure_stage"] = "outline"
            candidate["error"] = outline["outline_error"]
            candidates.append(candidate)
            continue
        if not candidate["outline_ok"]:
            candidate["failure_stage"] = "outline_validator"
            candidate["error"] = "大纲校验未通过，正文未启动"
            candidates.append(candidate)
            continue
        try:
            result = story_app._build_graph().invoke({
                "outline_id": outline["outline_id"],
                "knowledge_db": state["knowledge_db"],
                "user_request": state.get("user_request"),
                "out_dir": os.path.join(state["out_dir"], "story", f"candidate_{index}"),
                "outline_data": None,
                "function_constraints": None,
                "scene_plan": None,
                "scene_developments": None,
                "story": None,
                "story_validation": None,
                "first_story_validation": None,
                "story_revalidation": None,
                "story_repair_count": 0,
                "result_path": "",
            })
            story_path = result["result_path"]
            with open(story_path, encoding="utf-8") as story_file:
                exported = json.load(story_file)
            candidate.update({
                "story_json": os.path.abspath(str(story_path)),
                "story_status": exported.get("story_status", "unknown"),
                "story_validation": exported.get("story_validation") or {},
                "story_repair_count": exported.get("story_repair_count", 0),
            })
            evidence = candidate["story_validation"].get("function_execution_evidence") or []
            candidate["function_execution_evidence"] = evidence
            candidate["function_evidence_coverage"] = {
                "passed": sum(
                    item.get("status") == "PASS"
                    and item.get("segment_index") == segment_index
                    and item.get("function_name") == function_name
                    for segment_index, (function_name, item) in enumerate(
                        zip(candidate["function_chain"], evidence), 1
                    )
                ),
                "total": len(candidate["function_chain"]),
            }
            candidate["length_ok"] = exported.get("length_ok", True)
            candidate["hard_gate"] = _story_hard_gate(candidate)
            candidate["_story"] = exported
            print(f"[Pipeline] candidate={index} story={story_path}")
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            candidate["failure_stage"] = "story"
            candidate["error"] = str(exc)
        candidates.append(candidate)

    selection = _select_best_of(state.get("user_request"), candidates)
    winner = next(
        (item for item in candidates if item["candidate_index"] == selection["winner_index"]),
        None,
    )
    winner_outline = outlines[selection["winner_index"] - 1] if winner else outlines[0]
    public_candidates = [
        {key: value for key, value in item.items() if not key.startswith("_")}
        for item in candidates
    ]
    return {
        "outline_id": winner_outline.get("outline_id"),
        "outline_path": winner_outline.get("result_path"),
        "outline_result": winner_outline,
        "story_path": winner.get("story_json") if winner else None,
        "candidate_results": public_candidates,
        "selection": selection,
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
    if _best_of(state) == 2:
        selection = state.get("selection") or {
            "mode": "best_of_2", "status": "rejected", "winner": None,
            "winner_index": None, "reason": "未完成候选选择", "review": None,
        }
        candidates = state.get("candidate_results", [])
        winner = next(
            (item for item in candidates if item.get("candidate_index") == selection.get("winner_index")),
            None,
        )
        selected = selection.get("status") == "selected"
        follow_up = (winner or {}).get("story_status") if selected else "rejected"
        outcome_id = StoryKnowledgeStore(state["knowledge_db"]).record_generation_outcome(
            state["snapshot_id"], outline_result.get("pattern_id"),
            (winner or {}).get("outline_id") if selected else None,
            "dynamic", selected,
            bool((winner or {}).get("story_repair_count")),
            None if selected else "semantic",
            follow_up if follow_up in {"accepted", "rewritten"} else "rejected",
            {
                "generation_stage": "best_of_2",
                "selection": selection,
                "candidates": candidates,
            },
        )
        manifest.update({
            "generation_mode": "best_of_2",
            "candidates": candidates,
            "selection": selection,
            "selection_outcome_id": outcome_id,
        })
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
    parser.add_argument("--best-of", type=int, choices=(1, 2), default=1)
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
        "best_of": args.best_of,
        "out_dir": out_dir,
        "outline_id": None,
        "outline_path": None,
        "outline_result": None,
        "outline_results": [],
        "story_path": None,
        "candidate_results": [],
        "selection": None,
        "manifest_path": "",
    })
    print(f"[Pipeline] completed={result['manifest_path']}")


if __name__ == "__main__":
    main()
