"""统一 CLI：Function 提取、模板生成和正文生成。"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from KnowledgeBase import StoryKnowledgeStore
from Outline_Agent import app as outline_app
from Story_Agent import app as story_app


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KNOWLEDGE_DB = DATA / "knowledge" / "story_knowledge.db"


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 JSON: {path}") from exc


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _request(args):
    if args.request and args.request_file:
        raise ValueError("--request 与 --request-file 只能使用一个")
    if args.request_file:
        path = Path(args.request_file).resolve()
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"无法读取用户要求: {path}") from exc
    return (args.request or "").strip()


def _flatten_inputs(values):
    return [item for group in values for item in group]


def _source_manifest(root: Path):
    path = root / "manifest.json"
    if not path.is_file():
        return {}
    entries = _read_json(path)
    if not isinstance(entries, list):
        raise ValueError(f"manifest 必须是数组: {path}")
    return {
        Path(str(entry.get("txt_file", ""))).as_posix().lower(): entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("txt_file")
    }


def _collect_sources(inputs):
    sources = []
    seen = set()
    for raw in inputs:
        path = Path(raw).resolve()
        if path.is_file():
            candidates = [(path.parent, path)] if path.suffix.lower() == ".txt" else []
        elif path.is_dir():
            candidates = [(path, item) for item in path.rglob("*.txt") if item.is_file()]
        else:
            raise ValueError(f"输入路径不存在: {path}")
        for root, item in sorted(candidates, key=lambda pair: str(pair[1]).lower()):
            key = str(item).lower()
            if key not in seen:
                seen.add(key)
                sources.append((root, item))
    if not sources:
        raise ValueError("输入中没有 .txt 文件")
    return sources


def _prepare_corpus(inputs, target: Path):
    sources = _collect_sources(inputs)
    target.mkdir(parents=True, exist_ok=True)
    manifest_cache = {}
    entries = []
    for index, (root, source) in enumerate(sources, 1):
        if root not in manifest_cache:
            manifest_cache[root] = _source_manifest(root)
        relative = source.relative_to(root).as_posix().lower()
        entry = dict(manifest_cache[root].get(relative, {}))
        name = f"{index:04d}_{source.stem}.txt"
        shutil.copyfile(source, target / name)
        entry.update({
            "txt_file": name,
            "source_path": str(source),
            "story_id": entry.get("story_id") or "ST_" + hashlib.sha256(
                str(source).encode("utf-8")
            ).hexdigest()[:16],
            "category": entry.get("category") or root.name or "uncategorized",
        })
        entries.append(entry)
    _write_json(target / "manifest.json", entries)
    return target / "manifest.json", len(entries)


def _run_module(module, arguments):
    command = [sys.executable, "-X", "utf8", "-m", module, *arguments]
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines = []
    for line in process.stdout:
        print(line, end="")
        lines.append(line.rstrip())
    return_code = process.wait()
    if return_code:
        raise RuntimeError(f"{module} 失败，退出码={return_code}")
    return lines


def _snapshot_from_output(lines):
    matches = [
        match.group(1).strip()
        for line in lines
        if (match := re.search(r"OntologySnapshot\s*→\s*(.+)$", line))
    ]
    if not matches:
        raise ValueError("Function 流程没有发布 OntologySnapshot")
    path = Path(matches[-1]).resolve()
    if not path.is_dir():
        raise ValueError(f"OntologySnapshot 不存在: {path}")
    return path


def run_function(
    mode, inputs, out_dir=None, namespace=None, no_revise=False,
    batch_size=None, top_k=None, base_snapshot=None,
):
    run_id = time.strftime("%Y%m%dT%H%M%S")
    root = Path(out_dir).resolve() if out_dir else DATA / "story_cli" / "functions" / run_id
    input_dir = root / "input"
    output_dir = root / "output"
    manifest_path, count = _prepare_corpus(inputs, input_dir)
    namespace = namespace or "story_cli"
    if mode == "evolve" and not base_snapshot:
        base_snapshot = StoryKnowledgeStore(KNOWLEDGE_DB).serving_snapshot_id()
    if mode == "evolve" and base_snapshot:
        base_manifest = StoryKnowledgeStore(KNOWLEDGE_DB).load_snapshot_manifest(base_snapshot)
        if base_manifest.get("namespace") != namespace:
            raise ValueError(
                f"父 Snapshot namespace 不一致: {base_manifest.get('namespace')} != {namespace}"
            )
    arguments = [
        "--corpus", str(input_dir),
        "--namespace", namespace,
        "--out-dir", str(output_dir),
    ]
    if mode == "bootstrap":
        if no_revise:
            arguments.append("--no-revise")
        lines = _run_module("FunctionExtract_Agent", arguments)
    else:
        arguments.extend(["--knowledge-db", str(KNOWLEDGE_DB)])
        if base_snapshot:
            arguments.extend(["--base-snapshot", base_snapshot])
        if batch_size is not None:
            arguments.extend(["--batch-size", str(batch_size)])
        if top_k is not None:
            arguments.extend(["--top-k", str(top_k)])
        lines = _run_module("FunctionExtract_Agent.evolve", arguments)
    snapshot_path = _snapshot_from_output(lines)
    snapshot_id = snapshot_path.name
    observations_path = output_dir / f"bank_{namespace}.jsonl"
    occurrences_path = output_dir / "occurrences_final.jsonl"
    for path in (observations_path, occurrences_path):
        if not path.is_file():
            raise ValueError(f"Function 流程缺少模板所需产物: {path}")
    from StoryPattern_Agent.app import run_pattern_evolve

    pattern_result = run_pattern_evolve(snapshot_id, KNOWLEDGE_DB)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "namespace": namespace,
        "base_snapshot_id": base_snapshot if mode == "evolve" else None,
        "story_count": count,
        "corpus_dir": str(input_dir.resolve()),
        "corpus_manifest_path": str(manifest_path.resolve()),
        "snapshot_id": snapshot_id,
        "snapshot_path": str(snapshot_path),
        "observations_path": str(observations_path.resolve()),
        "occurrences_path": str(occurrences_path.resolve()),
        "output_dir": str(output_dir.resolve()),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "pattern_run_id": pattern_result["run_id"],
        "new_pattern_ids": pattern_result["new_pattern_ids"],
    }
    path = root / "function_run.json"
    _write_json(path, manifest)
    print(f"[StoryCLI] function_run={path}")
    return path


def _outline_state(
    snapshot_id, genre, out_dir, pattern=None, request=None,
    knowledge_db=KNOWLEDGE_DB, planner_mode="published",
):
    return {
        "snapshot_id": snapshot_id,
        "knowledge_db": str(knowledge_db),
        "genre": outline_app.normalize_genre(genre),
        "out_dir": str(out_dir),
        "pattern_request": pattern,
        "user_request": request or None,
        "planner_mode": planner_mode,
        "pattern_id": None,
        "pattern_name": "",
        "pattern_source": planner_mode,
        "pattern_selection": None,
        "ending_spec": None,
        "chain": [],
        "planner_references": None,
        "dynamic_candidates": [],
        "dynamic_candidate": None,
        "seed": None,
        "mechanism": None,
        "narrative": None,
        "contract_ledger": None,
        "outline": None,
        "validation": None,
        "outline_id": "",
        "result_path": "",
    }


def _run_outline(
    snapshot_id, genre, out_dir, pattern=None, request=None,
    knowledge_db=KNOWLEDGE_DB, planner_mode="published",
):
    result = outline_app._build_graph().invoke(_outline_state(
        snapshot_id, genre, out_dir, pattern, request, knowledge_db, planner_mode,
    ))
    validation = result.get("validation") or {}
    if not validation.get("overall_ok"):
        raise ValueError(f"Outline 校验未通过: {result['result_path']}")
    return result


def batch_outlines(
    snapshot_id, genre, count, patterns=None, request="", out_dir=None,
    knowledge_db=KNOWLEDGE_DB, planner_mode="published",
):
    if count < 1:
        raise ValueError("--count 必须大于 0")
    if not snapshot_id:
        snapshot_id = StoryKnowledgeStore(knowledge_db).serving_snapshot_id()
    genre = outline_app.normalize_genre(genre)
    root = Path(out_dir).resolve() if out_dir else DATA / "story_cli" / "outlines" / time.strftime("%Y%m%dT%H%M%S")
    graph = outline_app._build_graph()
    if planner_mode == "dynamic":
        if patterns:
            raise ValueError("dynamic Planner 不接受 --pattern")
        results = []
        for index in range(1, count + 1):
            run_dir = root / f"dynamic_{index:02d}"
            try:
                result = graph.invoke(_outline_state(
                    snapshot_id, genre, run_dir, None, request,
                    knowledge_db, planner_mode,
                ))
                validation = result.get("validation") or {}
                results.append({
                    "status": "accepted" if validation.get("overall_ok") is True else "blocked",
                    "pattern_id": None,
                    "pattern_name": result.get("pattern_name"),
                    "candidate_id": (result.get("dynamic_candidate") or {}).get("candidate_id"),
                    "classification": (result.get("dynamic_candidate") or {}).get("classification"),
                    "outline_id": result.get("outline_id"),
                    "result_path": result.get("result_path"),
                    "validation": validation,
                })
            except Exception as exc:
                results.append({
                    "status": "error", "pattern_id": None,
                    "pattern_name": None, "error": str(exc),
                })
        manifest = {
            "schema_version": 1,
            "batch_id": root.name,
            "snapshot_id": snapshot_id,
            "genre": genre,
            "planner_mode": planner_mode,
            "request": request or None,
            "requested_count": count,
            "accepted_count": sum(item["status"] == "accepted" for item in results),
            "attempted_count": sum(item["status"] in {"accepted", "blocked", "error"} for item in results),
            "results": results,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        path = root / "outline_batch_manifest.json"
        _write_json(path, manifest)
        print(f"[StoryCLI] outline_batch={path}")
        return path
    catalog = outline_app.load_catalog(snapshot_id, knowledge_db)
    store = StoryKnowledgeStore(knowledge_db)
    feedback = store.load_pattern_feedback(snapshot_id)
    all_candidates = outline_app.candidate_patterns(catalog, genre, feedback)
    used_ids = store.used_pattern_ids()
    available = [
        pattern for pattern in all_candidates
        if pattern.get("pattern_id") not in used_ids
    ]
    by_name = {}
    for pattern in available:
        by_name.setdefault(pattern["pattern_name"], []).append(pattern)
    requested_names = patterns or list(by_name)
    results = []
    for pattern in all_candidates:
        if pattern.get("pattern_id") in used_ids and (
            not patterns or pattern["pattern_name"] in requested_names
        ):
            results.append({
                "status": "skipped",
                "pattern_id": pattern.get("pattern_id"),
                "pattern_name": pattern.get("pattern_name"),
                "reason": "Pattern 已使用",
            })
    for pattern_name in requested_names:
        if len([item for item in results if item["status"] == "accepted"]) >= count:
            break
        candidates = by_name.get(pattern_name, [])
        if not candidates:
            if any(item.get("pattern_name") == pattern_name and item["status"] == "skipped" for item in results):
                continue
            results.append({
                "status": "skipped",
                "pattern_name": pattern_name,
                "reason": "Pattern 不存在或已使用",
            })
            continue
        pattern = candidates.pop(0)
        pattern_id = pattern.get("pattern_id")
        pattern_dir = root / re.sub(r"[\\/:*?\"<>|]", "_", pattern_name)
        try:
            result = graph.invoke(_outline_state(
                snapshot_id, genre, pattern_dir, pattern_name, request,
                knowledge_db,
            ))
            validation = result.get("validation") or {}
            results.append({
                "status": "accepted" if validation.get("overall_ok") is True else "blocked",
                "pattern_id": pattern_id,
                "pattern_name": pattern_name,
                "outline_id": result.get("outline_id"),
                "result_path": result.get("result_path"),
                "validation": validation,
            })
        except Exception as exc:
            results.append({
                "status": "error",
                "pattern_id": pattern_id,
                "pattern_name": pattern_name,
                "error": str(exc),
            })
    manifest = {
        "schema_version": 1,
        "batch_id": root.name,
        "snapshot_id": snapshot_id,
        "genre": genre,
        "planner_mode": planner_mode,
        "request": request or None,
        "requested_count": count,
        "accepted_count": sum(item["status"] == "accepted" for item in results),
        "attempted_count": sum(item["status"] in {"accepted", "blocked", "error"} for item in results),
        "results": results,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path = root / "outline_batch_manifest.json"
    _write_json(path, manifest)
    print(f"[StoryCLI] outline_batch={path}")
    return path


def build_template(function_run_path, genre, request="", pattern=None, out_dir=None):
    function_run_path = Path(function_run_path).resolve()
    function_run = _read_json(function_run_path)
    required = ("snapshot_id",)
    if any(not function_run.get(key) for key in required):
        raise ValueError("function_run.json 缺少模板构建所需字段")
    run_id = time.strftime("%Y%m%dT%H%M%S")
    root = Path(out_dir).resolve() if out_dir else DATA / "story_cli" / "templates" / run_id
    outline_dir = root / "outline"
    outline_result = _run_outline(
        function_run["snapshot_id"], genre, outline_dir, pattern, request,
    )
    catalog = StoryKnowledgeStore(KNOWLEDGE_DB).load_pattern_catalog(
        function_run["snapshot_id"]
    )
    selected = next(
        item for item in catalog["published_patterns"]
        if item["pattern_name"] == outline_result["pattern_name"]
    )
    bundle = {
        "schema_version": 2,
        "template_id": root.name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "function_run": str(function_run_path),
        "snapshot_id": function_run["snapshot_id"],
        "genre": outline_result["genre"],
        "pattern_name": outline_result["pattern_name"],
        "pattern": selected,
        "outline_id": outline_result["outline_id"],
        "outline_json": os.path.relpath(outline_result["result_path"], root),
        "template_request": request,
        "pattern_selection": outline_result.get("pattern_selection"),
    }
    bundle_path = root / "template_bundle.json"
    _write_json(bundle_path, bundle)
    print(f"[StoryCLI] template_bundle={bundle_path}")
    return bundle_path


def _resolve_bundle_path(bundle_path, value):
    path = Path(value)
    return path if path.is_absolute() else bundle_path.parent / path


def write_story(template_path, request="", out_dir=None):
    template_path = Path(template_path).resolve()
    bundle = _read_json(template_path)
    for key in ("snapshot_id", "pattern_name", "outline_id"):
        if not bundle.get(key):
            raise ValueError(f"Template Bundle 缺少字段: {key}")
    run_id = time.strftime("%Y%m%dT%H%M%S")
    root = Path(out_dir).resolve() if out_dir else DATA / "story_cli" / "stories" / run_id
    actual_outline_id = bundle["outline_id"]
    actual_outline_path = (
        _resolve_bundle_path(template_path, bundle["outline_json"])
        if bundle.get("outline_json") else None
    )
    if request:
        outline_result = _run_outline(
            bundle["snapshot_id"], bundle["genre"],
            root / "outline", bundle["pattern_name"], request,
        )
        actual_outline_id = outline_result["outline_id"]
        actual_outline_path = Path(outline_result["result_path"])
    story_result = story_app._build_graph().invoke({
        "outline_id": actual_outline_id,
        "knowledge_db": str(KNOWLEDGE_DB),
        "user_request": request or None,
        "out_dir": str(root / "story"),
        "outline_data": None,
        "function_constraints": None,
        "scene_plan": None,
        "scene_developments": None,
        "story": None,
        "result_path": "",
    })
    story_json = Path(story_result["result_path"])
    story_markdown = story_json.with_suffix(".md")
    manifest = {
        "schema_version": 2,
        "run_id": run_id,
        "template_bundle": str(template_path),
        "user_request": request,
        "actual_outline_id": actual_outline_id,
        "actual_outline_json": str(actual_outline_path.resolve()) if actual_outline_path else None,
        "story_json": str(story_json.resolve()),
        "story_markdown": str(story_markdown.resolve()),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    manifest_path = root / "story_run.json"
    _write_json(manifest_path, manifest)
    print(f"[StoryCLI] story_run={manifest_path}")
    return manifest_path


def _add_request_arguments(parser):
    parser.add_argument("--request", default=None, help="用户创作要求")
    parser.add_argument("--request-file", default=None, help="用户创作要求文本文件")


def _add_outline_arguments(parser, required=False):
    parser.add_argument("--snapshot-id", default=None)
    parser.add_argument("--knowledge-db", default=str(KNOWLEDGE_DB))
    parser.add_argument("--genre", required=required)
    parser.add_argument("--count", type=int, required=required)
    parser.add_argument("--pattern", action="append", default=None)
    parser.add_argument(
        "--planner-mode", choices=("published", "dynamic"), default="published",
        help="Planner 模式，默认使用已发布 Pattern",
    )
    _add_request_arguments(parser)
    parser.add_argument("--out-dir", default=None)


def show_library_status():
    result = StoryKnowledgeStore(KNOWLEDGE_DB).status()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog="StoryCLI", description="Function、模板和故事生成 CLI")
    commands = parser.add_subparsers(dest="command", required=True)

    library = commands.add_parser("library", help="统一知识库")
    library_commands = library.add_subparsers(dest="library_command", required=True)
    library_commands.add_parser("status", help="查看统一知识库状态")

    function = commands.add_parser("function", help="批量提取 Function")
    function_commands = function.add_subparsers(dest="function_command", required=True)
    bootstrap = function_commands.add_parser("bootstrap")
    bootstrap.add_argument("--input", action="append", nargs="+", required=True)
    bootstrap.add_argument("--namespace", default=None)
    bootstrap.add_argument("--no-revise", action="store_true")
    bootstrap.add_argument("--out-dir", default=None)
    evolve = function_commands.add_parser("evolve")
    evolve.add_argument("--input", action="append", nargs="+", required=True)
    evolve.add_argument("--namespace", default=None)
    evolve.add_argument("--base-snapshot", default=None)
    evolve.add_argument("--batch-size", type=int, default=None)
    evolve.add_argument("--top-k", type=int, default=None)
    evolve.add_argument("--out-dir", default=None)

    template = commands.add_parser("template", help="生成 Pattern 和 Outline 模板")
    template_commands = template.add_subparsers(dest="template_command", required=True)
    build = template_commands.add_parser("build")
    build.add_argument("--function-run", required=True)
    build.add_argument("--genre", required=True)
    build.add_argument("--pattern", default=None)
    _add_request_arguments(build)
    build.add_argument("--out-dir", default=None)

    outline = commands.add_parser("outline", help="批量生成大纲（简洁入口）")
    _add_outline_arguments(outline)
    outline_commands = outline.add_subparsers(dest="outline_command")
    batch = outline_commands.add_parser("batch", help="批量生成大纲")
    _add_outline_arguments(batch, required=True)

    story = commands.add_parser("story", help="使用 Template Bundle 写正文")
    story_commands = story.add_subparsers(dest="story_command", required=True)
    write = story_commands.add_parser("write")
    write.add_argument("--template", required=True)
    _add_request_arguments(write)
    write.add_argument("--out-dir", default=None)

    args = parser.parse_args(argv)
    try:
        if args.command == "library" and args.library_command == "status":
            show_library_status()
        elif args.command == "function" and args.function_command == "bootstrap":
            run_function(
                "bootstrap", _flatten_inputs(args.input), args.out_dir,
                args.namespace, args.no_revise,
            )
        elif args.command == "function" and args.function_command == "evolve":
            run_function(
                "evolve", _flatten_inputs(args.input), args.out_dir,
                args.namespace, batch_size=args.batch_size, top_k=args.top_k,
                base_snapshot=args.base_snapshot,
            )
        elif args.command == "template" and args.template_command == "build":
            build_template(
                args.function_run, args.genre, _request(args), args.pattern, args.out_dir,
            )
        elif args.command == "outline" and args.outline_command in (None, "batch"):
            if not args.genre or args.count is None:
                raise ValueError("outline 需要 --genre 和 --count")
            outline_args = (
                args.snapshot_id, args.genre, args.count, args.pattern,
                _request(args), args.out_dir, args.knowledge_db,
            )
            if args.planner_mode == "published":
                batch_outlines(*outline_args)
            else:
                batch_outlines(*outline_args, planner_mode=args.planner_mode)
        elif args.command == "story" and args.story_command == "write":
            write_story(args.template, _request(args), args.out_dir)
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[StoryCLI] error: {exc}", file=sys.stderr)
        return 1
