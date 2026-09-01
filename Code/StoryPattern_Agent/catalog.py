"""按固定发布规则生成只读 PatternCatalog。"""

from copy import deepcopy

from .state import StoryPatternState


# MVP-A 暂定：至少由两个不同故事支持，后续只需修改此常量和文档记录。
MIN_PATTERN_STORY_SUPPORT = 2
CATALOG_SCHEMA_VERSION = 2


def publish_pattern_catalog(state: StoryPatternState) -> dict:
    """分流候选、发布、拒绝和人工复核结果，不调用 LLM。"""
    snapshot_id = str((state.get("snapshot_manifest") or {}).get("snapshot_id") or "").strip()
    if not snapshot_id:
        raise ValueError("publish_pattern_catalog 需要 Snapshot ID")

    clusters = state.get("motif_clusters", [])
    summaries = state.get("pattern_summaries", [])
    if not clusters:
        raise ValueError("publish_pattern_catalog 需要 motif_clusters")
    if not isinstance(summaries, list):
        raise ValueError("publish_pattern_catalog 需要 pattern_summaries")
    contract_by_id = state.get("function_contract_by_id", {})
    requires_contracts = (state.get("snapshot_manifest") or {}).get("schema_version", 1) >= 3

    cluster_by_id = {}
    for cluster in clusters:
        cluster_id = str(cluster.get("cluster_id") or "").strip()
        if (
            not cluster_id or cluster_id in cluster_by_id
            or cluster.get("snapshot_id") != snapshot_id
            or not isinstance(cluster.get("story_support"), int)
        ):
            raise ValueError(f"motif cluster 结构无效: {cluster_id}")
        cluster_by_id[cluster_id] = cluster

    summary_by_cluster = {}
    candidate_patterns = []
    for summary in summaries:
        cluster_id = str(summary.get("cluster_id") or "").strip()
        if (
            not cluster_id or cluster_id in summary_by_cluster
            or cluster_id not in cluster_by_id
            or summary.get("snapshot_id") != snapshot_id
            or summary.get("story_support") != cluster_by_id[cluster_id]["story_support"]
        ):
            raise ValueError(f"pattern summary 结构无效: {cluster_id}")
        summary_by_cluster[cluster_id] = summary
        if requires_contracts:
            chain = summary.get("core_function_chain") or []
            for step in chain:
                function_id = step.get("function_id")
                contract = step.get("contract")
                if contract_by_id.get(function_id) != contract:
                    raise ValueError(f"pattern summary 缺少有效 FunctionContract: {cluster_id}")
        candidate_patterns.append(deepcopy(summary))

    published_patterns = []
    rejected_patterns = []
    manual_review_patterns = []
    for cluster_id, cluster in cluster_by_id.items():
        if cluster.get("needs_review"):
            manual_review_patterns.append({
                "cluster_id": cluster_id,
                "snapshot_id": snapshot_id,
                "reason": "CLUSTER_NEEDS_REVIEW",
                "review_reasons": deepcopy(cluster.get("review_reasons", [])),
                "member_motif_ids": list(cluster.get("member_motif_ids", [])),
                "story_ids": list(cluster.get("story_ids", [])),
                "story_support": cluster["story_support"],
                "evidence": deepcopy(cluster.get("evidence", [])),
            })
            continue

        if cluster.get("review_incomplete", False):
            manual_review_patterns.append({
                "cluster_id": cluster_id,
                "snapshot_id": snapshot_id,
                "reason": "REVIEW_INCOMPLETE",
                "review_reasons": [],
                "unreviewed_pair_ids": list(cluster.get("unreviewed_pair_ids", [])),
                "member_motif_ids": list(cluster.get("member_motif_ids", [])),
                "story_ids": list(cluster.get("story_ids", [])),
                "story_support": cluster["story_support"],
                "evidence": deepcopy(cluster.get("evidence", [])),
            })
            continue

        summary = summary_by_cluster.get(cluster_id)
        if summary is None:
            rejected_patterns.append({
                "cluster_id": cluster_id,
                "snapshot_id": snapshot_id,
                "reason": "SUMMARY_MISSING",
                "story_support": cluster["story_support"],
            })
            continue
        if cluster["story_support"] < MIN_PATTERN_STORY_SUPPORT:
            rejected_patterns.append({
                "pattern": deepcopy(summary),
                "reason": "INSUFFICIENT_STORY_SUPPORT",
                "minimum_story_support": MIN_PATTERN_STORY_SUPPORT,
            })
            continue
        published = deepcopy(summary)
        published["publication_status"] = "PUBLISHED"
        published_patterns.append(published)

    published_patterns.sort(key=lambda item: item["pattern_id"])
    rejected_patterns.sort(key=lambda item: item.get("cluster_id") or item.get("pattern", {}).get("pattern_id", ""))
    manual_review_patterns.sort(key=lambda item: item["cluster_id"])
    catalog = {
        "catalog_schema_version": CATALOG_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "status": "SUCCESS",
        "publish_rules": {
            "minimum_story_support": MIN_PATTERN_STORY_SUPPORT,
            "requires_needs_review_false": True,
            "requires_review_incomplete_false": True,
            "requires_summary": True,
            "requires_function_contract": requires_contracts,
        },
        "candidate_patterns": candidate_patterns,
        "published_patterns": published_patterns,
        "rejected_patterns": rejected_patterns,
        "manual_review_patterns": manual_review_patterns,
        "counts": {
            "candidates": len(candidate_patterns),
            "published": len(published_patterns),
            "rejected": len(rejected_patterns),
            "manual_review": len(manual_review_patterns),
        },
    }
    return {
        "pattern_catalog": catalog,
        "messages": [{
            "role": "system",
            "content": (
                f"[StoryPattern.publish_pattern_catalog] published={len(published_patterns)}，"
                f"rejected={len(rejected_patterns)}，manual_review={len(manual_review_patterns)}，"
                f"min_story_support={MIN_PATTERN_STORY_SUPPORT}"
            ),
        }],
    }
