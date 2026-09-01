"""生成 5 份含重复 Function 的新大纲和正文，回归验证索引对齐与正文入口校验。"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import Outline_Agent.app as outline_app
import Story_Agent.app as story_app


PATTERN_CANDIDATES = [
    ("悬疑惊悚", "亲密者秘密与害局"),
    ("末世科幻", "支持-暴力-操控循环"),
    ("悬疑惊悚", "循环调查推动抉择"),
    ("末世科幻", "末世危局中的救援与关系深化"),
    ("现代情感", "亲密关系升温遇阻"),
    ("现代情感", "拯救之恋"),
    ("悬疑惊悚", "线索涌现与调查启动"),
    ("现代情感", "情感误解揭示循环"),
    ("悬疑惊悚", "线索-行动-真相循环"),
]


def _invoke(graph, payload):
    last_error = None
    for attempt in range(2):
        try:
            return graph.invoke(payload)
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                print(f"  [retry] 当前样本重新运行一次: {exc}")
    raise last_error


def _new_outline(graph, genre, pattern, out_dir):
    return _invoke(graph, {
        "snapshot_id": outline_app.DEFAULT_SNAPSHOT_ID,
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


def _duplicate_check(state):
    chain = state["chain"]
    duplicates = {}
    for name in {step["function_name"] for step in chain}:
        positions = [
            index for index, step in enumerate(chain, 1)
            if step["function_name"] == name
        ]
        if len(positions) < 2:
            continue
        mechanism = [state["mechanism"]["steps"][index - 1] for index in positions]
        narrative = [state["narrative"]["steps"][index - 1] for index in positions]
        segments = [state["outline"]["segments"][index - 1] for index in positions]
        duplicates[name] = {
            "positions": positions,
            "occurrence_indices": [chain[index - 1]["occurrence_index"] for index in positions],
            "mechanism_distinct": len({
                (item["who_does_what"], item["why"], item["state_change"])
                for item in mechanism
            }) == len(mechanism),
            "narrative_distinct": len({
                item["genre_realization"] for item in narrative
            }) == len(narrative),
            "outline_distinct": len({
                tuple(item["beats"])
                for item in segments
            }) == len(segments),
        }
    return duplicates


def main():
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    batch = f"regression_story5_{timestamp}"
    root = os.path.join(story_app._DATA, "story_regression_5", batch)
    outline_dir = os.path.join(root, "outlines")
    story_dir = os.path.join(root, "stories")
    os.makedirs(outline_dir, exist_ok=True)
    os.makedirs(story_dir, exist_ok=True)

    outline_graph = outline_app._build_graph()
    story_graph = story_app._build_graph()
    outline_results = []
    stories = []
    candidate_index = 0
    for genre, pattern in PATTERN_CANDIDATES:
        if len(stories) >= 5:
            break
        candidate_index += 1
        sample_id = f"sample_{candidate_index:02d}"
        print(f"=== {sample_id} {genre} / {pattern}")
        try:
            state = _new_outline(outline_graph, genre, pattern, outline_dir)
        except Exception as exc:
            outline_results.append({
                "sample_id": sample_id,
                "genre": genre,
                "pattern": pattern,
                "status": "error",
                "reason": str(exc),
            })
            print(f"  outline_error={exc}")
            continue

        validation = state["validation"] or {}
        duplicate_check = _duplicate_check(state)
        accepted = validation.get("overall_ok") is True
        outline_item = {
            "sample_id": sample_id,
            "genre": genre,
            "pattern": pattern,
            "outline_path": state["result_path"],
            "status": "accepted" if accepted else "blocked",
            "overall_ok": validation.get("overall_ok"),
            "rule_issues": validation.get("rule_issues", []),
            "issues": validation.get("issues", []),
            "chain": state["chain"],
            "duplicate_check": duplicate_check,
        }
        outline_results.append(outline_item)
        print(f"  outline={state['result_path']}")
        print(f"  overall_ok={validation.get('overall_ok')} duplicates={duplicate_check}")
        if not accepted:
            print("  blocked: 不进入正文生成")
            continue

        try:
            story_state = _invoke(story_graph, {
                "outline_id": state["outline_id"],
                "knowledge_db": str(outline_app.DEFAULT_DB_PATH),
                "user_request": None,
                "out_dir": story_dir,
                "outline_data": None,
                "function_constraints": None,
                "scene_plan": None,
                "scene_developments": None,
                "story": None,
                "result_path": "",
            })
        except Exception as exc:
            outline_item["status"] = "story_error"
            outline_item["story_error"] = str(exc)
            print(f"  story_error={exc}")
            continue
        with open(story_state["result_path"], encoding="utf-8") as f:
            exported = json.load(f)
        story_item = {
            "sample_id": sample_id,
            "outline_path": state["result_path"],
            "story_json": story_state["result_path"],
            "story_markdown": story_state["result_path"].replace(".json", ".md"),
            "title": exported["story"]["title"],
            "chinese_char_count": exported["chinese_char_count"],
            "length_ok": exported["length_ok"],
        }
        stories.append(story_item)
        print(f"  story={story_state['result_path']} chars={exported['chinese_char_count']}")

    report = {
        "batch": batch,
        "requested_stories": 5,
        "generated_stories": len(stories),
        "outline_candidates": outline_results,
        "stories": stories,
        "formal_gate": "validation.overall_ok=false 的大纲不进入正文图",
        "alignment_check": "按 segment_index 对齐，重复 Function 保留 occurrence 独立位置",
    }
    report_path = os.path.join(root, "regression_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[Regression] root={root}")
    print(f"[Regression] generated={len(stories)}/5")
    print(f"[Regression] blocked={sum(item['status'] == 'blocked' for item in outline_results)}")
    print(f"[Regression] report={report_path}")


if __name__ == "__main__":
    main()
