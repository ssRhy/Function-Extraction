"""冻结 Snapshot 上的 Published Pattern 人物连续性评测。

每个案例使用正式知识库的隔离副本，避免重复评测消耗生产 Pattern 的一次性使用权。
阶段一默认是 3 Pattern × 3 题材 × 1 固定种子 × 3 次重复 = 27 份 Outline；
阶段二将 ``--seed-variants`` 提高到 3，即得到 81 份 Outline。
"""

import argparse
import copy
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, Field

from Contracts.ledger import build_relationship_ledger
from FunctionExtract_Agent.llm import chat_structured
from KnowledgeBase import StoryKnowledgeStore
import Outline_Agent.app as outline_app


DEFAULT_PATTERN_IDS = [
    "PAT_16cba7dd3f283150",
    "PAT_5507fe7dc2822593",
    "PAT_a0d7911f845c23ac",
]
GENRES = ["悬疑惊悚", "古风仙侠", "现代情感"]
SEED_REQUESTS = [
    "关系从最低限度的初始事实开始，所有信任、合作或对立都必须由行动和代价逐步建立。",
    "让每个核心人物都有独立的长期目标；人物可以暂时支持或阻碍主角，但不能无证据地改变立场。",
    "让关系变化只发生在合同允许的维度，并用可观察的行动、信息或代价支持，不把一次行动自动升级成爱情、和解或永久承诺。",
]


class CharacterAuditItem(BaseModel):
    character_id: str = Field(min_length=1)
    goal_consistent: bool
    stance_consistent: bool
    evidence: str = Field(min_length=1)
    issue: str = ""


class CharacterAudit(BaseModel):
    overall_ok: bool
    assessments: list[CharacterAuditItem]
    summary: str = Field(min_length=1)


CHARACTER_AUDIT_PROMPT = """你是人物连续性审查器。只根据输入的大纲种子、机制方案、关系账本和分段大纲，检查每个核心人物的长期目标与对主角立场是否连续。

只输出 JSON，字段严格如下：
{
  "overall_ok": true,
  "assessments": [
    {"character_id":"P1", "goal_consistent":true, "stance_consistent":true,
     "evidence":"具体行动如何符合该人物目标和立场", "issue":"问题或空字符串"}
  ],
  "summary":"总体判断"
}

规则：
1. assessments 必须覆盖输入 seed.characters 中的每个人物 ID，不能新增、遗漏或重复 ID。
2. goal_consistent 检查人物在各段中的行动是否能由自己的 goal、motivation、已知信息和代价解释；“帮助主角”“因为关心”等结论本身不是充分理由。
3. stance_consistent 以 seed.characters[].stance_toward_protagonist 的开场立场为基线，检查人物对主角的 support、obstruct、mixed 或 neutral 立场是否保持连续。立场变化必须有对应事件、信息、选择或关系变化证据。
4. 人物暂时阻碍主角的某一步，不自动等于立场转为 obstruct；人物暂时支持主角，也不自动等于信任、爱情或永久联盟。
5. 只审查人物目标和立场，不因题材偏好、文风或 Function 顺序本身扣分；但若大纲用无证据的关系跳变来推动 Function，必须判为不一致。"""


def _base_state(snapshot_id, genre, out_dir, pattern_name, knowledge_db):
    return {
        "snapshot_id": snapshot_id,
        "knowledge_db": str(knowledge_db),
        "genre": genre,
        "out_dir": str(out_dir),
        "pattern_request": pattern_name,
        "user_request": None,
        "planner_mode": "published",
        "pattern_id": None,
        "pattern_name": "",
        "pattern_source": "published",
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
        "realize_retry_count": 0,
        "outline_id": "",
        "result_path": "",
    }


def _load_patterns(store, snapshot_id, pattern_ids, require_ending_spec=False):
    catalog = store.load_pattern_catalog(snapshot_id)
    by_id = {item.get("pattern_id"): item for item in catalog["published_patterns"]}
    missing = [pattern_id for pattern_id in pattern_ids if pattern_id not in by_id]
    if missing:
        raise ValueError(f"Snapshot 缺少 Published Pattern: {', '.join(missing)}")
    patterns = [by_id[pattern_id] for pattern_id in pattern_ids]
    if require_ending_spec:
        open_ended = [
            pattern.get("pattern_id")
            for pattern in patterns
            if not pattern.get("ending_spec")
        ]
        if open_ended:
            raise ValueError(
                "完整 Outline 稳定性评测要求有证据的 ending_spec；"
                f"以下 Pattern 仅有局部结构证据: {', '.join(open_ended)}"
            )
    return patterns


def _read_seed_file(path):
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        item["seed_key"]: item
        for item in payload.get("seeds", [])
        if item.get("seed_key")
    }


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_seed_cases(snapshot_id, knowledge_db, patterns, genres, variant_count, seed_file):
    existing = _read_seed_file(seed_file)
    cases = []
    for pattern in patterns:
        for genre_name in genres:
            genre = outline_app.normalize_genre(genre_name)
            pattern_name = pattern["pattern_name"]
            planner_state = _base_state(
                snapshot_id, genre, "", pattern_name, knowledge_db,
            )
            planner_state.update(outline_app.planner_node(planner_state))
            for variant_index in range(variant_count):
                seed_key = f"{pattern['pattern_id']}::{genre}::seed_{variant_index + 1}"
                cached = existing.get(seed_key)
                if cached:
                    cached = copy.deepcopy(cached)
                    cached["seed"] = outline_app.StorySeed.model_validate(
                        cached["seed"],
                    ).model_dump()
                    cases.append(cached)
                    continue
                seed_state = copy.deepcopy(planner_state)
                seed_state["user_request"] = SEED_REQUESTS[variant_index % len(SEED_REQUESTS)]
                seed_state.update(outline_app.seed_node(seed_state))
                case = {
                    "seed_key": seed_key,
                    "pattern_id": pattern["pattern_id"],
                    "pattern_name": pattern_name,
                    "genre": genre,
                    "genre_label": genre_name,
                    "variant_index": variant_index + 1,
                    "seed_request": seed_state["user_request"],
                    "seed": seed_state["seed"],
                }
                existing[seed_key] = case
                cases.append(case)
                print(
                    f"[Seed] {pattern['pattern_id']} / {genre_name} / "
                    f"variant={variant_index + 1}"
                )
    return cases


def _add_snapshot_case_issues(state, ledger):
    """保留评测专属的 Snapshot 关系案例覆盖检查。"""
    references = state.get("planner_references") or {}
    relationship_cases = references.get("relationship_cases") or {}
    missing_functions = {
        change["function_name"]
        for change in ledger.get("changes", [])
        if not relationship_cases.get(change["function_name"])
    }
    issues = list(ledger.get("issues", []))
    issues.extend(
        f"{function_name}: no_snapshot_relationship_case"
        for function_name in sorted(missing_functions)
    )
    return {**ledger, "issues": issues, "ok": not issues}


def _run_case(snapshot_id, formal_db, eval_root, case, repeat_index):
    case_id = (
        f"{case['pattern_id']}_{case['genre']}_seed{case['variant_index']}"
        f"_repeat{repeat_index}"
    )
    case_dir = eval_root / "cases" / case_id
    out_dir = case_dir / "outline"
    db_path = case_dir / "knowledge.db"
    case_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(formal_db, db_path)
    state = _base_state(
        snapshot_id, case["genre"], out_dir, case["pattern_name"], db_path,
    )
    try:
        state.update(outline_app.planner_node(state))
        state["seed"] = copy.deepcopy(case["seed"])
        state.update(outline_app.mechanism_node(state))
        relationship_replay = build_relationship_ledger(
            state["chain"], state["mechanism"]["steps"], state["seed"],
        )
        relationship_replay = _add_snapshot_case_issues(state, relationship_replay)
        state.update(outline_app.scaffold_node(state))
        state.update(outline_app.realize_node(state))
        state.update(outline_app.validate_node(state))
        if outline_app._should_retry_realize(state):
            state.update(outline_app.realize_node(state))
            state.update(outline_app.validate_node(state))
        state.update(outline_app.export_node(state))
        result = json.loads(Path(state["result_path"]).read_text(encoding="utf-8"))
        validation = result.get("validation") or {}
        contract_issues = list(validation.get("contract_issues") or [])
        structural_ok = (
            not validation.get("rule_issues")
            and not contract_issues
            and relationship_replay["ok"]
        )
        semantic_ok = bool(validation.get("overall_ok"))
        overall_ok = structural_ok and semantic_ok
        return {
            "case_id": case_id,
            "seed_key": case["seed_key"],
            "pattern_id": case["pattern_id"],
            "pattern_name": case["pattern_name"],
            "genre": case["genre"],
            "genre_label": case["genre_label"],
            "variant_index": case["variant_index"],
            "repeat_index": repeat_index,
            "status": "generated",
            "outline_id": result.get("outline_id"),
            "result_path": str(Path(state["result_path"]).resolve()),
            "validation_ok": bool(validation.get("overall_ok")),
            "structural_ok": structural_ok,
            "semantic_ok": semantic_ok,
            "overall_ok": overall_ok,
            "contract_issues": contract_issues,
            "relationship_replay": relationship_replay,
            "hard_ok": overall_ok,
            "result": result,
        }
    except Exception as exc:
        return {
            "case_id": case_id,
            "seed_key": case["seed_key"],
            "pattern_id": case["pattern_id"],
            "pattern_name": case["pattern_name"],
            "genre": case["genre"],
            "genre_label": case["genre_label"],
            "variant_index": case["variant_index"],
            "repeat_index": repeat_index,
            "status": "error",
            "structural_ok": False,
            "semantic_ok": False,
            "overall_ok": False,
            "hard_ok": False,
            "error": str(exc),
        }


def _audit_characters(record):
    result = record["result"]
    seed = result["seed"]
    audit_input = {
        "seed": seed,
        "chain": result.get("chain", []),
        "mechanism_plan": result.get("mechanism_plan", {}),
        "contract_ledger": result.get("contract_ledger", {}),
        "outline": result.get("outline", {}),
    }
    audit = chat_structured([
        {"role": "system", "content": CHARACTER_AUDIT_PROMPT},
        {"role": "user", "content": json.dumps(audit_input, ensure_ascii=False)},
    ], CharacterAudit).model_dump()
    expected = [item["id"] for item in seed.get("characters", [])]
    actual = [item.get("character_id") for item in audit.get("assessments", [])]
    shape_issues = []
    if len(actual) != len(set(actual)):
        shape_issues.append("duplicate_character_ids")
    if set(actual) != set(expected):
        shape_issues.append("character_ids_do_not_match_seed")
    item_ok = all(
        item.get("goal_consistent") is True and item.get("stance_consistent") is True
        for item in audit.get("assessments", [])
    )
    computed_overall_ok = not shape_issues and item_ok
    return {
        "case_id": record["case_id"],
        "audit": audit,
        "shape_issues": shape_issues,
        "computed_overall_ok": computed_overall_ok,
        "passed": computed_overall_ok,
    }


def _summary(records, audits, snapshot_id, seed_count, repeats, require_ending_spec=False):
    generated = [item for item in records if item["status"] == "generated"]
    structural_pass = [item for item in generated if item.get("structural_ok")]
    semantic_pass = [item for item in generated if item.get("semantic_ok")]
    overall_pass = [item for item in generated if item.get("overall_ok")]
    ledger_pass = [
        item for item in generated
        if not (item.get("relationship_replay") or {}).get("issues")
    ]
    groups = defaultdict(list)
    for item in generated:
        groups[item["seed_key"]].append(item)
    complete_groups = [
        items for items in groups.values()
        if len(items) == repeats and all(item.get("overall_ok") for item in items)
    ]
    audit_pass = sum(item.get("passed") is True for item in audits)
    requested = len(records)
    overall_rate = len(overall_pass) / requested if requested else 0.0
    repeat_group_rate = len(complete_groups) / len(groups) if groups else 0.0
    return {
        "snapshot_id": snapshot_id,
        "requested_count": requested,
        "generated_count": len(generated),
        "structural_pass_count": len(structural_pass),
        "structural_pass_rate": len(structural_pass) / requested if requested else 0.0,
        "semantic_pass_count": len(semantic_pass),
        "semantic_pass_rate": len(semantic_pass) / requested if requested else 0.0,
        "overall_pass_count": len(overall_pass),
        "overall_pass_rate": overall_rate,
        "hard_pass_count": len(overall_pass),
        "hard_pass_rate": overall_rate,
        "relationship_ledger_pass_count": len(ledger_pass),
        "relationship_ledger_pass_rate": len(ledger_pass) / len(generated) if generated else 0.0,
        "seed_group_count": len(groups),
        "repeat_count": repeats,
        "complete_repeat_group_count": len(complete_groups),
        "complete_repeat_group_rate": repeat_group_rate,
        "character_audit_count": len(audits),
        "character_audit_pass_count": audit_pass,
        "character_audit_pass_rate": audit_pass / len(audits) if audits else 0.0,
        "structural_checks_all_pass": requested == 27 and len(structural_pass) == requested,
        "phase1_hard_checks_all_pass": requested == 27 and len(overall_pass) == requested,
        "repeat_generation_ge_80_percent": overall_rate >= 0.8,
        "expanded_test_eligible": (
            requested == 27
            and len(overall_pass) == requested
            and overall_rate >= 0.8
            and repeat_group_rate >= 0.8
        ),
        "stability_claim": False,
        "seed_variant_count": seed_count,
        "ending_spec_required": require_ending_spec,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--knowledge-db", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--seed-file", default=None)
    parser.add_argument("--seed-variants", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--audit-count", type=int, default=14)
    parser.add_argument(
        "--require-ending-spec", action="store_true",
        help="完整 Outline 稳定性评测只接受有证据 ending_spec 的 Published Pattern",
    )
    parser.add_argument("--pattern-id", action="append", dest="pattern_ids")
    args = parser.parse_args(argv)
    if args.seed_variants < 1 or args.repeats < 1:
        raise ValueError("--seed-variants 和 --repeats 必须大于0")
    formal_db = Path(args.knowledge_db).resolve()
    eval_root = Path(args.out_dir).resolve()
    store = StoryKnowledgeStore(str(formal_db))
    pattern_ids = args.pattern_ids or DEFAULT_PATTERN_IDS
    patterns = _load_patterns(
        store, args.snapshot_id, pattern_ids,
        require_ending_spec=args.require_ending_spec,
    )
    eval_root.mkdir(parents=True, exist_ok=True)
    seed_cases = _build_seed_cases(
        args.snapshot_id, str(formal_db), patterns, GENRES,
        args.seed_variants, args.seed_file,
    )
    _write_json(eval_root / "seed_cases.json", {
        "snapshot_id": args.snapshot_id,
        "seed_variant_count": args.seed_variants,
        "ending_spec_required": args.require_ending_spec,
        "seeds": seed_cases,
    })

    records = []
    results_path = eval_root / "outline_results.jsonl"
    if results_path.exists():
        results_path.unlink()
    total = len(seed_cases) * args.repeats
    for index, seed_case in enumerate(seed_cases, 1):
        for repeat in range(1, args.repeats + 1):
            record = _run_case(
                args.snapshot_id, formal_db, eval_root, seed_case, repeat,
            )
            records.append(record)
            with results_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(
                f"[Outline] {len(records)}/{total} {record['case_id']} "
                f"status={record['status']} overall_ok={record.get('overall_ok')}"
            )

    generated = [item for item in records if item["status"] == "generated"]
    audit_targets = generated[:args.audit_count]
    audits = []
    audits_path = eval_root / "character_audits.jsonl"
    if audits_path.exists():
        audits_path.unlink()
    for index, record in enumerate(audit_targets, 1):
        audit = _audit_characters(record)
        audits.append(audit)
        with audits_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(audit, ensure_ascii=False) + "\n")
        print(
            f"[CharacterAudit] {index}/{len(audit_targets)} "
            f"{record['case_id']} passed={audit['passed']}"
        )

    summary = _summary(
        records, audits, args.snapshot_id, args.seed_variants, args.repeats,
        args.require_ending_spec,
    )
    _write_json(eval_root / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
