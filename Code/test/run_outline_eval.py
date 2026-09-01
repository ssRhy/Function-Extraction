"""MVP-B 批量 + 三组对照：3 题材 × 3 份全系统大纲 + 两个基线。

基线：
- full：Outline_Agent（pattern 核心链 + Function Card + transition index）
- direct：只给题材，直接 LLM 写大纲
- function_only：只给题材 + 有序 Function 名（无定义/槽位/机制）

产物：data/outline_eval/<snapshot_id>/{full,comparison}/
comparison/<题材>.md 为 A/B/C 盲评稿，<题材>.key.json 为揭盲映射。

用法（Code/ 下）：
    python -X utf8 test/run_outline_eval.py
"""

import json
import os
import random
import sys
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pydantic import BaseModel, Field

from Agent.llm import chat_structured
import Outline_Agent.app as app


GENRES = ["悬疑惊悚", "现代情感", "末世科幻"]
K = 3


class CompSegment(BaseModel):
    heading: str
    beats: list[str]


class CompOutline(BaseModel):
    title: str
    segments: list[CompSegment]
    ending: str | None = None


_DIRECT_PROMPT = """你是网文作者。给定一个题材，写一份短篇故事大纲。只输出 JSON，字段名严格如下：
{"title": "标题", "segments": [{"heading": "段落标题", "beats": ["情节点"]}]}
分 3-5 段，逻辑连贯、有起承转合。"""

_FUNCTION_PROMPT = """你是网文作者。给定一个题材和一个有序的叙事功能列表（只有名字，无定义），按照这个顺序写一份短篇故事大纲。只输出 JSON，字段名严格如下：
{"title": "标题", "segments": [{"heading": "功能名", "beats": ["情节点"]}]}
每个功能写一段，顺序与输入一致。"""


def _full_case(snapshot_id, genre, pattern_name):
    state = {
        "snapshot_id": snapshot_id,
        "knowledge_db": str(app.DEFAULT_DB_PATH),
        "genre": genre,
        "out_dir": "",
        "pattern_request": pattern_name,
        "user_request": None,
        "pattern_id": None,
        "pattern_name": "",
        "ending_spec": None,
        "chain": [],
        "seed": None,
        "mechanism": None,
        "narrative": None,
        "outline": None,
        "validation": None,
        "outline_id": "",
        "result_path": "",
    }
    state.update(app.planner_node(state))
    state.update(app.seed_node(state))
    state.update(app.mechanism_node(state))
    state.update(app.scaffold_node(state))
    state.update(app.realize_node(state))
    state.update(app.validate_node(state))
    return state


def _full_to_comp(state):
    ending = state["outline"].get("ending")
    ending_text = None
    if ending:
        ending_text = "；".join([
            *ending["resolution_actions"],
            ending["conflict_resolution"],
            ending["final_state"],
        ])
    return {
        "title": state["pattern_name"],
        "segments": [
            {"heading": segment["function_name"], "beats": segment["beats"]}
            for segment in state["outline"]["segments"]
        ],
        "ending": ending_text,
    }


def _direct(genre):
    return chat_structured([
        {"role": "system", "content": _DIRECT_PROMPT},
        {"role": "user", "content": json.dumps({"genre": genre}, ensure_ascii=False)},
    ], CompOutline).model_dump()


def _function_only(genre, chain):
    return chat_structured([
        {"role": "system", "content": _FUNCTION_PROMPT},
        {"role": "user", "content": json.dumps(
            {"genre": genre, "functions": [step["function_name"] for step in chain]},
            ensure_ascii=False,
        )},
    ], CompOutline).model_dump()


def _render_comp(comp):
    lines = [f"# {comp['title']}", ""]
    for index, segment in enumerate(comp["segments"], 1):
        lines.append(f"## {index}. {segment['heading']}")
        lines.extend(segment["beats"])
        lines.append("")
    if comp.get("ending"):
        lines.append("## 结局")
        lines.append(comp["ending"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-id", default=app.DEFAULT_SNAPSHOT_ID)
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()

    snapshot_id = args.snapshot_id
    catalog = app.load_catalog()
    root = args.out_dir or os.path.join(app._DATA, "outline_eval", snapshot_id)
    full_dir = os.path.join(root, "full")
    cmp_dir = os.path.join(root, "comparison")
    os.makedirs(full_dir, exist_ok=True)
    os.makedirs(cmp_dir, exist_ok=True)

    print(f"=== full: {len(GENRES)} 题材 × {K} 份 ===")
    for genre_name in GENRES:
        genre = app.normalize_genre(genre_name)
        patterns = app.candidate_patterns(catalog, genre)[:K]
        cases = []
        for index, pattern in enumerate(patterns):
            state = _full_case(snapshot_id, genre, pattern["pattern_name"])
            prefix = f"{genre_name}_{index + 1}"
            json_path = os.path.join(full_dir, prefix + ".json")
            result = {
                "genre": genre,
                "pattern_name": state["pattern_name"],
                "chain": [step["function_name"] for step in state["chain"]],
                "seed": state["seed"],
                "mechanism_plan": state["mechanism"],
                "narrative_plan": state["narrative"],
                "outline": state["outline"],
                "validation": state["validation"],
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            with open(json_path.replace(".json", ".md"), "w", encoding="utf-8") as f:
                f.write(_render_comp(_full_to_comp(state)))
            print(f"  {genre_name} #{index + 1} {pattern['pattern_name']} "
                  f"overall_ok={state['validation']['overall_ok']} rule={state['validation']['rule_issues'] or '无'}")
            cases.append(state)

        top = cases[0]
        variants = [
            ("full", _full_to_comp(top)),
            ("direct", _direct(genre)),
            ("function_only", _function_only(genre, top["chain"])),
        ]
        rng = random.Random(sum(ord(ch) for ch in genre))
        rng.shuffle(variants)
        key = {}
        lines = [f"# 盲评稿：{genre_name}", ""]
        for label, (system, comp) in zip("ABC", variants):
            key[label] = system
            lines.append(f"## 方案 {label}")
            lines.append(_render_comp(comp))
        with open(os.path.join(cmp_dir, f"{genre_name}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        with open(os.path.join(cmp_dir, f"{genre_name}.key.json"), "w", encoding="utf-8") as f:
            json.dump({
                "genre": genre,
                "labels": key,
                "chain": [step["function_name"] for step in top["chain"]],
            }, f, ensure_ascii=False, indent=2)
        print(f"  comparison bundle -> {cmp_dir}/{genre_name}.md (+ .key.json)")


if __name__ == "__main__":
    main()
