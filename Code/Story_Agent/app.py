"""Story Agent - 从已生成大纲写成中文短篇正文。

线性图：START → load_outline → function_constraints → plan_scenes → develop_scenes → write_story → export → END
用法（Code/ 下）：
    python -X utf8 -m Story_Agent --outline-id OUT_xxx
"""

import argparse
import json
import os
import re
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VENDOR = os.path.join(_ROOT, "vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

from pydantic import ValidationError
from langgraph.graph import END, START, StateGraph

from FunctionExtract_Agent.llm import chat_structured
from KnowledgeBase import DEFAULT_DB_PATH, StoryKnowledgeStore
from Story_Agent.Prompt.Story_prompt import (
    DEVELOP_SCENES_PROMPT,
    FUNCTION_CONSTRAINT_PROMPT,
    SCENE_PLAN_PROMPT,
    STORY_PROMPT,
    STORY_VALIDATOR_PROMPT,
)
from Story_Agent.state import (
    FunctionConstraintPlan,
    SceneDevelopmentPlan,
    ScenePlanDraft,
    SourceOutlineDocument,
    StoryDraft,
    StoryValidation,
    StoryState,
)
from Story_Agent.validation import _function_execution_issues


_DATA = os.path.join(_ROOT, "data")
_MIN_CHINESE_CHARS = 3000


def load_outline_document(knowledge_db, outline_id):
    data = StoryKnowledgeStore(knowledge_db).load_outline(outline_id)
    try:
        document = SourceOutlineDocument.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"大纲缺少正文生成所需字段: {exc}") from exc
    if document.validation and document.validation.get("overall_ok") is False:
        raise ValueError(f"大纲校验未通过，正式正文批次拒绝生成: {outline_id}")
    return document.model_dump()


def _ending_target(source):
    return source.get("ending_target") or {
        "source": "llm_seed",
        "resolves": source.get("seed", {}).get("core_conflict", ""),
        "must_show": list(source.get("seed", {}).get("ending_requirements") or []),
        "final_state": source.get("seed", {}).get("ending_direction", ""),
    }


def _scene_plan_issues(source, plan):
    segments = source["outline"]["segments"]
    character_ids = {
        item.get("id") for item in (source.get("seed", {}).get("characters") or [])
        if item.get("id")
    }
    seen_indices = []
    scene_ids = set()
    issues = []
    for scene in plan["scenes"]:
        if scene["scene_id"] in scene_ids:
            issues.append(f"重复 scene_id: {scene['scene_id']}")
        scene_ids.add(scene["scene_id"])
        indices = scene["source_segment_indices"]
        if scene.get("is_ending"):
            if indices or scene["function_names"]:
                issues.append(f"{scene['scene_id']} 结局场景不能绑定 Function 段")
        else:
            if any(index < 1 or index > len(segments) for index in indices):
                issues.append(f"{scene['scene_id']} 引用了不存在的大纲段")
                continue
            expected_names = [segments[index - 1]["function_name"] for index in indices]
            if scene["function_names"] != expected_names:
                issues.append(f"{scene['scene_id']} 的 Function 与来源大纲段不一致")
        if character_ids:
            unknown = sorted(set(scene["characters"]) - character_ids)
            if unknown:
                issues.append(f"{scene['scene_id']} 引用了未定义人物: {', '.join(unknown)}")
        seen_indices.extend(indices)
    if set(seen_indices) != set(range(1, len(segments) + 1)):
        issues.append("场景计划未覆盖全部大纲段")
    if seen_indices != sorted(seen_indices):
        issues.append("场景计划改变了大纲段顺序")
    ending_scenes = [scene for scene in plan["scenes"] if scene.get("is_ending")]
    if not ending_scenes or plan["scenes"][-1] not in ending_scenes:
        issues.append("场景计划缺少位于 Function 场景之后的独立结局场景")
    return issues


def validate_character_names(source, story):
    """校验正文输出使用一份覆盖全部 seed 人物的稳定姓名映射。"""
    expected = {
        item.get("id") for item in (source.get("seed", {}).get("characters") or [])
        if item.get("id")
    }
    mapping = story.get("character_names") or {}
    if not expected:
        return story
    if set(mapping) != expected:
        raise ValueError("正文 character_names 必须恰好覆盖 seed.characters 中的人物 ID")
    names = [str(value).strip() for value in mapping.values()]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise ValueError("正文 character_names 必须是非空且互不重复的姓名")
    story["character_names"] = dict(zip(mapping, names))
    return story


def _align_story_scenes(scene_plan, story):
    expected = [scene["scene_id"] for scene in scene_plan["scenes"]]
    if len(story["scenes"]) != len(expected):
        raise ValueError("正文场景与场景计划的 scene_id 不完整对应")
    for scene, scene_id in zip(story["scenes"], expected):
        scene["scene_id"] = scene_id
    return story


def align_scene_developments(scene_plan, developments):
    expected = [scene["scene_id"] for scene in scene_plan["scenes"]]
    items = developments["developments"]
    if len(items) != len(expected):
        raise ValueError("场景展开必须与场景计划的 scene_id 一一对应")
    for item, scene_id in zip(items, expected):
        item["scene_id"] = scene_id
    return developments


def _story_text(story):
    return "\n\n".join(scene["text"].strip() for scene in story["scenes"])


def _render_markdown(story):
    return f"# {story['title']}\n\n{_story_text(story)}\n"


def _indexed_segments(source):
    return [
        {"segment_index": index, **segment}
        for index, segment in enumerate(source["outline"]["segments"], 1)
    ]


def align_function_constraints(source, constraints):
    segments = source["outline"]["segments"]
    expected_indices = list(range(1, len(segments) + 1))
    by_index = {item["segment_index"]: item for item in constraints["segments"]}
    if len(by_index) != len(constraints["segments"]) or set(by_index) != set(expected_indices):
        raise ValueError("Function 约束必须与来源大纲段一一对应")
    ordered = []
    for index in expected_indices:
        item = by_index[index]
        if item["function_name"] != segments[index - 1]["function_name"]:
            raise ValueError(f"第 {index} 段的 Function 约束与来源大纲不一致")
        ordered.append(item)
    constraints["segments"] = ordered
    return constraints


def build_scene_plan(source, draft):
    expected_indices = list(range(1, len(source["outline"]["segments"]) + 1))
    by_index = {item["segment_index"]: item for item in draft["segments"]}
    if len(by_index) != len(draft["segments"]) or set(by_index) != set(expected_indices):
        raise ValueError("场景草案必须与来源大纲段一一对应")
    scenes = []
    for index in expected_indices:
        segment = source["outline"]["segments"][index - 1]
        for detail in by_index[index]["scenes"]:
            scenes.append({
                "scene_id": f"S{len(scenes) + 1}",
                "source_segment_indices": [index],
                "function_names": [segment["function_name"]],
                **detail,
                "is_ending": False,
            })
    for detail in draft["ending"]:
        scenes.append({
            "scene_id": f"S{len(scenes) + 1}",
            "source_segment_indices": [],
            "function_names": [],
            **detail,
            "is_ending": True,
        })
    return {"scenes": scenes}


def load_outline_node(state):
    source = load_outline_document(state["knowledge_db"], state["outline_id"])
    out_dir = state.get("out_dir") or os.path.join(_DATA, "stories", source["snapshot_id"])
    return {"outline_data": source, "out_dir": out_dir}


def function_constraints_node(state):
    source = state["outline_data"]
    user = {
        "seed": source["seed"],
        "mechanism_plan": source["mechanism_plan"],
        "contract_ledger": source.get("contract_ledger"),
        "source_segments": _indexed_segments(source),
        "ending_target": _ending_target(source),
        "ending_budget": source.get("ending_budget") or {},
        "ending": source["outline"]["ending"],
    }
    constraints = chat_structured([
        {"role": "system", "content": FUNCTION_CONSTRAINT_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ], FunctionConstraintPlan).model_dump()
    return {"function_constraints": align_function_constraints(source, constraints)}


def plan_scenes_node(state):
    source = state["outline_data"]
    user = {
        "seed": source["seed"],
        "allowed_character_ids": [
            item["id"] for item in (source["seed"].get("characters") or [])
            if item.get("id")
        ],
        "mechanism_plan": source["mechanism_plan"],
        "narrative_plan": source["narrative_plan"],
        "source_segments": _indexed_segments(source),
        "function_constraints": state["function_constraints"],
        "ending": source["outline"]["ending"],
        "ending_target": _ending_target(source),
        "ending_budget": source.get("ending_budget") or {},
    }
    messages = [
        {"role": "system", "content": SCENE_PLAN_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]
    for attempt in range(2):
        draft = chat_structured(messages, ScenePlanDraft).model_dump()
        plan = build_scene_plan(source, draft)
        issues = _scene_plan_issues(source, plan)
        if not issues:
            return {"scene_plan": plan}
        if attempt == 0 and any("未定义人物" in issue for issue in issues):
            messages.append({
                "role": "user",
                "content": (
                    "场景计划存在人物引用错误：" + "；".join(issues)
                    + "。只修正 characters：它必须是 allowed_character_ids 的子集，"
                    "不得填写自然语言角色或临时人物；非核心人物改写到 beats/setting，"
                    "保持其他结构不变并重新输出完整 JSON。"
                ),
            })
            continue
        raise ValueError(f"场景计划不符合大纲: {'；'.join(issues)}")


def develop_scenes_node(state):
    source = state["outline_data"]
    user = {
        "seed": source["seed"],
        "narrative_plan": source["narrative_plan"],
        "function_constraints": state["function_constraints"],
        "scene_plan": state["scene_plan"],
        "ending": source["outline"]["ending"],
    }
    developments = chat_structured([
        {"role": "system", "content": DEVELOP_SCENES_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ], SceneDevelopmentPlan).model_dump()
    return {
        "scene_developments": align_scene_developments(
            state["scene_plan"], developments,
        )
    }


def write_story_node(state):
    source = state["outline_data"]
    user_request = state.get("user_request") or source.get("user_request")
    user = {
        "seed": source["seed"],
        "source_outline": source["outline"],
        "function_chain": [item["function_name"] for item in source["outline"]["segments"]],
        "function_constraints": state["function_constraints"],
        "scene_plan": state["scene_plan"],
        "scene_developments": state["scene_developments"],
        "user_request": user_request,
        "writing_requirements": {
            "min_chinese_chars": _MIN_CHINESE_CHARS,
        },
        "ending_target": _ending_target(source),
        "ending_budget": source.get("ending_budget") or {},
        "ending": source["outline"]["ending"],
    }
    repair = bool(state.get("story_validation")) and not state.get("story_repair_count", 0)
    if repair:
        user["current_story"] = state["story"]
    story = chat_structured([
        {"role": "system", "content": STORY_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        *([{"role": "user", "content": f"补充创作要求：{user_request}"}]
          if user_request else []),
        *([{
            "role": "user",
            "content": (
                "Story Validator 指出以下正文问题："
                + "；".join(state["story_validation"].get("issues") or [])
                + "。只修正这些问题。固定当前 title、character_names、scene_id、"
                "seed、Function chain、function_constraints、scene_plan、核心冲突和结局目标；"
                "不得修改任何上游结构或新增解决方案，只重新输出完整 JSON。"
            ),
        }] if repair else []),
    ], StoryDraft, reasoning_effort="medium").model_dump()
    story = validate_character_names(source, story)
    story = _align_story_scenes(state["scene_plan"], story)
    if repair:
        story["title"] = state["story"]["title"]
        story["character_names"] = state["story"]["character_names"]
    return {
        "story": story,
        "story_repair_count": state.get("story_repair_count", 0) + int(repair),
    }


def validate_story_node(state):
    source = state["outline_data"]
    user_request = state.get("user_request") or source.get("user_request")
    text = _story_text(state["story"])
    chinese_char_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    user = {
        "user_request": user_request,
        "seed": source["seed"],
        "source_outline": source["outline"],
        "function_chain": [item["function_name"] for item in source["outline"]["segments"]],
        "function_constraints": state["function_constraints"],
        "scene_plan": state["scene_plan"],
        "scene_developments": state["scene_developments"],
        "ending_target": _ending_target(source),
        "ending": source["outline"]["ending"],
        "story": state["story"],
        "chinese_char_count": chinese_char_count,
        "min_chinese_chars": _MIN_CHINESE_CHARS,
    }
    validation = chat_structured([
        {"role": "system", "content": STORY_VALIDATOR_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ], StoryValidation).model_dump()
    execution_issues = _function_execution_issues(
        source, state["scene_plan"], validation,
    )
    if execution_issues:
        validation["causal_constraints_ok"] = False
        validation["overall_ok"] = False
        validation["issues"] = list(dict.fromkeys(
            [*validation.get("issues", []), *execution_issues]
        ))
    validation["length_ok"] = chinese_char_count >= _MIN_CHINESE_CHARS
    if not validation["length_ok"] and not any(
        "长度" in issue or "字符" in issue for issue in validation["issues"]
    ):
        validation["issues"].append(
            f"正文中文字符数为 {chinese_char_count}，低于 {_MIN_CHINESE_CHARS}"
        )
    if not validation["overall_ok"] and not validation["issues"]:
        validation["issues"] = ["Validator 未提供可执行的问题说明"]
    if not validation["length_ok"]:
        validation["overall_ok"] = False
    result = {"story_validation": validation}
    if state.get("story_repair_count", 0):
        result["story_revalidation"] = validation
    else:
        result["first_story_validation"] = validation
    return result


def _should_repair_story(state):
    validation = state.get("story_validation") or {}
    return (
        validation.get("overall_ok") is False
        and validation.get("repairable") is True
        and not state.get("story_repair_count", 0)
    )


def story_failure_type(validation):
    if validation.get("overall_ok"):
        return None
    return "rule" if validation.get("length_ok") is False else "semantic"


def story_follow_up(validation_ok, repair_occurred):
    if not validation_ok:
        return "rejected"
    return "rewritten" if repair_occurred else "accepted"


def export_node(state):
    story = state["story"]
    text = _story_text(story)
    chinese_char_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    validation = state["story_validation"]
    repair_occurred = bool(state.get("story_repair_count"))
    follow_up_action = story_follow_up(bool(validation.get("overall_ok")), repair_occurred)
    result = {
        "source_outline_id": state["outline_id"],
        "source_outline": state["outline_data"],
        "function_constraints": state["function_constraints"],
        "scene_plan": state["scene_plan"],
        "scene_developments": state["scene_developments"],
        "story": story,
        "chinese_char_count": chinese_char_count,
        "length_ok": chinese_char_count >= _MIN_CHINESE_CHARS,
        "story_validation": validation,
        "first_story_validation": state.get("first_story_validation"),
        "story_revalidation": state.get("story_revalidation"),
        "story_repair_count": state.get("story_repair_count", 0),
        "story_status": follow_up_action,
        "needs_human_review": follow_up_action == "rejected",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    outcome_id = StoryKnowledgeStore(state["knowledge_db"]).record_generation_outcome(
        state["outline_data"]["snapshot_id"], None,
        state["outline_id"], state["outline_data"].get("planner_mode", "published"),
        bool(validation.get("overall_ok")), repair_occurred,
        story_failure_type(validation), follow_up_action,
        {
            "generation_stage": "story",
            "pattern_id": state["outline_data"].get("pattern_id"),
            "first_issues": (state.get("first_story_validation") or {}).get("issues", []),
            "first_validation": state.get("first_story_validation"),
            "repair_occurred": repair_occurred,
            "revalidation": state.get("story_revalidation"),
            "final_status": follow_up_action,
            "chinese_char_count": chinese_char_count,
        },
    )
    result["generation_outcome_id"] = outcome_id
    os.makedirs(state["out_dir"], exist_ok=True)
    base = f"{state['outline_id']}_story_{time.strftime('%Y%m%dT%H%M%S')}"
    json_path = os.path.join(state["out_dir"], base + ".json")
    md_path = os.path.join(state["out_dir"], base + ".md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_render_markdown(story))
    return {"result_path": json_path}


def _build_graph():
    graph = StateGraph(StoryState)
    graph.add_node("load_outline", load_outline_node)
    graph.add_node("function_constraints", function_constraints_node)
    graph.add_node("plan_scenes", plan_scenes_node)
    graph.add_node("develop_scenes", develop_scenes_node)
    graph.add_node("write_story", write_story_node)
    graph.add_node("validate_story", validate_story_node)
    graph.add_node("export", export_node)
    graph.add_edge(START, "load_outline")
    graph.add_edge("load_outline", "function_constraints")
    graph.add_edge("function_constraints", "plan_scenes")
    graph.add_edge("plan_scenes", "develop_scenes")
    graph.add_edge("develop_scenes", "write_story")
    graph.add_edge("write_story", "validate_story")
    graph.add_conditional_edges(
        "validate_story",
        lambda state: "write_story" if _should_repair_story(state) else "export",
        {"write_story": "write_story", "export": "export"},
    )
    graph.add_edge("export", END)
    return graph.compile()


def main():
    parser = argparse.ArgumentParser(description="按已生成大纲写成中文短篇正文")
    parser.add_argument("--outline-id", required=True, help="知识库中的大纲 ID")
    parser.add_argument("--knowledge-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--request", default=None, help="用户创作要求")
    parser.add_argument("--out-dir", default=None, help="正文输出目录")
    args = parser.parse_args()
    result = _build_graph().invoke({
        "outline_id": args.outline_id,
        "knowledge_db": args.knowledge_db,
        "user_request": args.request,
        "out_dir": args.out_dir,
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
    with open(result["result_path"], encoding="utf-8") as f:
        exported = json.load(f)
    print(f"[Story] result={result['result_path']}")
    print(f"[Story] chinese_char_count={exported['chinese_char_count']}")
    print(f"[Story] length_ok={exported['length_ok']}")


if __name__ == "__main__":
    main()
