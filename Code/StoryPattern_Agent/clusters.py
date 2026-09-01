"""基于 SAME_PATTERN 审查边构建 motif 候选 cluster。"""

import hashlib
from collections import Counter, defaultdict, deque

from .state import StoryPatternState


_VERDICTS = {"SAME_PATTERN", "RELATED", "DIFFERENT"}


def build_motif_clusters(state: StoryPatternState) -> dict:
    """构建候选 cluster，并保留证据与内部审查冲突。"""
    snapshot_id = str((state.get("snapshot_manifest") or {}).get("snapshot_id") or "").strip()
    if not snapshot_id:
        raise ValueError("build_motif_clusters 需要 Snapshot ID")

    candidates = state.get("motif_candidates", [])
    candidate_by_id = {item.get("motif_id"): item for item in candidates}
    if not candidates or len(candidate_by_id) != len(candidates) or None in candidate_by_id:
        raise ValueError("motif_candidates 为空或包含缺失/重复 motif_id")
    for motif_id, candidate in candidate_by_id.items():
        story_ids = candidate.get("story_ids")
        if (
            candidate.get("snapshot_id") != snapshot_id
            or not isinstance(story_ids, list) or not story_ids
            or candidate.get("story_support") != len(set(story_ids))
            or not isinstance(candidate.get("evidence"), list)
        ):
            raise ValueError(f"motif candidate 结构无效: {motif_id}")

    reviews = state.get("motif_pair_reviews", [])
    reviewed_pairs = defaultdict(list)
    same_edges = []
    for review in reviews:
        pair_id = str(review.get("variant_pair_id") or "").strip()
        members = review.get("member_motif_ids")
        verdict = review.get("verdict")
        if (
            review.get("snapshot_id") != snapshot_id or not pair_id
            or not isinstance(members, list) or len(members) != 2 or members[0] == members[1]
            or any(member not in candidate_by_id for member in members)
            or verdict not in _VERDICTS
        ):
            raise ValueError(f"motif pair review 结构无效: {pair_id}")
        key = tuple(sorted(members))
        reviewed_pairs[key].append(review)
        if verdict == "SAME_PATTERN":
            same_edges.append(key)

    variant_pairs = state.get("motif_variant_pairs", [])
    variant_by_key = {}
    for pair in variant_pairs:
        pair_id = str(pair.get("variant_pair_id") or "").strip()
        members = pair.get("member_motif_ids")
        if (
            pair.get("snapshot_id") != snapshot_id or not pair_id
            or not isinstance(members, list) or len(members) != 2 or members[0] == members[1]
            or any(member not in candidate_by_id for member in members)
        ):
            raise ValueError(f"motif variant pair 结构无效: {pair_id}")
        key = tuple(sorted(members))
        if key in variant_by_key:
            raise ValueError(f"重复 motif variant pair: {pair_id}")
        variant_by_key[key] = pair

    adjacency = defaultdict(set)
    for left, right in same_edges:
        adjacency[left].add(right)
        adjacency[right].add(left)

    components = []
    visited = set()
    for start in sorted(adjacency):
        if start in visited:
            continue
        queue = deque([start])
        visited.add(start)
        members = []
        while queue:
            motif_id = queue.popleft()
            members.append(motif_id)
            for neighbor in sorted(adjacency[motif_id]):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        components.append(sorted(members))
    for motif_id in sorted(set(candidate_by_id) - visited):
        components.append([motif_id])

    clusters = []
    for member_ids in components:
        member_set = set(member_ids)
        internal_reviews = [
            review
            for key, pair_reviews in reviewed_pairs.items()
            if set(key) <= member_set
            for review in pair_reviews
        ]
        internal_reviews.sort(key=lambda item: item["variant_pair_id"])

        reasons = []
        reviewed_pair_keys = set(reviewed_pairs)
        unreviewed_pair_ids = sorted(
            variant_by_key[key]["variant_pair_id"]
            for key in variant_by_key
            if set(key) <= member_set and key not in reviewed_pair_keys
        )
        for review in internal_reviews:
            if review["verdict"] != "SAME_PATTERN":
                reasons.append({
                    "type": "INTERNAL_REVIEW_CONFLICT",
                    "variant_pair_id": review["variant_pair_id"],
                    "verdict": review["verdict"],
                })
            if review.get("order_conflicts"):
                reasons.append({
                    "type": "ORDER_CONFLICT",
                    "variant_pair_id": review["variant_pair_id"],
                    "details": list(review["order_conflicts"]),
                })
        for key, pair_reviews in reviewed_pairs.items():
            if set(key) <= member_set and len({item["verdict"] for item in pair_reviews}) > 1:
                reasons.append({
                    "type": "PAIR_VERDICT_CONFLICT",
                    "member_motif_ids": list(key),
                    "variant_pair_ids": sorted(item["variant_pair_id"] for item in pair_reviews),
                })

        needs_review = bool(reasons)
        review_incomplete = bool(unreviewed_pair_ids)
        review_status = (
            "CONFLICT" if needs_review else
            "INCOMPLETE" if review_incomplete else
            "CLEAN"
        )

        evidence_by_key = {}
        story_categories = {}
        story_ids = set()
        for motif_id in member_ids:
            candidate = candidate_by_id[motif_id]
            story_ids.update(candidate["story_ids"])
            for evidence in candidate["evidence"]:
                story_id = str(evidence.get("story_id") or "").strip()
                category = str(evidence.get("category") or "").strip()
                occurrence_ids = evidence.get("occurrence_ids")
                if not story_id or not category or not isinstance(occurrence_ids, list) or not occurrence_ids:
                    raise ValueError(f"motif evidence 结构无效: {motif_id}")
                if story_id in story_categories and story_categories[story_id] != category:
                    raise ValueError(f"故事题材不一致: {story_id}")
                story_categories[story_id] = category
                key = (
                    story_id,
                    tuple(evidence.get("structural_orders", [])),
                    tuple(evidence.get("repeat_counts", [])),
                    tuple(occurrence_ids),
                )
                if key not in evidence_by_key:
                    evidence_by_key[key] = dict(evidence, source_motif_ids=[])
                evidence_by_key[key]["source_motif_ids"].append(motif_id)

        evidence = list(evidence_by_key.values())
        for item in evidence:
            item["source_motif_ids"].sort()
        evidence.sort(key=lambda item: (
            item["story_id"], item.get("structural_orders", []), item["occurrence_ids"],
        ))
        digest = hashlib.sha256("|".join(member_ids).encode("utf-8")).hexdigest()[:16]
        same_review_ids = sorted(
            item["variant_pair_id"]
            for item in internal_reviews if item["verdict"] == "SAME_PATTERN"
        )
        clusters.append({
            "cluster_id": f"MCL_{digest}",
            "snapshot_id": snapshot_id,
            "member_motif_ids": member_ids,
            "member_count": len(member_ids),
            "story_ids": sorted(story_ids),
            "story_support": len(story_ids),
            "category_counts": dict(sorted(Counter(story_categories.values()).items())),
            "evidence_count": len(evidence),
            "evidence": evidence,
            "same_pattern_edge_ids": same_review_ids,
            "review_edges": internal_reviews,
            "needs_review": needs_review,
            "review_incomplete": review_incomplete,
            "review_status": review_status,
            "unreviewed_pair_ids": unreviewed_pair_ids,
            "review_reasons": reasons,
        })

    clusters.sort(key=lambda item: (
        item["needs_review"], -item["story_support"], -item["member_count"], item["cluster_id"],
    ))
    return {
        "motif_clusters": clusters,
        "messages": [{
            "role": "system",
            "content": (
                f"[StoryPattern.build_motif_clusters] same_edges={len(same_edges)}，"
                f"clusters={len(clusters)}，needs_review="
                f"{sum(item['needs_review'] for item in clusters)}"
            ),
        }],
    }
