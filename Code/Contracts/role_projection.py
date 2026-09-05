"""从冻结 Snapshot 投影可供 Outline Planner 使用的角色参考。"""

from collections import defaultdict

from Contracts.story_profile import ROLE_POSITIONS, StoryProfileRecord


def project_role_references(
    functions: list[dict],
    contracts: list[dict],
    occurrences: list[dict],
    story_profiles: list[dict],
    max_cases: int = 3,
) -> dict:
    profiles = {}
    for record in story_profiles:
        parsed = StoryProfileRecord.model_validate(record)
        profiles[parsed.story_id] = parsed.profile
    contracts_by_name = {item.get("function_name"): item for item in contracts}
    stats = {}
    people_by_position = defaultdict(lambda: defaultdict(set))
    protagonist_by_position = defaultdict(lambda: defaultdict(int))
    roles_by_position = defaultdict(lambda: defaultdict(set))
    goals_by_position = defaultdict(lambda: defaultdict(set))
    stances_by_position = defaultdict(lambda: defaultdict(set))
    counts = defaultdict(int)
    cases = defaultdict(list)

    def person_context(profile, person_id):
        character = next((item for item in profile.characters if item.id == person_id), None)
        if character is None:
            return {}
        stance = "self" if person_id == profile.protagonist_id else "neutral"
        for relationship in profile.relationships:
            if relationship.source_id == person_id:
                stance = relationship.stance_toward_protagonist
                break
        return {
            "structural_role": character.structural_role,
            "long_term_goal": character.long_term_goal,
            "stance_toward_protagonist": stance,
        }

    for occurrence in occurrences:
        if occurrence.get("status") != "MATCHED":
            continue
        name = occurrence.get("function_name")
        profile = profiles.get(occurrence.get("story_id"))
        if not name or profile is None:
            continue
        counts[name] += 1
        bindings = occurrence.get("role_bindings") or {}
        for position in ROLE_POSITIONS:
            for person_id in bindings.get(position, []):
                context = person_context(profile, person_id)
                people_by_position[name][position].add((occurrence.get("story_id"), person_id))
                roles_by_position[name][position].add(context.get("structural_role", "unknown"))
                goals_by_position[name][position].add(context.get("long_term_goal", ""))
                stances_by_position[name][position].add(
                    context.get("stance_toward_protagonist", "neutral")
                )
                if person_id == profile.protagonist_id:
                    protagonist_by_position[name][position] += 1
        deltas = occurrence.get("relationship_deltas") or []
        if deltas and len(cases[name]) < max_cases:
            person_by_id = {item.id: item for item in profile.characters}
            transformed = []
            for delta in deltas:
                source = person_by_id.get(delta.get("source_id"))
                target = person_by_id.get(delta.get("target_id"))
                if source is None or target is None:
                    continue
                transformed.append({
                    "source_role": source.structural_role,
                    "target_role": target.structural_role,
                    "dimension": delta.get("dimension", ""),
                    "before": delta.get("before", ""),
                    "after": delta.get("after", ""),
                })
            if transformed:
                cases[name].append({
                    "function_name": name,
                    "occurrence_id": occurrence.get("occurrence_id"),
                    "story_id": occurrence.get("story_id"),
                    "role_context": {
                        position: [person_context(profile, person_id) for person_id in bindings.get(position, [])]
                        for position in ROLE_POSITIONS if bindings.get(position)
                    },
                    "relationship_deltas": transformed,
                })

    names = {item.get("function_name") for item in functions}
    for name in names:
        stats[name] = {
            "function_name": name,
            "occurrence_count": counts[name],
            "declared_role_slots": (contracts_by_name.get(name) or {}).get("role_slots", []),
            "positions": {
                position: {
                    "binding_count": sum(
                        len(occurrence.get("role_bindings", {}).get(position, []))
                        for occurrence in occurrences
                        if occurrence.get("status") == "MATCHED"
                        and occurrence.get("function_name") == name
                    ),
                    "person_count": len(people_by_position[name][position]),
                    "protagonist_count": protagonist_by_position[name][position],
                    "structural_roles": sorted(roles_by_position[name][position]),
                    "long_term_goals": sorted(
                        goal for goal in goals_by_position[name][position] if goal
                    ),
                    "stances": sorted(stances_by_position[name][position]),
                }
                for position in ROLE_POSITIONS
                if people_by_position[name][position] or position in (contracts_by_name.get(name) or {}).get("role_slots", [])
            },
        }
    return {
        "role_stats": {name: stats[name] for name in sorted(stats)},
        "relationship_cases": {name: cases[name] for name in sorted(cases)},
    }
