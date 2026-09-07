"""Function Coordinator 的确定性路由测试。"""

import json
import sys

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

    def fake_run(command, stage, attempt, timeout):
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

    def fake_run(command, stage, attempt, timeout):
        calls.append(stage)
        return {"status": "FAILED", "snapshot_id": None}

    monkeypatch.setattr(app, "_run_stage", fake_run)
    result = app.run_coordinator(**_kwargs())

    assert result["status"] == "FAILED"
    assert calls == ["BOOTSTRAP"]


def test_transient_function_failure_retries_once(monkeypatch):
    calls = []

    def fake_run(command, stage, attempt, timeout):
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
    def fake_run(command, stage, attempt, timeout):
        if stage == "BOOTSTRAP":
            return {"status": "PASS", "snapshot_id": "snapshot_x"}
        return {"status": "FAILED", "error_code": "PATTERN_FAILED"}

    monkeypatch.setattr(app, "_run_stage", fake_run)
    result = app.run_coordinator(**_kwargs())

    assert result["status"] == "FAILED"
    assert result["snapshot_id"] == "snapshot_x"
    assert result["pattern_result"]["error_code"] == "PATTERN_FAILED"


def test_transient_pattern_connection_failure_retries_pattern_only(monkeypatch):
    function_command = _real_child({"status": "PASS", "snapshot_id": "snapshot_x"})
    pattern_commands = iter([
        _real_child({"status": "FAILED", "error": "Connection error"}, 1),
        _real_child({"status": "SUCCESS", "run_id": "pattern_x"}),
    ])
    calls = []
    real_run_stage = app._run_stage

    monkeypatch.setattr(app, "_function_command", lambda _state: function_command)
    monkeypatch.setattr(app, "_pattern_command", lambda _state: next(pattern_commands))
    monkeypatch.setattr(
        app,
        "_run_stage",
        lambda command, stage, attempt, timeout: (
            calls.append((stage, attempt)) or real_run_stage(command, stage, attempt, timeout)
        ),
    )

    result = app.run_coordinator(**_kwargs())

    assert result["status"] == "SUCCESS"
    assert calls == [("BOOTSTRAP", 1), ("PATTERN", 1), ("PATTERN", 2)]
    assert result["attempts"] == {"function": 1, "pattern": 2}


def test_parse_run_result_ignores_non_json_output():
    output = "progress\n{\"run_result\": {\"status\": \"SUCCESS\"}}\n"
    assert app._parse_run_result(output) == {"status": "SUCCESS"}


def _real_child(result, returncode=0):
    payload = json.dumps({"run_result": result}, ensure_ascii=False)
    code = f"print('child progress'); print({payload!r}); raise SystemExit({returncode})"
    return [sys.executable, "-c", code]


def test_real_subprocesses_route_successful_function_to_pattern(monkeypatch):
    commands = {
        "function": _real_child({"status": "PASS", "snapshot_id": "snapshot_real"}),
        "pattern": _real_child({"status": "SUCCESS", "run_id": "pattern_real"}),
    }
    monkeypatch.setattr(app, "_function_command", lambda _state: commands["function"])
    monkeypatch.setattr(app, "_pattern_command", lambda _state: commands["pattern"])

    result = app.run_coordinator(**_kwargs())

    assert result["status"] == "SUCCESS"
    assert result["snapshot_id"] == "snapshot_real"
    assert result["function_result"]["process_returncode"] == 0
    assert result["pattern_result"]["run_id"] == "pattern_real"


def test_real_subprocess_nonzero_exit_overrides_reported_success(monkeypatch):
    monkeypatch.setattr(
        app, "_function_command",
        lambda _state: _real_child({"status": "PASS", "snapshot_id": "snapshot_real"}, 7),
    )

    result = app.run_coordinator(**_kwargs())

    assert result["status"] == "FAILED"
    assert result["function_result"]["status"] == "FAILED"
    assert result["function_result"]["process_returncode"] == 7
    assert result["pattern_result"] is None


def test_real_subprocess_timeout_is_retryable_and_stops(monkeypatch):
    monkeypatch.setattr(
        app, "_function_command",
        lambda _state: [sys.executable, "-c", "import time; time.sleep(10)"],
    )

    options = _kwargs()
    options.update(stage_timeout=0.05, max_retries=0)
    result = app.run_coordinator(**options)

    assert result["status"] == "FAILED"
    assert result["function_result"]["error_code"] == "STAGE_TIMEOUT"
    assert result["function_result"]["retryable"] is True
    assert result["pattern_result"] is None


def test_permanent_error_code_overrides_retryable_flag():
    state = {
        "function_result": {
            "status": "FAILED", "error_code": "EVALUATION_FAILED", "retryable": True,
        },
        "function_attempt": 1,
        "max_retries": 1,
    }

    assert app.route_after_function(state) == "stop"


def test_evolve_inherits_parent_snapshot_namespace(monkeypatch):
    captured = {}

    class FakeStore:
        def __init__(self, _path):
            pass

        def initialize(self):
            pass

        def load_snapshot_manifest(self, _snapshot_id):
            return {"namespace": "parent_namespace"}

    class FakeGraph:
        def invoke(self, state):
            captured.update(state)
            return {"final_result": {"status": "FAILED"}}

    monkeypatch.setattr(app, "StoryKnowledgeStore", FakeStore)
    monkeypatch.setattr(app, "_build_graph", lambda: FakeGraph())
    options = _kwargs()
    options.update(mode="evolve", namespace="wrong_namespace", base_snapshot_id="parent")

    app.run_coordinator(**options)

    assert captured["namespace"] == "parent_namespace"
