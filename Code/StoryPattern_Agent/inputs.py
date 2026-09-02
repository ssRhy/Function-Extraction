"""Story Pattern Agent 输入加载节点。"""

import re

from KnowledgeBase import StoryKnowledgeStore
from .state import StoryPatternState


_REQUIRED_OBSERVATION_FIELDS = (
    "obs_id",
    "story_id",
    "event",
    "before_state",
    "after_state",
)


def _function_indices(functions: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    by_name, by_id = {}, {}
    for func in functions:
        name = str(func.get("function_name") or "").strip()
        function_id = str(func.get("function_id") or "").strip()
        if not name or not function_id:
            raise ValueError("Function 缺少 function_name 或 function_id")
        if name in by_name:
            raise ValueError(f"重复 function_name: {name}")
        if function_id in by_id:
            raise ValueError(f"重复 function_id: {function_id}")
        by_name[name] = func
        by_id[function_id] = func
    return by_name, by_id


def _metadata_index(items: object) -> tuple[list[str], dict[str, dict]]:
    if not isinstance(items, list) or not items:
        raise ValueError("知识库 Story 元数据必须是非空数组")
    order, metadata = [], {}
    for index, entry in enumerate(items):
        story_id = str(entry.get("story_id") or "").strip() if isinstance(entry, dict) else ""
        if not story_id:
            raise ValueError(f"Story metadata[{index}] 缺少 story_id")
        if story_id in metadata:
            raise ValueError(f"Story metadata 中重复 story_id: {story_id}")
        item = dict(entry)
        order.append(story_id)
        metadata[story_id] = item
    return order, metadata


def _group_observations(
    observations: list[dict],
    story_metadata: dict[str, dict],
) -> dict[str, list[dict]]:
    seen, grouped = set(), {}
    for index, obs in enumerate(observations):
        missing = [
            field for field in _REQUIRED_OBSERVATION_FIELDS
            if not str(obs.get(field) or "").strip()
        ]
        if missing:
            raise ValueError(f"Observation[{index}] 缺少必要字段: {', '.join(missing)}")
        obs_id = obs["obs_id"]
        story_id = obs["story_id"]
        if obs_id in seen:
            raise ValueError(f"重复 obs_id: {obs_id}")
        if story_id not in story_metadata:
            raise ValueError(f"Observation 的 story_id 不在 manifest 中: {story_id}")
        match = re.fullmatch(rf"{re.escape(story_id)}_obs_[0-9a-f]{{12}}", obs_id)
        if not match:
            raise ValueError(f"非法 obs_id: {obs_id}")
        seen.add(obs_id)
        order = obs.get("observation_order")
        if not isinstance(order, int) or order < 1:
            order = index + 1
        grouped.setdefault(story_id, []).append((order, obs_id, obs))

    result = {}
    for story_id, items in grouped.items():
        items.sort(key=lambda item: (item[0], item[1]))
        result[story_id] = [obs for _order, _obs_id, obs in items]
    return result


def load_inputs(state: StoryPatternState) -> dict:
    """从统一知识库读取冻结本体、Observation 与 Story 元数据。"""
    store = StoryKnowledgeStore(state["knowledge_db"])
    source = store.load_story_pattern_inputs(state["snapshot_id"])
    manifest = source["manifest"]
    functions = source["functions"]
    contracts = source["contracts"]
    manifest_order, all_metadata = _metadata_index(source["story_metadata"])
    observations_by_story = _group_observations(
        source["observations"],
        all_metadata,
    )
    observations_by_story = {
        story_id: observations_by_story.get(story_id, [])
        for story_id in manifest_order
    }
    function_by_name, function_by_id = _function_indices(functions)
    function_contract_by_id = {item["function_id"]: item for item in contracts}
    story_ids = manifest_order
    story_metadata = {story_id: all_metadata[story_id] for story_id in story_ids}

    return {
        "snapshot_manifest": manifest,
        "functions": functions,
        "function_by_name": function_by_name,
        "function_by_id": function_by_id,
        "function_contracts": contracts,
        "function_contract_by_id": function_contract_by_id,
        "story_metadata": story_metadata,
        "observations_by_story": observations_by_story,
        "preloaded_occurrences": source["occurrences"],
        "story_ids": story_ids,
        "current_story_index": 0,
        "current_story_id": None,
        "current_metadata": None,
        "current_observations": [],
        "current_occurrences": [],
        "all_occurrences": [],
        "occurrences_by_story": {},
        "story_sequences": {},
        "current_sequence": [],
        "structural_sequences": {},
        "current_structural_sequence": [],
        "function_contexts": {},
        "motif_candidates": [],
        "motif_variant_pairs": [],
        "motif_review_queue": [],
        "current_motif_pair_index": 0,
        "motif_pair_reviews": [],
        "motif_clusters": [],
        "pattern_summaries": [],
        "skipped_clusters": [],
        "story_traces": [],
        "errors": [],
        "messages": [{
            "role": "system",
            "content": (
                f"[StoryPattern.load_inputs] Snapshot={manifest['snapshot_id']}，"
                f"Function={len(functions)}，Contract={len(contracts)}，故事={len(story_ids)}，"
                f"Observation={sum(len(items) for items in observations_by_story.values())}"
            ),
        }],
    }
