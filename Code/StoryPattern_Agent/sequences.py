"""Story Pattern Agent 的 occurrence 加载与故事序列节点。"""

import hashlib
from collections import Counter, defaultdict

from KnowledgeBase import StoryKnowledgeStore
from .state import StoryPatternState


def load_occurrences_node(state: StoryPatternState) -> dict:
    """读取同一 Snapshot 内发布的 FunctionOccurrence，并按故事分组。"""
    occurrences = state.get("preloaded_occurrences")
    if occurrences is None:
        occurrences = StoryKnowledgeStore(state["knowledge_db"]).load_occurrences(
            state["snapshot_id"]
        )
    story_ids = set(state.get("story_ids", []))
    grouped: dict[str, list[dict]] = {story_id: [] for story_id in story_ids}
    seen = set()
    snapshot_id = (state.get("snapshot_manifest") or {}).get("snapshot_id")
    for occurrence in occurrences:
        occurrence_id = occurrence["occurrence_id"]
        story_id = occurrence["story_id"]
        if occurrence_id in seen:
            raise ValueError(f"重复 occurrence_id: {occurrence_id}")
        if story_id not in story_ids:
            raise ValueError(f"FunctionOccurrence 的 story_id 不在 manifest 中: {story_id}")
        if occurrence.get("snapshot_id") != snapshot_id:
            raise ValueError(f"FunctionOccurrence snapshot_id 不匹配: {occurrence_id}")
        seen.add(occurrence_id)
        grouped[story_id].append(occurrence)

    return {
        "all_occurrences": occurrences,
        "occurrences_by_story": grouped,
        "messages": [{
            "role": "system",
            "content": f"[StoryPattern.load_occurrences] occurrence={len(occurrences)}，故事={len(grouped)}",
        }],
    }


def _sequence_key(occurrence: dict) -> tuple[int, int, str]:
    observation_order = occurrence.get("observation_order")
    if isinstance(observation_order, int) and observation_order > 0:
        return observation_order, 0, occurrence["occurrence_id"]
    indices = occurrence.get("source_sentence_indices") or []
    if indices:
        return min(indices), 0, occurrence["occurrence_id"]
    return 0, 1, occurrence["occurrence_id"]


def build_story_sequences(state: StoryPatternState) -> dict:
    """按原文位置稳定排序当前故事 occurrence，生成 Function 序列。"""
    story_id = state.get("current_story_id")
    if not story_id:
        raise ValueError("build_story_sequences 需要 current_story_id")
    occurrences = state.get("occurrences_by_story", {}).get(story_id, [])
    sequence = []
    for index, occurrence in enumerate(sorted(occurrences, key=_sequence_key), 1):
        item = {
            "order": index,
            "occurrence_id": occurrence["occurrence_id"],
            "obs_id": occurrence["obs_id"],
            "function_id": occurrence.get("function_id"),
            "function_name": occurrence.get("function_name"),
            "status": occurrence["status"],
        }
        sequence.append(item)
    story_sequences = dict(state.get("story_sequences", {}))
    story_sequences[story_id] = sequence
    return {
        "story_sequences": story_sequences,
        "current_sequence": sequence,
        "messages": [{
            "role": "system",
            "content": f"[StoryPattern.build_story_sequences] {story_id}，FunctionOccurrence={len(sequence)}",
        }],
    }


def annotate_repetitions(state: StoryPatternState) -> dict:
    """将连续的同一已确认 Function 标记为 repetition run。"""
    story_id = state.get("current_story_id")
    if not story_id:
        raise ValueError("annotate_repetitions 需要 current_story_id")
    sequence = state.get("current_sequence", [])
    structural = []
    for item in sequence:
        same_run = (
            structural
            and item.get("status") == "MATCHED"
            and structural[-1]["status"] == "MATCHED"
            and item.get("function_id") == structural[-1]["function_id"]
        )
        if same_run:
            run = structural[-1]
            run["repeat_count"] += 1
            run["occurrence_ids"].append(item["occurrence_id"])
            run["obs_ids"].append(item["obs_id"])
            run["raw_orders"].append(item["order"])
            continue
        structural.append({
            "order": len(structural) + 1,
            "function_id": item.get("function_id"),
            "function_name": item.get("function_name"),
            "status": item["status"],
            "repeat_count": 1,
            "occurrence_ids": [item["occurrence_id"]],
            "obs_ids": [item["obs_id"]],
            "raw_orders": [item["order"]],
        })

    structural_sequences = dict(state.get("structural_sequences", {}))
    structural_sequences[story_id] = structural
    return {
        "structural_sequences": structural_sequences,
        "current_structural_sequence": structural,
        "messages": [{
            "role": "system",
            "content": (
                f"[StoryPattern.annotate_repetitions] {story_id}，"
                f"raw={len(sequence)}，runs={len(structural)}"
            ),
        }],
    }


def index_function_contexts(state: StoryPatternState) -> dict:
    """将全部故事结构序列反向索引为 Function 的真实故事上下文。"""
    story_ids = state.get("story_ids", [])
    if not story_ids:
        raise ValueError("index_function_contexts 需要 story_ids")
    structural_sequences = state.get("structural_sequences", {})
    missing = [story_id for story_id in story_ids if story_id not in structural_sequences]
    if missing:
        raise ValueError(f"故事缺少 structural_sequence: {', '.join(missing)}")
    function_by_id = state.get("function_by_id", {})
    if not function_by_id:
        raise ValueError("index_function_contexts 需要 function_by_id")

    contexts = {function_id: [] for function_id in function_by_id}
    story_metadata = state.get("story_metadata", {})
    segment_count = 0

    def add_segment(story_id: str, segment: list[dict]) -> None:
        nonlocal segment_count
        if not segment:
            return
        segment_count += 1
        cards = [{
            "function_id": run["function_id"],
            "function_name": run["function_name"],
            "repeat_count": run["repeat_count"],
            "structural_order": run["order"],
            "occurrence_ids": list(run["occurrence_ids"]),
        } for run in segment]
        category = (story_metadata.get(story_id) or {}).get("category")
        for anchor_index, run in enumerate(segment):
            contexts[run["function_id"]].append({
                "story_id": story_id,
                "category": category,
                "structural_order": run["order"],
                "anchor_index": anchor_index,
                "repeat_count": run["repeat_count"],
                "occurrence_ids": list(run["occurrence_ids"]),
                "segment": [dict(card) for card in cards],
            })

    for story_id in story_ids:
        segment = []
        for run in structural_sequences[story_id]:
            status = run.get("status")
            if status not in {"MATCHED", "UNCERTAIN", "OTHER"}:
                raise ValueError(f"结构节点 status 无效: {story_id}#{run.get('order')}: {status}")
            if status != "MATCHED":
                add_segment(story_id, segment)
                segment = []
                continue
            function_id = run.get("function_id")
            function = function_by_id.get(function_id)
            if function is None:
                raise ValueError(f"结构节点引用未知 Function: {story_id}#{run.get('order')}: {function_id}")
            if run.get("function_name") != function.get("function_name"):
                raise ValueError(f"结构节点 Function ID/名称不一致: {story_id}#{run.get('order')}")
            segment.append(run)
        add_segment(story_id, segment)

    context_count = sum(len(items) for items in contexts.values())
    return {
        "function_contexts": contexts,
        "messages": [{
            "role": "system",
            "content": (
                f"[StoryPattern.index_function_contexts] Function={len(contexts)}，"
                f"contexts={context_count}，segments={segment_count}"
            ),
        }],
    }


def extract_motif_candidates(state: StoryPatternState) -> dict:
    """从 Function 上下文中提取长度 3–6 的精确连续 motif 候选。"""
    snapshot_id = str((state.get("snapshot_manifest") or {}).get("snapshot_id") or "").strip()
    if not snapshot_id:
        raise ValueError("extract_motif_candidates 需要 Snapshot ID")
    function_by_id = state.get("function_by_id", {})
    if not function_by_id:
        raise ValueError("extract_motif_candidates 需要 function_by_id")
    function_contexts = state.get("function_contexts", {})
    if not function_contexts or not any(function_contexts.values()):
        raise ValueError("extract_motif_candidates 需要非空 function_contexts")

    anchors = []
    for indexed_function_id, contexts in function_contexts.items():
        if indexed_function_id not in function_by_id:
            raise ValueError(f"Function context 引用未知 Function: {indexed_function_id}")
        if not isinstance(contexts, list):
            raise ValueError(f"Function context 必须是列表: {indexed_function_id}")
        for context in contexts:
            if not isinstance(context, dict):
                raise ValueError(f"Function context 必须是对象: {indexed_function_id}")
            story_id = str(context.get("story_id") or "").strip()
            category = str(context.get("category") or "").strip()
            segment = context.get("segment")
            anchor_index = context.get("anchor_index")
            if not story_id or not category or not isinstance(segment, list) or not segment:
                raise ValueError(f"Function context 缺少必要字段: {indexed_function_id}")
            if not isinstance(anchor_index, int) or not 0 <= anchor_index < len(segment):
                raise ValueError(f"Function context anchor_index 无效: {indexed_function_id}")

            for card in segment:
                if not isinstance(card, dict):
                    raise ValueError(f"segment card 必须是对象: {story_id}")
                function_id = card.get("function_id")
                function = function_by_id.get(function_id)
                if function is None:
                    raise ValueError(f"segment card 引用未知 Function: {story_id}: {function_id}")
                if card.get("function_name") != function.get("function_name"):
                    raise ValueError(f"segment card Function ID/名称不一致: {story_id}: {function_id}")
                repeat_count = card.get("repeat_count")
                structural_order = card.get("structural_order")
                occurrence_ids = card.get("occurrence_ids")
                if (
                    not isinstance(repeat_count, int) or repeat_count < 1
                    or not isinstance(structural_order, int) or structural_order < 1
                    or not isinstance(occurrence_ids, list) or len(occurrence_ids) != repeat_count
                    or any(not isinstance(item, str) or not item for item in occurrence_ids)
                ):
                    raise ValueError(f"segment card 结构无效: {story_id}: {function_id}")

            anchor = segment[anchor_index]
            if anchor["function_id"] != indexed_function_id:
                raise ValueError(f"Function context 锚点与索引不一致: {story_id}")
            if context.get("structural_order") != anchor["structural_order"]:
                raise ValueError(f"Function context 结构位置与锚点不一致: {story_id}")
            if context.get("repeat_count") != anchor["repeat_count"]:
                raise ValueError(f"Function context repetition 与锚点不一致: {story_id}")
            if context.get("occurrence_ids") != anchor["occurrence_ids"]:
                raise ValueError(f"Function context occurrence 与锚点不一致: {story_id}")
            if anchor_index == 0:
                anchors.append(context)

    if not anchors:
        raise ValueError("function_contexts 中没有 anchor_index == 0 的片段")

    grouped: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    anchors.sort(key=lambda item: (item["story_id"], item["structural_order"]))
    for context in anchors:
        segment = context["segment"]
        for length in range(3, min(6, len(segment)) + 1):
            for start in range(len(segment) - length + 1):
                window = segment[start:start + length]
                function_ids = tuple(card["function_id"] for card in window)
                grouped[function_ids].append({
                    "story_id": context["story_id"],
                    "category": context["category"],
                    "structural_orders": [card["structural_order"] for card in window],
                    "repeat_counts": [card["repeat_count"] for card in window],
                    "occurrence_ids": [
                        occurrence_id
                        for card in window
                        for occurrence_id in card["occurrence_ids"]
                    ],
                })

    candidates = []
    for function_ids, evidence in grouped.items():
        story_ids = sorted({item["story_id"] for item in evidence})
        variants: dict[tuple[int, ...], list[dict]] = defaultdict(list)
        for item in evidence:
            variants[tuple(item["repeat_counts"])].append(item)
        digest = hashlib.sha256("|".join(function_ids).encode("utf-8")).hexdigest()[:16]
        candidates.append({
            "motif_id": f"MC_{digest}",
            "snapshot_id": snapshot_id,
            "function_ids": list(function_ids),
            "function_names": [function_by_id[item]["function_name"] for item in function_ids],
            "length": len(function_ids),
            "tier": "REPEATED" if len(story_ids) >= 2 else "SINGLE_STORY",
            "story_support": len(story_ids),
            "story_ids": story_ids,
            "evidence_count": len(evidence),
            "category_counts": dict(sorted(Counter(item["category"] for item in evidence).items())),
            "repeat_variants": [{
                "repeat_counts": list(repeat_counts),
                "story_support": len({item["story_id"] for item in items}),
                "evidence_count": len(items),
            } for repeat_counts, items in sorted(variants.items())],
            "evidence": evidence,
        })

    candidates.sort(key=lambda item: (
        -item["story_support"],
        -item["evidence_count"],
        item["length"],
        item["function_ids"],
    ))
    return {
        "motif_candidates": candidates,
        "messages": [{
            "role": "system",
            "content": (
                f"[StoryPattern.extract_motif_candidates] segments={len(anchors)}，"
                f"candidates={len(candidates)}"
            ),
        }],
    }
