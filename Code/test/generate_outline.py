"""最小冒烟：一条 core_function_chain → 一份单轮短篇大纲。

验证 Phase 3 五节点的职责与数据流（不建 Agent、不铺图）：
Planner（确定性 FOLLOW）→ StorySeed → MechanismPlan → OutlineRealizer → Validator

用法（Code/ 下）：
    python -X utf8 test/generate_outline.py [题材]
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pydantic import BaseModel, Field

from Agent.llm import chat_structured


SNAPSHOT_ID = "evolve_250_20260822T063550401096Z_13b1bbda248f"
_DATA = os.path.join(os.path.dirname(__file__), "..", "data")


# ---------- 输入加载 ----------

def load_catalog():
    path = os.path.join(_DATA, "story_pattern_evolve_250", "pattern_catalog.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_cards():
    path = os.path.join(_DATA, "function_cards", SNAPSHOT_ID, "function_cards.jsonl")
    return {
        card["function_name"]: card
        for card in (json.loads(line) for line in open(path, encoding="utf-8") if line.strip())
    }


def load_mechanisms():
    path = os.path.join(_DATA, "transition_index", SNAPSHOT_ID, "transition_index.json")
    return json.load(open(path, encoding="utf-8"))["mechanisms"]


# ---------- Planner（确定性 FOLLOW） ----------

def planner(catalog, cards):
    pattern = max(
        catalog["published_patterns"],
        key=lambda p: (p.get("story_support", 0), p.get("pattern_name", "")),
    )
    chain = []
    for step in pattern["core_function_chain"]:
        name = step["function_name"]
        abstraction = (cards.get(name) or {}).get("abstraction") or {}
        chain.append({
            "function_name": name,
            "definition": step.get("definition", ""),
            "preconditions": abstraction.get("preconditions", []),
            "role_slots": abstraction.get("role_slots", []),
            "state_transition": abstraction.get("state_transition", {}),
        })
    return pattern, chain


# ---------- Schema ----------

class SeedCharacter(BaseModel):
    id: str = Field(description="稳定人物 ID，如 P1")
    label: str = Field(description="身份标签，如 女主/对立方")
    role: str = Field(description="结构角色，如 hero/opponent/helper/love_interest")
    goal: str = Field(description="目标")


class StorySeed(BaseModel):
    genre: str
    world_setting: str
    characters: list[SeedCharacter]
    core_conflict: str
    ending_direction: str


class MechanismStep(BaseModel):
    function_name: str
    role_bindings: dict[str, str] = Field(description="role_slot -> 人物ID")
    who_does_what: str
    why: str
    state_change: str
    connects_to_next: str


class MechanismPlan(BaseModel):
    steps: list[MechanismStep]


class OutlineSegment(BaseModel):
    function_name: str
    beats: list[str]


class OutlineRealization(BaseModel):
    segments: list[OutlineSegment]
    final_ledger: list[str]


class SegmentCheck(BaseModel):
    function_name: str
    recoverable: bool
    issue: str


class OutlineValidation(BaseModel):
    segment_checks: list[SegmentCheck]
    overall_ok: bool
    issues: list[str]


# ---------- 提示词（均需含 "JSON"，供 json_object 模式） ----------

_SEED_PROMPT = """你是网文大纲策划。给定一条 Function 序列（叙事结构骨架），生成故事种子。只输出 JSON，字段名严格如下：
{
  "genre": "题材",
  "world_setting": "世界观",
  "characters": [{"id": "稳定ID如P1", "label": "身份标签如女主/对立方", "role": "结构角色如hero/opponent/helper/love_interest", "goal": "目标"}],
  "core_conflict": "核心冲突",
  "ending_direction": "结局方向"
}
人物数量最少，能覆盖序列所需角色槽位即可，不写姓名。"""

_MECH_PROMPT = """你是叙事机制规划者。给定 Function 序列（含角色槽位、状态变化、参考实现机制）、故事种子人物，为每个 Function 生成实例化方案。只输出 JSON，字段名严格如下：
{"steps": [{"function_name": "函数名", "role_bindings": {"角色槽位": "人物ID"}, "who_does_what": "谁对谁做什么", "why": "为何发生", "state_change": "状态怎么变", "connects_to_next": "怎么连接下一步"}]}"""

_REALIZE_PROMPT = """你是大纲实现者。给定 Function 序列、故事种子和机制方案，按顺序写成分段大纲。只输出 JSON，字段名严格如下：
{"segments": [{"function_name": "函数名", "beats": ["情节点1", "情节点2"]}], "final_ledger": ["人物目标/关系/秘密/资源/未解决冲突/世界规则"]}
每段对应一个 Function，2-4 个情节点。"""

_VALIDATE_PROMPT = """你是大纲校验者。给定目标 Function 序列、故事种子和分段大纲，逐段检查情节能否恢复出目标 Function，并检查前置条件、状态连续性、角色一致性、结局闭合。只输出 JSON，字段名严格如下：
{"segment_checks": [{"function_name": "函数名", "recoverable": true, "issue": "问题或空"}], "overall_ok": true, "issues": ["总体问题"]}"""


# ---------- 五节点 ----------

def _compact_chain(chain):
    return [
        {k: step[k] for k in ("function_name", "definition", "preconditions", "role_slots", "state_transition")}
        for step in chain
    ]


def _align(chain, items, key):
    """按 chain 顺序确定性重排 LLM 输出，核心链顺序不交给 LLM 自由发挥。"""
    by_key = {item[key]: item for item in items}
    return [by_key[step["function_name"]] for step in chain]


def seed_story(chain, genre):
    user = {"genre": genre, "chain": _compact_chain(chain)}
    return chat_structured([
        {"role": "system", "content": _SEED_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ], StorySeed).model_dump()


def mechanism_plan(chain, seed, mechanisms):
    hints = {
        step["function_name"]: [
            item["surface_form"]
            for item in mechanisms.get(step["function_name"], {}).get("mechanisms", [])[:3]
        ]
        for step in chain
    }
    user = {"chain": _compact_chain(chain), "reference_mechanisms": hints, "seed": seed}
    data = chat_structured([
        {"role": "system", "content": _MECH_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ], MechanismPlan).model_dump()
    data["steps"] = _align(chain, data["steps"], "function_name")
    return data


def realize(chain, seed, mechanism):
    user = {"chain": _compact_chain(chain), "seed": seed, "mechanism_plan": mechanism}
    data = chat_structured([
        {"role": "system", "content": _REALIZE_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ], OutlineRealization).model_dump()
    data["segments"] = _align(chain, data["segments"], "function_name")
    return data


def validate(chain, seed, outline):
    user = {
        "target_chain": [step["function_name"] for step in chain],
        "seed": seed,
        "outline": outline,
    }
    return chat_structured([
        {"role": "system", "content": _VALIDATE_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ], OutlineValidation).model_dump()


def rule_check(chain, outline):
    actual = [segment["function_name"] for segment in outline["segments"]]
    target = [step["function_name"] for step in chain]
    return [] if actual == target else [f"段顺序/覆盖不一致: {actual} != {target}"]


def main():
    genre = sys.argv[1] if len(sys.argv) > 1 else "悬疑惊悚"
    catalog = load_catalog()
    cards = load_cards()
    mechanisms = load_mechanisms()
    pattern, chain = planner(catalog, cards)
    print(f"[Planner] FOLLOW pattern={pattern['pattern_name']}")
    print(f"[Planner] chain={[step['function_name'] for step in chain]}")

    seed = seed_story(chain, genre)
    mechanism = mechanism_plan(chain, seed, mechanisms)
    outline = realize(chain, seed, mechanism)
    validation = validate(chain, seed, outline)
    validation["rule_issues"] = rule_check(chain, outline)

    result = {
        "snapshot_id": SNAPSHOT_ID,
        "pattern_name": pattern["pattern_name"],
        "genre": genre,
        "chain": [step["function_name"] for step in chain],
        "seed": seed,
        "mechanism_plan": mechanism,
        "outline": outline,
        "validation": validation,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    out_dir = os.path.join(_DATA, "outlines", SNAPSHOT_ID)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"smoke_{genre}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({
        "seed": seed,
        "mechanism_plan": mechanism,
        "outline": outline,
        "validation": validation,
    }, ensure_ascii=False, indent=2))
    print(f"已保存 -> {out_path}")


if __name__ == "__main__":
    main()
