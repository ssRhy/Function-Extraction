"""Story Pattern Agent 独立 LangGraph State。"""

from typing import Annotated, TypedDict

from langgraph.graph import add_messages


class StoryPatternState(TypedDict, total=False):
    messages: Annotated[list, add_messages]

    knowledge_db: str
    snapshot_id: str
    out_dir: str
    snapshot_manifest: dict | None
    functions: list[dict]
    function_by_name: dict[str, dict]
    function_by_id: dict[str, dict]
    function_contracts: list[dict]
    function_contract_by_id: dict[str, dict]

    story_metadata: dict[str, dict]
    observations_by_story: dict[str, list[dict]]
    story_ids: list[str]

    current_story_index: int
    current_story_id: str | None
    current_metadata: dict | None
    current_observations: list[dict]
    current_occurrences: list[dict]
    all_occurrences: list[dict]
    preloaded_occurrences: list[dict]
    occurrences_by_story: dict[str, list[dict]]
    story_sequences: dict[str, list[dict]]
    current_sequence: list[dict]
    structural_sequences: dict[str, list[dict]]
    current_structural_sequence: list[dict]
    function_contexts: dict[str, list[dict]]
    motif_candidates: list[dict]
    motif_variant_pairs: list[dict]
    motif_review_queue: list[dict]
    current_motif_pair_index: int
    motif_pair_reviews: list[dict]
    motif_clusters: list[dict]
    pattern_summaries: list[dict]
    skipped_clusters: list[str]
    story_traces: list[dict]
    errors: list[str]

    parent_snapshot_id: str | None
    namespace: str
    workflow: str
    pattern_run_id: str
    already_complete: bool
    parent_sequences: dict[str, dict]
    occurrence_signatures: dict[str, str]
    sequence_records: dict[str, dict]
    new_story_ids: list[str]
    changed_story_ids: list[str]
    unchanged_story_ids: list[str]
    removed_story_ids: list[str]
    parent_clusters: list[dict]
    parent_patterns: list[dict]
    changed_cluster_ids: list[str]
    retired_pattern_ids: list[str]
    pattern_records: list[dict]
    new_pattern_ids: list[str]
    pattern_result: dict
