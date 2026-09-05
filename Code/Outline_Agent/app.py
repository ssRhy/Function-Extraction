"""Outline Agent - 按题材生成单轮短篇大纲。

图流程：published 走 Pattern 选择；dynamic 走 dynamic_seed → dynamic_planner；两者随后共用
mechanism → scaffold → realize → validate → export → END。
读取知识库与派生索引，完整大纲写入知识库并导出 JSON/Markdown。

用法（Code/ 下）：
    python -X utf8 -m Outline_Agent --genre 悬疑惊悚
"""

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VENDOR = os.path.join(_ROOT, "vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

from langgraph.graph import StateGraph, START, END

from FunctionExtract_Agent.llm import chat_structured
from Contracts.function_contract import relationship_effects
from Contracts.ledger import build_contract_ledger, normalize_relationship_befores
from Contracts.role_projection import project_role_references
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
    DYNAMIC_SEED_PROMPT,
    NARRATIVE_PROMPT,
    MECH_PROMPT,
    PATTERN_SELECTION_PROMPT,
    REALIZE_PROMPT,
    SEED_PROMPT,
    VALIDATE_PROMPT,
)
from Outline_Agent.dynamic_planner import plan_dynamic_outline


_DATA = os.path.join(_ROOT, "data")
_GENRE_KEYS = ["01_悬疑惊悚", "02_古风仙侠", "03_现代情感", "04_末世科幻", "05_现实家庭职场"]


# ---------- 输入加载 ----------

def load_catalog(snapshot_id, knowledge_db=DEFAULT_DB_PATH):
    return StoryKnowledgeStore(knowledge_db).load_pattern_catalog(snapshot_id)


def load_contracts(snapshot_id, knowledge_db=DEFAULT_DB_PATH):
    return {
        item["function_id"]: item
        for item in StoryKnowledgeStore(knowledge_db).load_contracts(snapshot_id)
    }


def _occurrence_sort_key(occurrence):
    order = occurrence.get("observation_order")
    if isinstance(order, int) and order > 0:
        return order, 0, occurrence.get("occurrence_id", "")
    indices = occurrence.get("source_sentence_indices") or []
    return min(indices) if indices else 0, 1, occurrence.get("occurrence_id", "")


def build_function_transitions(occurrences):
    """从冻结 Snapshot 的 MATCHED occurrence 统计 Function 邻接转移。"""
    by_story = defaultdict(list)
    for occurrence in occurrences:
        if occurrence.get("status") == "MATCHED" and occurrence.get("function_name"):
            by_story[occurrence.get("story_id", "")].append(occurrence)

    counts = Counter()
    stories = defaultdict(set)
    for story_id, items in by_story.items():
        previous = None
        for occurrence in sorted(items, key=_occurrence_sort_key):
            current = occurrence["function_name"]
            if current == previous:
                continue
            if previous is not None:
                counts[(previous, current)] += 1
                stories[(previous, current)].add(story_id)
            previous = current

    result = defaultdict(list)
    for (source, target), count in counts.items():
        result[source].append({
            "from": source,
            "to": target,
            "count": count,
            "support_stories": len(stories[(source, target)]),
        })
    return {
        source: sorted(items, key=lambda item: (-item["count"], item["to"]))
        for source, items in result.items()
    }


def _motif_references(pattern, rows):
    motif_ids = set(pattern.get("member_motif_ids") or [])
    references = []
    for row in rows:
        if row.get("motif_id") not in motif_ids:
            continue
        references.append({
            "motif_id": row["motif_id"],
            "function_ids": row.get("function_ids", []),
            "function_names": row.get("function_names", []),
            "length": row.get("length", 0),
            "evidence": row.get("evidence", {}),
        })
    return references


def _instance_cases(functions, occurrences, chain):
    occurrences_by_id = {
        item.get("occurrence_id"): item
        for item in occurrences
        if item.get("occurrence_id")
    }
    functions_by_id = {
        item.get("function_id"): item
        for item in functions
        if item.get("function_id")
    }
    functions_by_name = {item.get("function_name"): item for item in functions}
    cases = {}
    for step in chain:
        name = step["function_name"]
        function = functions_by_id.get(step.get("function_id")) or functions_by_name.get(name)
        supporting_ids = (function or {}).get("supporting_obs_ids", [])
        candidates = [occurrences_by_id[item] for item in supporting_ids if item in occurrences_by_id]
        if not candidates:
            candidates = [item for item in occurrences if item.get("function_name") == name]
        selected = []
        seen_forms = set()
        for occurrence in sorted(candidates, key=_occurrence_sort_key):
            surface_form = str(occurrence.get("surface_form") or "").strip()
            if not surface_form or surface_form in seen_forms:
                continue
            seen_forms.add(surface_form)
            selected.append({
                "occurrence_id": occurrence["occurrence_id"],
                "story_id": occurrence.get("story_id", ""),
                "surface_form": surface_form,
                "event": occurrence.get("event", ""),
                "before_state": occurrence.get("before_state", ""),
                "after_state": occurrence.get("after_state", ""),
            })
            if len(selected) == 3:
                break
        cases[name] = selected
    return cases


def load_planner_references(snapshot_id, pattern, chain, knowledge_db=DEFAULT_DB_PATH):
    """读取 Planner 的三类只读参考：转移、所选 motif 和真实实例。"""
    store = StoryKnowledgeStore(knowledge_db)
    functions = store.load_functions(snapshot_id)
    occurrences = store.load_occurrences(snapshot_id)
    motifs = _motif_references(pattern, store.load_motif_evidence(snapshot_id))
    transitions = build_function_transitions(occurrences)
    role_references = project_role_references(
        functions, store.load_contracts(snapshot_id), occurrences,
        store.load_story_profiles(snapshot_id),
    )
    names = {step["function_name"] for step in chain}
    return {
        "motifs": motifs,
        "transitions": {
            name: transitions.get(name, [])[:3]
            for name in names
            if transitions.get(name)
        },
        "instance_cases": _instance_cases(functions, occurrences, chain),
        **role_references,
    }


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


def planner(catalog, genre, pattern_name=None, contracts=None, references=None):
    references = references or {}
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
        snapshot_contract = (contracts or {}).get(step.get("function_id"))
        pattern_contract = step.get("contract")
        if snapshot_contract and pattern_contract and snapshot_contract != pattern_contract:
            raise ValueError(f"Pattern 与 Snapshot Contract 不一致: {name}")
        contract = snapshot_contract or pattern_contract
        if contracts and contract is None:
            raise ValueError(f"Pattern 缺少 FunctionContract: {name}")
        chain.append({
            "segment_index": index,
            "function_id": step.get("function_id"),
            "function_name": name,
            "definition": step.get("definition", ""),
            "preconditions": contract.get("preconditions", []) if contract else [],
            "role_slots": contract.get("role_slots", []) if contract else [],
            "contract": contract or {},
            "reference_transitions": references.get("transitions", {}).get(name, []),
            "reference_instance_cases": references.get("instance_cases", {}).get(name, []),
            "reference_role_stats": references.get("role_stats", {}).get(name, {}),
            "reference_relationship_cases": references.get("relationship_cases", {}).get(name, []),
        })
    return pattern, annotate_occurrences(chain)


def _compact_chain(chain):
    keys = (
        "segment_index", "function_id", "function_name", "definition", "preconditions", "role_slots",
        "contract", "reference_transitions", "reference_instance_cases",
        "reference_role_stats", "reference_relationship_cases",
        "occurrence_index", "occurrence_total",
    )
    return [
        {
            k: step.get(
                k,
                {} if k == "reference_role_stats"
                else [] if k in {"reference_transitions", "reference_instance_cases", "reference_relationship_cases"}
                else None,
            )
            for k in keys
        }
        for step in chain
    ]


def _relationship_constraints(chain):
    return [
        {
            "segment_index": step["segment_index"],
            "function_name": step["function_name"],
            "allowed_role_pairs": [
                list(effect["role_slots"])
                for effect in relationship_effects(step.get("contract") or {})
            ],
            "allowed_effects": [
                {
                    "role_slots": list(effect["role_slots"]),
                    "aspect": effect["aspect"],
                    "before": effect["before"],
                    "after": effect["after"],
                }
                for effect in relationship_effects(step.get("contract") or {})
            ],
        }
        for step in chain
    ]


def build_ending_target(ending_spec, seed):
    """将可选的 Pattern 结局规范统一为本轮实际结局目标。"""
    if ending_spec:
        return {"source": "pattern", **ending_spec}
    return {
        "source": "seed",
        "resolves": seed.get("core_conflict", ""),
        "must_show": [],
        "final_state": seed.get("ending_direction", ""),
    }


def build_ending_budget(state):
    """汇总 ending 可使用的前序义务、伏笔和关系状态，不新增持久化 schema。"""
    ledger = state.get("contract_ledger") or {}
    relationship_ledger = ledger.get("relationship_ledger") or {}
    payoffs = []
    for step in (state.get("narrative") or {}).get("steps", []):
        for payoff in step.get("setup_payoffs", []):
            if payoff.get("payoff_segment_index") is None:
                payoffs.append({
                    "segment_index": step.get("segment_index"),
                    "content": payoff.get("content", ""),
                    "payoff": payoff.get("payoff", ""),
                })
    states = {}
    for change in relationship_ledger.get("changes", []):
        key = (change.get("source_id"), change.get("target_id"), change.get("dimension"))
        states[key] = {
            "source_id": change.get("source_id"),
            "target_id": change.get("target_id"),
            "dimension": change.get("dimension", ""),
            "after": change.get("after", ""),
        }
    return {
        "unresolved_obligations": ledger.get("obligations") or [],
        "ending_payoffs": payoffs,
        "relationship_state_upper_bounds": list(states.values()),
    }


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


_PERSON_ID_RE = re.compile(r"(?<![A-Za-z0-9_])P\d+(?![A-Za-z0-9_])")
_IDENTITY_MARKERS = (
    "同一人", "合并", "互换", "冒充", "伪装成", "认作", "当作", "实际是", "原来是",
)
_CAUTIOUS_RELATION_MARKERS = (
    "低信任", "信任极低", "不信任", "保持戒备", "互相提防", "谨慎合作", "有限合作",
    "临时合作", "脆弱合作", "尚未达成协作", "未达成协作", "关系紧张", "敌对",
)
_STRONG_RELATION_MARKERS = (
    "互信", "完全信任", "彼此信任", "稳定联盟", "正式结盟", "和解", "相互和解",
    "坚定盟友", "永久联盟", "永久承诺",
)
_NEGATION_MARKERS = ("不", "未", "无", "没有", "并非", "不是", "并不是", "不能", "尚未", "拒绝", "并未")


def _has_unnegated_marker(text, markers):
    for marker in markers:
        for match in re.finditer(re.escape(marker), text):
            prefix = text[max(0, match.start() - 4):match.start()]
            if not any(prefix.endswith(negation) for negation in _NEGATION_MARKERS):
                return True
    return False


def _ending_text(outline):
    ending = (outline or {}).get("ending") or {}
    return " ".join(
        [
            *[str(item) for item in ending.get("resolution_actions") or []],
            str(ending.get("conflict_resolution") or ""),
            str(ending.get("final_state") or ""),
        ]
    )


def _ending_semantic_issues(state):
    """补充可确定的结局边界；开放式因果仍由 Validator 语义判断。"""
    outline = state.get("outline") or {}
    ending_text = _ending_text(outline)
    seed = state.get("seed") or {}
    seed_ids = {item.get("id") for item in seed.get("characters") or []}
    ending_ids = set(_PERSON_ID_RE.findall(ending_text))
    issues = []

    unknown_ids = sorted(ending_ids - seed_ids)
    if unknown_ids:
        issues.append(f"结局引用 seed 之外的人物 ID: {', '.join(unknown_ids)}")

    for sentence in re.split(r"[。！？；\n]", ending_text):
        ids = _PERSON_ID_RE.findall(sentence)
        if len(set(ids)) >= 2 and (
            _has_unnegated_marker(sentence, _IDENTITY_MARKERS)
            or (
                re.search(r"身份(?:是|为|等同|互换|相同|一致)", sentence)
                and not any(negation in sentence for negation in ("不是", "并非", "未", "不"))
            )
        ):
            issues.append("结局合并或互换了不同人物 ID 的身份")
            break

    prior_relation_parts = [
        *[str(item) for item in (outline.get("final_ledger") or [])],
        json.dumps(
            [character.get("relationships") or {} for character in seed.get("characters") or []],
            ensure_ascii=False,
        ),
    ]
    for step in (state.get("mechanism") or {}).get("steps", []):
        for change in step.get("relationship_changes") or []:
            prior_relation_parts.append(json.dumps(change, ensure_ascii=False))
    for change in (state.get("contract_ledger") or {}).get("relationship_ledger", {}).get("changes", []):
        prior_relation_parts.append(json.dumps(change, ensure_ascii=False))
    for bound in (state.get("ending_budget") or {}).get("relationship_state_upper_bounds", []):
        prior_relation_parts.append(json.dumps(bound, ensure_ascii=False))

    for prior in prior_relation_parts:
        if not _has_unnegated_marker(prior, _CAUTIOUS_RELATION_MARKERS):
            continue
        prior_ids = set(_PERSON_ID_RE.findall(prior))
        if prior_ids and ending_ids and not prior_ids & ending_ids:
            continue
        if _has_unnegated_marker(ending_text, _STRONG_RELATION_MARKERS):
            issues.append("结局关系状态超过前序谨慎/低信任状态，不能直接写成互信、和解或稳定联盟")
            break
    return list(dict.fromkeys(issues))


def _should_retry_realize(state):
    validation = state.get("validation") or {}
    return (
        validation.get("overall_ok") is False
        and not validation.get("contract_issues")
        and not validation.get("rule_issues")
        and not state.get("realize_retry_count", 0)
    )


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


def dynamic_seed_node(state):
    user = {
        "genre": state["genre"],
        "user_request": state.get("user_request"),
    }
    seed = chat_structured([
        {"role": "system", "content": DYNAMIC_SEED_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ], StorySeed).model_dump()
    return {"seed": seed}

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
    selected = next(
        pattern for pattern in available
        if pattern.get("pattern_name") == pattern_request
    ) if pattern_request else available[0]
    base_chain = [
        {"function_id": step.get("function_id"), "function_name": step["function_name"]}
        for step in selected["core_function_chain"]
    ]
    references = load_planner_references(
        state["snapshot_id"], selected, base_chain, state["knowledge_db"],
    )
    pattern, chain = planner(
        catalog, state["genre"], pattern_request, contracts, references,
    )
    pattern_id = pattern.get("pattern_id")
    if not pattern_id:
        raise ValueError(f"Pattern 缺少稳定 ID: {pattern['pattern_name']}")
    return {
        "pattern_source": "published",
        "pattern_id": pattern_id,
        "pattern_name": pattern["pattern_name"],
        "ending_spec": pattern.get("ending_spec"),
        "chain": chain,
        "planner_references": references,
    }


def dynamic_planner_node(state):
    references, candidates, selected = plan_dynamic_outline(state, chat_structured)
    return {
        "pattern_source": "dynamic",
        "pattern_id": None,
        "pattern_name": selected["candidate_id"],
        "ending_spec": None,
        "chain": selected["chain"],
        "planner_references": references,
        "dynamic_candidates": candidates,
        "dynamic_candidate": selected,
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
        "ending_target": build_ending_target(state.get("ending_spec"), state["seed"]),
        "relationship_constraints": _relationship_constraints(state["chain"]),
        "reference_motifs": (state.get("planner_references") or {}).get("motifs", []),
        "reference_role_stats": (state.get("planner_references") or {}).get("role_stats", {}),
        "reference_relationship_cases": (state.get("planner_references") or {}).get("relationship_cases", {}),
    }
    messages = [
        {"role": "system", "content": MECH_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]
    for attempt in range(2):
        data = chat_structured(messages, MechanismPlan).model_dump()
        data["steps"] = _align(state["chain"], data["steps"])
        data["steps"] = normalize_relationship_befores(
            state["chain"], data["steps"], state["seed"],
        )
        ledger = build_contract_ledger(state["chain"], data["steps"], state["seed"])
        if not ledger["issues"]:
            return {"mechanism": data, "contract_ledger": ledger}
        if attempt == 0:
            messages = messages + [{
                "role": "user",
                "content": (
                    "Mechanism 方案存在确定性 Contract/关系账本错误："
                    + "；".join(ledger["issues"])
                    + "。请只修正这些边界：没有有效双角色关系 effect 的 Function，"
                    "relationship_changes 必须为空；关系变化双方必须是同一个允许角色对的绑定人物；"
                    "before 必须沿用关系账本，不得自由改写，并重新输出完整 JSON。"
                ),
            }]
    raise ValueError("Mechanism 方案不合法: " + "；".join(ledger["issues"]))


def scaffold_node(state):
    user = {
        "chain": _compact_chain(state["chain"]),
        "seed": state["seed"],
        "mechanism_plan": state["mechanism"],
        "ending_target": build_ending_target(state.get("ending_spec"), state["seed"]),
        "ending_budget": build_ending_budget(state),
        "reference_motifs": (state.get("planner_references") or {}).get("motifs", []),
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
        "ending_target": build_ending_target(state.get("ending_spec"), state["seed"]),
        "ending_budget": build_ending_budget(state),
        "seed": state["seed"],
        "mechanism_plan": state["mechanism"],
        "narrative_plan": state["narrative"],
        "contract_ledger": state.get("contract_ledger"),
    }
    messages = [
        {"role": "system", "content": REALIZE_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]
    retry = _should_retry_realize(state)
    if retry:
        messages.append({
            "role": "user",
            "content": (
                "Validator 上次指出以下语义问题："
                + "；".join(state["validation"].get("issues") or [])
                + "。只修正被指出的 beats 或 ending 身份、因果、关系措辞和义务兑现；"
                "固定 seed、Function chain、role_bindings、mechanism、relationship_changes、narrative，"
                "不得新增人物、真相、证据、解决方案或改变结构，并重新输出完整 JSON。"
            ),
        })
    data = chat_structured(messages, OutlineRealization).model_dump()
    data["segments"] = _align(state["chain"], data["segments"])
    return {
        "outline": data,
        "realize_retry_count": state.get("realize_retry_count", 0) + int(retry),
    }


def validate_node(state):
    validation_ledger = dict(state.get("contract_ledger") or {})
    validation_ledger.pop("warnings", None)
    user = {
        "target_chain": [
            {"segment_index": step["segment_index"], "function_name": step["function_name"]}
            for step in state["chain"]
        ],
        "ending_target": build_ending_target(state.get("ending_spec"), state["seed"]),
        "ending_budget": build_ending_budget(state),
        "generated_ending": (state.get("outline") or {}).get("ending"),
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
    semantic_issues = _ending_semantic_issues({**state, "ending_budget": build_ending_budget(state)})
    if semantic_issues:
        data["overall_ok"] = False
        data["issues"] = list(dict.fromkeys(data.get("issues", []) + semantic_issues))
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
        lines.append(
            f"- {char['id']}（{char['label']} · {char['role']} · "
            f"立场={char.get('stance_toward_protagonist', 'neutral')}）：{char['goal']}"
        )
    lines.append("")
    lines.append("## 开场人物关系")
    relationship_rows = [
        (char["id"], target_id, description)
        for char in result["seed"]["characters"]
        for target_id, description in (char.get("relationships") or {}).items()
    ]
    for source_id, target_id, description in relationship_rows:
        lines.append(f"- {source_id} → {target_id}：{description}")
    if not relationship_rows:
        lines.append("- 无预设关系边")
    lines.append("")
    lines.append("## Function 关系变化")
    relation_changes = [
        (step["segment_index"], change)
        for step in result["mechanism_plan"]["steps"]
        for change in step.get("relationship_changes", [])
    ]
    for segment_index, change in relation_changes:
        lines.append(
            f"- 第{segment_index}段 {change['source_id']} → {change['target_id']}："
            f"{change['dimension']} {change['before']} → {change['after']}（{change['evidence']}）"
        )
    if not relation_changes:
        lines.append("- 无有证据支持的关系变化")
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
        "pattern_source": state.get("pattern_source") or (
            "dynamic" if state.get("planner_mode") == "dynamic" else "published"
        ),
        "planner_mode": state.get("planner_mode", "published"),
        "pattern_name": state["pattern_name"],
        "genre": state["genre"],
        "user_request": state.get("user_request"),
        "ending_spec": state.get("ending_spec"),
        "ending_target": build_ending_target(state.get("ending_spec"), state["seed"]),
        "ending_budget": build_ending_budget(state),
        "chain": [step["function_name"] for step in state["chain"]],
        "seed": state["seed"],
        "mechanism_plan": state["mechanism"],
        "narrative_plan": state["narrative"],
        "contract_ledger": state.get("contract_ledger"),
        "planner_references": state.get("planner_references"),
        "dynamic_candidate": state.get("dynamic_candidate"),
        "dynamic_candidates": state.get("dynamic_candidates", []),
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
    graph.add_node("dynamic_seed", dynamic_seed_node)
    graph.add_node("dynamic_planner", dynamic_planner_node)
    graph.add_node("seed", seed_node)
    graph.add_node("mechanism", mechanism_node)
    graph.add_node("scaffold", scaffold_node)
    graph.add_node("realize", realize_node)
    graph.add_node("validate", validate_node)
    graph.add_node("export", export_node)
    graph.add_conditional_edges(
        START,
        lambda state: "dynamic" if state.get("planner_mode") == "dynamic" else "published",
        {"published": "select_pattern", "dynamic": "dynamic_seed"},
    )
    graph.add_edge("select_pattern", "planner")
    graph.add_edge("planner", "seed")
    graph.add_edge("dynamic_seed", "dynamic_planner")
    graph.add_edge("dynamic_planner", "mechanism")
    graph.add_edge("seed", "mechanism")
    graph.add_edge("mechanism", "scaffold")
    graph.add_edge("scaffold", "realize")
    graph.add_edge("realize", "validate")
    graph.add_conditional_edges(
        "validate",
        lambda state: "realize" if _should_retry_realize(state) else "export",
        {"realize": "realize", "export": "export"},
    )
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
    parser.add_argument(
        "--planner-mode", choices=("published", "dynamic"), default="published",
        help="Planner 模式，默认使用已发布 Pattern",
    )
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    genre = normalize_genre(args.genre)
    if args.planner_mode == "dynamic" and args.pattern:
        raise ValueError("dynamic Planner 不接受 --pattern")
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
        "planner_mode": args.planner_mode,
        "pattern_id": None,
        "pattern_name": "",
        "pattern_source": args.planner_mode,
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
    })

    validation = result["validation"] or {}
    print(f"[Planner] mode={args.planner_mode} pattern={result['pattern_name']}")
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
