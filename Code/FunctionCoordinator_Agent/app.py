"""Function 流程调度：Bootstrap/Evolve → Pattern。"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

from langgraph.graph import END, START, StateGraph

from Contracts.run_result import failed_run_result
from .state import FunctionCoordinatorState


_CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_STAGE_TIMEOUT = 1800.0
_PERMANENT_ERROR_CODES = {
    "CORPUS_NOT_FOUND", "NO_STORIES", "BASE_SNAPSHOT_LOAD_FAILED",
    "CHECKPOINT_NOT_FOUND", "RUN_NOT_RESUMABLE", "NO_FUNCTION_SURVIVED",
    "EVALUATION_FAILED", "PATTERN_START_FAILED",
}


def _command_env() -> dict[str, str]:
    env = os.environ.copy()
    paths = [_CODE_ROOT]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _function_command(state: FunctionCoordinatorState) -> list[str]:
    module = "FunctionExtract_Agent" if state["mode"] == "bootstrap" else "FunctionExtract_Agent.evolve"
    command = [
        sys.executable, "-m", module,
        "--corpus", state["corpus"],
        "--namespace", state["namespace"],
        "--out-dir", state["out_dir"],
        "--knowledge-db", state["knowledge_db"],
        "--snapshot-root", state["snapshot_root"],
    ]
    if state.get("stories"):
        command.extend(["--stories", state["stories"]])
    elif state.get("limit") is not None:
        command.extend(["--limit", str(state["limit"])])
    if state["mode"] == "evolve" and state.get("base_snapshot_id"):
        command.extend(["--base-snapshot", state["base_snapshot_id"]])
    if state["mode"] == "bootstrap" and state.get("no_revise"):
        command.append("--no-revise")
    if state["mode"] == "evolve":
        if state.get("batch_size") is not None:
            command.extend(["--batch-size", str(state["batch_size"])])
        if state.get("top_k") is not None:
            command.extend(["--top-k", str(state["top_k"])])
    return command


def _pattern_command(state: FunctionCoordinatorState) -> list[str]:
    command = [
        sys.executable, "-m", "StoryPattern_Agent",
        "--snapshot", state["function_result"]["snapshot_id"],
        "--knowledge-db", state["knowledge_db"],
    ]
    if state.get("rebuild_pattern"):
        command.append("--rebuild")
    return command


def _parse_run_result(output: str) -> dict:
    for line in reversed(output.splitlines()):
        line = line.strip()
        if '"run_result"' not in line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = payload.get("run_result")
        if isinstance(result, dict):
            return result
    raise ValueError("子 Agent 未返回结构化 run_result")


def _is_transient_failure(output: str) -> bool:
    text = output.lower()
    return any(item in text for item in (
        "timeout", "timed out", "rate limit", "429", "connection reset",
        "temporarily unavailable", "超时", "连接被重置", "限流",
    ))


def _should_retry(result: dict) -> bool:
    if result.get("error_code") in _PERMANENT_ERROR_CODES:
        return False
    if result.get("error_code") == "STAGE_TIMEOUT":
        return True
    return bool(result.get("retryable", False))


def _stage_failure(stage: str, error_code: str, error: str, *, retryable: bool,
                   process_returncode: int | None = None) -> dict:
    result = failed_run_result(
        stage=stage.lower(),
        workflow=stage.lower() if stage in {"BOOTSTRAP", "EVOLVE"} else None,
        run_id=None,
        namespace=None,
        snapshot_id=None,
        parent_snapshot_id=None,
        error_code=error_code,
        error=error,
        retryable=retryable,
    )
    if process_returncode is not None:
        result["process_returncode"] = process_returncode
    return result


def _read_stage_output(stream, stage: str, lines: list[str]) -> None:
    for line in stream:
        print(f"[{stage}] {line}", end="")
        lines.append(line)


def _run_stage(command: list[str], stage: str, attempt: int,
               timeout: float | None = DEFAULT_STAGE_TIMEOUT) -> dict:
    print(f"[Coordinator] {stage} attempt={attempt}: {' '.join(command)}")
    lines = []
    process = subprocess.Popen(
        command,
        cwd=_CODE_ROOT,
        env=_command_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    assert process.stdout is not None
    reader = threading.Thread(
        target=_read_stage_output, args=(process.stdout, stage, lines), daemon=True,
    )
    reader.start()
    started = time.monotonic()
    while process.poll() is None:
        remaining = None if timeout is None else timeout - (time.monotonic() - started)
        if remaining is not None and remaining <= 0:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            return_code = process.wait()
            reader.join()
            return _stage_failure(
                stage, "STAGE_TIMEOUT", f"{stage} 阶段超过 {timeout:g} 秒",
                retryable=True, process_returncode=return_code,
            )
        time.sleep(0.1 if remaining is None else min(remaining, 0.1))
    reader.join()
    return_code = process.wait()
    output = "".join(lines)
    try:
        result = _parse_run_result(output)
    except ValueError as exc:
        return _stage_failure(
            stage, "MISSING_RUN_RESULT", str(exc),
            retryable=return_code != 0 and _is_transient_failure(output),
            process_returncode=return_code,
        )
    result["process_returncode"] = return_code
    if return_code != 0:
        result["status"] = "FAILED"
        result.setdefault("error_code", "PROCESS_EXIT_NONZERO")
        result.setdefault("error", f"{stage} 子进程退出码为 {return_code}")
        result.setdefault("retryable", _is_transient_failure(output))
    return result


def _function_succeeded(result: dict) -> bool:
    return result.get("status") == "PASS" and bool(result.get("snapshot_id"))


def _pattern_succeeded(result: dict) -> bool:
    return result.get("status") == "SUCCESS"


def run_function_node(state: FunctionCoordinatorState) -> dict:
    attempt = state.get("function_attempt", 0) + 1
    return {
        "function_attempt": attempt,
        "function_result": _run_stage(
            _function_command(state), state["mode"].upper(), attempt,
            state.get("stage_timeout", DEFAULT_STAGE_TIMEOUT),
        ),
    }


def route_after_function(state: FunctionCoordinatorState) -> str:
    result = state["function_result"]
    if _function_succeeded(result):
        return "pattern"
    if _should_retry(result) and state["function_attempt"] <= state.get("max_retries", 0):
        return "retry_function"
    return "stop"


def run_pattern_node(state: FunctionCoordinatorState) -> dict:
    attempt = state.get("pattern_attempt", 0) + 1
    return {
        "pattern_attempt": attempt,
        "pattern_result": _run_stage(
            _pattern_command(state), "PATTERN", attempt,
            state.get("stage_timeout", DEFAULT_STAGE_TIMEOUT),
        ),
    }


def route_after_pattern(state: FunctionCoordinatorState) -> str:
    result = state["pattern_result"]
    if _pattern_succeeded(result):
        return "done"
    if _should_retry(result) and state["pattern_attempt"] <= state.get("max_retries", 0):
        return "retry_pattern"
    return "stop"


def finish_node(state: FunctionCoordinatorState) -> dict:
    function_result = state.get("function_result") or {}
    pattern_result = state.get("pattern_result")
    success = _function_succeeded(function_result) and bool(
        pattern_result and _pattern_succeeded(pattern_result)
    )
    final = {
        "status": "SUCCESS" if success else "FAILED",
        "mode": state["mode"],
        "snapshot_id": function_result.get("snapshot_id"),
        "function_result": function_result,
        "pattern_result": pattern_result,
        "attempts": {
            "function": state.get("function_attempt", 0),
            "pattern": state.get("pattern_attempt", 0),
        },
    }
    return {"final_result": final}


def _build_graph():
    graph = StateGraph(FunctionCoordinatorState)
    graph.add_node("run_function", run_function_node)
    graph.add_node("run_pattern", run_pattern_node)
    graph.add_node("finish", finish_node)
    graph.add_edge(START, "run_function")
    graph.add_conditional_edges(
        "run_function",
        route_after_function,
        {"pattern": "run_pattern", "retry_function": "run_function", "stop": "finish"},
    )
    graph.add_conditional_edges(
        "run_pattern",
        route_after_pattern,
        {"done": "finish", "retry_pattern": "run_pattern", "stop": "finish"},
    )
    graph.add_edge("finish", END)
    return graph.compile()


def run_coordinator(**kwargs) -> dict:
    state: FunctionCoordinatorState = {
        "mode": kwargs["mode"],
        "corpus": os.path.abspath(kwargs["corpus"]),
        "stories": kwargs.get("stories"),
        "limit": kwargs.get("limit"),
        "namespace": kwargs["namespace"],
        "base_snapshot_id": kwargs.get("base_snapshot_id"),
        "knowledge_db": os.path.abspath(kwargs["knowledge_db"]),
        "out_dir": os.path.abspath(kwargs["out_dir"]),
        "snapshot_root": os.path.abspath(kwargs["snapshot_root"]),
        "no_revise": kwargs.get("no_revise", False),
        "batch_size": kwargs.get("batch_size"),
        "top_k": kwargs.get("top_k"),
        "rebuild_pattern": kwargs.get("rebuild_pattern", False),
        "max_retries": kwargs.get("max_retries", 1),
        "stage_timeout": kwargs.get("stage_timeout", DEFAULT_STAGE_TIMEOUT),
        "function_attempt": 0,
        "pattern_attempt": 0,
    }
    if state["mode"] == "evolve" and not state.get("base_snapshot_id"):
        raise ValueError("Coordinator 的 evolve 模式需要显式 base_snapshot_id")
    return _build_graph().invoke(state)["final_result"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Function 调度：Bootstrap/Evolve → Pattern")
    parser.add_argument("--mode", choices=("bootstrap", "evolve"), required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--stories", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--base-snapshot", dest="base_snapshot_id", default=None)
    parser.add_argument("--knowledge-db", required=True)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--snapshot-root", required=True)
    parser.add_argument("--no-revise", action="store_true")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--rebuild-pattern", action="store_true")
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--stage-timeout", type=float, default=DEFAULT_STAGE_TIMEOUT,
                        help="每个子 Agent 阶段最长运行秒数（缺省 1800）")
    args = parser.parse_args(argv)
    out_dir = args.out_dir or os.path.join(
        _CODE_ROOT, "data", "coordinator", datetime.now().strftime("%Y%m%dT%H%M%S"),
    )
    try:
        result = run_coordinator(
            mode=args.mode,
            corpus=args.corpus,
            stories=args.stories,
            limit=args.limit,
            namespace=args.namespace,
            base_snapshot_id=args.base_snapshot_id,
            knowledge_db=args.knowledge_db,
            out_dir=out_dir,
            snapshot_root=args.snapshot_root,
            no_revise=args.no_revise,
            batch_size=args.batch_size,
            top_k=args.top_k,
            rebuild_pattern=args.rebuild_pattern,
            max_retries=args.max_retries,
            stage_timeout=args.stage_timeout,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        failure = failed_run_result(
            stage="coordinator", workflow=args.mode, run_id=None,
            namespace=args.namespace, snapshot_id=None,
            parent_snapshot_id=args.base_snapshot_id,
            error_code="COORDINATOR_ERROR", error=str(exc),
        )
        print(json.dumps({"run_result": failure}, ensure_ascii=False))
        return 1
    print(json.dumps({"run_result": result}, ensure_ascii=False))
    return 0 if result["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
