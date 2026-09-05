"""不可变 OntologySnapshot 的发布、加载与校验。"""

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone

from Contracts.function_contract import validate_function_contracts
from Contracts.state_vocabulary import StateVocabulary
from Contracts.story_profile import (
    EventRoleBindings,
    RelationshipDelta,
    ROLE_POSITION_SET,
    StoryProfileRecord,
    validate_event_roles,
)


_CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SNAPSHOT_ROOT = os.path.join(_CODE_ROOT, "data", "ontology_snapshots")


def _json_bytes(value: object, *, jsonl: bool = False) -> bytes:
    if jsonl:
        lines = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value]
        return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_functions(functions: list[dict]) -> None:
    if not functions:
        raise ValueError("OntologySnapshot 不能发布空 Function 集合")
    ids, names = set(), set()
    for index, func in enumerate(functions):
        function_id = str(func.get("function_id") or "").strip()
        name = str(func.get("function_name") or "").strip()
        definition = str(func.get("definition") or "").strip()
        if not function_id or not name or not definition:
            raise ValueError(f"Function[{index}] 缺少 function_id、function_name 或 definition")
        if function_id in ids:
            raise ValueError(f"重复 function_id: {function_id}")
        if name in names:
            raise ValueError(f"重复 function_name: {name}")
        ids.add(function_id)
        names.add(name)


def _validate_occurrences(
    occurrences: list[dict],
    functions: list[dict],
    snapshot_id: str | None = None,
    story_profiles: list[dict] | None = None,
    contracts: list[dict] | None = None,
) -> None:
    by_id = {f["function_id"]: f for f in functions}
    profiles = {
        record["story_id"]: StoryProfileRecord.model_validate(record).profile
        for record in (story_profiles or [])
    }
    contracts_by_name = {
        item["function_name"]: item for item in (contracts or [])
    }
    seen = set()
    for index, occurrence in enumerate(occurrences):
        occurrence_id = str(occurrence.get("occurrence_id") or "").strip()
        obs_id = str(occurrence.get("obs_id") or "").strip()
        observation_version_id = str(occurrence.get("observation_version_id") or "").strip()
        story_id = str(occurrence.get("story_id") or "").strip()
        status = occurrence.get("status")
        if not occurrence_id or occurrence_id != obs_id or not story_id or not observation_version_id:
            raise ValueError(f"FunctionOccurrence[{index}] 缺少一致的 occurrence_id/obs_id、observation_version_id 或 story_id")
        if occurrence_id in seen:
            raise ValueError(f"重复 occurrence_id: {occurrence_id}")
        profile = profiles.get(story_id)
        if profile is None:
            raise ValueError(f"FunctionOccurrence[{index}] 没有对应 StoryProfile: {story_id}")
        if any(field not in occurrence for field in ("participant_ids", "role_bindings", "relationship_deltas")):
            raise ValueError(
                f"FunctionOccurrence[{index}] 缺少 participant_ids、role_bindings 或 relationship_deltas"
            )
        participant_ids = occurrence.get("participant_ids")
        if not isinstance(participant_ids, list) or any(not isinstance(item, str) for item in participant_ids):
            raise ValueError(f"FunctionOccurrence[{index}] participant_ids 格式无效")
        try:
            if set((occurrence.get("role_bindings") or {})) != ROLE_POSITION_SET:
                raise ValueError("role_bindings 必须包含全部标准角色位置")
            bindings = EventRoleBindings.model_validate(occurrence.get("role_bindings"))
            deltas = [RelationshipDelta.model_validate(item) for item in occurrence.get("relationship_deltas", [])]
            validate_event_roles(profile, participant_ids, bindings, deltas)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"FunctionOccurrence[{index}] 人物角色或关系边无效: {exc}") from exc
        source_indices = set(occurrence.get("source_sentence_indices") or [])
        for delta in deltas:
            if not set(delta.evidence_sentence_indices).issubset(source_indices):
                raise ValueError(f"FunctionOccurrence[{index}] 关系变化缺少对应事件证据")
        if status not in {"MATCHED", "OTHER", "UNCERTAIN"}:
            raise ValueError(f"FunctionOccurrence[{index}] status 无效: {status}")
        if snapshot_id is not None and occurrence.get("snapshot_id") != snapshot_id:
            raise ValueError(f"FunctionOccurrence[{index}] snapshot_id 不一致")
        function_id = occurrence.get("function_id")
        function_name = occurrence.get("function_name")
        if status == "MATCHED":
            func = by_id.get(function_id)
            if func is None or func["function_name"] != function_name:
                raise ValueError(f"FunctionOccurrence[{index}] 引用了未知 Function")
            contract = contracts_by_name.get(function_name)
            if contract:
                missing = [
                    role for role in contract.get("role_slots", [])
                    if not bindings.model_dump().get(role)
                ]
                if missing:
                    raise ValueError(
                        f"FunctionOccurrence[{index}] 缺少 FunctionContract 角色槽位: {', '.join(missing)}"
                    )
        elif status == "OTHER":
            if function_id is not None or function_name != "OTHER":
                raise ValueError(f"FunctionOccurrence[{index}] OTHER 绑定无效")
        elif function_id is not None or function_name is not None:
            raise ValueError(f"FunctionOccurrence[{index}] UNCERTAIN 不能绑定 Function")
        seen.add(occurrence_id)


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_jsonl(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _validate_story_profiles(records: list[dict]) -> None:
    seen_stories, seen_versions = set(), set()
    for index, record in enumerate(records):
        try:
            parsed = StoryProfileRecord.model_validate(record)
        except ValueError as exc:
            raise ValueError(f"StoryProfile[{index}] 无效: {exc}") from exc
        if parsed.story_id in seen_stories:
            raise ValueError(f"重复 StoryProfile story_id: {parsed.story_id}")
        if parsed.story_version_id in seen_versions:
            raise ValueError(f"重复 StoryProfile story_version_id: {parsed.story_version_id}")
        seen_stories.add(parsed.story_id)
        seen_versions.add(parsed.story_version_id)


def validate_snapshot(snapshot_path: str) -> dict:
    """校验快照结构、内容约束与哈希，成功时返回 manifest。"""
    manifest_path = os.path.join(snapshot_path, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise ValueError(f"缺少 manifest.json: {snapshot_path}")
    manifest = _read_json(manifest_path)
    schema_version = manifest.get("schema_version")
    if schema_version != 5:
        raise ValueError(f"不支持的 snapshot schema_version: {manifest.get('schema_version')}")
    if manifest.get("verdict") != "PASS":
        raise ValueError("OntologySnapshot verdict 必须为 PASS")
    if manifest.get("manifest_file") != "manifest.json":
        raise ValueError("manifest_file 必须为 manifest.json")
    if manifest.get("functions_file") != "functions.jsonl":
        raise ValueError("functions_file 必须为 functions.jsonl")
    if manifest.get("evaluation_file") != "evaluation.json":
        raise ValueError("evaluation_file 必须为 evaluation.json")
    if manifest.get("occurrences_file") != "occurrences.jsonl":
        raise ValueError("occurrences_file 必须为 occurrences.jsonl")
    if manifest.get("story_profiles_file") != "story_profiles.jsonl":
        raise ValueError("story_profiles_file 必须为 story_profiles.jsonl")
    if manifest.get("function_contracts_file") and manifest.get("function_contracts_file") != "function_contracts.jsonl":
        raise ValueError("function_contracts_file 必须为 function_contracts.jsonl")
    if manifest.get("source_workflow") not in {"bootstrap", "evolve"}:
        raise ValueError("source_workflow 必须为 bootstrap 或 evolve")
    if not str(manifest.get("run_id") or "").strip():
        raise ValueError("OntologySnapshot 缺少 run_id")

    functions_path = os.path.join(snapshot_path, "functions.jsonl")
    evaluation_path = os.path.join(snapshot_path, "evaluation.json")
    if not os.path.isfile(functions_path) or not os.path.isfile(evaluation_path):
        raise ValueError("OntologySnapshot 缺少 functions 或 evaluation 文件")
    with open(functions_path, "rb") as f:
        functions_bytes = f.read()
    with open(evaluation_path, "rb") as f:
        evaluation_bytes = f.read()
    if _sha256(functions_bytes) != manifest.get("functions_sha256"):
        raise ValueError("functions.jsonl SHA-256 校验失败")
    if _sha256(evaluation_bytes) != manifest.get("evaluation_sha256"):
        raise ValueError("evaluation.json SHA-256 校验失败")
    profiles_path = os.path.join(snapshot_path, "story_profiles.jsonl")
    if not os.path.isfile(profiles_path):
        raise ValueError("OntologySnapshot 缺少 story_profiles.jsonl")
    with open(profiles_path, "rb") as f:
        profiles_bytes = f.read()
    if _sha256(profiles_bytes) != manifest.get("story_profiles_sha256"):
        raise ValueError("story_profiles.jsonl SHA-256 校验失败")

    functions = _read_jsonl(functions_path)
    evaluation = _read_json(evaluation_path)
    story_profiles = _read_jsonl(profiles_path)
    _validate_functions(functions)
    _validate_story_profiles(story_profiles)
    if len(functions) != manifest.get("function_count"):
        raise ValueError("manifest function_count 与 functions.jsonl 不一致")
    if len(story_profiles) != manifest.get("story_profile_count"):
        raise ValueError("manifest story_profile_count 与 story_profiles.jsonl 不一致")
    if evaluation.get("verdict") != "PASS":
        raise ValueError("evaluation.json verdict 必须为 PASS")
    occurrences_path = os.path.join(snapshot_path, "occurrences.jsonl")
    if not os.path.isfile(occurrences_path):
        raise ValueError("OntologySnapshot 缺少 occurrences 文件")
    with open(occurrences_path, "rb") as f:
        occurrences_bytes = f.read()
    if _sha256(occurrences_bytes) != manifest.get("occurrences_sha256"):
        raise ValueError("occurrences.jsonl SHA-256 校验失败")
    occurrences = _read_jsonl(occurrences_path)
    if len(occurrences) != manifest.get("occurrence_count"):
        raise ValueError("manifest occurrence_count 与 occurrences.jsonl 不一致")
    contracts = []
    if manifest.get("function_contracts_file"):
        contracts_path = os.path.join(snapshot_path, "function_contracts.jsonl")
        if not os.path.isfile(contracts_path):
            raise ValueError("OntologySnapshot 缺少 FunctionContract 文件")
        with open(contracts_path, "rb") as f:
            contracts_bytes = f.read()
        if _sha256(contracts_bytes) != manifest.get("function_contracts_sha256"):
            raise ValueError("function_contracts.jsonl SHA-256 校验失败")
        contracts = _read_jsonl(contracts_path)
        if len(contracts) != manifest.get("function_contract_count"):
            raise ValueError("manifest function_contract_count 与 function_contracts.jsonl 不一致")
        validate_function_contracts(functions, contracts)
        if manifest.get("state_vocabulary_file"):
            if manifest["state_vocabulary_file"] != "state_vocabulary.json":
                raise ValueError("state_vocabulary_file 必须为 state_vocabulary.json")
            vocabulary_path = os.path.join(snapshot_path, manifest["state_vocabulary_file"])
            if not os.path.isfile(vocabulary_path):
                raise ValueError("OntologySnapshot 缺少 state_vocabulary.json")
            with open(vocabulary_path, "rb") as f:
                vocabulary_bytes = f.read()
            if _sha256(vocabulary_bytes) != manifest.get("state_vocabulary_sha256"):
                raise ValueError("state_vocabulary.json SHA-256 校验失败")
            StateVocabulary.from_dict(_read_json(vocabulary_path))
    _validate_occurrences(
        occurrences, functions, manifest.get("snapshot_id"), story_profiles, contracts,
    )
    if os.path.basename(os.path.normpath(snapshot_path)) != manifest.get("snapshot_id"):
        raise ValueError("目录名与 manifest snapshot_id 不一致")
    return manifest


def load_snapshot(snapshot_path: str) -> tuple[dict, list[dict], dict]:
    """校验并读取快照。"""
    manifest = validate_snapshot(snapshot_path)
    functions = _read_jsonl(os.path.join(snapshot_path, manifest["functions_file"]))
    evaluation = _read_json(os.path.join(snapshot_path, manifest["evaluation_file"]))
    return manifest, functions, evaluation


def load_occurrences(snapshot_path: str) -> list[dict]:
    """校验并读取快照中的 FunctionOccurrence。"""
    manifest = validate_snapshot(snapshot_path)
    return _read_jsonl(os.path.join(snapshot_path, manifest["occurrences_file"]))


def load_function_contracts(snapshot_path: str, *, validate: bool = True) -> list[dict]:
    """读取快照中的 FunctionContract；迁移父快照时可显式跳过旧数据校验。"""
    manifest = (
        validate_snapshot(snapshot_path)
        if validate
        else _read_json(os.path.join(snapshot_path, "manifest.json"))
    )
    if not manifest.get("function_contracts_file"):
        return []
    return _read_jsonl(os.path.join(snapshot_path, manifest["function_contracts_file"]))


def load_story_profiles(snapshot_path: str) -> list[dict]:
    """校验并读取快照中的 StoryProfile。"""
    manifest = validate_snapshot(snapshot_path)
    return _read_jsonl(os.path.join(snapshot_path, manifest["story_profiles_file"]))


def publish_snapshot(
    functions: list[dict],
    evaluation: dict,
    source_workflow: str,
    namespace: str,
    snapshots_root: str | None = None,
    occurrences: list[dict] | None = None,
    function_contracts: list[dict] | None = None,
    parent_snapshot_id: str | None = None,
    run_id: str | None = None,
    story_profiles: list[dict] | None = None,
) -> str | None:
    """PASS 时原子发布不可变快照；相同内容重复发布返回已有目录。"""
    if evaluation.get("verdict") != "PASS":
        return None
    if source_workflow not in {"bootstrap", "evolve"}:
        raise ValueError(f"未知 source_workflow: {source_workflow}")
    _validate_functions(functions)
    occurrences = [dict(item) for item in (occurrences or [])]
    for item in occurrences:
        item.pop("snapshot_id", None)
        if any(field not in item for field in ("participant_ids", "role_bindings", "relationship_deltas")):
            raise ValueError("FunctionOccurrence 缺少 participant_ids、role_bindings 或 relationship_deltas")
        bindings = EventRoleBindings.model_validate(item.get("role_bindings"))
        item["participant_ids"] = list(dict.fromkeys(item.get("participant_ids") or []))
        item["role_bindings"] = bindings.model_dump()
        item["relationship_deltas"] = [
            RelationshipDelta.model_validate(delta).model_dump()
            for delta in (item.get("relationship_deltas") or [])
        ]
    contracts = [dict(item) for item in (function_contracts or [])]
    if function_contracts is not None:
        validate_function_contracts(functions, contracts)
    if story_profiles is None:
        raise ValueError("OntologySnapshot 必须包含 StoryProfile")
    profiles = [StoryProfileRecord.model_validate(item).model_dump() for item in story_profiles]
    _validate_story_profiles(profiles)
    _validate_occurrences(occurrences, functions, story_profiles=profiles, contracts=contracts)
    schema_version = 5

    root = os.path.abspath(snapshots_root or DEFAULT_SNAPSHOT_ROOT)
    os.makedirs(root, exist_ok=True)
    functions_bytes = _json_bytes(functions, jsonl=True)
    evaluation_bytes = _json_bytes(evaluation)
    contracts_bytes = _json_bytes(contracts, jsonl=True)
    profiles_bytes = _json_bytes(profiles, jsonl=True)
    vocabulary = StateVocabulary.from_contracts(contracts) if function_contracts is not None else None
    vocabulary_bytes = _json_bytes(vocabulary.to_dict()) if vocabulary else b""
    functions_sha = _sha256(functions_bytes)
    evaluation_sha = _sha256(evaluation_bytes)
    contracts_sha = _sha256(contracts_bytes)
    profiles_sha = _sha256(profiles_bytes)
    content_sha = _sha256(functions_bytes + contracts_bytes + vocabulary_bytes + profiles_bytes)
    effective_run_id = run_id or f"FR_{_sha256((namespace + content_sha).encode('utf-8'))[:16]}"

    for entry in os.scandir(root):
        if not entry.is_dir():
            continue
        manifest_path = os.path.join(entry.path, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue
        manifest = _read_json(manifest_path)
        if (
            manifest.get("namespace") == namespace
            and manifest.get("source_workflow") == source_workflow
            and manifest.get("functions_sha256") == functions_sha
            and manifest.get("evaluation_sha256") == evaluation_sha
            and manifest.get("story_profiles_sha256") == profiles_sha
            and manifest.get("schema_version") == schema_version
            and manifest.get("parent_snapshot_id") == parent_snapshot_id
            and manifest.get("run_id") == effective_run_id
            and bool(manifest.get("function_contracts_file")) == (function_contracts is not None)
        ):
            validate_snapshot(entry.path)
            existing = _read_jsonl(os.path.join(entry.path, "occurrences.jsonl"))
            for item in existing:
                item.pop("snapshot_id", None)
            if existing != occurrences:
                continue
            existing_profiles = _read_jsonl(os.path.join(entry.path, "story_profiles.jsonl"))
            if existing_profiles != profiles:
                continue
            if function_contracts is not None:
                existing_contracts = _read_jsonl(os.path.join(entry.path, "function_contracts.jsonl"))
                if existing_contracts != contracts:
                    continue
            return entry.path

    now = datetime.now(timezone.utc)
    created_at = now.isoformat().replace("+00:00", "Z")
    safe_namespace = re.sub(r"[^A-Za-z0-9._-]+", "_", namespace).strip("_") or "ontology"
    timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    snapshot_id = f"{safe_namespace}_{timestamp}_{content_sha[:12]}"
    snapshot_path = os.path.join(root, snapshot_id)
    if os.path.exists(snapshot_path):
        raise FileExistsError(f"OntologySnapshot 已存在且禁止覆盖: {snapshot_path}")

    published_occurrences = [dict(item, snapshot_id=snapshot_id) for item in occurrences]
    occurrences_bytes = _json_bytes(published_occurrences, jsonl=True)
    manifest = {
        "schema_version": schema_version,
        "snapshot_id": snapshot_id,
        "parent_snapshot_id": parent_snapshot_id,
        "run_id": effective_run_id,
        "source_workflow": source_workflow,
        "namespace": namespace,
        "created_at": created_at,
        "verdict": "PASS",
        "function_count": len(functions),
        "occurrence_count": len(published_occurrences),
        "story_profile_count": len(profiles),
        "manifest_file": "manifest.json",
        "functions_file": "functions.jsonl",
        "evaluation_file": "evaluation.json",
        "occurrences_file": "occurrences.jsonl",
        "story_profiles_file": "story_profiles.jsonl",
        "functions_sha256": functions_sha,
        "evaluation_sha256": evaluation_sha,
        "occurrences_sha256": _sha256(occurrences_bytes),
        "story_profiles_sha256": profiles_sha,
    }
    if function_contracts is not None:
        manifest.update({
            "function_contract_count": len(contracts),
            "function_contracts_file": "function_contracts.jsonl",
            "function_contracts_sha256": contracts_sha,
            "state_vocabulary_file": "state_vocabulary.json",
            "state_vocabulary_sha256": _sha256(vocabulary_bytes),
        })

    with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=root) as tmp:
        with open(os.path.join(tmp, "functions.jsonl"), "wb") as f:
            f.write(functions_bytes)
        with open(os.path.join(tmp, "evaluation.json"), "wb") as f:
            f.write(evaluation_bytes)
        with open(os.path.join(tmp, "occurrences.jsonl"), "wb") as f:
            f.write(occurrences_bytes)
        with open(os.path.join(tmp, "story_profiles.jsonl"), "wb") as f:
            f.write(profiles_bytes)
        if function_contracts is not None:
            with open(os.path.join(tmp, "function_contracts.jsonl"), "wb") as f:
                f.write(contracts_bytes)
            with open(os.path.join(tmp, "state_vocabulary.json"), "wb") as f:
                f.write(vocabulary_bytes)
        with open(os.path.join(tmp, "manifest.json"), "wb") as f:
            f.write(_json_bytes(manifest))
        os.replace(tmp, snapshot_path)
    validate_snapshot(snapshot_path)
    return snapshot_path
