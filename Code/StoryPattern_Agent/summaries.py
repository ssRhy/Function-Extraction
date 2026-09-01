"""为通过规则检查的 motif cluster 生成故事模式摘要。"""

import json

from Agent.llm import chat_structured
from .Prompt.Summary_prompt import StoryPatternSummary, SUMMARY_SYSTEM_PROMPT
from .state import StoryPatternState


def _cluster_payload(
    cluster: dict,
    candidate_by_id: dict,
    function_by_id: dict,
    function_contract_by_id: dict,
) -> dict:
    members = []
    for motif_id in cluster["member_motif_ids"]:
        candidate = candidate_by_id.get(motif_id)
        if candidate is None:
            raise ValueError(f"cluster 引用未知 motif candidate: {motif_id}")
        sequence = []
        for function_id in candidate.get("function_ids", []):
            function = function_by_id.get(function_id)
            if function is None:
                raise ValueError(f"motif candidate 引用未知 Function: {motif_id}: {function_id}")
            item = {
                "function_id": function_id,
                "function_name": function["function_name"],
                "definition": function["definition"],
            }
            contract = function_contract_by_id.get(function_id)
            if contract is not None:
                item["contract"] = contract
            sequence.append(item)
        members.append({"motif_id": motif_id, "sequence": sequence})
    return {
        "cluster_id": cluster["cluster_id"],
        "snapshot_id": cluster["snapshot_id"],
        "story_support": cluster["story_support"],
        "category_counts": cluster["category_counts"],
        "members": members,
        "evidence": cluster["evidence"],
    }


def summarize_story_patterns(state: StoryPatternState) -> dict:
    """仅为无需人工复核的 cluster 调用 LLM，并绑定可追溯引用。"""
    snapshot_id = str((state.get("snapshot_manifest") or {}).get("snapshot_id") or "").strip()
    if not snapshot_id:
        raise ValueError("summarize_story_patterns 需要 Snapshot ID")
    function_by_id = state.get("function_by_id", {})
    function_contract_by_id = state.get("function_contract_by_id", {})
    candidates = state.get("motif_candidates", [])
    candidate_by_id = {item.get("motif_id"): item for item in candidates}
    if not function_by_id or not candidates or len(candidate_by_id) != len(candidates) or None in candidate_by_id:
        raise ValueError("summarize_story_patterns 需要有效的 functions 和 motif_candidates")

    clusters = state.get("motif_clusters", [])
    if not clusters:
        raise ValueError("summarize_story_patterns 需要 motif_clusters")
    summaries = []
    skipped_clusters = []
    for cluster in clusters:
        cluster_id = str(cluster.get("cluster_id") or "").strip()
        if (
            cluster.get("snapshot_id") != snapshot_id or not cluster_id
            or cluster.get("needs_review") not in {True, False}
            or not isinstance(cluster.get("member_motif_ids"), list)
        ):
            raise ValueError(f"motif cluster 结构无效: {cluster_id}")
        if cluster["needs_review"] or cluster.get("review_incomplete", False):
            skipped_clusters.append(cluster_id)
            continue

        payload = _cluster_payload(
            cluster, candidate_by_id, function_by_id, function_contract_by_id,
        )
        result = chat_structured([
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ], StoryPatternSummary)
        data = result.model_dump()
        function_by_name = {item["function_name"]: item for item in function_by_id.values()}
        core_names = [str(name).strip() for name in data["core_function_names"]]
        if len(core_names) < 4 or any(name not in function_by_name for name in core_names):
            raise ValueError(f"summary 核心 Function 无效: {cluster_id}")
        summaries.append({
            "pattern_id": cluster.get("pattern_id") or f"PAT_{cluster_id.removeprefix('MCL_')}",
            "snapshot_id": snapshot_id,
            "cluster_id": cluster_id,
            "pattern_name": data["pattern_name"].strip(),
            "abstract_definition": data["abstract_definition"].strip(),
            "core_function_chain": [
                {
                    "function_id": function_by_name[name]["function_id"],
                    "function_name": name,
                    "definition": function_by_name[name]["definition"],
                    **({
                        "contract": function_contract_by_id[
                            function_by_name[name]["function_id"]
                        ],
                    } if function_contract_by_id else {}),
                }
                for name in core_names
            ],
            "optional_steps": data["optional_steps"],
            "applicability_conditions": data["applicability_conditions"],
            "counterexamples_limitations": data["counterexamples_limitations"],
            "ending_spec": data["ending_spec"],
            "story_ids": list(cluster["story_ids"]),
            "story_support": cluster["story_support"],
            "category_counts": dict(cluster["category_counts"]),
            "evidence": list(cluster["evidence"]),
            "evidence_count": cluster["evidence_count"],
            "member_motif_ids": list(cluster["member_motif_ids"]),
            "review_edge_ids": list(cluster["same_pattern_edge_ids"]),
        })

    summaries.sort(key=lambda item: item["pattern_id"])
    return {
        "pattern_summaries": summaries,
        "skipped_clusters": skipped_clusters,
        "messages": [{
            "role": "system",
            "content": (
                f"[StoryPattern.summarize_story_patterns] summarized={len(summaries)}，"
                f"skipped_needs_review={len(skipped_clusters)}"
            ),
        }],
    }
