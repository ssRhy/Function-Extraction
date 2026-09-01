"""Story Pattern Agent 的 motif 配对 LLM 审查节点。"""

import json

from Agent.llm import chat_structured
from .Prompt.Review_prompt import MotifPairReview, REVIEW_SYSTEM_PROMPT
from .state import StoryPatternState


def has_next_motif_pair(state: StoryPatternState) -> bool:
    """判断是否还有待 LLM 审查的 motif 配对。"""
    index = state["current_motif_pair_index"]
    if index < 0:
        raise IndexError(f"current_motif_pair_index 不能为负数: {index}")
    pairs = state["motif_review_queue"] if "motif_review_queue" in state else state.get("motif_variant_pairs", [])
    return index < len(pairs)


def _candidate_payload(
    candidate: dict,
    function_by_id: dict[str, dict],
    occurrence_by_id: dict[str, dict],
    observation_by_id: dict[str, dict],
) -> dict:
    sequence = []
    for function_id in candidate["function_ids"]:
        function = function_by_id[function_id]
        sequence.append({
            "function_id": function_id,
            "function_name": function["function_name"],
            "definition": function["definition"],
        })

    evidence = []
    for item in candidate.get("evidence", []):
        observations = []
        for occurrence_id in item.get("occurrence_ids", []):
            occurrence = occurrence_by_id.get(occurrence_id)
            if occurrence is None:
                raise ValueError(f"motif evidence 引用未知 occurrence: {occurrence_id}")
            observation = observation_by_id.get(occurrence.get("obs_id"))
            if observation is None:
                raise ValueError(f"occurrence 引用未知 Observation: {occurrence_id}")
            if occurrence.get("story_id") != item.get("story_id"):
                raise ValueError(f"motif evidence 故事归属不一致: {occurrence_id}")
            observations.append({
                "obs_id": observation["obs_id"],
                "event": observation.get("event", ""),
                "before_state": observation.get("before_state", ""),
                "after_state": observation.get("after_state", ""),
                "narrative_effect": observation.get("narrative_effect", ""),
                "surface_form": observation.get("surface_form", ""),
            })
        evidence.append({
            "story_id": item.get("story_id"),
            "category": item.get("category"),
            "repeat_counts": item.get("repeat_counts"),
            "observations": observations,
        })
    return {
        "motif_id": candidate["motif_id"],
        "tier": candidate["tier"],
        "sequence": sequence,
        "evidence": evidence,
    }


def review_motif_pairs(state: StoryPatternState) -> dict:
    """审查当前 motif 变体配对，并推进一个 LangGraph 循环位置。"""
    index = state.get("current_motif_pair_index")
    if not isinstance(index, int):
        raise ValueError("review_motif_pairs 需要 current_motif_pair_index")
    if not has_next_motif_pair(state):
        raise IndexError(f"current_motif_pair_index 越界: {index}")

    snapshot_id = str((state.get("snapshot_manifest") or {}).get("snapshot_id") or "").strip()
    if not snapshot_id:
        raise ValueError("review_motif_pairs 需要 Snapshot ID")
    function_by_id = state.get("function_by_id", {})
    if not function_by_id:
        raise ValueError("review_motif_pairs 需要 function_by_id")

    candidates = state.get("motif_candidates", [])
    candidate_by_id = {item.get("motif_id"): item for item in candidates}
    if len(candidate_by_id) != len(candidates) or None in candidate_by_id:
        raise ValueError("motif_candidates 包含缺失或重复 motif_id")

    pairs = state["motif_review_queue"] if "motif_review_queue" in state else state.get("motif_variant_pairs", [])
    pair = pairs[index]
    pair_id = str(pair.get("variant_pair_id") or "").strip()
    member_ids = pair.get("member_motif_ids")
    if pair.get("snapshot_id") != snapshot_id or not pair_id:
        raise ValueError("motif variant pair Snapshot ID 或 pair ID 无效")
    if not isinstance(member_ids, list) or len(member_ids) != 2 or member_ids[0] == member_ids[1]:
        raise ValueError(f"motif variant pair 成员无效: {pair_id}")
    if any(member_id not in candidate_by_id for member_id in member_ids):
        raise ValueError(f"motif variant pair 引用未知 candidate: {pair_id}")
    reviews = list(state.get("motif_pair_reviews", []))
    if any(item.get("variant_pair_id") == pair_id for item in reviews):
        raise ValueError(f"motif pair 已审查: {pair_id}")

    occurrence_by_id = {
        item.get("occurrence_id"): item for item in state.get("all_occurrences", [])
    }
    observation_by_id = {
        item.get("obs_id"): item
        for observations in state.get("observations_by_story", {}).values()
        for item in observations
    }
    payload = {
        "variant_pair": pair,
        "left_motif": _candidate_payload(
            candidate_by_id[member_ids[0]], function_by_id, occurrence_by_id, observation_by_id,
        ),
        "right_motif": _candidate_payload(
            candidate_by_id[member_ids[1]], function_by_id, occurrence_by_id, observation_by_id,
        ),
    }
    result = chat_structured([
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ], MotifPairReview)
    review = result.model_dump()
    review.update({
        "variant_pair_id": pair_id,
        "snapshot_id": snapshot_id,
        "recall_tier": pair.get("recall_tier"),
        "embedding_similarity": pair.get("similarity"),
        "member_motif_ids": list(member_ids),
        "story_ids": list(pair.get("story_ids", [])),
    })
    reviews.append(review)
    return {
        "current_motif_pair_index": index + 1,
        "motif_pair_reviews": reviews,
        "messages": [{
            "role": "system",
            "content": (
                f"[StoryPattern.review_motif_pairs] {index + 1}/"
                f"{len(pairs)}，{pair_id}={result.verdict}"
            ),
        }],
    }
