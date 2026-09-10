"""稳定 Function 的证据驱动状态契约。"""

import json
import os
from copy import deepcopy

from FunctionExtract_Agent.llm import chat_structured
from Contracts.function_contract import (
    FunctionContractBody,
    definition_sha256,
    validate_function_contracts,
)
from Contracts.state_vocabulary import StateVocabulary
from FunctionExtract_Agent.Prompt.Contract_prompt import CONTRACT_SYSTEM_PROMPT


def _select_evidence(function: dict, bank: dict[str, dict], limit: int = 12) -> list[dict]:
    resident = [bank[oid] for oid in function.get("supporting_obs_ids", []) if oid in bank]
    resident.sort(key=lambda item: (str(item.get("story_id", "")), str(item.get("obs_id", ""))))
    selected, seen_stories = [], set()
    for observation in resident:
        story_id = observation.get("story_id")
        if story_id not in seen_stories:
            selected.append(observation)
            seen_stories.add(story_id)
        if len(selected) >= limit:
            return selected
    for observation in resident:
        if observation not in selected:
            selected.append(observation)
        if len(selected) >= limit:
            break
    return selected


def _format_evidence(observations: list[dict]) -> str:
    rows = []
    for observation in observations:
        rows.append({
            "obs_id": observation.get("obs_id"),
            "story_id": observation.get("story_id"),
            "event": observation.get("event", ""),
            "participants": observation.get("participants", []),
            "participant_ids": observation.get("participant_ids", []),
            "role_bindings": observation.get("role_bindings", {}),
            "relationship_deltas": observation.get("relationship_deltas", []),
            "before_state": observation.get("before_state", ""),
            "after_state": observation.get("after_state", ""),
            "affected_aspect": observation.get("affected_aspect", ""),
        })
    return json.dumps(rows, ensure_ascii=False)


def build_function_contract(function: dict, bank: dict[str, dict]) -> dict:
    evidence = _select_evidence(function, bank)
    if not evidence:
        raise ValueError(f"Function {function.get('function_name')} 没有可驻留证据，不能发布契约")
    user = (
        f"Function: {function['function_name']}\n"
        f"定义: {function['definition']}\n"
        f"Observation JSON: {_format_evidence(evidence)}"
    )
    body = chat_structured([
        {"role": "system", "content": CONTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ], FunctionContractBody).model_dump()
    contract = {
        "function_id": function["function_id"],
        "function_name": function["function_name"],
        "definition_sha256": definition_sha256(function),
        "evidence_refs": [item["obs_id"] for item in evidence],
        **body,
    }
    validate_function_contracts([function], [contract])
    return contract


def _read_existing(path: str) -> dict[str, dict]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return {
            item["function_id"]: item
            for item in (json.loads(line) for line in handle if line.strip())
        }


def _write_contracts(path: str, contracts: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for contract in contracts:
            handle.write(json.dumps(contract, ensure_ascii=False) + "\n")


def _write_vocabulary(path: str, contracts: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(StateVocabulary.from_contracts(contracts).to_dict(), handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _sanitize_legacy_contract(contract: dict) -> dict:
    """在子 Snapshot 中丢弃历史单角色关系授权，保持新合同门槛严格。"""
    sanitized = deepcopy(contract)
    effects = sanitized.get("effects") or []
    valid_effects = [
        effect for effect in effects
        if not (
            effect.get("aspect") in {"RELATIONSHIP_STATUS", "RELATIONSHIP"}
            and (
                len(effect.get("role_slots", [])) != 2
                or len(set(effect.get("role_slots", []))) != 2
            )
        )
    ]
    if len(valid_effects) != len(effects):
        # 只有旧关系授权时，降级为普通 Function 状态，避免重新生成再次污染关系边。
        if valid_effects:
            sanitized["effects"] = valid_effects
        else:
            sanitized["effects"] = [
                {**effect, "aspect": "FUNCTION_STATE"}
                for effect in effects
            ]
    return sanitized


def _prune_optional_role_slots(contract: dict) -> dict:
    """只保留 Contract 实际引用的必需角色槽位。"""
    if not contract:
        return contract
    referenced = []
    for item in [*(contract.get("preconditions") or []), *(contract.get("effects") or [])]:
        referenced.extend(item.get("role_slots") or [])
    obligations = contract.get("obligation_effects") or {}
    for group in ("opens", "advances", "resolves"):
        for item in obligations.get(group) or []:
            referenced.extend(item.get("role_slots") or [])
    required = set(referenced)
    return {
        **contract,
        "role_slots": [role for role in contract.get("role_slots", []) if role in required],
    }


def build_function_contracts(
    functions: list[dict],
    observations: list[dict],
    out_dir: str,
    existing_contracts: list[dict] | None = None,
) -> list[dict]:
    """逐 Function 生成契约；定义未变的成功结果可断点复用。"""
    if not functions:
        raise ValueError("空 Function 集不能构建 FunctionContract")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "function_contracts.jsonl")
    existing = {
        function_id: _prune_optional_role_slots(_sanitize_legacy_contract(contract))
        for function_id, contract in _read_existing(path).items()
    }
    for contract in existing_contracts or []:
        existing.setdefault(
            contract["function_id"],
            _prune_optional_role_slots(_sanitize_legacy_contract(contract)),
        )
    bank = {item.get("obs_id"): item for item in observations if item.get("obs_id")}
    contracts = []
    for function in functions:
        cached = _prune_optional_role_slots(existing.get(function.get("function_id")))
        if cached and cached.get("definition_sha256") == definition_sha256(function):
            try:
                validate_function_contracts([function], [cached])
                contracts.append(cached)
                continue
            except ValueError:
                pass
        contracts.append(_prune_optional_role_slots(build_function_contract(function, bank)))
        _write_contracts(path, contracts)
    validate_function_contracts(functions, contracts)
    _write_contracts(path, contracts)
    _write_vocabulary(os.path.join(out_dir, "state_vocabulary.json"), contracts)
    return contracts
