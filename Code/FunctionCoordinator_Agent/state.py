from typing import Literal, TypedDict


class FunctionCoordinatorState(TypedDict, total=False):
    mode: Literal["bootstrap", "evolve"]
    corpus: str
    stories: str | None
    limit: int | None
    namespace: str
    base_snapshot_id: str | None
    knowledge_db: str
    registry_db: str | None
    out_dir: str
    snapshot_root: str
    no_revise: bool
    batch_size: int | None
    top_k: int | None
    rebuild_pattern: bool
    max_retries: int
    stage_timeout: float
    function_attempt: int
    pattern_attempt: int
    function_result: dict
    pattern_result: dict
    final_result: dict
