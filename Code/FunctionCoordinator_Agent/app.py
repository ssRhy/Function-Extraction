"""Function 流程调度：Bootstrap/Evolve → Pattern。"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

from langgraph.graph import END, START, StateGraph

from .state import FunctionCoordinatorState


_CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def _run_stage(command: list[str], stage: str, attempt: int) -> dict:
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
    for line in process.stdout:
        print(f"[{stage}] {line}", end="")
        lines.append(line)
    return_code = process.wait()
    output = "".join(lines)
    try:
        result = _parse_run_result(output)
    except ValueError as exc:
        result = {
            "status": "FAILED",
            "error_code": "MISSING_RUN_RESULT",
            "error": str(exc),
            "retryable": return_code != 0 and _is_transient_failure(output),
        }
    result["process_returncode"] = return_code
    if return_code != 0 and result.get("status") not in {"FAIL", "FAILED"}:
        result["status"] = "FAILED"
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
        ),
    }


def route_after_function(state: FunctionCoordinatorState) -> str:
    result = state["function_result"]
    if _function_succeeded(result):
        return "pattern"
    if result.get("retryable") and state["function_attempt"] <= state.get("max_retries", 0):
        return "retry_function"
    return "stop"


def run_pattern_node(state: FunctionCoordinatorState) -> dict:
    attempt = state.get("pattern_attempt", 0) + 1
    return {
        "pattern_attempt": attempt,
        "pattern_result": _run_stage(
            _pattern_command(state), "PATTERN", attempt,
        ),
    }


def route_after_pattern(state: FunctionCoordinatorState) -> str:
    result = state["pattern_result"]
    if _pattern_succeeded(result):
        return "done"
    if result.get("retryable") and state["pattern_attempt"] <= state.get("max_retries", 0):
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
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"run_result": {
            "status": "FAILED",
            "error_code": "COORDINATOR_ERROR",
            "error": str(exc),
        }}, ensure_ascii=False))
        return 1
    print(json.dumps({"run_result": result}, ensure_ascii=False))
    return 0 if result["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
