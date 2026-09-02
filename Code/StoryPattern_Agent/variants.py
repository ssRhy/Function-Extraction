"""Story Pattern Agent 的 motif 语义变体召回节点。"""

import hashlib
from itertools import combinations

import numpy as np

from FunctionExtract_Agent.Embedding.embedding import Embedder
from .state import StoryPatternState


VARIANT_MIN_SIMILARITY = 0.75
VARIANT_HIGH_SIMILARITY = 0.85
VARIANT_TOP_K = 5
GAP_SIMILARITY = 0.75


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / denominator) if denominator else 0.0


def _align(left: list[str], right: list[str], vectors: dict[str, np.ndarray]) -> tuple[float, list]:
    if len(left) == len(right):
        pairs = list(zip(left, right))
        return sum(_cosine(vectors[a], vectors[b]) for a, b in pairs) / len(pairs), pairs

    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    options = []
    for positions in combinations(range(len(longer)), len(shorter)):
        similarity = sum(
            _cosine(vectors[function_id], vectors[longer[position]])
            for function_id, position in zip(shorter, positions)
        )
        options.append((similarity, positions))
    matched_score, matched_positions = max(
        options, key=lambda item: (item[0], tuple(-index for index in item[1]))
    )
    score = (
        matched_score
        + GAP_SIMILARITY * (len(longer) - len(shorter))
    ) / len(longer)
    alignment = []
    short_index = 0
    for long_index, function_id in enumerate(longer):
        if short_index < len(shorter) and long_index == matched_positions[short_index]:
            pair = (shorter[short_index], function_id)
            short_index += 1
        else:
            pair = (None, function_id)
        alignment.append(pair if len(left) < len(right) else pair[::-1])
    return score, alignment


def retrieve_motif_variants(state: StoryPatternState) -> dict:
    """用位置对齐的 Function 语义相似度召回 motif 变体候选对。"""
    snapshot_id = str((state.get("snapshot_manifest") or {}).get("snapshot_id") or "").strip()
    if not snapshot_id:
        raise ValueError("retrieve_motif_variants 需要 Snapshot ID")
    function_by_id = state.get("function_by_id", {})
    if not function_by_id:
        raise ValueError("retrieve_motif_variants 需要 function_by_id")
    candidates = state.get("motif_candidates", [])
    if not candidates:
        raise ValueError("retrieve_motif_variants 需要 motif_candidates")

    seen_ids = set()
    eligible = []
    used_function_ids = set()
    for candidate in candidates:
        motif_id = str(candidate.get("motif_id") or "").strip()
        function_ids = candidate.get("function_ids")
        function_names = candidate.get("function_names")
        story_ids = candidate.get("story_ids")
        if not motif_id or motif_id in seen_ids:
            raise ValueError(f"motif_id 缺失或重复: {motif_id}")
        if candidate.get("snapshot_id") != snapshot_id:
            raise ValueError(f"motif candidate Snapshot ID 不匹配: {motif_id}")
        if (
            not isinstance(function_ids, list) or not 3 <= len(function_ids) <= 6
            or candidate.get("length") != len(function_ids)
            or not isinstance(function_names, list) or len(function_names) != len(function_ids)
            or not isinstance(story_ids, list) or not story_ids
        ):
            raise ValueError(f"motif candidate 结构无效: {motif_id}")
        for function_id, function_name in zip(function_ids, function_names):
            function = function_by_id.get(function_id)
            if function is None:
                raise ValueError(f"motif candidate 引用未知 Function: {motif_id}: {function_id}")
            if function.get("function_name") != function_name:
                raise ValueError(f"motif candidate Function ID/名称不一致: {motif_id}: {function_id}")
        seen_ids.add(motif_id)
        unique_story_count = len(set(story_ids))
        if candidate.get("story_support") != unique_story_count:
            raise ValueError(f"motif candidate 支持数无效: {motif_id}")
        if candidate.get("tier") == "SINGLE_STORY" and unique_story_count != 1:
            raise ValueError(f"SINGLE_STORY 支持数无效: {motif_id}")
        if candidate.get("tier") == "REPEATED" and unique_story_count < 2:
            raise ValueError(f"REPEATED 支持数无效: {motif_id}")
        if candidate.get("tier") not in {"SINGLE_STORY", "REPEATED"}:
            raise ValueError(f"motif candidate tier 无效: {motif_id}")
        eligible.append(candidate)
        used_function_ids.update(function_ids)

    if len(eligible) < 2:
        raise ValueError("至少需要两个 motif candidates")

    ordered_function_ids = sorted(used_function_ids)
    texts = []
    for function_id in ordered_function_ids:
        function = function_by_id[function_id]
        definition = str(function.get("definition") or "").strip()
        if not definition:
            raise ValueError(f"Function 缺少 definition: {function_id}")
        texts.append(f"{function['function_name']}。{definition}")
    encoded = Embedder().encode_cached(texts)
    vectors = dict(zip(ordered_function_ids, encoded))

    eligible = sorted(eligible, key=lambda item: item["motif_id"])
    pair_data = {}
    neighbors = {item["motif_id"]: [] for item in eligible}
    for index, left in enumerate(eligible):
        for right in eligible[index + 1:]:
            combined_story_ids = sorted(set(left["story_ids"]) | set(right["story_ids"]))
            if len(combined_story_ids) < 2:
                continue
            similarity, aligned_ids = _align(left["function_ids"], right["function_ids"], vectors)
            if similarity < VARIANT_MIN_SIMILARITY:
                continue
            member_ids = [left["motif_id"], right["motif_id"]]
            key = tuple(member_ids)
            pair_data[key] = (left, right, similarity, aligned_ids, combined_story_ids)
            neighbors[left["motif_id"]].append((similarity, right["motif_id"], key))
            neighbors[right["motif_id"]].append((similarity, left["motif_id"], key))

    selected = {}
    for motif_id, items in neighbors.items():
        items.sort(key=lambda item: (-item[0], item[1]))
        for rank, (_similarity, _other_id, key) in enumerate(items[:VARIANT_TOP_K], 1):
            selected.setdefault(key, []).append({"motif_id": motif_id, "rank": rank})

    pairs = []
    for key, selected_by in selected.items():
        left, right, similarity, aligned_ids, combined_story_ids = pair_data[key]
        member_ids = list(key)
        digest = hashlib.sha256("|".join(member_ids).encode("utf-8")).hexdigest()[:16]
        alignment = []
        for left_id, right_id in aligned_ids:
            alignment.append({
                "left_function_id": left_id,
                "left_function_name": function_by_id[left_id]["function_name"] if left_id else None,
                "right_function_id": right_id,
                "right_function_name": function_by_id[right_id]["function_name"] if right_id else None,
                "similarity": round(_cosine(vectors[left_id], vectors[right_id]), 4)
                if left_id and right_id else None,
            })
        pairs.append({
            "variant_pair_id": f"MV_{digest}",
            "snapshot_id": snapshot_id,
            "member_motif_ids": member_ids,
            "similarity": round(similarity, 4),
            "recall_tier": "HIGH" if similarity >= VARIANT_HIGH_SIMILARITY else "EXPANDED",
            "length_difference": abs(left["length"] - right["length"]),
            "shared_story_ids": sorted(set(left["story_ids"]) & set(right["story_ids"])),
            "combined_story_ids": combined_story_ids,
            "story_support": len(combined_story_ids),
            "story_ids": combined_story_ids,
            "selected_by": selected_by,
            "alignment": alignment,
        })

    pairs.sort(key=lambda item: (-item["similarity"], item["member_motif_ids"]))
    return {
        "motif_variant_pairs": pairs,
        "messages": [{
            "role": "system",
            "content": (
                f"[StoryPattern.retrieve_motif_variants] candidates={len(eligible)}，"
                f"pairs={len(pairs)}，top_k={VARIANT_TOP_K}，"
                f"min_similarity={VARIANT_MIN_SIMILARITY}"
            ),
        }],
    }
