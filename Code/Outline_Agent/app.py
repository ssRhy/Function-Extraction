"""Outline Agent - 按题材生成单轮短篇大纲。

线性图：START → planner → seed → mechanism → scaffold → realize → validate → export → END
读取知识库与派生索引，完整大纲写入知识库并导出 JSON/Markdown。

用法（Code/ 下）：
    python -X utf8 -m Outline_Agent --genre 悬疑惊悚
"""

import argparse
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VENDOR = os.path.join(_ROOT, "vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

from langgraph.graph import StateGraph, START, END

from FunctionExtract_Agent.llm import chat_structured
from Contracts.ledger import build_contract_ledger
from KnowledgeBase import DEFAULT_DB_PATH, StoryKnowledgeStore

from Outline_Agent.state import (
    OutlineState,
    StorySeed,
    MechanismPlan,
    NarrativePlan,
    OutlineRealization,
    OutlineValidation,
    PatternSelection,
)
from Outline_Agent.Prompt.Outline_prompt import (
    NARRATIVE_PROMPT,
    MECH_PROMPT,
    PATTERN_SELECTION_PROMPT,
    REALIZE_PROMPT,
    SEED_PROMPT,
    VALIDATE_PROMPT,
)


_DATA = os.path.join(_ROOT, "data")
_GENRE_KEYS = ["01_悬疑惊悚", "02_古风仙侠", "03_现代情感", "04_末世科幻", "05_现实家庭职场"]


# ---------- 输入加载 ----------

def load_catalog(snapshot_id, knowledge_db=DEFAULT_DB_PATH):
    return StoryKnowledgeStore(knowledge_db).load_pattern_catalog(snapshot_id)


def load_cards(snapshot_id):
    path = os.path.join(_DATA, "function_cards", snapshot_id, "function_cards.jsonl")
    if not os.path.isfile(path):
        return {}
    return {
        card["function_name"]: card
        for card in (json.loads(line) for line in open(path, encoding="utf-8") if line.strip())
    }


def load_contracts(snapshot_id, knowledge_db=DEFAULT_DB_PATH):
    return {
        item["function_id"]: item
        for item in StoryKnowledgeStore(knowledge_db).load_contracts(snapshot_id)
    }


def load_mechanisms(snapshot_id):
    path = os.path.join(_DATA, "transition_index", snapshot_id, "transition_index.json")
    if not os.path.isfile(path):
        return {}
    return json.load(open(path, encoding="utf-8"))["mechanisms"]


# ---------- 纯函数 ----------

def normalize_genre(genre):
    for key in _GENRE_KEYS:
        if genre in (key, key.split("_", 1)[1]):
            return key
    raise ValueError(f"未知题材: {genre}（可选：{', '.join(_GENRE_KEYS)}）")


def candidate_patterns(catalog, genre):
    published = catalog["published_patterns"]
    candidates = [p for p in published if genre in p.get("category_counts", {})]
    pool = candidates or published
    return sorted(pool, key=lambda p: (
        not bool(p.get("ending_spec")),
        -p.get("story_support", 0),
        p.get("pattern_name", ""),
    ))


def available_patterns(catalog, genre, knowledge_db=DEFAULT_DB_PATH):
    used = StoryKnowledgeStore(knowledge_db).used_pattern_ids()
    return [
        pattern for pattern in candidate_patterns(catalog, genre)
        if pattern.get("pattern_id") not in used
    ]


def annotate_occurrences(chain):
    """为链上每个 Function 标注第几次出现/共几次，供重复段递进使用。"""
    total = {}
    for step in chain:
        name = step["function_name"]
        total[name] = total.get(name, 0) + 1
    seen = {}
    for step in chain:
        name = step["function_name"]
        seen[name] = seen.get(name, 0) + 1
        step["occurrence_index"] = seen[name]
        step["occurrence_total"] = total[name]
    return chain


def planner(catalog, cards, genre, pattern_name=None, contracts=None):
    ordered = candidate_patterns(catalog, genre)
    if pattern_name:
        pattern = next((p for p in ordered if p["pattern_name"] == pattern_name), None)
        if pattern is None:
            raise ValueError(f"题材 {genre} 下没有 pattern: {pattern_name}")
    else:
        pattern = ordered[0]
    chain = []
    for index, step in enumerate(pattern["core_function_chain"], 1):
        name = step["function_name"]
        abstraction = (cards.get(name) or {}).get("abstraction") or {}
        snapshot_contract = (contracts or {}).get(step.get("function_id"))
        pattern_contract = step.get("contract")
        if snapshot_contract and pattern_contract and snapshot_contract != pattern_contract:
            raise ValueError(f"Pattern 与 Snapshot Contract 不一致: {name}")
        contract = snapshot_contract or pattern_contract
        if contracts and contract is None:
            raise ValueError(f"Pattern 缺少 FunctionContract: {name}")
        chain.append({
            "segment_index": index,
            "function_name": name,
            "definition": step.get("definition", ""),
            "preconditions": (
                contract.get("preconditions", [])
                if contract else abstraction.get("preconditions", [])
            ),
            "role_slots": (
                contract.get("role_slots", [])
                if contract else abstraction.get("role_slots", [])
            ),
            "state_transition": abstraction.get("state_transition", {}),
            "contract": contract or {},
        })
    return pattern, annotate_occurrences(chain)


def _compact_chain(chain):
    return [
        {k: step[k] for k in (
            "segment_index", "function_name", "definition", "preconditions", "role_slots", "state_transition",
            "contract", "occurrence_index", "occurrence_total",
        )}
        for step in chain
    ]


def _align(chain, items):
    """按唯一的 segment_index 重排并校验 LLM 输出。"""
    expected = [step["segment_index"] for step in chain]
    by_index = {item["segment_index"]: item for item in items}
    if len(by_index) != len(items) or set(by_index) != set(expected):
        raise ValueError("LLM 输出必须覆盖每个唯一 segment_index，且不能重复")
    aligned = []
    for step in chain:
        item = by_index[step["segment_index"]]
        if item["function_name"] != step["function_name"]:
            raise ValueError(f"segment_index={step['segment_index']} 的 Function 与链不一致")
        aligned.append(item)
    return aligned


def rule_check(chain, outline, ending_spec=None):
    issues = []
    actual = [segment["function_name"] for segment in outline["segments"]]
    target = [step["function_name"] for step in chain]
    if actual != target:
        issues.append(f"段顺序/覆盖不一致: {actual} != {target}")
    by_name = {}
    for segment in outline["segments"]:
        by_name.setdefault(segment["function_name"], []).append(tuple(segment["beats"]))
    for name, beat_sets in by_name.items():
        if len(beat_sets) > 1 and len(set(beat_sets)) == 1:
            issues.append(f"重复 Function 未递进：{name} 的重复段落情节完全相同")
    ending = outline.get("ending") or {}
    if not ending:
        issues.append("大纲缺少独立的结局收束 ending")
    else:
        for field in ("resolution_actions", "conflict_resolution", "final_state"):
            if not ending.get(field):
                issues.append(f"结局收束缺少 {field}")
    return issues


def narrative_plan_issues(chain, narrative):
    issues = []
    last_index = len(chain)
    for step in narrative["steps"]:
        current = step["segment_index"]
        for setup in step["setup_payoffs"]:
            target = setup.get("payoff_segment_index")
            if target is not None and (target <= current or target > last_index):
                issues.append(
                    f"segment_index={current} 的伏笔兑现位置必须是后续段或 ending"
                )
    return issues


# ---------- 节点 ----------

def select_pattern_node(state):
    if state.get("pattern_request") or not state.get("user_request"):
        return {}
    catalog = load_catalog(state["snapshot_id"], state["knowledge_db"])
    candidates = available_patterns(catalog, state["genre"], state["knowledge_db"])
    if not candidates:
        raise ValueError(f"题材 {state['genre']} 没有可用 Pattern")
    user = {
        "genre": state["genre"],
        "user_request": state["user_request"],
        "candidates": [
            {
                "candidate_index": index,
                "pattern_name": pattern["pattern_name"],
                "story_support": pattern.get("story_support", 0),
                "function_chain": [
                    step["function_name"] for step in pattern["core_function_chain"]
                ],
                "ending_spec": pattern.get("ending_spec"),
            }
            for index, pattern in enumerate(candidates, 1)
        ],
    }
    choice = chat_structured([
        {"role": "system", "content": PATTERN_SELECTION_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ], PatternSelection).model_dump()
    index = choice["candidate_index"]
    if index > len(candidates):
        raise ValueError(f"Pattern 选择序号无效: {index}")
    return {
        "pattern_request": candidates[index - 1]["pattern_name"],
        "pattern_selection": choice,
    }

def planner_node(state):
    catalog = load_catalog(state["snapshot_id"], state["knowledge_db"])
    all_candidates = candidate_patterns(catalog, state["genre"])
    available = available_patterns(catalog, state["genre"], state["knowledge_db"])
    pattern_request = state.get("pattern_request")
    if pattern_request and not any(
        pattern.get("pattern_name") == pattern_request for pattern in available
    ):
        if any(pattern.get("pattern_name") == pattern_request for pattern in all_candidates):
            raise ValueError(f"Pattern 已使用或不可用: {pattern_request}")
        raise ValueError(f"题材 {state['genre']} 下没有 pattern: {pattern_request}")
    if not available:
        raise ValueError(f"题材 {state['genre']} 没有可用 Pattern")
    catalog = {**catalog, "published_patterns": available}
    contracts = load_contracts(state["snapshot_id"], state["knowledge_db"])
    cards = load_cards(state["snapshot_id"])
    if not contracts and not cards:
        raise ValueError(f"Snapshot {state['snapshot_id']} 没有 FunctionContract 或 Function Card")
    pattern, chain = planner(
        catalog, cards, state["genre"], pattern_request, contracts,
    )
    pattern_id = pattern.get("pattern_id")
    if not pattern_id:
        raise ValueError(f"Pattern 缺少稳定 ID: {pattern['pattern_name']}")
    return {
        "pattern_id": pattern_id,
        "pattern_name": pattern["pattern_name"],
        "ending_spec": pattern.get("ending_spec"),
        "chain": chain,
    }


def seed_node(state):
    user = {
        "genre": state["genre"],
        "chain": _compact_chain(state["chain"]),
        "ending_spec": state.get("ending_spec"),
        "user_request": state.get("user_request"),
    }
    seed = chat_structured([
        {"role": "system", "content": SEED_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ], StorySeed).model_dump()
    return {"seed": seed}


def mechanism_node(state):
    user = {
        "chain": _compact_chain(state["chain"]),
        "seed": state["seed"],
    }
    data = chat_structured([
        {"role": "system", "content": MECH_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ], MechanismPlan).model_dump()
    data["steps"] = _align(state["chain"], data["steps"])
    ledger = build_contract_ledger(state["chain"], data["steps"], state["seed"])
    return {"mechanism": data, "contract_ledger": ledger}


def scaffold_node(state):
    mechanisms = load_mechanisms(state["snapshot_id"])
    hints = {
        step["function_name"]: [
            item["surface_form"]
            for item in mechanisms.get(step["function_name"], {}).get("mechanisms", [])[:3]
        ]
        for step in state["chain"]
    }
    user = {
        "chain": _compact_chain(state["chain"]),
        "seed": state["seed"],
        "mechanism_plan": state["mechanism"],
        "reference_mechanisms": hints,
        "ending_spec": state.get("ending_spec"),
    }
    messages = [
        {"role": "system", "content": NARRATIVE_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]
    for attempt in range(2):
        data = chat_structured(messages, NarrativePlan).model_dump()
        data["steps"] = _align(state["chain"], data["steps"])
        issues = narrative_plan_issues(state["chain"], data)
        if not issues:
            return {"narrative": data}
        if attempt == 0:
            messages = messages + [{
                "role": "user",
                "content": (
                    "叙事展开方案存在确定性错误：" + "；".join(issues)
                    + "。请只修正 payoff_segment_index：只能填当前链中后续段的整数，"
                    "最后一段只能填 null；保持其他内容不变，并重新输出完整 JSON。"
                ),
            }]
    raise ValueError("叙事展开方案不合法: " + "；".join(issues))


def realize_node(state):
    user = {
        "chain": _compact_chain(state["chain"]),
        "ending_spec": state.get("ending_spec"),
        "seed": state["seed"],
        "mechanism_plan": state["mechanism"],
        "narrative_plan": state["narrative"],
        "contract_ledger": state.get("contract_ledger"),
    }
    data = chat_structured([
        {"role": "system", "content": REALIZE_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ], OutlineRealization).model_dump()
    data["segments"] = _align(state["chain"], data["segments"])
    return {"outline": data}


def validate_node(state):
    validation_ledger = dict(state.get("contract_ledger") or {})
    validation_ledger.pop("warnings", None)
    user = {
        "target_chain": [
            {"segment_index": step["segment_index"], "function_name": step["function_name"]}
            for step in state["chain"]
        ],
        "ending_spec": state.get("ending_spec"),
        "seed": state["seed"],
        "mechanism_plan": state["mechanism"],
        "narrative_plan": state["narrative"],
        "outline": state["outline"],
        "contract_ledger": validation_ledger,
    }
    data = chat_structured([
        {"role": "system", "content": VALIDATE_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ], OutlineValidation).model_dump()
    data["rule_issues"] = rule_check(
        state["chain"], state["outline"], state.get("ending_spec"),
    )
    if data["rule_issues"]:
        data["overall_ok"] = False
        data["issues"] = list(data.get("issues", [])) + data["rule_issues"]
    contract_ledger = state.get("contract_ledger") or {}
    data["contract_issues"] = list(dict.fromkeys(contract_ledger.get("issues", [])))
    data["contract_warnings"] = list(dict.fromkeys(contract_ledger.get("warnings", [])))
    if data["contract_issues"]:
        data["overall_ok"] = False
        data["issues"] = list(data.get("issues", [])) + data["contract_issues"]
    return {"validation": data}


def _render_markdown(result):
    lines = [
        f"# 大纲：{result['pattern_name']}（{result['genre']}）",
        "",
        f"核心链：{' → '.join(result['chain'])}",
        "",
        "## 故事种子",
        f"- 世界观：{result['seed']['world_setting']}",
        f"- 核心冲突：{result['seed']['core_conflict']}",
        f"- 结局方向：{result['seed']['ending_direction']}",
        "",
        "## 人物",
    ]
    for char in result["seed"]["characters"]:
        lines.append(f"- {char['id']}（{char['label']} · {char['role']}）：{char['goal']}")
    lines.append("")
    lines.append("## 分段大纲")
    for index, segment in enumerate(result["outline"]["segments"], 1):
        lines.append(f"### {index}. {segment['function_name']}")
        for beat in segment["beats"]:
            lines.append(f"{beat}")
        if segment.get("link"):
            lines.append(f"衔接：{segment['link']}")
        lines.append("")
    ending = result["outline"].get("ending")
    if ending:
        lines.append("## 结局兑现")
        lines.append(f"- 解决动作：{'；'.join(ending['resolution_actions'])}")
        lines.append(f"- 冲突解决：{ending['conflict_resolution']}")
        lines.append(f"- 稳定终态：{ending['final_state']}")
        lines.append("")
    lines.append("## 校验")
    lines.append(f"- overall_ok: {result['validation']['overall_ok']}")
    lines.append(f"- rule_issues: {result['validation']['rule_issues'] or '无'}")
    lines.append(f"- contract_issues: {result['validation'].get('contract_issues') or '无'}")
    lines.append(f"- contract_warnings: {result['validation'].get('contract_warnings') or '无'}")
    if result.get("contract_ledger"):
        lines.append(f"- contract_obligations: {result['contract_ledger'].get('obligations') or '无'}")
    for check in result["validation"]["segment_checks"]:
        lines.append(f"- {check['function_name']}: recoverable={check['recoverable']} {check['issue']}")
    return "\n".join(lines) + "\n"


def export_node(state):
    result = {
        "schema_version": 1,
        "snapshot_id": state["snapshot_id"],
        "pattern_id": state.get("pattern_id"),
        "pattern_name": state["pattern_name"],
        "genre": state["genre"],
        "user_request": state.get("user_request"),
        "ending_spec": state.get("ending_spec"),
        "chain": [step["function_name"] for step in state["chain"]],
        "seed": state["seed"],
        "mechanism_plan": state["mechanism"],
        "narrative_plan": state["narrative"],
        "contract_ledger": state.get("contract_ledger"),
        "outline": state["outline"],
        "validation": state["validation"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    markdown = _render_markdown(result)
    outline_id = StoryKnowledgeStore(state["knowledge_db"]).record_outline(result, markdown)
    result["outline_id"] = outline_id
    os.makedirs(state["out_dir"], exist_ok=True)
    base = f"{state['genre'].split('_', 1)[1]}_{time.strftime('%Y%m%dT%H%M%S')}"
    json_path = os.path.join(state["out_dir"], base + ".json")
    md_path = os.path.join(state["out_dir"], base + ".md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    return {"outline_id": outline_id, "result_path": json_path}


def _build_graph():
    graph = StateGraph(OutlineState)
    graph.add_node("select_pattern", select_pattern_node)
    graph.add_node("planner", planner_node)
    graph.add_node("seed", seed_node)
    graph.add_node("mechanism", mechanism_node)
    graph.add_node("scaffold", scaffold_node)
    graph.add_node("realize", realize_node)
    graph.add_node("validate", validate_node)
    graph.add_node("export", export_node)
    graph.add_edge(START, "select_pattern")
    graph.add_edge("select_pattern", "planner")
    graph.add_edge("planner", "seed")
    graph.add_edge("seed", "mechanism")
    graph.add_edge("mechanism", "scaffold")
    graph.add_edge("scaffold", "realize")
    graph.add_edge("realize", "validate")
    graph.add_edge("validate", "export")
    graph.add_edge("export", END)
    return graph.compile()


def main():
    parser = argparse.ArgumentParser(description="按题材生成单轮短篇大纲")
    parser.add_argument("--genre", required=True, help="题材（如 悬疑惊悚 或 01_悬疑惊悚）")
    parser.add_argument("--pattern", default=None, help="指定 pattern 名称（题材内，配合 --list-patterns 查看）")
    parser.add_argument("--list-patterns", action="store_true", help="列出题材下的候选 pattern 后退出")
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--knowledge-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--request", default=None, help="用户故事要求")
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    genre = normalize_genre(args.genre)
    if args.list_patterns:
        for index, pattern in enumerate(available_patterns(
            load_catalog(args.snapshot_id, args.knowledge_db), genre, args.knowledge_db,
        ), 1):
            chain = [step["function_name"] for step in pattern["core_function_chain"]]
            print(f"{index}. {pattern['pattern_name']} (support={pattern['story_support']}) -> {' -> '.join(chain)}")
        return
    out_dir = args.out_dir or os.path.join(_DATA, "outlines", args.snapshot_id)
    app = _build_graph()
    result = app.invoke({
        "snapshot_id": args.snapshot_id,
        "knowledge_db": args.knowledge_db,
        "genre": genre,
        "out_dir": out_dir,
        "pattern_request": args.pattern,
        "user_request": args.request,
        "pattern_id": None,
        "pattern_name": "",
        "pattern_selection": None,
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
    print(f"[Planner] FOLLOW pattern={result['pattern_name']}")
    print(f"[Planner] chain={result['chain']}")
    print(f"[Validate] overall_ok={validation.get('overall_ok')}")
    print(f"[Validate] rule_issues={validation.get('rule_issues') or '无'}")
    print(f"[Outline] outline_id={result['outline_id']}")
    if validation.get("rule_issues") or not validation.get("overall_ok"):
        print(f"[Validate] 校验未通过，产物仍保留 -> {result['result_path']}")
    else:
        print(f"大纲已生成 -> {result['result_path']}")


if __name__ == "__main__":
    main()
