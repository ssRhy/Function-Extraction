"""一次性 driver：用指定 Snapshot 跑 StoryPattern 全流程（纯库串联）。

用法（Code/ 下）:
    python -X utf8 test/run_story_pattern.py \
        --snapshot <snapshot_id> --out-dir data/story_pattern_<tag>
"""

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "test"))

import Agent  # 兼容入口：把 FunctionExtract_Agent 加入 sys.path（Embedding 等顶层模块依赖）
from KnowledgeBase import StoryKnowledgeStore
from story_pattern_loader import inputs, sequences, stories, clusters, summaries, catalog

# 需要 Embedder / LLM 的模块延迟导入（variants 加载 Embedder，review 依赖 Agent.llm）
variants = None
review = None
review_queue = None


def _write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_jsonl(path: str, items: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--knowledge-db", default=None)
    parser.add_argument("--phase", default="full", help="sequences|motifs|variants|clusters|full")
    parser.add_argument("--replay-high", default=None,
                        help="复用已有 HIGH review JSONL（按 variant_pair_id 回放，跳过 LLM 非确定性）")
    parser.add_argument("--replay-summaries", default=None,
                        help="复用已有 pattern_summaries JSON（按 cluster_id 回放，跳过 summary LLM）")
    args = parser.parse_args()

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    knowledge = StoryKnowledgeStore(args.knowledge_db) if args.knowledge_db else StoryKnowledgeStore()

    t0 = time.time()
    state = {
        "knowledge_db": str(knowledge.db_path),
        "snapshot_id": args.snapshot,
        "out_dir": out_dir,
    }
    state.update(inputs.load_inputs(state))
    state.update(sequences.load_occurrences_node(state))
    print(f"[inputs] Snapshot={state['snapshot_manifest']['snapshot_id']} "
          f"Function={len(state['functions'])} 故事={len(state['story_ids'])} "
          f"occurrence={len(state['all_occurrences'])}")

    while stories.has_next_story(state):
        state.update(stories.select_story(state))
        state.update(sequences.build_story_sequences(state))
        state.update(sequences.annotate_repetitions(state))
        state["current_story_index"] += 1
    raw = sum(len(seq) for seq in state["story_sequences"].values())
    runs = sum(len(seq) for seq in state["structural_sequences"].values())
    print(f"[sequences] raw={raw} structural_runs={runs} 耗时={time.time() - t0:.1f}s")
    _write_jsonl(os.path.join(out_dir, "story_sequences.jsonl"), [
        {"story_id": sid, "sequence": seq} for sid, seq in state["story_sequences"].items()
    ])
    _write_jsonl(os.path.join(out_dir, "structural_sequences.jsonl"), [
        {"story_id": sid, "sequence": seq} for sid, seq in state["structural_sequences"].items()
    ])
    if args.phase == "sequences":
        print("phase=sequences 完成")
        return

    state.update(sequences.index_function_contexts(state))
    state.update(sequences.extract_motif_candidates(state))
    candidates = state["motif_candidates"]
    from collections import Counter
    tier = Counter(c.get("tier") for c in candidates)
    length = Counter(c.get("length") for c in candidates)
    print(f"[motifs] candidates={len(candidates)} tier={dict(tier)} length={dict(sorted(length.items()))}")
    _write_jsonl(os.path.join(out_dir, "motif_candidates.jsonl"), candidates)
    if args.phase == "motifs":
        print("phase=motifs 完成")
        return

    global variants, review, review_queue
    from story_pattern_loader import variants
    state.update(variants.retrieve_motif_variants(state))
    pairs = state["motif_variant_pairs"]
    tier = Counter(p.get("recall_tier") for p in pairs)
    print(f"[variants] pairs={len(pairs)} tier={dict(tier)}")
    _write_jsonl(os.path.join(out_dir, "motif_variant_pairs.jsonl"), pairs)
    if args.phase == "variants":
        print("phase=variants 完成")
        return

    # HIGH 全量 LLM 审查（逐对推进）
    from story_pattern_loader import review
    high_pairs = [p for p in pairs if p.get("recall_tier") == "HIGH"]
    state["motif_review_queue"] = high_pairs
    state["current_motif_pair_index"] = 0
    state["motif_pair_reviews"] = []
    review_path = os.path.join(out_dir, "high_pair_reviews.jsonl")
    replay_by_id = {}
    if args.replay_high and os.path.exists(args.replay_high):
        with open(args.replay_high, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                pair_id = str(item.get("variant_pair_id") or "").strip()
                if pair_id and pair_id not in replay_by_id:
                    replay_by_id[pair_id] = item
        print(f"[review] 回放冻结 HIGH review {len(replay_by_id)} 条（跳过 LLM）", flush=True)
    review_t0 = time.time()
    while review.has_next_motif_pair(state):
        idx = state["current_motif_pair_index"]
        pair = high_pairs[idx]
        pair_id = str(pair.get("variant_pair_id") or "").strip()
        replayed = replay_by_id.get(pair_id)
        if replayed is not None and replayed.get("snapshot_id") == state["snapshot_manifest"]["snapshot_id"]:
            state["motif_pair_reviews"] = list(state["motif_pair_reviews"]) + [replayed]
            state["current_motif_pair_index"] = idx + 1
            if (idx + 1) % 20 == 0 or not review.has_next_motif_pair(state):
                _write_jsonl(review_path, state["motif_pair_reviews"])
                print(f"[review] {idx + 1}/{len(high_pairs)}（回放）耗时={time.time() - review_t0:.1f}s", flush=True)
            continue
        state.update(review.review_motif_pairs(state))
        if (idx + 1) % 20 == 0 or not review.has_next_motif_pair(state):
            _write_jsonl(review_path, state["motif_pair_reviews"])
            print(f"[review] {idx + 1}/{len(high_pairs)} 耗时={time.time() - review_t0:.1f}s", flush=True)
    reviews = state["motif_pair_reviews"]
    verdict = Counter(r.get("verdict") for r in reviews)
    print(f"[review] HIGH 全量 {len(reviews)} 条 verdict={dict(verdict)}")
    _write_jsonl(review_path, reviews)

    state.update(clusters.build_motif_clusters(state))
    clusters_state = state["motif_clusters"]
    clean = sum(1 for c in clusters_state if not c.get("needs_review") and not c.get("review_incomplete"))
    need = sum(1 for c in clusters_state if c.get("needs_review"))
    incomplete = sum(1 for c in clusters_state if c.get("review_incomplete"))
    print(f"[clusters] total={len(clusters_state)} clean={clean} needs_review={need} review_incomplete={incomplete}")
    _write_jsonl(os.path.join(out_dir, "motif_clusters.jsonl"), clusters_state)
    if args.phase == "clusters":
        print("phase=clusters 完成")
        return

    replay_summaries = {}
    if args.replay_summaries and os.path.exists(args.replay_summaries):
        with open(args.replay_summaries, encoding="utf-8") as f:
            for item in json.load(f):
                cluster_id = str(item.get("cluster_id") or "").strip()
                if cluster_id and cluster_id not in replay_summaries:
                    replay_summaries[cluster_id] = item
        print(f"[summaries] 回放冻结 summary {len(replay_summaries)} 条（跳过 LLM）", flush=True)
    if replay_summaries:
        used = []
        skipped = list(state.get("skipped_clusters", []))
        for cluster in state["motif_clusters"]:
            cluster_id = str(cluster.get("cluster_id") or "").strip()
            cached = replay_summaries.get(cluster_id)
            if cached is not None and cached.get("snapshot_id") == state["snapshot_manifest"]["snapshot_id"]:
                used.append(cached)
                continue
            if cluster.get("needs_review") or cluster.get("review_incomplete", False):
                skipped.append(cluster_id)
        state["pattern_summaries"] = used
        state["skipped_clusters"] = skipped
    else:
        state.update(summaries.summarize_story_patterns(state))
    print(f"[summaries] generated={len(state['pattern_summaries'])} skipped={len(state['skipped_clusters'])}")
    _write_json(os.path.join(out_dir, "pattern_summaries.json"), state["pattern_summaries"])

    state.update(catalog.publish_pattern_catalog(state))
    catalog_state = state.get("pattern_catalog") or {}
    print(f"[catalog] published={len(catalog_state.get('published_patterns', []))} "
          f"rejected={len(catalog_state.get('rejected_patterns', []))} "
          f"manual_review={len(catalog_state.get('manual_review_patterns', []))}")
    _write_json(os.path.join(out_dir, "pattern_catalog.json"), catalog_state)

    knowledge.record_pattern_catalog(os.path.join(out_dir, "pattern_catalog.json"))
    print(f"[knowledge] {knowledge.db_path}")

    report = {
        "snapshot_id": state["snapshot_manifest"]["snapshot_id"],
        "functions": len(state["functions"]),
        "stories": len(state["story_ids"]),
        "occurrences": len(state["all_occurrences"]),
        "raw_sequence_nodes": raw,
        "structural_runs": runs,
        "motif_candidates": len(candidates),
        "variant_pairs": len(pairs),
        "high_reviewed": len(reviews),
        "clusters": len(clusters_state),
        "summaries": len(state["pattern_summaries"]),
        "catalog_published": len(catalog_state.get("published_patterns", [])),
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    _write_json(os.path.join(out_dir, "run_report.json"), report)
    print(f"[done] 总耗时 {report['elapsed_seconds']}s → {out_dir}")


if __name__ == "__main__":
    main()
