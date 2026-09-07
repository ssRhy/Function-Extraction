"""副本上的 Evolve → Pattern → candidate smoke → promote 薄控制入口。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sqlite3
import sys
import time
from pathlib import Path

from Contracts.snapshot import DEFAULT_SNAPSHOT_ROOT, validate_snapshot
from Contracts.occurrence import assignment_metrics
from FunctionCoordinator_Agent.app import run_coordinator
from KnowledgeBase import DEFAULT_DB_PATH, StoryKnowledgeStore
from Outline_Agent import app as outline_app
from StoryCLI.app import _outline_state
from Story_Agent import app as story_app


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DEFAULT_REGISTRY_DB = DATA / "registry" / "functions.db"
MAX_UNTOUCHED_CHANGED_RATIO = 0.10
MIN_ASSIGNMENT_COVERAGE_RATIO = 0.90
MIN_PUBLISHED_PATTERN_RATIO = 0.50


class _CandidateRejected(RuntimeError):
    def __init__(self, reasons: list[dict]):
        self.reasons = reasons
        super().__init__("；".join(item["message"] for item in reasons))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_sqlite(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    with sqlite3.connect(source) as source_conn, sqlite3.connect(target) as target_conn:
        source_conn.backup(target_conn)


def _check_db(path: Path) -> dict:
    with sqlite3.connect(path) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check")]
    if integrity != "ok" or foreign_keys:
        raise ValueError(
            f"SQLite 检查失败: integrity={integrity}, foreign_key_check={foreign_keys}"
        )
    return {"integrity_check": integrity, "foreign_key_check": foreign_keys}


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _stage_inputs(stories: list[str], corpus_dir: Path, genre: str) -> list[str]:
    corpus_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    names = []
    for index, raw_path in enumerate(stories, 1):
        source = Path(raw_path).resolve()
        if not source.is_file() or source.suffix.lower() != ".txt":
            raise ValueError(f"故事必须是存在的 .txt 文件: {source}")
        name = source.name
        if name in names:
            name = f"{index:02d}_{name}"
        shutil.copy2(source, corpus_dir / name)
        names.append(name)
        entries.append({
            "txt_file": name,
            "story_id": source.stem,
            "category": genre,
            "question_title": source.stem,
        })
    _write_json(corpus_dir / "manifest.json", entries)
    return names


def _copy_parent_snapshot(
    source_root: Path, target_root: Path, snapshot_id: str,
) -> dict:
    source_path = source_root / snapshot_id
    source_manifest = validate_snapshot(str(source_path))
    if source_manifest.get("snapshot_id") != snapshot_id:
        raise ValueError(f"父 Snapshot ID 不一致: {source_path}")
    target_path = target_root / snapshot_id
    shutil.copytree(source_path, target_path)
    target_manifest = validate_snapshot(str(target_path))
    if target_manifest.get("snapshot_id") != snapshot_id:
        raise ValueError(f"副本父 Snapshot ID 不一致: {target_path}")
    return {
        "source_path": str(source_path),
        "target_path": str(target_path),
        "snapshot_id": snapshot_id,
    }


def _require(condition: bool, stage: str, message: str) -> None:
    if not condition:
        raise RuntimeError(f"{stage}: {message}")


def _function_body(function: dict) -> dict:
    return {
        key: function.get(key)
        for key in (
            "function_id", "function_name", "definition", "status",
            "hard_negatives", "realization_patterns", "confusable_functions",
        )
    }


def _snapshot_regression(
    store: StoryKnowledgeStore,
    parent_snapshot_id: str,
    candidate_snapshot_id: str,
    pattern_result: dict,
    input_story_ids: set[str],
) -> dict:
    parent_story_ids = set(store.load_pattern_sequences(parent_snapshot_id))
    story_delta = pattern_result.get("story_delta") or {}
    changed_story_ids = set(story_delta.get("changed") or [])
    old_changed_story_ids = sorted(
        (changed_story_ids & parent_story_ids) - input_story_ids
    )
    changed_limit = max(
        1, math.ceil(len(parent_story_ids) * MAX_UNTOUCHED_CHANGED_RATIO)
    )

    parent_metrics = assignment_metrics(store.load_occurrences(parent_snapshot_id))
    candidate_metrics = assignment_metrics(store.load_occurrences(candidate_snapshot_id))
    parent_published = sum(
        row["status"] == "published"
        for row in store.load_snapshot_pattern_rows(parent_snapshot_id)
    )
    candidate_published = sum(
        row["status"] == "published"
        for row in store.load_snapshot_pattern_rows(candidate_snapshot_id)
    )

    parent_functions = {
        item["function_id"]: _function_body(item)
        for item in store.load_functions(parent_snapshot_id)
    }
    candidate_functions = {
        item["function_id"]: _function_body(item)
        for item in store.load_functions(candidate_snapshot_id)
    }
    function_body_unchanged = parent_functions == candidate_functions
    reasons = []
    if function_body_unchanged and len(old_changed_story_ids) > changed_limit:
        reasons.append({
            "code": "OLD_STORY_SEQUENCE_REGRESSION",
            "message": (
                f"Function 本体未变，但未参与本批输入的旧故事 changed="
                f"{len(old_changed_story_ids)} > {changed_limit}"
            ),
        })
    parent_coverage = parent_metrics["assignment_coverage"]
    candidate_coverage = candidate_metrics["assignment_coverage"]
    coverage_threshold = parent_coverage * MIN_ASSIGNMENT_COVERAGE_RATIO
    if candidate_coverage < coverage_threshold:
        reasons.append({
            "code": "ASSIGNMENT_COVERAGE_REGRESSION",
            "message": (
                f"assignment coverage 从 {parent_coverage:.4f} 降到 "
                f"{candidate_coverage:.4f}，低于门槛 {coverage_threshold:.4f}"
            ),
        })
    published_threshold = math.ceil(parent_published * MIN_PUBLISHED_PATTERN_RATIO)
    if candidate_published < published_threshold:
        reasons.append({
            "code": "PUBLISHED_PATTERN_REGRESSION",
            "message": (
                f"Published Pattern 从 {parent_published} 降到 "
                f"{candidate_published}，低于门槛 {published_threshold}"
            ),
        })
    return {
        "passed": not reasons,
        "reasons": reasons,
        "function_body_unchanged": function_body_unchanged,
        "old_story_changes": {
            "changed": len(old_changed_story_ids),
            "limit": changed_limit,
            "story_ids": old_changed_story_ids,
            "parent_story_count": len(parent_story_ids),
            "input_story_ids": sorted(input_story_ids),
        },
        "assignment_coverage": {
            "parent": parent_coverage,
            "candidate": candidate_coverage,
            "minimum_ratio": MIN_ASSIGNMENT_COVERAGE_RATIO,
            "threshold": round(coverage_threshold, 4),
        },
        "published_patterns": {
            "parent": parent_published,
            "candidate": candidate_published,
            "minimum_ratio": MIN_PUBLISHED_PATTERN_RATIO,
            "threshold": published_threshold,
        },
    }


def _outline_result(
    snapshot_id: str,
    genre: str,
    request: str,
    pattern: str | None,
    knowledge_db: Path,
    out_dir: Path,
) -> dict:
    result = outline_app._build_graph().invoke(_outline_state(
        snapshot_id, genre, out_dir, pattern, request, knowledge_db,
    ))
    return result


def run_release(
    stories: list[str],
    genre: str,
    request: str,
    *,
    source_db=DEFAULT_DB_PATH,
    source_registry_db=DEFAULT_REGISTRY_DB,
    source_snapshot_root=DEFAULT_SNAPSHOT_ROOT,
    out_dir: str | Path | None = None,
    pattern: str | None = None,
    stage_timeout: float = 1800.0,
    force_promote: bool = False,
) -> dict:
    source_db = Path(source_db).resolve()
    source_registry_db = Path(source_registry_db).resolve()
    source_snapshot_root = Path(source_snapshot_root).resolve()
    if not source_db.is_file():
        raise ValueError(f"知识库不存在: {source_db}")
    genre = outline_app.normalize_genre(genre)
    request = request.strip()
    if not stories or not request:
        raise ValueError("release_pipeline 需要至少一个故事和非空创作要求")

    root = Path(out_dir).resolve() if out_dir else (
        DATA / "release_runs" / time.strftime("%Y%m%dT%H%M%S")
    )
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"输出目录非空: {root}")
    root.mkdir(parents=True, exist_ok=True)

    work_db = root / "knowledge.db"
    db_backup = root / "knowledge.before.db"
    work_registry = root / "registry.db"
    snapshot_root = root / "snapshots"
    corpus_dir = root / "corpus"
    evolve_dir = root / "evolve"
    outline_dir = root / "outline"
    story_dir = root / "story"
    report_path = root / "release_report.json"
    report = {
        "schema_version": 1,
        "status": "FAILED",
        "release_id": "RP_" + hashlib.sha256(str(root).encode()).hexdigest()[:16],
        "source_db": str(source_db),
        "work_db": str(work_db),
        "db_backup": str(db_backup),
        "source_snapshot_root": str(source_snapshot_root),
        "genre": genre,
        "request": request,
        "stories": [str(Path(item).resolve()) for item in stories],
        "force_promote": force_promote,
        "report_path": str(report_path),
        "checks": {},
    }
    previous_serving = None
    promoted = False

    try:
        report["stage"] = "backup"
        _check_db(source_db)
        source_hash = _sha256(source_db)
        _copy_sqlite(source_db, db_backup)
        _copy_sqlite(source_db, work_db)
        report["source_sha256_before"] = source_hash
        report["checks"]["source_db"] = _check_db(source_db)
        report["checks"]["db_backup"] = _check_db(db_backup)
        report["checks"]["work_db_before"] = _check_db(work_db)
        report["checks"]["backup"] = "PASS"
        if source_registry_db.is_file():
            _copy_sqlite(source_registry_db, work_registry)

        report["stage"] = "prepare"
        story_files = _stage_inputs(stories, corpus_dir, genre)
        store = StoryKnowledgeStore(work_db)
        previous_serving = store.serving_snapshot_id()
        report["serving_before"] = previous_serving
        parent_manifest = store.load_snapshot_manifest(previous_serving)
        namespace = parent_manifest["namespace"]
        report["parent_snapshot_id"] = previous_serving
        report["parent_snapshot"] = _copy_parent_snapshot(
            source_snapshot_root, snapshot_root, previous_serving,
        )
        report["checks"]["parent_snapshot"] = "PASS"

        report["stage"] = "evolve_pattern"
        coordinator = run_coordinator(
            mode="evolve",
            corpus=str(corpus_dir),
            stories=",".join(story_files),
            namespace=namespace,
            base_snapshot_id=previous_serving,
            knowledge_db=str(work_db),
            registry_db=str(work_registry),
            out_dir=str(evolve_dir),
            snapshot_root=str(snapshot_root),
            max_retries=1,
            stage_timeout=stage_timeout,
        )
        report["coordinator"] = coordinator
        _require(coordinator.get("status") == "SUCCESS", "evolve_pattern", "Coordinator 失败")
        function_result = coordinator.get("function_result") or {}
        pattern_result = coordinator.get("pattern_result") or {}
        candidate_id = function_result.get("snapshot_id") or coordinator.get("snapshot_id")
        report["function_run_id"] = function_result.get("run_id")
        report["pattern_run_id"] = pattern_result.get("run_id")
        report["candidate_snapshot_id"] = candidate_id
        _require(bool(candidate_id), "gate", "没有候选 Snapshot")

        report["stage"] = "gate"
        candidate_path = snapshot_root / candidate_id
        candidate_manifest = validate_snapshot(str(candidate_path))
        _require(
            candidate_manifest.get("parent_snapshot_id") == previous_serving,
            "gate", "候选 Snapshot 父节点不是旧 serving",
        )
        pattern_run = store.load_pattern_run(candidate_id)
        pattern_rows = store.load_snapshot_pattern_rows(candidate_id)
        published = [row for row in pattern_rows if row["status"] == "published"]
        _require(pattern_run and pattern_run["status"] == "SUCCESS", "gate", "Pattern Run 未成功")
        _require(bool(published), "gate", "候选 Snapshot 没有 Published Pattern")
        catalog = store.load_pattern_catalog(candidate_id)
        candidates = outline_app.available_patterns(
            catalog, genre, str(work_db), store.load_pattern_feedback(candidate_id),
        )
        _require(bool(candidates), "gate", "Planner 无法读取候选 Pattern")
        report["pattern_count"] = {
            "published": len(published),
            "all_snapshot_rows": len(pattern_rows),
        }
        report["checks"]["candidate_snapshot"] = "PASS"
        report["checks"]["planner_read"] = "PASS"
        report["checks"]["work_db_before_promote"] = _check_db(work_db)

        report["stage"] = "outline"
        outline = _outline_result(candidate_id, genre, request, pattern, work_db, outline_dir)
        report["outline_id"] = outline["outline_id"]
        report["outline_path"] = str(Path(outline["result_path"]).resolve())
        validation_ok = (outline.get("validation") or {}).get("overall_ok") is True
        report["checks"]["outline_validator"] = "PASS" if validation_ok else "REJECT"
        if not validation_ok:
            raise _CandidateRejected([{
                "code": "OUTLINE_VALIDATION_FAILED",
                "message": "Outline Validator 未通过",
            }])

        report["stage"] = "story"
        story = story_app._build_graph().invoke({
            "outline_id": outline["outline_id"],
            "knowledge_db": str(work_db),
            "user_request": request,
            "out_dir": str(story_dir),
            "outline_data": None,
            "function_constraints": None,
            "scene_plan": None,
            "scene_developments": None,
            "story": None,
            "result_path": "",
        })
        story_path = Path(story["result_path"]).resolve()
        if not story_path.is_file():
            raise _CandidateRejected([{
                "code": "STORY_EXPORT_FAILED",
                "message": "正文没有导出",
            }])
        story_payload = json.loads(story_path.read_text(encoding="utf-8"))
        if not story_payload.get("story", {}).get("scenes"):
            raise _CandidateRejected([{
                "code": "STORY_EMPTY",
                "message": "正文场景为空",
            }])
        report["story_path"] = str(story_path)
        report["story_length_ok"] = bool(story_payload.get("length_ok"))
        report["checks"]["story_export"] = "PASS"
        report["checks"]["story_length"] = "PASS" if report["story_length_ok"] else "REJECT"

        outcomes = store.load_generation_outcomes(candidate_id)
        outcome = next((item for item in outcomes if item.get("outline_id") == outline["outline_id"]), None)
        _require(outcome is not None, "outcome", "缺少 generation_outcomes 记录")
        with store.connect() as conn:
            pattern_usage_count = conn.execute(
                "SELECT COUNT(*) FROM pattern_usage WHERE snapshot_id=?", (candidate_id,)
            ).fetchone()[0]
        _require(pattern_usage_count > 0, "outcome", "缺少 pattern_usage 审计记录")
        report["outcome_id"] = outcome["outcome_id"]
        report["pattern_usage_count"] = pattern_usage_count
        report["checks"]["outcome"] = "PASS"
        report["checks"]["final_db"] = _check_db(work_db)

        input_story_ids = {Path(item).stem for item in stories}
        regression = _snapshot_regression(
            store, previous_serving, candidate_id, pattern_result, input_story_ids,
        )
        report["regression"] = regression
        rejection_reasons = list(regression["reasons"])
        if not report["story_length_ok"]:
            rejection_reasons.append({
                "code": "STORY_LENGTH_FAILED",
                "message": "Story smoke 的 length_ok=false",
            })
        if rejection_reasons:
            report["rejection_reasons"] = rejection_reasons
        if rejection_reasons and not force_promote:
            raise _CandidateRejected(rejection_reasons)
        if rejection_reasons:
            report["candidate_gate_override"] = "FORCE_PROMOTE"
        report["checks"]["candidate_regression"] = "PASS" if not rejection_reasons else "OVERRIDE"

        report["stage"] = "promote"
        promoted = True
        store.promote_snapshot(candidate_id)
        report["serving_after_promote"] = store.serving_snapshot_id()
        _require(report["serving_after_promote"] == candidate_id, "promote", "serving 未切换到候选")
        _require(
            outline_app.resolve_snapshot_id(None, work_db) == candidate_id,
            "promote", "promote 后默认 Planner 未读取候选 serving",
        )
        report["checks"]["promote"] = "PASS"
        report["status"] = "PROMOTED"
        report["stage"] = "complete"
    except _CandidateRejected as exc:
        report["status"] = "REJECTED_CANDIDATE"
        report["rejection_reasons"] = exc.reasons
        report["stage"] = "candidate_gate"
    except BaseException as exc:
        report["status"] = "FAILED"
        report["error"] = str(exc) or type(exc).__name__
        if promoted and previous_serving:
            try:
                StoryKnowledgeStore(work_db).promote_snapshot(previous_serving)
                report["rollback"] = "PASS"
            except BaseException as rollback_exc:
                report["rollback"] = "FAILED"
                report["rollback_error"] = str(rollback_exc)
    finally:
        if work_db.is_file():
            try:
                report["serving_after"] = StoryKnowledgeStore(work_db).serving_snapshot_id()
                report["checks"]["final_db"] = _check_db(work_db)
            except BaseException as exc:
                report["final_db_error"] = str(exc)
        if source_db.is_file():
            report["source_sha256_after"] = _sha256(source_db)
            report["source_unchanged"] = report.get("source_sha256_before") == report["source_sha256_after"]
        _write_json(report_path, report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="副本上的 Evolve → Pattern → candidate smoke → promote")
    parser.add_argument("--story", action="append", required=True, help="新故事 .txt，可重复")
    parser.add_argument("--genre", required=True)
    request = parser.add_mutually_exclusive_group(required=True)
    request.add_argument("--request")
    request.add_argument("--request-file")
    parser.add_argument("--pattern", default=None)
    parser.add_argument("--knowledge-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--registry-db", default=str(DEFAULT_REGISTRY_DB))
    parser.add_argument("--snapshot-root", default=str(DEFAULT_SNAPSHOT_ROOT),
                        help="正式父 Snapshot 根目录")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--stage-timeout", type=float, default=1800.0)
    parser.add_argument("--force-promote", action="store_true", help="人工显式覆盖候选回归与 length_ok 门禁")
    args = parser.parse_args(argv)
    user_request = args.request
    if args.request_file:
        user_request = Path(args.request_file).read_text(encoding="utf-8")
    try:
        report = run_release(
            args.story, args.genre, user_request or "",
            source_db=args.knowledge_db,
            source_registry_db=args.registry_db,
            source_snapshot_root=args.snapshot_root,
            out_dir=args.out_dir,
            pattern=args.pattern,
            stage_timeout=args.stage_timeout,
            force_promote=args.force_promote,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[ReleasePipeline] error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PROMOTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
