"""跨 Bootstrap、Evolve、Pattern 的运行结果契约。"""


def failed_run_result(
    *,
    stage: str,
    workflow: str | None,
    run_id: str | None,
    namespace: str | None,
    snapshot_id: str | None,
    parent_snapshot_id: str | None,
    error_code: str,
    error: str,
    retryable: bool = False,
    report: dict | None = None,
) -> dict:
    result = {
        "status": "FAILED",
        "stage": stage,
        "workflow": workflow,
        "run_id": run_id,
        "namespace": namespace,
        "snapshot_id": snapshot_id,
        "parent_snapshot_id": parent_snapshot_id,
        "error_code": error_code,
        "error": error or "unknown error",
        "retryable": retryable,
    }
    if report is not None:
        result["report"] = report
    return result
