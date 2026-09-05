"""运行时动态 Function Planner。

Planner 只读取一个已冻结 Snapshot，并把候选链保存在当前 LangGraph 状态中。
它不创建 Function、Pattern 或任何新的知识库记录。
"""

from collections import Counter, defaultdict
from difflib import SequenceMatcher
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

from Contracts.ledger import check_contract_chain
from Contracts.role_projection import project_role_references
from Contracts.state_vocabulary import StateVocabulary
from FunctionExtract_Agent.llm import chat_structured
from KnowledgeBase import DEFAULT_DB_PATH, StoryKnowledgeStore


Operation = Literal[
    "REUSE_MOTIF",
    "COMPOSE_MOTIFS",
    "MUTATE_MOTIF",
    "BRIDGE",
    "EXPLORE",
]

BEAM_WIDTH = 4
MAX_EXTENSIONS = 3
MAX_CHAIN_LENGTH = 8
MIN_CHAIN_LENGTH = 2
CHAIN_SIMILARITY_THRESHOLD = 0.8


class DynamicExtension(BaseModel):
    operation: Operation
    function_ids: list[str] = Field(default_factory=list, max_length=MAX_CHAIN_LENGTH)
    motif_ids: list[str] = Field(default_factory=list, max_length=MAX_CHAIN_LENGTH)
    reason: str = Field(default="未说明理由", min_length=1)
    expected_state: str = Field(default="未说明预期状态", min_length=1)
    overlap_sizes: list[int] = Field(default_factory=list, max_length=MAX_CHAIN_LENGTH)
    novelty_reason: str = Field(default="未说明结构新意", min_length=1)
    goal_fit: float = Field(default=0.5, ge=0, le=1)
    complete: bool = False


class DynamicPlanResponse(BaseModel):
    extensions: list[DynamicExtension] = Field(min_length=1)


def _occurrence_sort_key(occurrence):
    order = occurrence.get("observation_order")
    if isinstance(order, int) and order > 0:
        return order, 0, occurrence.get("occurrence_id", "")
    indices = occurrence.get("source_sentence_indices") or []
    return min(indices) if indices else 0, 1, occurrence.get("occurrence_id", "")


def _build_transitions(occurrences):
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


def _instance_cases(functions, occurrences):
    occurrences_by_id = {
        item.get("occurrence_id"): item for item in occurrences
        if item.get("occurrence_id")
    }
    cases = defaultdict(list)
    seen = defaultdict(set)
    for occurrence in sorted(occurrences, key=_occurrence_sort_key):
        name = occurrence.get("function_name")
        surface_form = str(occurrence.get("surface_form") or "").strip()
        if not name or not surface_form or surface_form in seen[name]:
            continue
        seen[name].add(surface_form)
        cases[name].append({
            "occurrence_id": occurrence["occurrence_id"],
            "story_id": occurrence.get("story_id", ""),
            "surface_form": surface_form,
            "event": occurrence.get("event", ""),
            "before_state": occurrence.get("before_state", ""),
            "after_state": occurrence.get("after_state", ""),
        })

    for function in functions:
        name = function.get("function_name")
        supporting_ids = function.get("supporting_obs_ids", [])
        supported = [occurrences_by_id[item] for item in supporting_ids
                     if item in occurrences_by_id]
        if supported:
            cases[name] = [
                item for item in cases[name]
                if item["occurrence_id"] in {x["occurrence_id"] for x in supported}
            ] or cases[name][:3]
        cases[name] = cases[name][:3]
    return dict(cases)


def _published_patterns(store, snapshot_id):
    try:
        return store.load_pattern_catalog(snapshot_id).get("published_patterns", [])
    except ValueError:
        return []


def _mature_motifs(rows, patterns):
    """只把已进入已发布 Pattern 的 motif 作为成熟 motif。"""
    mature_ids = {
        motif_id
        for pattern in patterns
        for motif_id in pattern.get("member_motif_ids", [])
    }
    grouped = {}
    support = defaultdict(set)
    evidence = defaultdict(list)
    for row in rows:
        motif_id = row.get("motif_id")
        if motif_id not in mature_ids:
            continue
        grouped.setdefault(motif_id, {
            "motif_id": motif_id,
            "function_ids": list(row.get("function_ids") or []),
            "function_names": list(row.get("function_names") or []),
            "length": row.get("length", 0),
        })
        item = row.get("evidence") or {}
        if item.get("story_id"):
            support[motif_id].add(item["story_id"])
        evidence[motif_id].append(item)
    result = []
    for motif_id, motif in grouped.items():
        motif["story_support"] = len(support[motif_id])
        motif["evidence"] = evidence[motif_id][:3]
        result.append(motif)
    return sorted(result, key=lambda item: (-item["story_support"], item["motif_id"]))


def build_dynamic_references(snapshot_id, knowledge_db=DEFAULT_DB_PATH):
    """读取动态 Planner 的完整只读输入。"""
    store = StoryKnowledgeStore(knowledge_db)
    functions = store.load_functions(snapshot_id)
    contracts = {
        item["function_id"]: item for item in store.load_contracts(snapshot_id)
    }
    occurrences = store.load_occurrences(snapshot_id)
    role_references = project_role_references(
        functions, list(contracts.values()), occurrences,
        store.load_story_profiles(snapshot_id),
    )
    patterns = _published_patterns(store, snapshot_id)
    motifs = _mature_motifs(store.load_motif_evidence(snapshot_id), patterns)
    vocabulary = StateVocabulary.from_contracts(list(contracts.values())).to_dict()
    return {
        "snapshot_id": snapshot_id,
        "functions": functions,
        "contracts": contracts,
        "state_vocabulary": vocabulary,
        "transitions": _build_transitions(occurrences),
        "motifs": motifs,
        "instance_cases": _instance_cases(functions, occurrences),
        **role_references,
        "published_patterns": [
            {
                "pattern_id": pattern.get("pattern_id"),
                "pattern_name": pattern.get("pattern_name"),
                "function_ids": [
                    step.get("function_id") or step.get("function_name")
                    for step in pattern.get("core_function_chain", [])
                ],
            }
            for pattern in patterns
        ],
    }


def _menu(references):
    return [
        {
            "function_id": function.get("function_id"),
            "function_name": function.get("function_name"),
            "definition": function.get("definition", ""),
            "role_slots": (references.get("contracts", {}).get(function.get("function_id")) or {}).get(
                "role_slots", function.get("role_slots", [])
            ),
            "preconditions": (references.get("contracts", {}).get(function.get("function_id")) or {}).get(
                "preconditions", []
            ),
            "effects": (references.get("contracts", {}).get(function.get("function_id")) or {}).get(
                "effects", []
            ),
            "obligation_effects": (references.get("contracts", {}).get(function.get("function_id")) or {}).get(
                "obligation_effects", {}
            ),
        }
        for function in references.get("functions", [])
    ]


def _motif_menu(references):
    return [
        {
            "motif_id": motif["motif_id"],
            "function_ids": motif["function_ids"],
            "function_names": motif["function_names"],
            "story_support": motif.get("story_support", 0),
        }
        for motif in references.get("motifs", [])
    ]


def _planner_prompt(seed, user_request, chain, references):
    return (
        "你是动态 Function Planner。根据故事种子、用户目标、当前链、FunctionContract、"
        "状态词汇、角色位置统计、关系变化案例、真实转移和成熟 motif，提出下一批候选扩展。只输出符合 schema 的 JSON。\n"
        "允许的 operation：REUSE_MOTIF（完整复用一个 motif）、COMPOSE_MOTIFS（按顺序拼接至少两个 motif）、"
        "MUTATE_MOTIF（以一个 motif 为基线，至少替换一个 Function）、BRIDGE（追加一个桥接 Function）、"
        "EXPLORE（从 Function 级别自由追加一个或多个 Function）。\n"
        "function_ids 只能来自 function_menu，motif_ids 只能来自 motif_menu。REUSE_MOTIF 和"
        "COMPOSE_MOTIFS 以 motif_ids 为准，function_ids 可以省略；程序会按 motif 序列重建最终链；"
        "MUTATE_MOTIF 必须给出只做局部替换后的完整序列；BRIDGE 必须只有一个 Function。"
        "COMPOSE_MOTIFS 必须给出 motif 之间的 overlap_sizes（可为 0）；最终 function_ids 可省略，"
        "程序会以 motif 序列和实际合法 overlap 为准重建；novelty_reason 必须说明新产生的跨 motif 结构或状态推进。"
        "除被引用 motif 自身已经包含的内部回环外，不得把 current_chain 已使用的 Function 再次加入扩展；"
        "如果 motif 与 current_chain 的边界相接，必须通过合法 overlap 消解边界重复。"
        "每次最多输出 3 个 extensions；每个 extension 必须包含 operation、function_ids、motif_ids、"
        "reason、expected_state、overlap_sizes、novelty_reason、goal_fit、complete 字段。"
        "每次只扩展当前链，不要改写当前链；"
        "链总长度不能超过 8。complete=true 表示当前链已经足够。JSON 形状示例："
        '{"extensions":[{"operation":"EXPLORE","function_ids":["F_ID"],'
        '"motif_ids":[],"reason":"理由","expected_state":"状态变化",'
        '"overlap_sizes":[],"novelty_reason":"新结构",'
        '"goal_fit":0.8,"complete":true}]}\n'
        + json.dumps({
            "story_seed": seed,
            "user_request": user_request,
            "current_chain": chain,
            "function_menu": _menu(references),
            "motif_menu": _motif_menu(references),
            "state_vocabulary": references.get("state_vocabulary", {}),
            "transitions": references.get("transitions", {}),
            "role_stats": references.get("role_stats", {}),
            "relationship_cases": references.get("relationship_cases", {}),
        }, ensure_ascii=False)
    )


def _motif_map(references):
    return {item["motif_id"]: item for item in references.get("motifs", [])}


def _allowed_repeat_ids(steps, references):
    allowed = set()
    motifs = _motif_map(references)
    for step in steps:
        for motif_id in step.get("motif_ids", []):
            ids = motifs.get(motif_id, {}).get("function_ids", [])
            allowed.update(function_id for function_id, count in Counter(ids).items() if count > 1)
    return allowed


def _longest_overlap(left, right):
    for size in range(min(len(left), len(right)), 0, -1):
        if left[-size:] == right[:size]:
            return size
    return 0


def _merge_with_overlap(left, right, requested=None):
    if not left:
        return list(right), 0
    computed = _longest_overlap(left, right)
    overlap = computed if requested is None else requested
    if (
        overlap < 0
        or overlap > min(len(left), len(right))
        or (overlap and left[-overlap:] != right[:overlap])
    ):
        overlap = computed
    return list(left) + list(right[overlap:]), overlap


def _compose_motifs(extension, references):
    motifs = _motif_map(references)
    if len(extension.motif_ids) < 2:
        raise ValueError("COMPOSE_MOTIFS 至少需要两个 motif")
    if any(motif_id not in motifs for motif_id in extension.motif_ids):
        missing = next(motif_id for motif_id in extension.motif_ids if motif_id not in motifs)
        raise ValueError(f"未知 motif: {missing}")
    requested_overlaps = extension.overlap_sizes[:len(extension.motif_ids) - 1]
    result = []
    overlaps = []
    for index, motif_id in enumerate(extension.motif_ids):
        function_ids = motifs[motif_id]["function_ids"]
        requested = (
            requested_overlaps[index - 1]
            if index and index - 1 < len(requested_overlaps) else None
        )
        result, overlap = _merge_with_overlap(result, function_ids, requested)
        if index:
            overlaps.append(overlap)
    return result, overlaps


def _expanded_function_ids(extension, references):
    motifs = _motif_map(references)
    operation = extension.operation
    if operation == "REUSE_MOTIF":
        if len(extension.motif_ids) != 1:
            raise ValueError("REUSE_MOTIF 必须引用一个 motif")
        expected = motifs.get(extension.motif_ids[0])
        if not expected:
            raise ValueError(f"未知 motif: {extension.motif_ids[0]}")
        return list(expected["function_ids"])
    if operation == "COMPOSE_MOTIFS":
        return _compose_motifs(extension, references)[0]
    if operation == "MUTATE_MOTIF":
        if len(extension.motif_ids) != 1:
            raise ValueError("MUTATE_MOTIF 必须引用一个 motif")
        base = motifs.get(extension.motif_ids[0])
        if not base:
            raise ValueError(f"未知 motif: {extension.motif_ids[0]}")
        if not extension.function_ids:
            raise ValueError("MUTATE_MOTIF 必须给出替换后的 Function 序列")
        if len(extension.function_ids) != len(base["function_ids"]):
            raise ValueError("MUTATE_MOTIF 必须保持 motif 长度")
        changed = sum(
            left != right
            for left, right in zip(extension.function_ids, base["function_ids"])
        )
        if extension.function_ids == base["function_ids"]:
            raise ValueError("MUTATE_MOTIF 至少替换一个 Function")
        if changed > max(1, len(base["function_ids"]) // 2):
            raise ValueError("MUTATE_MOTIF 必须保持局部替换")
        return list(extension.function_ids)
    if operation == "BRIDGE" and len(extension.function_ids) != 1:
        raise ValueError("BRIDGE 只能追加一个 Function")
    if not extension.function_ids:
        raise ValueError(f"{operation} 必须给出 Function ID")
    return list(extension.function_ids)


def _extension_append(current_ids, extension, references):
    segment = _expanded_function_ids(extension, references)
    merged, boundary_overlap = _merge_with_overlap(current_ids, segment)
    appended = merged[len(current_ids):]
    if not appended:
        raise ValueError("扩展与当前链完全重叠，没有产生新 Function")
    if set(appended) & set(current_ids):
        raise ValueError("扩展引入跨段重复 Function；重复只能来自同一 motif 内部")
    internal_overlaps = []
    if extension.operation == "COMPOSE_MOTIFS":
        _, internal_overlaps = _compose_motifs(extension, references)
    return appended, {
        "segment_function_ids": segment,
        "boundary_overlap": boundary_overlap,
        "internal_overlap_sizes": internal_overlaps,
    }


def _chain_steps(function_ids, references, extension, merge_report=None):
    functions = {item["function_id"]: item for item in references.get("functions", [])}
    contracts = references.get("contracts", {})
    transitions = references.get("transitions", {})
    cases = references.get("instance_cases", {})
    steps = []
    for index, function_id in enumerate(function_ids):
        function = functions.get(function_id)
        contract = contracts.get(function_id)
        if not function:
            raise ValueError(f"未知 Function ID: {function_id}")
        if not contract:
            raise ValueError(f"Function 缺少 Snapshot Contract: {function_id}")
        steps.append({
            "function_id": function_id,
            "function_name": function["function_name"],
            "definition": function.get("definition", ""),
            "preconditions": contract.get("preconditions", []),
            "role_slots": contract.get("role_slots", []),
            "contract": contract,
            "reference_transitions": transitions.get(function["function_name"], [])[:3],
            "reference_instance_cases": cases.get(function["function_name"], [])[:3],
            "reference_role_stats": (references.get("role_stats", {}).get(function["function_name"]) or {}),
            "reference_relationship_cases": references.get("relationship_cases", {}).get(function["function_name"], [])[:3],
            "operation": extension.operation,
            "motif_ids": list(extension.motif_ids),
            "selection_reason": extension.reason,
            "expected_state": extension.expected_state,
            "novelty_reason": extension.novelty_reason,
            "boundary_overlap": (
                (merge_report or {}).get("boundary_overlap", 0) if index == 0 else 0
            ),
            "internal_overlap_sizes": (
                (merge_report or {}).get("internal_overlap_sizes", []) if index == 0 else []
            ),
        })
    return steps


def _state_and_obligation_report(steps):
    contract_chain = [{
        "function_name": step["function_name"],
        "contract": step["contract"],
    } for step in steps]
    state_issues = check_contract_chain(contract_chain)
    current = {}
    opened = set()
    resolved = set()
    conflicts = []
    for step in steps:
        contract = step["contract"]
        for effect in contract.get("effects", []):
            for role in effect.get("role_slots", []):
                key = (role, effect.get("aspect"))
                before = effect.get("before")
                if key in current and current[key] != before:
                    conflicts.append(
                        f"{step['function_name']} 的效果前状态与前序冲突: {key[0]}/{key[1]}"
                    )
                current[key] = effect.get("after")
        for field in ("opens", "advances", "resolves"):
            for item in (contract.get("obligation_effects") or {}).get(field, []):
                key = item.get("key")
                if field == "resolves":
                    resolved.add(key)
                elif key:
                    opened.add(key)
    unresolved = sorted(opened - resolved)
    return {
        "state_issues": state_issues,
        "state_conflicts": conflicts,
        "opened_obligations": sorted(opened),
        "resolved_obligations": sorted(resolved),
        "unresolved_obligations": unresolved,
    }


def validate_dynamic_chain(function_ids, references, seed=None, *, allowed_repeat_ids=None):
    """对 LLM 产生的 Function 链做不依赖 LLM 的硬校验。"""
    functions = {item["function_id"]: item for item in references.get("functions", [])}
    contracts = references.get("contracts", {})
    hard_issues = []
    if not function_ids:
        hard_issues.append("候选链不能为空")
    if len(function_ids) > MAX_CHAIN_LENGTH:
        hard_issues.append(f"候选链超过最大长度 {MAX_CHAIN_LENGTH}")
    if any(not function_id or function_id not in functions for function_id in function_ids):
        hard_issues.append("候选链包含当前 Snapshot 不存在的 Function ID")
    if any(function_id not in contracts for function_id in function_ids):
        hard_issues.append("候选链包含不存在的 FunctionContract")
    allowed_repeat_ids = set(allowed_repeat_ids or [])
    repeated = {
        function_id for function_id, count in Counter(function_ids).items()
        if count > 1 and function_id not in allowed_repeat_ids
    }
    if repeated:
        hard_issues.append(
            "候选链包含未由 motif 内部结构解释的重复 Function: "
            + ", ".join(sorted(repeated))
        )
    for function_id in function_ids:
        contract = contracts.get(function_id) or {}
        declared = set(contract.get("role_slots", []))
        if not declared:
            hard_issues.append(f"{function_id} 没有可绑定的角色槽位")
        for field in ("preconditions", "effects"):
            for item in contract.get(field, []):
                if not set(item.get("role_slots", [])).issubset(declared):
                    hard_issues.append(f"{function_id} 的 {field} 含无法绑定的角色槽位")
    if seed is not None and not seed.get("characters"):
        hard_issues.append("故事种子没有可绑定角色")
    if hard_issues:
        return {"valid": False, "hard_issues": list(dict.fromkeys(hard_issues))}
    report = _state_and_obligation_report([{
        "function_name": functions[function_id]["function_name"],
        "contract": contracts[function_id],
    } for function_id in function_ids])
    return {
        "valid": True,
        "hard_issues": [],
        **report,
        "warnings": list(dict.fromkeys(
            report["state_issues"] + report["state_conflicts"]
            + (["存在未闭合义务: " + ", ".join(report["unresolved_obligations"])]
               if report["unresolved_obligations"] else [])
        )),
    }


def _sequence_similarity(left, right):
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def classify_dynamic_chain(function_ids, published_patterns):
    """按当前已发布链分类，不把动态候选写回 Pattern。"""
    best = 0.0
    exact = False
    for pattern in published_patterns or []:
        other = pattern.get("function_ids") or [
            step.get("function_id") or step.get("function_name")
            for step in pattern.get("core_function_chain", [])
        ]
        if list(function_ids) == list(other):
            exact = True
            best = 1.0
            break
        best = max(best, _sequence_similarity(function_ids, other))
    if exact:
        return "REUSE"
    return "VARIANT" if best >= 0.6 else "NOVEL"


def _structure_novelty(function_ids, steps, references):
    motif_edges = set()
    for motif_id in {
        motif_id for step in steps for motif_id in step.get("motif_ids", [])
    }:
        motif = _motif_map(references).get(motif_id) or {}
        motif_edges.update(zip(motif.get("function_ids", []), motif.get("function_ids", [])[1:]))
    chain_edges = set(zip(function_ids, function_ids[1:]))
    new_edges = sorted(chain_edges - motif_edges)
    overlap_count = sum(
        step.get("boundary_overlap", 0)
        + sum(step.get("internal_overlap_sizes", []))
        for step in steps
    )
    novelty_score = min(
        1.0,
        (len(new_edges) + min(overlap_count, 2)) / max(len(chain_edges), 1),
    )
    return {
        "new_transition_edges": [
            {"from": left, "to": right} for left, right in new_edges
        ],
        "overlap_count": overlap_count,
        "novelty_score": round(novelty_score, 6),
        "reasons": [
            step["novelty_reason"] for step in steps
            if step.get("novelty_reason")
        ],
    }


def _state_quality(validation):
    penalty = (
        len(validation.get("state_issues", [])) * 0.01
        + len(validation.get("state_conflicts", [])) * 0.02
        + len(validation.get("unresolved_obligations", [])) * 0.005
    )
    return max(0.0, 1.0 - min(1.0, penalty))


def _score_chain(steps, extension_scores, references, classification, novelty, validation):
    transitions = references.get("transitions", {})
    support = 0.0
    possible = max(len(steps) - 1, 1)
    for left, right in zip(steps, steps[1:]):
        options = transitions.get(left["function_name"], [])
        item = next((item for item in options if item.get("to") == right["function_name"]), None)
        if item:
            support += min(1.0, (item.get("count", 0) + item.get("support_stories", 0)) / 6)
    fit = sum(extension_scores) / max(len(extension_scores), 1)
    class_bonus = {"REUSE": 0.0, "VARIANT": 0.02, "NOVEL": 0.04}[classification]
    state_quality = _state_quality(validation)
    return round(
        fit * 0.45 + support / possible * 0.25
        + state_quality * 0.15 + novelty["novelty_score"] * 0.15
        + class_bonus,
        6,
    )


def _beam_score(beam, references):
    steps = beam["steps"]
    function_ids = [step["function_id"] for step in steps]
    classification = classify_dynamic_chain(
        function_ids, references.get("published_patterns", []),
    )
    novelty = _structure_novelty(function_ids, steps, references)
    return _score_chain(
        steps,
        beam["score_parts"],
        references,
        classification,
        novelty,
        beam["validation"],
    )


def _select_diverse_beams(beams, references, width):
    """按完整质量分排序，同时删除完全重复和近似路径。"""
    ranked = sorted(
        ((_beam_score(beam, references), beam) for beam in beams),
        key=lambda item: (-item[0], [step["function_id"] for step in item[1]["steps"]]),
    )
    selected = []
    selected_keys = set()
    for score, beam in ranked:
        key = tuple(step["function_id"] for step in beam["steps"])
        if key in selected_keys:
            continue
        if any(
            _sequence_similarity(
                list(key), [step["function_id"] for step in other["steps"]]
            ) >= CHAIN_SIMILARITY_THRESHOLD
            for other in selected
        ):
            continue
        beam["rank_score"] = score
        selected.append(beam)
        selected_keys.add(key)
        if len(selected) == width:
            return selected
    return selected


def _candidate_id(function_ids, operations):
    payload = json.dumps({"function_ids": function_ids, "operations": operations}, sort_keys=True)
    return "DYN_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def generate_dynamic_candidates(
    seed,
    references,
    user_request=None,
    *,
    beam_width=BEAM_WIDTH,
    max_extensions=MAX_EXTENSIONS,
    max_chain_length=MAX_CHAIN_LENGTH,
    llm=None,
):
    """用有限 Beam Search 生成并去重候选链，返回按分数排序的候选。"""
    if not references.get("functions"):
        raise ValueError("动态 Planner 缺少 Snapshot Function")
    if max_chain_length != MAX_CHAIN_LENGTH:
        raise ValueError("动态 Planner 暂不支持修改 max_chain_length")
    beams = [{"steps": [], "score_parts": [], "operations": []}]
    finished = []
    llm = llm or chat_structured
    for _ in range(max_chain_length):
        next_beams = []
        for beam in beams:
            current_ids = [step["function_id"] for step in beam["steps"]]
            extended = False
            response = llm([
                {"role": "system", "content": "你负责严格按输入 schema 输出动态 Function 扩展。"},
                {"role": "user", "content": _planner_prompt(
                    seed, user_request, current_ids, references,
                )},
            ], DynamicPlanResponse)
            extensions = response.extensions[:max_extensions]
            for extension in extensions:
                try:
                    appended, merge_report = _extension_append(
                        current_ids, extension, references,
                    )
                    if len(current_ids) + len(appended) > max_chain_length:
                        continue
                    function_ids = current_ids + appended
                    steps = beam["steps"] + _chain_steps(
                        appended, references, extension, merge_report,
                    )
                    validation = validate_dynamic_chain(
                        function_ids,
                        references,
                        seed,
                        allowed_repeat_ids=_allowed_repeat_ids(steps, references),
                    )
                    if not validation["valid"]:
                        continue
                except ValueError:
                    continue
                operations = beam["operations"] + [extension.operation]
                score_parts = beam["score_parts"] + [extension.goal_fit]
                candidate = {
                    "steps": steps,
                    "score_parts": score_parts,
                    "operations": operations,
                    "validation": validation,
                    "complete": extension.complete or len(function_ids) >= max_chain_length,
                }
                extended = True
                if candidate["complete"] and len(function_ids) >= MIN_CHAIN_LENGTH:
                    finished.append(candidate)
                elif len(function_ids) < max_chain_length:
                    next_beams.append(candidate)
                    extended = True
            if not extended and len(current_ids) >= MIN_CHAIN_LENGTH:
                beam["complete"] = True
                finished.append(beam)
        beams = _select_diverse_beams(next_beams, references, beam_width)
        if not beams:
            break

    candidates = []
    for item in _select_diverse_beams(finished, references, beam_width):
        steps = item["steps"]
        function_ids = [step["function_id"] for step in steps]
        classification = classify_dynamic_chain(
            function_ids, references.get("published_patterns", []),
        )
        validation = validate_dynamic_chain(
            function_ids,
            references,
            seed,
            allowed_repeat_ids=_allowed_repeat_ids(steps, references),
        )
        for index, step in enumerate(steps, 1):
            step["segment_index"] = index
        novelty = _structure_novelty(function_ids, steps, references)
        score = _score_chain(
            steps, item["score_parts"], references, classification, novelty,
            validation,
        )
        candidate = {
            "candidate_id": _candidate_id(function_ids, item["operations"]),
            "pattern_source": "dynamic",
            "pattern_id": None,
            "classification": classification,
            "function_ids": function_ids,
            "chain": steps,
            "operations": item["operations"],
            "score": score,
            "structure_novelty": novelty,
            "validation": validation,
        }
        candidates.append(candidate)
    candidates.sort(key=lambda item: (-item["score"], item["function_ids"], item["candidate_id"]))
    return candidates[:beam_width]


def plan_dynamic_outline(state, llm=None):
    """Outline 节点使用的入口：候选只回到当前运行状态。"""
    references = build_dynamic_references(state["snapshot_id"], state["knowledge_db"])
    candidates = generate_dynamic_candidates(
        state["seed"], references, state.get("user_request"),
        llm=llm,
    )
    if not candidates:
        raise ValueError("动态 Planner 未生成可用候选链")
    selected = candidates[0]
    return references, candidates, selected
