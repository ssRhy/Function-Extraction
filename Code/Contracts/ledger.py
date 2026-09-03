"""按 FunctionContract 计算故事链的状态与叙事义务账本。"""

from Contracts.state_vocabulary import StateVocabulary


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
    if not any(step.get("contract") for step in chain):
        return {
            "enabled": False, "states": [], "obligations": [],
            "transitions": [], "issues": [], "warnings": [],
        }

    vocabulary = StateVocabulary.from_contracts([
        step["contract"] for step in chain if step.get("contract")
    ])
    mechanism_by_name = {step.get("function_name"): step for step in mechanism_steps}
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
        mechanism = mechanism_by_name.get(step.get("function_name"), {})
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

    return {
        "enabled": True,
        "states": [
            {"role": role, "aspect": aspect, "state": state_raw[(role, aspect)]}
            for (role, aspect) in sorted(states)
        ],
        "obligations": list(obligations.values()),
        "transitions": transitions,
        "issues": issues,
        "warnings": warnings,
        "state_vocabulary": vocabulary.to_dict(),
    }
