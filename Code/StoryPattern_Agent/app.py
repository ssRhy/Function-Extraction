"""DB 驱动的增量 Pattern Evolve LangGraph。"""

import argparse
import hashlib
import json
import time
from collections import Counter, defaultdict

from langgraph.graph import END, START, StateGraph

from KnowledgeBase import DEFAULT_DB_PATH, StoryKnowledgeStore
from Contracts.run_result import failed_run_result
from .clusters import build_motif_clusters
from .inputs import load_inputs
from .review import review_motif_pairs
from .sequences import annotate_repetitions, build_story_sequences, load_occurrences_node
from .state import StoryPatternState
from .summaries import summarize_story_patterns
from .variants import retrieve_motif_variants


PATTERN_STAGE_TIMEOUT_SECONDS = 15 * 60


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(*values) -> str:
    return hashlib.sha256("|".join(str(value) for value in values).encode("utf-8")).hexdigest()


def _check_stage_timeout(stage: str, deadline: float, completed: int) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError(
            f"Pattern {stage} 阶段超时：已完成 {completed} 条，"
            f"预算 {PATTERN_STAGE_TIMEOUT_SECONDS}s"
        )


def _occurrence_signature(items: list[dict]) -> str:
    ordered = sorted(items, key=lambda item: (
        min(item.get("source_sentence_indices") or [0]), item["occurrence_id"],
    ))
    return _digest(_json([{
        "occurrence_id": item["occurrence_id"],
        "obs_id": item["obs_id"],
        "function_id": item.get("function_id"),
        "status": item["status"],
        "source_sentence_indices": item.get("source_sentence_indices") or [],
    } for item in ordered]))


def _summary_input_signature(state: StoryPatternState, cluster: dict) -> str:
    """只绑定该 Cluster 摘要实际使用的 Function 定义与 Contract。"""
    candidate_by_id = {item["motif_id"]: item for item in state["motif_candidates"]}
    function_names = {
        function_id: function_name
        for candidate in candidate_by_id.values()
        for function_id, function_name in zip(
            candidate["function_ids"], candidate.get("function_names", []),
        )
    }
    function_ids = sorted({
        function_id
        for motif_id in cluster["member_motif_ids"]
        for function_id in candidate_by_id[motif_id]["function_ids"]
    })
    payload = []
    for function_id in function_ids:
        function = state.get("function_by_id", {}).get(function_id, {})
        payload.append({
            "function_id": function_id,
            "function_name": function.get("function_name") or function_names.get(function_id, ""),
            "definition": function.get("definition", ""),
            "contract": state.get("function_contract_by_id", {}).get(function_id),
        })
    return _digest(_json(payload))


def load_pattern_delta(state: StoryPatternState) -> dict:
    """固定父子 Snapshot，并只从 DB 计算故事级变化。"""
    store = StoryKnowledgeStore(state["knowledge_db"])
    source = load_inputs(state)
    loaded = {**state, **source}
    occurrences = load_occurrences_node(loaded)
    loaded.update(occurrences)
    manifest = loaded["snapshot_manifest"]
    snapshot_id = manifest["snapshot_id"]
    parent_snapshot_id = store.load_snapshot_manifest(snapshot_id).get("parent_snapshot_id")
    if parent_snapshot_id is None:
        with store.connect() as conn:
            row = conn.execute(
                "SELECT parent_snapshot_id FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
        parent_snapshot_id = row["parent_snapshot_id"] if row else None
    workflow = manifest["source_workflow"]
    if workflow == "evolve" and not parent_snapshot_id:
        raise ValueError("Evolve Snapshot 缺少父 Snapshot")

    parent_sequences = store.load_pattern_sequences(parent_snapshot_id)
    if workflow == "evolve" and not parent_sequences:
        raise ValueError(f"父 Snapshot 缺少 Pattern sequence: {parent_snapshot_id}")
    signatures = {
        story_id: _occurrence_signature(items)
        for story_id, items in loaded["occurrences_by_story"].items()
    }
    parent_story_ids = set(parent_sequences)
    current_story_ids = set(signatures)
    new_story_ids = sorted(current_story_ids - parent_story_ids)
    removed_story_ids = sorted(parent_story_ids - current_story_ids)
    changed_story_ids = sorted(
        story_id for story_id in current_story_ids & parent_story_ids
        if signatures[story_id] != parent_sequences[story_id]["occurrence_signature"]
    )
    unchanged_story_ids = sorted(
        current_story_ids - set(new_story_ids) - set(changed_story_ids)
    )
    return {
        **source,
        **occurrences,
        "parent_snapshot_id": parent_snapshot_id,
        "namespace": manifest["namespace"],
        "workflow": workflow,
        "parent_sequences": parent_sequences,
        "occurrence_signatures": signatures,
        "new_story_ids": new_story_ids,
        "changed_story_ids": changed_story_ids,
        "unchanged_story_ids": unchanged_story_ids,
        "removed_story_ids": removed_story_ids,
        "parent_clusters": store.load_motif_clusters(parent_snapshot_id),
        "parent_patterns": store.load_snapshot_pattern_rows(parent_snapshot_id),
        "messages": [{
            "role": "system",
            "content": (
                f"[Pattern.load_pattern_delta] new={len(new_story_ids)}, "
                f"changed={len(changed_story_ids)}, unchanged={len(unchanged_story_ids)}, "
                f"removed={len(removed_story_ids)}"
            ),
        }],
    }


def update_story_sequences(state: StoryPatternState) -> dict:
    """继承未变化序列，只重建新增或变化故事。"""
    records = {}
    raw_sequences = {}
    structural_sequences = {}
    parent_snapshot_id = state.get("parent_snapshot_id")
    for story_id in state["unchanged_story_ids"]:
        parent = state["parent_sequences"][story_id]
        payload = dict(parent["payload"])
        raw_sequences[story_id] = payload["raw_sequence"]
        structural_sequences[story_id] = payload["structural_sequence"]
        records[story_id] = {
            "occurrence_signature": state["occurrence_signatures"][story_id],
            "inherited_from_snapshot_id": parent_snapshot_id,
            "payload": payload,
        }
    for story_id in sorted(set(state["new_story_ids"] + state["changed_story_ids"])):
        working = {**state, "current_story_id": story_id, "story_sequences": raw_sequences}
        sequence_result = build_story_sequences(working)
        raw_sequences = sequence_result["story_sequences"]
        working.update(sequence_result)
        working["structural_sequences"] = structural_sequences
        structural_result = annotate_repetitions(working)
        structural_sequences = structural_result["structural_sequences"]
        payload = {
            "story_id": story_id,
            "raw_sequence": raw_sequences[story_id],
            "structural_sequence": structural_sequences[story_id],
        }
        records[story_id] = {
            "occurrence_signature": state["occurrence_signatures"][story_id],
            "inherited_from_snapshot_id": None,
            "payload": payload,
        }
    return {
        "story_sequences": raw_sequences,
        "structural_sequences": structural_sequences,
        "sequence_records": records,
        "messages": [{
            "role": "system",
            "content": (
                f"[Pattern.update_story_sequences] rebuilt="
                f"{len(state['new_story_ids']) + len(state['changed_story_ids'])}, "
                f"inherited={len(state['unchanged_story_ids'])}"
            ),
        }],
    }


def _story_motif_rows(state: StoryPatternState, story_id: str) -> list[dict]:
    rows = []
    segment = []
    category = str((state["story_metadata"].get(story_id) or {}).get("story_type") or "uncategorized")

    def add_windows() -> None:
        if len(segment) < 3:
            return
        for length in range(3, min(6, len(segment)) + 1):
            for start in range(len(segment) - length + 1):
                window = segment[start:start + length]
                function_ids = [item["function_id"] for item in window]
                motif_id = "MC_" + _digest(*function_ids)[:16]
                rows.append({
                    "motif_id": motif_id,
                    "function_ids": function_ids,
                    "function_names": [state["function_by_id"][item]["function_name"] for item in function_ids],
                    "length": length,
                    "evidence": {
                        "story_id": story_id,
                        "category": category,
                        "structural_orders": [item["order"] for item in window],
                        "repeat_counts": [item["repeat_count"] for item in window],
                        "occurrence_ids": [
                            occurrence_id for item in window for occurrence_id in item["occurrence_ids"]
                        ],
                    },
                })

    for item in state["structural_sequences"][story_id]:
        if item["status"] == "MATCHED":
            segment.append(item)
        else:
            add_windows()
            segment = []
    add_windows()
    return rows


def update_motif_evidence(state: StoryPatternState) -> dict:
    """继承未变化故事的 Motif 证据，并更新变化故事。"""
    store = StoryKnowledgeStore(state["knowledge_db"])
    unchanged = set(state["unchanged_story_ids"])
    rows = [
        item for item in store.load_motif_evidence(state.get("parent_snapshot_id"))
        if item["evidence"]["story_id"] in unchanged
    ]
    for story_id in sorted(set(state["new_story_ids"] + state["changed_story_ids"])):
        rows.extend(_story_motif_rows(state, story_id))

    grouped = {}
    for row in rows:
        motif = grouped.setdefault(row["motif_id"], {
            "motif_id": row["motif_id"],
            "snapshot_id": state["snapshot_id"],
            "function_ids": list(row["function_ids"]),
            "length": row["length"],
            "evidence": [],
        })
        evidence = row["evidence"]
        motif["evidence"].append({
            key: evidence[key]
            for key in (
                "story_id", "category", "structural_orders", "repeat_counts", "occurrence_ids",
            )
            if key in evidence
        })
    candidates = []
    for motif in grouped.values():
        function_names = []
        for function_id in motif["function_ids"]:
            function = state["function_by_id"].get(function_id)
            if function is None:
                raise ValueError(f"Motif 证据引用未知 Function: {motif['motif_id']}: {function_id}")
            function_names.append(function["function_name"])
        motif["function_names"] = function_names
        motif["evidence"].sort(key=lambda item: (
            item["story_id"], item["structural_orders"], item["occurrence_ids"],
        ))
        story_ids = sorted({item["story_id"] for item in motif["evidence"]})
        motif.update({
            "story_ids": story_ids,
            "story_support": len(story_ids),
            "evidence_count": len(motif["evidence"]),
            "tier": "REPEATED" if len(story_ids) >= 2 else "SINGLE_STORY",
            "category_counts": dict(sorted(Counter(
                item["category"] for item in motif["evidence"]
            ).items())),
        })
        candidates.append(motif)
    candidates.sort(key=lambda item: item["motif_id"])
    return {
        "motif_candidates": candidates,
        "messages": [{
            "role": "system",
            "content": f"[Pattern.update_motif_evidence] motifs={len(candidates)}, evidence={len(rows)}",
        }],
    }


def _pair_input_signature(state: StoryPatternState, pair: dict) -> str:
    candidate_by_id = {item["motif_id"]: item for item in state["motif_candidates"]}
    function_payload = {
        function_id: {
            "definition": state["function_by_id"][function_id]["definition"],
            "contract": state["function_contract_by_id"].get(function_id),
        }
        for motif_id in pair["member_motif_ids"]
        for function_id in candidate_by_id[motif_id]["function_ids"]
    }
    motif_payload = [{
        "motif_id": motif_id,
        "function_ids": candidate_by_id[motif_id]["function_ids"],
        "evidence": candidate_by_id[motif_id]["evidence"],
    } for motif_id in pair["member_motif_ids"]]
    return _digest(_json({"functions": function_payload, "motifs": motif_payload}))


def retrieve_variant_pairs(state: StoryPatternState) -> dict:
    if len(state["motif_candidates"]) < 2:
        return {"motif_variant_pairs": [], "messages": [{
            "role": "system", "content": "[Pattern.retrieve_variant_pairs] pairs=0",
        }]}
    result = retrieve_motif_variants(state)
    candidate_by_id = {item["motif_id"]: item for item in state["motif_candidates"]}
    review_pairs = []
    for item in result["motif_variant_pairs"]:
        members = item["member_motif_ids"]
        ranks = {selected["motif_id"]: selected["rank"] for selected in item["selected_by"]}
        if (
            item["recall_tier"] != "HIGH"
            or max(candidate_by_id[motif_id]["length"] for motif_id in members) < 4
            or set(ranks) != set(members)
            or max(ranks.values()) > 2
        ):
            continue
        pair = dict(item)
        pair["input_signature"] = _pair_input_signature(state, pair)
        review_pairs.append(pair)
    return {
        "motif_variant_pairs": review_pairs,
        "messages": result["messages"] + [{
            "role": "system",
            "content": f"[Pattern.retrieve_variant_pairs] review_pairs={len(review_pairs)}",
        }],
    }


def _review_selected(state: StoryPatternState, selected: list[dict]) -> list[dict]:
    store = StoryKnowledgeStore(state["knowledge_db"])
    reviews = list(state.get("motif_pair_reviews", []))
    deadline = time.monotonic() + PATTERN_STAGE_TIMEOUT_SECONDS
    for index, pair in enumerate(selected, 1):
        _check_stage_timeout("Motif Review", deadline, index - 1)
        cached = store.load_motif_pair_review(pair["variant_pair_id"], pair["input_signature"])
        if cached:
            review = dict(cached)
            review["snapshot_id"] = state["snapshot_id"]
        else:
            working = {
                **state,
                "motif_review_queue": [pair],
                "current_motif_pair_index": 0,
                "motif_pair_reviews": [],
            }
            review = review_motif_pairs(working)["motif_pair_reviews"][0]
        review["input_signature"] = pair["input_signature"]
        review["embedding_similarity"] = pair["similarity"]
        review["recall_tier"] = pair["recall_tier"]
        reviews.append(review)
        _check_stage_timeout("Motif Review", deadline, index)
    return reviews


def review_changed_pairs(state: StoryPatternState) -> dict:
    selected = state["motif_variant_pairs"]
    reviews = _review_selected(state, selected)
    return {
        "motif_pair_reviews": reviews,
        "messages": [{
            "role": "system",
            "content": f"[Pattern.review_changed_pairs] high={len(selected)}, reviewed={len(reviews)}",
        }],
    }


def rebuild_clusters(state: StoryPatternState) -> dict:
    if not state["motif_candidates"]:
        retired = sorted({
            item.get("pattern_id") for item in state.get("parent_clusters", [])
            if item.get("pattern_id")
        })
        return {"motif_clusters": [], "changed_cluster_ids": [],
                "retired_pattern_ids": retired, "messages": [{
            "role": "system", "content": "[Pattern.rebuild_clusters] clusters=0",
        }]}
    result = build_motif_clusters(state)
    clusters = result["motif_clusters"]
    parent_clusters = state.get("parent_clusters", [])
    parent_patterns = {item["pattern_id"]: item for item in state.get("parent_patterns", [])}
    parent_by_id = {item["cluster_id"]: item for item in parent_clusters}
    children_by_parent = defaultdict(list)
    for cluster in clusters:
        members = set(cluster["member_motif_ids"])
        parent_ids = sorted(
            item["cluster_id"] for item in parent_clusters
            if members & set(item["member_motif_ids"])
        )
        cluster["parent_cluster_ids"] = parent_ids
        for parent_id in parent_ids:
            children_by_parent[parent_id].append(cluster)

    contract_by_id = state["function_contract_by_id"]
    requires_contracts = bool(state["snapshot_manifest"].get("function_contracts_file"))
    for cluster in clusters:
        candidates = [
            item for item in state["motif_candidates"]
            if item["motif_id"] in cluster["member_motif_ids"]
        ]
        anchor_candidates = [
            item for item in candidates
            if len(item.get("function_ids", [])) >= 4
        ] or candidates
        anchor = sorted(anchor_candidates, key=lambda item: (
            -item["story_support"], -item["length"], item["motif_id"],
        ))[0]
        cluster["anchor_motif_id"] = anchor["motif_id"]
        cluster["structure_signature"] = _digest(_json(sorted(
            (item["motif_id"], item["function_ids"]) for item in candidates
        )))
        cluster["summary_input_signature"] = _summary_input_signature(state, cluster)
        eligible = (
            cluster["review_status"] == "CLEAN"
            and cluster["story_support"] >= 2
            and max(item["length"] for item in candidates) >= 4
            and (
                not requires_contracts
                or all(function_id in contract_by_id for function_id in anchor["function_ids"])
            )
        )
        cluster["status"] = (
            "blocked" if cluster["review_status"] == "CONFLICT"
            else "published" if eligible else "candidate"
        )

        parent_pattern_ids = sorted({
            parent_by_id[parent_id].get("pattern_id")
            for parent_id in cluster["parent_cluster_ids"]
            if parent_by_id[parent_id].get("pattern_id") in parent_patterns
        })
        pattern_id = None
        if len(parent_pattern_ids) > 1:
            pattern_id = min(
                parent_pattern_ids,
                key=lambda item: (parent_patterns[item].get("born_at") or "", item),
            )
            cluster["merged_pattern_ids"] = [item for item in parent_pattern_ids if item != pattern_id]
        elif len(parent_pattern_ids) == 1:
            candidate_pattern_id = parent_pattern_ids[0]
            parent_cluster = next(
                parent_by_id[item] for item in cluster["parent_cluster_ids"]
                if parent_by_id[item].get("pattern_id") == candidate_pattern_id
            )
            siblings = children_by_parent[parent_cluster["cluster_id"]]
            if len(siblings) == 1 or parent_cluster.get("anchor_motif_id") in cluster["member_motif_ids"]:
                pattern_id = candidate_pattern_id
        if pattern_id is None and cluster["status"] == "published":
            pattern_id = "PAT_" + _digest(cluster["anchor_motif_id"])[:16]
        cluster["pattern_id"] = pattern_id

    current_parent_ids = {
        parent_id for cluster in clusters for parent_id in cluster["parent_cluster_ids"]
    }
    changed = [
        cluster["cluster_id"] for cluster in clusters
        if not cluster["parent_cluster_ids"]
        or len(cluster["parent_cluster_ids"]) != 1
        or parent_by_id[cluster["parent_cluster_ids"][0]].get("structure_signature") != cluster["structure_signature"]
        or parent_by_id[cluster["parent_cluster_ids"][0]].get("summary_input_signature") != cluster["summary_input_signature"]
        or parent_by_id[cluster["parent_cluster_ids"][0]].get("story_ids") != cluster["story_ids"]
    ]
    retired = [
        item.get("pattern_id") for item in parent_clusters
        if item["cluster_id"] not in current_parent_ids and item.get("pattern_id")
    ]
    return {
        "motif_clusters": clusters,
        "changed_cluster_ids": sorted(changed),
        "retired_pattern_ids": sorted(set(retired)),
        "messages": [{
            "role": "system",
            "content": (
                f"[Pattern.rebuild_clusters] clusters={len(clusters)}, "
                f"published={sum(item['status'] == 'published' for item in clusters)}, "
                f"blocked={sum(item['status'] == 'blocked' for item in clusters)}"
            ),
        }],
    }


def summarize_changed_clusters(state: StoryPatternState) -> dict:
    parent_patterns = {item["pattern_id"]: item for item in state.get("parent_patterns", [])}
    parent_clusters = {
        item.get("pattern_id"): item
        for item in state.get("parent_clusters", [])
        if item.get("pattern_id")
    }
    pattern_records = []
    new_pattern_ids = []
    summary_count = 0
    summary_deadline = time.monotonic() + PATTERN_STAGE_TIMEOUT_SECONDS
    for cluster in state["motif_clusters"]:
        pattern_id = cluster.get("pattern_id")
        if not pattern_id or cluster["status"] == "candidate":
            continue
        parent = parent_patterns.get(pattern_id)
        if cluster["status"] == "blocked":
            if parent:
                pattern = dict(parent["pattern"])
                pattern.update({"snapshot_id": state["snapshot_id"], "publication_status": "BLOCKED"})
                pattern_records.append({
                    "pattern_id": pattern_id,
                    "pattern_version_id": parent["pattern_version_id"],
                    "status": "blocked",
                    "is_new": False,
                    "structure_signature": parent["structure_signature"],
                    "pattern": pattern,
                    "version": None,
                })
            continue

        same_structure = bool(parent and parent["structure_signature"] == cluster["structure_signature"])
        parent_cluster = parent_clusters.get(pattern_id)
        same_summary_input = bool(
            parent and parent_cluster
            and parent_cluster.get("summary_input_signature") == cluster["summary_input_signature"]
        )
        if same_structure and same_summary_input:
            pattern = dict(parent["pattern"])
            pattern.update({
                "snapshot_id": state["snapshot_id"],
                "cluster_id": cluster["cluster_id"],
                "story_ids": list(cluster["story_ids"]),
                "story_support": cluster["story_support"],
                "category_counts": dict(cluster["category_counts"]),
                "evidence": list(cluster["evidence"]),
                "evidence_count": cluster["evidence_count"],
                "member_motif_ids": list(cluster["member_motif_ids"]),
                "publication_status": "PUBLISHED",
            })
        else:
            _check_stage_timeout("Pattern Summary", summary_deadline, summary_count)
            summary_state = {
                **state,
                "motif_clusters": [cluster],
                "pattern_summaries": [],
            }
            summaries = summarize_story_patterns(summary_state)["pattern_summaries"]
            if len(summaries) != 1:
                raise ValueError(f"Pattern summary 数量异常: {cluster['cluster_id']}")
            pattern = summaries[0]
            pattern["publication_status"] = "PUBLISHED"
            summary_count += 1
            _check_stage_timeout("Pattern Summary", summary_deadline, summary_count)

        evidence_changed = not parent or sorted(parent["pattern"].get("story_ids") or []) != cluster["story_ids"]
        if parent and same_structure and same_summary_input and not evidence_changed:
            version_id = parent["pattern_version_id"]
            version = None
        else:
            action = (
                "CREATE" if not parent else
                "STRUCTURE_EXTENDED" if not same_structure else
                "SEMANTICS_REVISED" if not same_summary_input else "EVIDENCE_EXTENDED"
            )
            version_id = "PV_" + _digest(
                pattern_id, state["snapshot_id"], action,
                cluster["structure_signature"], cluster["summary_input_signature"],
                _json(cluster["story_ids"]),
            )[:16]
            version = {
                "pattern_version_id": version_id,
                "pattern_id": pattern_id,
                "snapshot_id": state["snapshot_id"],
                "parent_version_id": parent["pattern_version_id"] if parent else None,
                "action": action,
                "structure_signature": cluster["structure_signature"],
                "summary_input_signature": cluster["summary_input_signature"],
                "pattern": pattern,
            }
        is_new = parent is None
        if is_new:
            new_pattern_ids.append(pattern_id)
        pattern_records.append({
            "pattern_id": pattern_id,
            "pattern_version_id": version_id,
            "status": "published",
            "is_new": is_new,
            "structure_signature": cluster["structure_signature"],
            "summary_input_signature": cluster["summary_input_signature"],
            "pattern": pattern,
            "version": version,
        })
    lifecycle = set(state.get("retired_pattern_ids", []))
    merged = {
        pattern_id
        for cluster in state["motif_clusters"]
        for pattern_id in cluster.get("merged_pattern_ids", [])
    }
    active_ids = {item["pattern_id"] for item in pattern_records}
    for status, pattern_ids in (("merged", merged), ("retired", lifecycle)):
        for pattern_id in sorted(pattern_ids - active_ids):
            parent = parent_patterns.get(pattern_id)
            if not parent:
                continue
            pattern = dict(parent["pattern"])
            pattern.update({"snapshot_id": state["snapshot_id"], "publication_status": status.upper()})
            pattern_records.append({
                "pattern_id": pattern_id,
                "pattern_version_id": parent["pattern_version_id"],
                "status": status,
                "is_new": False,
                "structure_signature": parent["structure_signature"],
                "pattern": pattern,
                "version": None,
            })
    return {
        "pattern_records": pattern_records,
        "new_pattern_ids": sorted(new_pattern_ids),
        "messages": [{
            "role": "system",
            "content": (
                f"[Pattern.summarize_changed_clusters] llm_summaries={summary_count}, "
                f"new_patterns={len(new_pattern_ids)}"
            ),
        }],
    }


def publish_pattern_set(state: StoryPatternState) -> dict:
    store = StoryKnowledgeStore(state["knowledge_db"])
    result = {
        "status": "SUCCESS",
        "parent_snapshot_id": state.get("parent_snapshot_id"),
        "namespace": state["namespace"],
        "workflow": state["workflow"],
        "story_delta": {
            "new": state["new_story_ids"],
            "changed": state["changed_story_ids"],
            "unchanged": state["unchanged_story_ids"],
            "removed": state["removed_story_ids"],
        },
        "counts": {
            "sequences": len(state["sequence_records"]),
            "motifs": len(state["motif_candidates"]),
            "pair_reviews": len(state["motif_pair_reviews"]),
            "clusters": len(state["motif_clusters"]),
            "candidate_clusters": sum(item["status"] == "candidate" for item in state["motif_clusters"]),
            "published_clusters": sum(item["status"] == "published" for item in state["motif_clusters"]),
            "blocked_clusters": sum(item["status"] == "blocked" for item in state["motif_clusters"]),
            "published_patterns": sum(item["status"] == "published" for item in state["pattern_records"]),
            "blocked_patterns": sum(item["status"] == "blocked" for item in state["pattern_records"]),
            "retired_patterns": sum(item["status"] == "retired" for item in state["pattern_records"]),
            "merged_patterns": sum(item["status"] == "merged" for item in state["pattern_records"]),
        },
        "new_pattern_ids": state["new_pattern_ids"],
        "updated_pattern_ids": sorted(
            item["pattern_id"] for item in state["pattern_records"]
            if not item["is_new"] and item.get("version")
        ),
    }
    committed = store.commit_pattern_run(state["snapshot_id"], {
        "sequences": state["sequence_records"],
        "motifs": state["motif_candidates"],
        "reviews": state["motif_pair_reviews"],
        "clusters": state["motif_clusters"],
        "patterns": state["pattern_records"],
        "result": result,
    })
    return {
        "pattern_result": committed,
        "messages": [{
            "role": "system",
            "content": f"[Pattern.publish_pattern_set] published={result['counts']['published_patterns']}",
        }],
    }


def _build_graph() -> StateGraph:
    graph = StateGraph(StoryPatternState)
    graph.add_node("load_pattern_delta", load_pattern_delta)
    graph.add_node("update_story_sequences", update_story_sequences)
    graph.add_node("update_motif_evidence", update_motif_evidence)
    graph.add_node("retrieve_variant_pairs", retrieve_variant_pairs)
    graph.add_node("review_changed_pairs", review_changed_pairs)
    graph.add_node("rebuild_clusters", rebuild_clusters)
    graph.add_node("summarize_changed_clusters", summarize_changed_clusters)
    graph.add_node("publish_pattern_set", publish_pattern_set)
    graph.add_edge(START, "load_pattern_delta")
    graph.add_edge("load_pattern_delta", "update_story_sequences")
    graph.add_edge("update_story_sequences", "update_motif_evidence")
    graph.add_edge("update_motif_evidence", "retrieve_variant_pairs")
    graph.add_edge("retrieve_variant_pairs", "review_changed_pairs")
    graph.add_edge("review_changed_pairs", "rebuild_clusters")
    graph.add_edge("rebuild_clusters", "summarize_changed_clusters")
    graph.add_edge("summarize_changed_clusters", "publish_pattern_set")
    graph.add_edge("publish_pattern_set", END)
    return graph


def run_pattern_evolve(
    snapshot_id: str, knowledge_db=DEFAULT_DB_PATH, rebuild: bool = False,
) -> dict:
    store = StoryKnowledgeStore(knowledge_db)
    existing = store.load_pattern_run(snapshot_id)
    if existing and existing["status"] == "SUCCESS" and not rebuild:
        return existing["payload"]
    if rebuild:
        store.clear_pattern_snapshot(snapshot_id)
    manifest = store.load_snapshot_manifest(snapshot_id)
    with store.connect() as conn:
        row = conn.execute(
            "SELECT parent_snapshot_id FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
    input_signature = _digest(snapshot_id, row["parent_snapshot_id"], _json(manifest))
    run = None
    try:
        run = store.begin_pattern_run(snapshot_id, input_signature)
        result = _build_graph().compile().invoke({
            "messages": [],
            "knowledge_db": str(knowledge_db),
            "snapshot_id": snapshot_id,
        })
        return result["pattern_result"]
    except BaseException as exc:
        error = str(exc) or type(exc).__name__
        if run:
            store.fail_pattern_run(snapshot_id, failed_run_result(
                stage="pattern", workflow=run["workflow"], run_id=run["run_id"],
                namespace=run["namespace"], snapshot_id=snapshot_id,
                parent_snapshot_id=run.get("parent_snapshot_id"),
                error_code="PATTERN_RUN_FAILED", error=error,
                retryable=isinstance(exc, (TimeoutError, ConnectionError)),
            ))
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="StoryPattern_Agent")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--knowledge-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_pattern_evolve(args.snapshot, args.knowledge_db, args.rebuild)
        print(json.dumps({"run_result": result}, ensure_ascii=False))
        return 0
    except BaseException as exc:
        run = StoryKnowledgeStore(args.knowledge_db).load_pattern_run(args.snapshot)
        if run and isinstance(run.get("payload"), dict) and run["payload"].get("status") == "FAILED":
            failure = run["payload"]
        else:
            failure = failed_run_result(
                stage="pattern", workflow=run.get("workflow") if run else None,
                run_id=run.get("run_id") if run else None,
                namespace=run.get("namespace") if run else None,
                snapshot_id=args.snapshot, parent_snapshot_id=run.get("parent_snapshot_id") if run else None,
                error_code="PATTERN_START_FAILED", error=str(exc) or type(exc).__name__,
            )
        print(json.dumps({"run_result": failure}, ensure_ascii=False))
        return 1
