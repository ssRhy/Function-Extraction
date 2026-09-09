"""Story 正文的确定性结构校验。"""


def _function_execution_issues(source, scene_plan, validation):
    expected = [
        (index, segment["function_name"])
        for index, segment in enumerate(source["outline"]["segments"], 1)
    ]
    evidence = validation.get("function_execution_evidence") or []
    issues = []
    if len(evidence) != len(expected):
        issues.append(
            f"逐 Function 执行证据数量为 {len(evidence)}，应为 {len(expected)}"
        )

    scenes = scene_plan.get("scenes", [])
    scene_positions = {
        scene.get("scene_id"): position
        for position, scene in enumerate(scenes)
    }
    previous_position = -1
    for item, (segment_index, function_name) in zip(evidence, expected):
        if item.get("segment_index") != segment_index:
            issues.append(f"Function 执行证据 segment_index 应为 {segment_index}")
        if item.get("function_name") != function_name:
            issues.append(f"第 {segment_index} 段 Function 执行证据名称不一致")
        if not (item.get("evidence") or "").strip():
            issues.append(f"第 {segment_index} 段缺少正文执行证据")
        scene_id = item.get("scene_id")
        scene = next(
            (
                scene for scene in scenes
                if scene.get("scene_id") == scene_id
                and not scene.get("is_ending")
                and segment_index in scene.get("source_segment_indices", [])
                and function_name in scene.get("function_names", [])
            ),
            None,
        )
        if scene is None:
            issues.append(
                f"第 {segment_index} 段 Function 执行证据 scene_id 不属于对应 Function 场景"
            )
        elif scene_positions[scene_id] <= previous_position:
            issues.append("逐 Function 执行证据的 scene_id 未按目标链顺序排列")
        elif item.get("status") == "MISSING":
            issues.append(f"第 {segment_index} 段 Function 正文执行缺失")
        if scene is not None:
            previous_position = scene_positions[scene_id]

    return list(dict.fromkeys(issues))
