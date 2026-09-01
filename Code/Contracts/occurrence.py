"""将 Observation 对齐到最终 Function 集合。"""


def align_occurrences(
    functions: list[dict],
    observations: list[dict],
    prior_occurrences: list[dict] | None = None,
) -> list[dict]:
    """以最终 supporting_obs_ids 为准生成可发布的 FunctionOccurrence。"""
    support: dict[str, list[dict]] = {}
    for func in functions:
        for obs_id in func.get("supporting_obs_ids", []):
            support.setdefault(obs_id, []).append(func)

    prior_by_id = {
        item.get("obs_id") or item.get("occurrence_id"): item
        for item in (prior_occurrences or [])
        if item.get("obs_id") or item.get("occurrence_id")
    }
    by_id = {
        obs.get("obs_id") or obs.get("occurrence_id"): obs
        for obs in observations
        if obs.get("obs_id") or obs.get("occurrence_id")
    }
    for obs_id, item in prior_by_id.items():
        by_id.setdefault(obs_id, item)

    result = []
    for obs_id, obs in by_id.items():
        occurrence = dict(obs)
        occurrence.update(prior_by_id.get(obs_id, {}))
        occurrence["obs_id"] = obs_id
        occurrence["occurrence_id"] = obs_id
        matches = support.get(obs_id, [])
        if len(matches) == 1:
            func = matches[0]
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
