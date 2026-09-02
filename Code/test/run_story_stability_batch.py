"""运行 3 题材 × 3 大纲 × 2 次正文的短篇稳定性批次。"""

import json
import os
import sys
import time
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import Outline_Agent.app as outline_app
import Story_Agent.app as story_app


GENRES = ["悬疑惊悚", "现代情感", "末世科幻"]
PATTERNS_PER_GENRE = 3
STORIES_PER_OUTLINE = 2


def _invoke(graph, payload):
    last_error = None
    for attempt in range(2):
        try:
            return graph.invoke(payload)
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                print(f"  [retry] 重跑当前调用: {exc}")
    raise last_error


def _new_outline(graph, genre, pattern, out_dir, snapshot_id):
    return _invoke(graph, {
        "snapshot_id": snapshot_id,
        "knowledge_db": str(outline_app.DEFAULT_DB_PATH),
        "genre": outline_app.normalize_genre(genre),
        "out_dir": out_dir,
        "pattern_request": pattern,
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


def _story_payload(outline_id, out_dir):
    return {
        "outline_id": outline_id,
        "knowledge_db": str(outline_app.DEFAULT_DB_PATH),
        "user_request": None,
        "out_dir": out_dir,
        "outline_data": None,
        "function_constraints": None,
        "scene_plan": None,
        "scene_developments": None,
        "story": None,
        "result_path": "",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-id", required=True)
    snapshot_id = parser.parse_args().snapshot_id
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    batch = f"stability_{timestamp}"
    root = os.path.join(story_app._DATA, "story_stability", batch)
    outline_dir = os.path.join(root, "outlines")
    story_dir = os.path.join(root, "stories")
    os.makedirs(outline_dir, exist_ok=True)
    os.makedirs(story_dir, exist_ok=True)

    catalog = outline_app.load_catalog(snapshot_id)
    outline_graph = outline_app._build_graph()
    story_graph = story_app._build_graph()
    outlines = []
    stories = []

    for genre_name in GENRES:
        genre = outline_app.normalize_genre(genre_name)
        patterns = outline_app.candidate_patterns(catalog, genre)[:PATTERNS_PER_GENRE]
        for pattern_index, pattern in enumerate(patterns, 1):
            outline_id = f"{genre_name}_{pattern_index:02d}"
            print(f"=== outline {outline_id}: {pattern['pattern_name']}")
            outline_item = {
                "outline_id": outline_id,
                "genre": genre,
                "pattern_name": pattern["pattern_name"],
            }
            try:
                state = _new_outline(
                    outline_graph, genre, pattern["pattern_name"], outline_dir, snapshot_id,
                )
            except Exception as exc:
                outline_item.update({"status": "error", "error": str(exc)})
                outlines.append(outline_item)
                print(f"  outline_error={exc}")
                continue

            validation = state.get("validation") or {}
            outline_item.update({
                "status": "accepted" if validation.get("overall_ok") is True else "blocked",
                "outline_path": state.get("result_path"),
                "overall_ok": validation.get("overall_ok"),
                "rule_issues": validation.get("rule_issues", []),
                "issues": validation.get("issues", []),
                "function_chain": [step["function_name"] for step in state["chain"]],
                "narrative_steps": len(state["narrative"]["steps"]),
                "setup_payoff_count": sum(
                    len(step["setup_payoffs"]) for step in state["narrative"]["steps"]
                ),
                "reaction_count": sum(
                    bool(step["reaction_beat"]) for step in state["narrative"]["steps"]
                ),
            })
            outlines.append(outline_item)
            print(f"  overall_ok={validation.get('overall_ok')} path={state.get('result_path')}")
            if validation.get("overall_ok") is not True:
                print("  blocked: 不进入正式正文批次")
                continue

            for sample_index in range(1, STORIES_PER_OUTLINE + 1):
                sample_id = f"{outline_id}_run_{sample_index:02d}"
                sample_out_dir = os.path.join(story_dir, sample_id)
                print(f"  --- {sample_id}")
                try:
                    story_state = _invoke(
                        story_graph,
                        _story_payload(state["outline_id"], sample_out_dir),
                    )
                    with open(story_state["result_path"], encoding="utf-8") as f:
                        exported = json.load(f)
                    story_item = {
                        "sample_id": sample_id,
                        "outline_id": outline_id,
                        "outline_path": state["result_path"],
                        "story_json": story_state["result_path"],
                        "story_markdown": story_state["result_path"].replace(".json", ".md"),
                        "title": exported["story"]["title"],
                        "scene_count": len(exported["story"].get("scenes", [])),
                        "chinese_char_count": exported["chinese_char_count"],
                        "length_ok": exported["length_ok"],
                        "status": "generated",
                    }
                except Exception as exc:
                    story_item = {
                        "sample_id": sample_id,
                        "outline_id": outline_id,
                        "outline_path": state["result_path"],
                        "status": "error",
                        "error": str(exc),
                    }
                stories.append(story_item)
                if story_item["status"] == "generated":
                    print(
                        f"    title={story_item['title']} scenes={story_item['scene_count']} "
                        f"chars={story_item['chinese_char_count']} length_ok={story_item['length_ok']}"
                    )
                else:
                    print(f"    story_error={story_item['error']}")

    paired = {}
    for story in stories:
        if story["status"] != "generated":
            continue
        paired.setdefault(story["outline_id"], []).append(story)
    for outline_id, items in paired.items():
        if len(items) != 2:
            continue
        counts = [item["chinese_char_count"] for item in items]
        items[0]["paired_char_delta"] = abs(counts[0] - counts[1])
        items[1]["paired_char_delta"] = items[0]["paired_char_delta"]

    report = {
        "batch": batch,
        "snapshot_id": snapshot_id,
        "protocol": (
            f"{len(GENRES)} genres × {PATTERNS_PER_GENRE} outlines per genre "
            f"× {STORIES_PER_OUTLINE} story samples per outline"
        ),
        "generation_graph": "load_outline → function_constraints → plan_scenes → develop_scenes → write_story → export",
        "outlines": outlines,
        "stories": stories,
        "summary": {
            "requested_outlines": len(GENRES) * PATTERNS_PER_GENRE,
            "accepted_outlines": sum(item.get("status") == "accepted" for item in outlines),
            "blocked_or_error_outlines": sum(item.get("status") != "accepted" for item in outlines),
            "requested_stories": len(GENRES) * PATTERNS_PER_GENRE * STORIES_PER_OUTLINE,
            "generated_stories": sum(item.get("status") == "generated" for item in stories),
            "length_ok_count": sum(item.get("length_ok") is True for item in stories),
            "paired_runs": sum(len(items) == 2 for items in paired.values()),
        },
    }
    report_path = os.path.join(root, "stability_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[Stability] root={root}")
    print(f"[Stability] summary={json.dumps(report['summary'], ensure_ascii=False)}")
    print(f"[Stability] report={report_path}")


if __name__ == "__main__":
    main()
