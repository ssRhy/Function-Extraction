"""为 EXPANDED motif pair 生成分阶段审查队列。"""

from .state import StoryPatternState


def build_expanded_review_queue(state: StoryPatternState) -> dict:
    """按 cluster 内部、cluster 桥接、其余候选的顺序排列 EXPANDED pair。"""
    snapshot_id = str((state.get("snapshot_manifest") or {}).get("snapshot_id") or "").strip()
    if not snapshot_id:
        raise ValueError("build_expanded_review_queue 需要 Snapshot ID")
    pairs = state.get("motif_variant_pairs", [])
    reviews = state.get("motif_pair_reviews", [])
    clusters = state.get("motif_clusters", [])
    if not pairs:
        raise ValueError("build_expanded_review_queue 需要 motif_variant_pairs")
    if not clusters:
        raise ValueError("build_expanded_review_queue 需要 motif_clusters")

    reviewed = {
        tuple(sorted(item["member_motif_ids"]))
        for item in reviews
        if isinstance(item.get("member_motif_ids"), list) and len(item["member_motif_ids"]) == 2
    }
    motif_cluster = {}
    for cluster in clusters:
        for motif_id in cluster.get("member_motif_ids", []):
            motif_cluster[motif_id] = cluster["cluster_id"]

    queue = []
    for pair in pairs:
        if pair.get("snapshot_id") != snapshot_id:
            raise ValueError(f"motif variant pair Snapshot ID 不匹配: {pair.get('variant_pair_id')}")
        if pair.get("recall_tier") != "EXPANDED":
            continue
        members = pair.get("member_motif_ids")
        if not isinstance(members, list) or len(members) != 2 or members[0] == members[1]:
            raise ValueError(f"motif variant pair 成员无效: {pair.get('variant_pair_id')}")
        key = tuple(sorted(members))
        if key in reviewed:
            continue
        left_cluster = motif_cluster.get(members[0])
        right_cluster = motif_cluster.get(members[1])
        if left_cluster and left_cluster == right_cluster:
            priority, reason = 1, "INTERNAL_CLUSTER_PAIR"
        elif left_cluster and right_cluster and left_cluster != right_cluster:
            priority, reason = 2, "CLUSTER_BRIDGE_PAIR"
        else:
            priority, reason = 3, "UNCONNECTED_PAIR"
        item = dict(pair)
        item["review_priority"] = priority
        item["queue_reason"] = reason
        queue.append(item)

    queue.sort(key=lambda item: (
        item["review_priority"], -item.get("similarity", 0.0), item["variant_pair_id"],
    ))
    return {
        "motif_review_queue": queue,
        "messages": [{
            "role": "system",
            "content": (
                f"[StoryPattern.build_expanded_review_queue] total={len(queue)}，"
                f"internal={sum(item['review_priority'] == 1 for item in queue)}，"
                f"bridge={sum(item['review_priority'] == 2 for item in queue)}，"
                f"unconnected={sum(item['review_priority'] == 3 for item in queue)}"
            ),
        }],
    }
