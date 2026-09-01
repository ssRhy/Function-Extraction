"""批量生成正文并用独立 LLM 评审自动汇总质量问题。

用法（Code/ 下）：
    python -X utf8 test/run_story_batch.py
"""

import json
import os
import sys
import time
from collections import Counter

from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import Story_Agent.app as story_app
from Agent.llm import chat_structured
from KnowledgeBase import DEFAULT_DB_PATH, StoryKnowledgeStore


SNAPSHOT_ID = "evolve_250_20260822T063550401096Z_13b1bbda248f"
OUTLINE_ROOT = os.path.join(story_app._DATA, "outlines", SNAPSHOT_ID)
LEGACY_OUTLINES = [
    os.path.join(OUTLINE_ROOT, genre, f"outline_{index}.json")
    for genre in ("悬疑惊悚", "现代情感", "末世科幻")
    for index in range(1, 4)
]
CURRENT_OUTLINE = os.path.join(OUTLINE_ROOT, "悬疑惊悚_20260827T220804.json")
OUTLINE_PATHS = LEGACY_OUTLINES + [CURRENT_OUTLINE]


class QualityIssue(BaseModel):
    category: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)


class StoryQualityReport(BaseModel):
    structure_completeness: int = Field(ge=1, le=5)
    causal_coherence: int = Field(ge=1, le=5)
    character_motivation: int = Field(ge=1, le=5)
    conflict_resolution: int = Field(ge=1, le=5)
    ending_closure: int = Field(ge=1, le=5)
    readability: int = Field(ge=1, le=5)
    issues: list[QualityIssue]
    summary: str = Field(min_length=1)


QUALITY_PROMPT = """你是中文短篇正文的质量诊断器。请根据输入的大纲、Function 约束、场景计划和正文，诊断实际写作质量，只输出 JSON，不改写正文。

输出字段严格如下：
{
  "structure_completeness": 1,
  "causal_coherence": 1,
  "character_motivation": 1,
  "conflict_resolution": 1,
  "ending_closure": 1,
  "readability": 1,
  "issues": [{"category":"问题类别","severity":"high|medium|low","evidence":"正文中的具体证据或位置","recommendation":"针对该问题的最小改进方向"}],
  "summary":"整体诊断"
}

评分标准：1=明显失败，3=基本可读但有明显缺陷，5=稳定完整。
重点检查：
1. Function 顺序和场景计划是否真的在正文中发生，而不是只被解释；
2. 前一事件是否造成后一事件，是否存在跳步、突兀转折或重复场景；
3. 主角和关键人物的行动是否有动机支撑；
4. 核心冲突是否真正推进并得到处理；
5. 最后场景是否完成大纲要求的解决动作和稳定终态，不要把“准备行动”当成解决；
6. 篇幅、节奏、重复、空泛叙述和不自然表达。

只报告能从输入正文直接观察到的问题。没有问题时 issues 输出空数组。"""


def _legacy_ending(data):
    if data["outline"].get("ending"):
        return data
    segments = data["outline"]["segments"]
    last_segment = segments[-1]
    beats = last_segment.get("beats", [])
    ledger = data["outline"].get("final_ledger", [])
    final_text = ledger[-1] if ledger else (beats[-1] if beats else "故事进入暂时稳定状态")
    data["outline"]["ending"] = {
        "resolution_actions": beats[-1:] or ["完成最后一段行动"],
        "conflict_resolution": final_text,
        "final_state": final_text,
    }
    return data


def _import_batch_outline(path):
    with open(path, encoding="utf-8") as f:
        data = _legacy_ending(json.load(f))
    if data.get("validation", {}).get("overall_ok") is False:
        raise ValueError(f"大纲校验未通过，正式正文批次跳过: {path}")
    data.setdefault("snapshot_id", SNAPSHOT_ID)
    data.setdefault("generated_at", time.strftime(
        "%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(path)),
    ))
    markdown = f"# 大纲：{data['pattern_name']}（{data['genre']}）\n"
    return StoryKnowledgeStore(DEFAULT_DB_PATH).record_outline(data, markdown)


def _quality_input(result, sample_id):
    source = result["source_outline"]
    return {
        "sample_id": sample_id,
        "genre": source["genre"],
        "pattern_name": source["pattern_name"],
        "outline": source["outline"],
        "function_constraints": result["function_constraints"],
        "scene_plan": result["scene_plan"],
        "scene_developments": result["scene_developments"],
        "story": result["story"],
        "chinese_char_count": result["chinese_char_count"],
    }


def _render_report(batch, reports):
    lines = [f"# {len(reports)} 篇正文自动质量诊断", "", f"批次：{batch}", ""]
    for item in reports:
        lines.extend([
            f"## {item['sample_id']}｜{item['genre']}｜{item['title']}",
            "",
            f"中文字符数：{item['chinese_char_count']}；长度达标：{item['length_ok']}",
            f"评分：结构 {item['quality']['structure_completeness']}，因果 {item['quality']['causal_coherence']}，人物 {item['quality']['character_motivation']}，冲突解决 {item['quality']['conflict_resolution']}，结局闭合 {item['quality']['ending_closure']}，可读性 {item['quality']['readability']}",
            f"总结：{item['quality']['summary']}",
            "",
        ])
        for issue in item["quality"]["issues"]:
            lines.append(f"- [{issue['severity']}] {issue['category']}：{issue['evidence']}；建议：{issue['recommendation']}")
        if not item["quality"]["issues"]:
            lines.append("- 未发现需要记录的具体问题。")
        lines.append("")
    return "\n".join(lines)


def _invoke_story(graph, payload):
    last_error = None
    for attempt in range(1, 3):
        try:
            return graph.invoke(payload)
        except Exception as exc:
            last_error = exc
            if attempt < 2 and "正式正文批次" not in str(exc):
                print(f"  [retry] 单篇链路重跑 1/1: {exc}")
            elif "正式正文批次" in str(exc):
                break
    raise last_error


def main():
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    batch = f"usage_batch_story{len(OUTLINE_PATHS)}_{timestamp}"
    root = os.path.join(story_app._DATA, f"story_batch_{len(OUTLINE_PATHS)}", batch)
    os.makedirs(root, exist_ok=True)

    graph = story_app._build_graph()
    reports = []
    skipped = []
    for index, outline_path in enumerate(OUTLINE_PATHS, 1):
        sample_id = f"story_{index:02d}"
        out_dir = os.path.join(root, sample_id)
        print(f"=== {sample_id}/{len(OUTLINE_PATHS)} {outline_path}")
        try:
            outline_id = _import_batch_outline(outline_path)
            result = _invoke_story(graph, {
                "outline_id": outline_id,
                "knowledge_db": str(DEFAULT_DB_PATH),
                "user_request": None,
                "out_dir": out_dir,
                "outline_data": None,
                "function_constraints": None,
                "scene_plan": None,
                "scene_developments": None,
                "story": None,
                "result_path": "",
            })
        except ValueError as exc:
            skipped.append({
                "sample_id": sample_id,
                "source_outline_path": os.path.abspath(outline_path),
                "reason": str(exc),
            })
            print(f"  skipped={exc}")
            continue
        with open(result["result_path"], encoding="utf-8") as f:
            exported = json.load(f)
        quality = chat_structured([
            {"role": "system", "content": QUALITY_PROMPT},
            {"role": "user", "content": json.dumps(
                _quality_input(exported, sample_id), ensure_ascii=False,
            )},
        ], StoryQualityReport).model_dump()
        reports.append({
            "sample_id": sample_id,
            "source_outline_path": os.path.abspath(outline_path),
            "result_path": result["result_path"],
            "markdown_path": result["result_path"].replace(".json", ".md"),
            "genre": exported["source_outline"]["genre"],
            "pattern_name": exported["source_outline"]["pattern_name"],
            "title": exported["story"]["title"],
            "chinese_char_count": exported["chinese_char_count"],
            "length_ok": exported["length_ok"],
            "quality": quality,
        })
        print(f"  result={result['result_path']}")
        print(f"  quality={quality['summary']}")
    issue_counts = Counter()
    severity_counts = Counter()
    for item in reports:
        for issue in item["quality"]["issues"]:
            issue_counts[issue["category"]] += 1
            severity_counts[issue["severity"]] += 1
    batch_result = {
        "batch": batch,
        "snapshot_id": SNAPSHOT_ID,
        "count": len(reports),
        "requested_count": len(OUTLINE_PATHS),
        "skipped": skipped,
        "input_policy": "使用 OUTLINE_PATHS 指定的大纲；历史大纲仅在内存中补 outline.ending",
        "generation_graph": "load_outline → function_constraints → plan_scenes → develop_scenes → write_story → export",
        "quality_evaluator": "独立 LLM 诊断；不改写正文，不作为生成阻断条件",
        "length_ok_count": sum(item["length_ok"] for item in reports),
        "issue_counts": dict(issue_counts),
        "severity_counts": dict(severity_counts),
        "reports": reports,
    }
    json_path = os.path.join(root, "quality_report.json")
    md_path = os.path.join(root, "quality_report.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(batch_result, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_render_report(batch, reports))
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({
            "batch": batch,
            "outline_paths": [os.path.abspath(path) for path in OUTLINE_PATHS],
            "legacy_ending_adapter": True,
            "skipped": skipped,
            "quality_report": json_path,
        }, f, ensure_ascii=False, indent=2)
    print(f"[Batch] root={root}")
    print(f"[Batch] stories={len(reports)} skipped={len(skipped)} length_ok={batch_result['length_ok_count']}/{len(reports)}")
    print(f"[Batch] issue_counts={dict(issue_counts)}")
    print(f"[Batch] quality_report={json_path}")


if __name__ == "__main__":
    main()
