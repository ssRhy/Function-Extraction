"""按 FunctionContract 计算故事链的状态与叙事义务账本。"""

from Contracts.function_contract import relationship_effects
from Contracts.state_vocabulary import StateVocabulary


def _relation_pairs(contract, bindings):
    pairs = set()
    for effect in relationship_effects(contract):
        people = tuple(bindings.get(slot) for slot in effect["role_slots"])
        if all(isinstance(person_id, str) for person_id in people) and len(set(people)) == 2:
            pairs.add(frozenset(people))
    return pairs


def _seed_relationship_before(seed, source_id, target_id):
    for character in seed.get("characters", []):
        if character.get("id") == source_id:
            value = (character.get("relationships") or {}).get(target_id)
            if isinstance(value, str) and value.strip():
                return value
    return None


def _contract_relationship_before(contract, bindings, source_id, target_id):
    for effect in relationship_effects(contract):
        people = {bindings.get(slot) for slot in effect["role_slots"]}
        if people == {source_id, target_id}:
            return effect.get("before")
    return None


def _expected_relationship_before(
    seed, contract, bindings, source_id, target_id, key, current,
):
    if key in current:
        return current[key]
    return (
        _seed_relationship_before(seed, source_id, target_id)
        or _contract_relationship_before(contract, bindings, source_id, target_id)
    )


def normalize_relationship_befores(
    chain: list[dict],
    mechanism_steps: list[dict],
    seed: dict,
) -> list[dict]:
    """用 seed/Contract/前一步 after 固定关系变化的 before。"""
    normalized = [
        {
            **step,
            "relationship_changes": [dict(change) for change in step.get("relationship_changes", [])],
        }
        for step in mechanism_steps
    ]
    step_by_index = {
        step.get("segment_index") or index: step
        for index, step in enumerate(normalized, 1)
    }
    current = {}
    for index, chain_step in enumerate(chain, 1):
        segment_index = chain_step.get("segment_index") or index
        mechanism = step_by_index.get(segment_index) or {}
        bindings = mechanism.get("role_bindings") or {}
        contract = chain_step.get("contract") or {}
        for change in mechanism.get("relationship_changes", []):
            key = (change.get("source_id"), change.get("target_id"), change.get("dimension"))
            expected = _expected_relationship_before(
                seed, contract, bindings, key[0], key[1], key, current,
            )
            if expected:
                change["before"] = expected
            current[key] = change.get("after")
    return normalized


def build_relationship_ledger(
    chain: list[dict],
    mechanism_steps: list[dict],
    seed: dict,
) -> dict:
    """校验机制方案中的关系变化是否有角色与契约证据支持。"""
    people = {item.get("id") for item in seed.get("characters", [])}
    step_by_index = {
        step.get("segment_index") or index: step
        for index, step in enumerate(mechanism_steps, 1)
    }
    changes, issues = [], []
    current = {}
    for index, step in enumerate(chain, 1):
        name = step.get("function_name")
        segment_index = step.get("segment_index") or index
        mechanism = step_by_index.get(segment_index) or {}
        bindings = mechanism.get("role_bindings") or {}
        bound_people = {value for value in bindings.values() if isinstance(value, str)}
        contract = step.get("contract") or {}
        relation_effects = relationship_effects(contract)
        allowed_pairs = _relation_pairs(contract, bindings)
        for change in mechanism.get("relationship_changes") or []:
            source_id = change.get("source_id")
            target_id = change.get("target_id")
            dimension = change.get("dimension")
            key = (source_id, target_id, dimension)
            if source_id not in people or target_id not in people:
                issues.append(f"{name} 关系变化引用未知人物: {source_id}/{target_id}")
            if source_id == target_id:
                issues.append(f"{name} 关系变化不能连接同一人物: {source_id}")
            if not {source_id, target_id}.issubset(bound_people):
                issues.append(f"{name} 关系变化缺少本步角色绑定: {source_id}/{target_id}")
            if not relation_effects:
                issues.append(f"{name} 的 FunctionContract 未声明有效的双角色关系效果")
            elif frozenset((source_id, target_id)) not in allowed_pairs:
                issues.append(f"{name} 的关系变化未匹配同一关系效果的两个角色槽位: {source_id}/{target_id}")
            if not str(change.get("evidence") or "").strip():
                issues.append(f"{name} 关系变化缺少证据: {source_id}/{target_id}")
            if not str(change.get("dimension") or "").strip():
                issues.append(f"{name} 关系变化缺少维度: {source_id}/{target_id}")
            if change.get("before") == change.get("after"):
                issues.append(f"{name} 关系变化前后状态相同: {source_id}/{target_id}")
            expected_before = _expected_relationship_before(
                seed, contract, bindings, source_id, target_id, key, current,
            )
            if expected_before is not None and change.get("before") != expected_before:
                issues.append(
                    f"{name} 关系变化前状态不连续: {source_id}/{target_id}/{dimension} "
                    f"expected={expected_before} actual={change.get('before')}"
                )
            state_changes = mechanism.get("character_state_changes") or {}
            for person_id in (source_id, target_id):
                if person_id not in state_changes:
                    issues.append(f"{name} 关系变化缺少人物状态对应项: {person_id}")
            current[key] = change.get("after")
            changes.append({
                "segment_index": segment_index,
                "function_name": name,
                "source_id": source_id,
                "target_id": target_id,
                "dimension": dimension or "",
                "before": change.get("before", ""),
                "after": change.get("after", ""),
                "evidence": change.get("evidence", ""),
            })
    return {"ok": not issues, "changes": changes, "issues": issues}


def check_contract_chain(chain: list[dict]) -> list[str]:
    """检查相邻 Function 的状态前置条件是否有前序效果支撑。"""
    if not any(step.get("contract") for step in chain):
        return []

    effects = []
    issues = []
    for index, step in enumerate(chain):
        contract = step.get("contract") or {}
        if not contract:
            issues.append(f"{step['function_name']} 缺少 FunctionContract")
            continue
        for precondition in contract.get("preconditions", []):
            if index == 0:
                continue
            supported = any(
                effect.get("aspect") == precondition.get("aspect")
                and effect.get("after") == precondition.get("state")
                for effect in effects
            )
            if not supported:
                issues.append(
                    f"{step['function_name']} 的前置状态 "
                    f"{precondition.get('aspect')}={precondition.get('state')} "
                    "未由前序效果建立"
                )
        effects.extend(contract.get("effects", []))
    return issues


def build_contract_ledger(
    chain: list[dict],
    mechanism_steps: list[dict],
    seed: dict,
) -> dict:
    """将实例角色绑定应用到合同，返回可审计的状态/义务账本。"""
    relationship_ledger = build_relationship_ledger(chain, mechanism_steps, seed)
    if not any(step.get("contract") for step in chain):
        return {
            "enabled": False, "states": [], "obligations": [],
            "transitions": [], "relationship_ledger": relationship_ledger,
            "issues": relationship_ledger["issues"], "warnings": [],
        }

    vocabulary = StateVocabulary.from_contracts([
        step["contract"] for step in chain if step.get("contract")
    ])
    mechanism_by_index = {
        step.get("segment_index") or index: step
        for index, step in enumerate(mechanism_steps, 1)
    }
    person_ids = {item.get("id") for item in seed.get("characters", [])}
    states = {}
    state_raw = {}
    obligations = {}
    transitions = []
    issues = []
    warnings = list(check_contract_chain(chain))

    def bound(role_slot, bindings):
        return bindings.get(role_slot, f"slot:{role_slot}")

    def obligation_key(item, bindings):
        roles = tuple(bound(role, bindings) for role in item.get("role_slots", []))
        return (vocabulary.canonical("obligation_key", item.get("key")), roles)

    for index, step in enumerate(chain):
        contract = step.get("contract") or {}
        segment_index = step.get("segment_index") or index + 1
        mechanism = mechanism_by_index.get(segment_index, {})
        bindings = mechanism.get("role_bindings") or {}
        declared_roles = set(contract.get("role_slots", []))
        missing_roles = sorted(declared_roles - set(bindings))
        if missing_roles:
            issues.append(
                f"{step['function_name']} 缺少角色绑定: {', '.join(missing_roles)}"
            )
        unknown_people = sorted(set(bindings.values()) - person_ids)
        if unknown_people:
            warnings.append(
                f"{step['function_name']} 使用非人物参与项: {', '.join(unknown_people)}"
            )
        if not str(mechanism.get("state_change") or "").strip():
            issues.append(f"{step['function_name']} 缺少实例状态变化说明")

        transition = {
            "segment_index": segment_index,
            "function_name": step["function_name"],
            "role_bindings": dict(bindings),
            "preconditions": [],
            "effects": [],
            "opens": [],
            "advances": [],
            "resolves": [],
        }
        for precondition in contract.get("preconditions", []):
            resolved = []
            for role_slot in precondition.get("role_slots", []):
                aspect_id = vocabulary.canonical("aspect", precondition["aspect"])
                state_id = vocabulary.canonical("state", precondition["state"])
                key = (bound(role_slot, bindings), aspect_id)
                current = states.get(key)
                if current is not None and current != state_id:
                    warnings.append(
                        f"{step['function_name']} 前置状态不匹配: "
                        f"{key[0]}/{precondition['aspect']} 当前={state_raw[key]} "
                        f"需要={precondition['state']}"
                    )
                states.setdefault(key, state_id)
                state_raw.setdefault(key, precondition["state"])
                resolved.append({"role": key[0], "aspect": precondition["aspect"], "state": precondition["state"]})
            transition["preconditions"].extend(resolved)

        for effect in contract.get("effects", []):
            resolved = []
            for role_slot in effect.get("role_slots", []):
                aspect_id = vocabulary.canonical("aspect", effect["aspect"])
                before_id = vocabulary.canonical("state", effect["before"])
                after_id = vocabulary.canonical("state", effect["after"])
                key = (bound(role_slot, bindings), aspect_id)
                current = states.get(key)
                if current is not None and current != before_id:
                    warnings.append(
                        f"{step['function_name']} 效果前状态不匹配: "
                        f"{key[0]}/{effect['aspect']} 当前={state_raw[key]} "
                        f"需要={effect['before']}"
                    )
                states[key] = after_id
                state_raw[key] = effect["after"]
                resolved.append({
                    "role": key[0], "aspect": effect["aspect"],
                    "before": effect["before"], "after": effect["after"],
                })
            transition["effects"].extend(resolved)

        for field in ("opens", "advances", "resolves"):
            for item in (contract.get("obligation_effects") or {}).get(field, []):
                key = obligation_key(item, bindings)
                if field == "resolves":
                    obligations.pop(key, None)
                else:
                    obligations[key] = {
                        "key": item["key"],
                        "role_slots": [bound(role, bindings) for role in item.get("role_slots", [])],
                        "description": item["description"],
                        "satisfied_when": item["satisfied_when"],
                        "source_function": step["function_name"],
                    }
                transition[field].append(item["key"])
        transitions.append(transition)

    issues.extend(relationship_ledger["issues"])
    return {
        "enabled": True,
        "states": [
            {"role": role, "aspect": aspect, "state": state_raw[(role, aspect)]}
            for (role, aspect) in sorted(states)
        ],
        "obligations": list(obligations.values()),
        "transitions": transitions,
        "relationship_ledger": relationship_ledger,
        "issues": issues,
        "warnings": warnings,
        "state_vocabulary": vocabulary.to_dict(),
    }
