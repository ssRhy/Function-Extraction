"""Function Coordinator 的确定性路由测试。"""

from FunctionCoordinator_Agent import app


def _kwargs():
    return {
        "mode": "bootstrap",
        "corpus": "/tmp/corpus",
        "namespace": "test",
        "knowledge_db": "/tmp/knowledge.db",
        "out_dir": "/tmp/out",
        "snapshot_root": "/tmp/snapshots",
        "max_retries": 1,
    }


def test_success_routes_function_to_pattern_and_finishes(monkeypatch):
    calls = []

    def fake_run(command, stage, attempt):
        calls.append((stage, attempt))
        if stage == "BOOTSTRAP":
            return {"status": "PASS", "snapshot_id": "snapshot_x"}
        return {"status": "SUCCESS", "run_id": "PR_x"}

    monkeypatch.setattr(app, "_run_stage", fake_run)
    result = app.run_coordinator(**_kwargs())

    assert result["status"] == "SUCCESS"
    assert result["snapshot_id"] == "snapshot_x"
    assert calls == [("BOOTSTRAP", 1), ("PATTERN", 1)]


def test_function_failure_stops_before_pattern(monkeypatch):
    calls = []

    def fake_run(command, stage, attempt):
        calls.append(stage)
        return {"status": "FAIL", "snapshot_id": None}

    monkeypatch.setattr(app, "_run_stage", fake_run)
    result = app.run_coordinator(**_kwargs())

    assert result["status"] == "FAILED"
    assert calls == ["BOOTSTRAP"]


def test_transient_function_failure_retries_once(monkeypatch):
    calls = []

    def fake_run(command, stage, attempt):
        calls.append((stage, attempt))
        if stage == "BOOTSTRAP" and attempt == 1:
            return {"status": "FAILED", "retryable": True}
        if stage == "BOOTSTRAP":
            return {"status": "PASS", "snapshot_id": "snapshot_x"}
        return {"status": "SUCCESS"}

    monkeypatch.setattr(app, "_run_stage", fake_run)
    result = app.run_coordinator(**_kwargs())

    assert result["status"] == "SUCCESS"
    assert calls == [("BOOTSTRAP", 1), ("BOOTSTRAP", 2), ("PATTERN", 1)]


def test_pattern_failure_does_not_hide_function_snapshot(monkeypatch):
    def fake_run(command, stage, attempt):
        if stage == "BOOTSTRAP":
            return {"status": "PASS", "snapshot_id": "snapshot_x"}
        return {"status": "FAILED", "error_code": "PATTERN_FAILED"}

    monkeypatch.setattr(app, "_run_stage", fake_run)
    result = app.run_coordinator(**_kwargs())

    assert result["status"] == "FAILED"
    assert result["snapshot_id"] == "snapshot_x"
    assert result["pattern_result"]["error_code"] == "PATTERN_FAILED"


def test_parse_run_result_ignores_non_json_output():
    output = "progress\n{\"run_result\": {\"status\": \"SUCCESS\"}}\n"
    assert app._parse_run_result(output) == {"status": "SUCCESS"}
