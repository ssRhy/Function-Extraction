"""DB 驱动的增量 Pattern Evolve LangGraph。"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict

from langgraph.graph import END, START, StateGraph

from KnowledgeBase import DEFAULT_DB_PATH, StoryKnowledgeStore
from .clusters import build_motif_clusters
from .inputs import load_inputs
from .review import review_motif_pairs
from .sequences import annotate_repetitions, build_story_sequences, load_occurrences_node
from .state import StoryPatternState
from .summaries import summarize_story_patterns
from .variants import retrieve_motif_variants


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(*values) -> str:
    return hashlib.sha256("|".join(str(value) for value in values).encode("utf-8")).hexdigest()


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
    category = str((state["story_metadata"].get(story_id) or {}).get("category") or "uncategorized")

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
            "function_names": list(row["function_names"]),
            "length": row["length"],
            "evidence": [],
        })
        motif["evidence"].append(dict(row["evidence"]))
    candidates = []
    for motif in grouped.values():
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
    pairs = []
    for item in result["motif_variant_pairs"]:
        pair = dict(item)
        pair["input_signature"] = _pair_input_signature(state, pair)
        pairs.append(pair)
    return {"motif_variant_pairs": pairs, "messages": result["messages"]}


def _review_selected(state: StoryPatternState, selected: list[dict]) -> list[dict]:
    store = StoryKnowledgeStore(state["knowledge_db"])
    reviews = list(state.get("motif_pair_reviews", []))
    for pair in selected:
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
    return reviews


def review_changed_pairs(state: StoryPatternState) -> dict:
    selected = [item for item in state["motif_variant_pairs"] if item["recall_tier"] == "HIGH"]
    reviews = _review_selected(state, selected)
    return {
        "motif_pair_reviews": reviews,
        "messages": [{
            "role": "system",
            "content": f"[Pattern.review_changed_pairs] high={len(selected)}, reviewed={len(reviews)}",
        }],
    }


def _same_components(motif_ids: list[str], reviews: list[dict]) -> dict[str, set[str]]:
    adjacency = {motif_id: set() for motif_id in motif_ids}
    for review in reviews:
        if review["verdict"] == "SAME_PATTERN":
            left, right = review["member_motif_ids"]
            adjacency[left].add(right)
            adjacency[right].add(left)
    components = {}
    for motif_id in motif_ids:
        if motif_id in components:
            continue
        members, stack = set(), [motif_id]
        while stack:
            current = stack.pop()
            if current in members:
                continue
            members.add(current)
            stack.extend(adjacency[current] - members)
        for member in members:
            components[member] = members
    return components


def review_internal_bridges(state: StoryPatternState) -> dict:
    """只补审会影响已形成 Cluster 或重复 Motif 的 EXPANDED 边。"""
    reviews = list(state.get("motif_pair_reviews", []))
    reviewed = {tuple(sorted(item["member_motif_ids"])) for item in reviews}
    candidate_by_id = {item["motif_id"]: item for item in state["motif_candidates"]}
    expanded = [item for item in state["motif_variant_pairs"] if item["recall_tier"] == "EXPANDED"]
    reviewed_count = 0
    while True:
        components = _same_components(list(candidate_by_id), reviews)
        selected = []
        for pair in expanded:
            key = tuple(sorted(pair["member_motif_ids"]))
            if key in reviewed:
                continue
            left, right = pair["member_motif_ids"]
            left_component, right_component = components[left], components[right]
            internal = left_component == right_component
            bridge = (
                len(left_component) > 1 or len(right_component) > 1
                or (
                    candidate_by_id[left]["story_support"] >= 2
                    and candidate_by_id[right]["story_support"] >= 2
                )
            )
            if internal or bridge:
                selected.append(pair)
        if not selected:
            break
        additions = _review_selected({**state, "motif_pair_reviews": reviews}, selected)
        reviews = additions
        reviewed.update(tuple(sorted(item["member_motif_ids"])) for item in selected)
        reviewed_count += len(selected)
    return {
        "motif_pair_reviews": reviews,
        "messages": [{
            "role": "system",
            "content": f"[Pattern.review_internal_bridges] expanded_reviewed={reviewed_count}",
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
        anchor = sorted(candidates, key=lambda item: (
            -item["story_support"], -item["length"], item["motif_id"],
        ))[0]
        cluster["anchor_motif_id"] = anchor["motif_id"]
        cluster["structure_signature"] = _digest(_json(sorted(
            (item["motif_id"], item["function_ids"]) for item in candidates
        )))
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
    pattern_records = []
    new_pattern_ids = []
    summary_count = 0
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
        if same_structure:
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

        evidence_changed = not parent or sorted(parent["pattern"].get("story_ids") or []) != cluster["story_ids"]
        if parent and same_structure and not evidence_changed:
            version_id = parent["pattern_version_id"]
            version = None
        else:
            action = (
                "CREATE" if not parent else
                "EVIDENCE_EXTENDED" if same_structure else "STRUCTURE_EXTENDED"
            )
            version_id = "PV_" + _digest(
                pattern_id, state["snapshot_id"], action,
                cluster["structure_signature"], _json(cluster["story_ids"]),
            )[:16]
            version = {
                "pattern_version_id": version_id,
                "pattern_id": pattern_id,
                "snapshot_id": state["snapshot_id"],
                "parent_version_id": parent["pattern_version_id"] if parent else None,
                "action": action,
                "structure_signature": cluster["structure_signature"],
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
    graph.add_node("review_internal_bridges", review_internal_bridges)
    graph.add_node("rebuild_clusters", rebuild_clusters)
    graph.add_node("summarize_changed_clusters", summarize_changed_clusters)
    graph.add_node("publish_pattern_set", publish_pattern_set)
    graph.add_edge(START, "load_pattern_delta")
    graph.add_edge("load_pattern_delta", "update_story_sequences")
    graph.add_edge("update_story_sequences", "update_motif_evidence")
    graph.add_edge("update_motif_evidence", "retrieve_variant_pairs")
    graph.add_edge("retrieve_variant_pairs", "review_changed_pairs")
    graph.add_edge("review_changed_pairs", "review_internal_bridges")
    graph.add_edge("review_internal_bridges", "rebuild_clusters")
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
    store.begin_pattern_run(snapshot_id, input_signature)
    try:
        result = _build_graph().compile().invoke({
            "messages": [],
            "knowledge_db": str(knowledge_db),
            "snapshot_id": snapshot_id,
        })
        return result["pattern_result"]
    except Exception as exc:
        store.fail_pattern_run(snapshot_id, str(exc))
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="StoryPattern_Agent")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--knowledge-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_pattern_evolve(args.snapshot, args.knowledge_db, args.rebuild)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[StoryPattern] error: {exc}")
        return 1
