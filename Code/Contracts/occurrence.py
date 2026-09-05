"""将 Observation 对齐到最终 Function 集合。"""

from collections import Counter


def assignment_metrics(occurrences: list[dict]) -> dict:
    """从正式 FunctionOccurrence 计算实际分配率。"""
    counts = Counter(item.get("status") for item in occurrences)
    total = len(occurrences)
    ratio = lambda count: round(count / total, 4) if total else 0.0
    return {
        "total": total,
        "matched": counts.get("MATCHED", 0),
        "uncertain": counts.get("UNCERTAIN", 0),
        "other": counts.get("OTHER", 0),
        "assignment_coverage": ratio(counts.get("MATCHED", 0)),
        "uncertain_rate": ratio(counts.get("UNCERTAIN", 0)),
        "other_rate": ratio(counts.get("OTHER", 0)),
    }


def align_occurrences(
    functions: list[dict],
    observations: list[dict],
    contracts: list[dict] | None = None,
) -> list[dict]:
    """以最终 supporting_obs_ids 为准生成可发布的 FunctionOccurrence。"""
    support: dict[str, list[dict]] = {}
    for func in functions:
        for obs_id in func.get("supporting_obs_ids", []):
            support.setdefault(obs_id, []).append(func)

    by_id = {
        obs.get("obs_id") or obs.get("occurrence_id"): obs
        for obs in observations
        if obs.get("obs_id") or obs.get("occurrence_id")
    }
    contracts_by_name = {
        item.get("function_name"): item
        for item in (contracts or [])
        if item.get("function_name")
    }

    result = []
    for obs_id, obs in by_id.items():
        occurrence = dict(obs)
        occurrence["obs_id"] = obs_id
        occurrence["occurrence_id"] = obs_id
        occurrence["observation_version_id"] = obs.get("observation_version_id")
        matches = support.get(obs_id, [])
        if len(matches) == 1:
            func = matches[0]
            contract = contracts_by_name.get(func["function_name"])
            missing = [
                role for role in (contract or {}).get("role_slots", [])
                if not (occurrence.get("role_bindings") or {}).get(role)
            ]
            if missing:
                occurrence.update({
                    "status": "UNCERTAIN",
                    "function_id": None,
                    "function_name": None,
                    "candidate_functions": [func["function_name"]],
                    "reason": f"FunctionContract 角色槽位未完整绑定: {', '.join(missing)}",
                })
            else:
                occurrence.update({
                    "status": "MATCHED",
                    "function_id": func["function_id"],
                    "function_name": func["function_name"],
                })
        elif not matches and occurrence.get("label") == "NOVEL":
            occurrence.update({
                "status": "OTHER",
                "function_id": None,
                "function_name": "OTHER",
            })
        else:
            occurrence.update({
                "status": "UNCERTAIN",
                "function_id": None,
                "function_name": None,
            })
            if len(matches) > 1:
                occurrence["candidate_functions"] = [f["function_name"] for f in matches]
        result.append(occurrence)
    return result
