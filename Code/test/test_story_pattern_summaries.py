"""Story Pattern summary 节点测试。"""

from copy import deepcopy

import pytest

from story_pattern_loader import summaries


def _state(needs_review=False):
    functions = {
        f"F_{index}": {
            "function_id": f"F_{index}",
            "function_name": f"FUNCTION_{index}",
            "definition": f"定义_{index}",
        }
        for index in range(1, 5)
    }
    candidates = [{
        "motif_id": "MC_A",
        "snapshot_id": "snapshot_test",
        "function_ids": ["F_1", "F_2", "F_3", "F_4"],
    }]
    clusters = [{
        "cluster_id": "MCL_A",
        "snapshot_id": "snapshot_test",
        "member_motif_ids": ["MC_A"],
        "needs_review": needs_review,
        "story_ids": ["s1"],
        "story_support": 1,
        "category_counts": {"悬疑": 1},
        "evidence_count": 1,
        "evidence": [{
            "story_id": "s1",
            "category": "悬疑",
            "occurrence_ids": ["s1_obs_001"],
        }],
        "same_pattern_edge_ids": ["MV_A"],
    }]
    return {
        "snapshot_manifest": {"snapshot_id": "snapshot_test"},
        "function_by_id": functions,
        "motif_candidates": candidates,
        "motif_clusters": clusters,
    }


def test_summarizes_clean_clusters_and_binds_snapshot_evidence(monkeypatch):
    captured = {}

    def fake_chat(messages, schema):
        captured["messages"] = messages
        return schema(
            pattern_name="资源推进危机链",
            abstract_definition="角色获得资源后遭遇升级威胁，并进入下一阶段行动。",
            core_function_names=["FUNCTION_1", "FUNCTION_2", "FUNCTION_3", "FUNCTION_4"],
            optional_steps=["可插入一次关系铺垫"],
            applicability_conditions=["角色需要从准备阶段进入危机应对阶段"],
            counterexamples_limitations=["不适用于核心因果方向相反的序列"],
        )

    monkeypatch.setattr(summaries, "chat_structured", fake_chat)
    state = _state()
    before = deepcopy(state)
    result = summaries.summarize_story_patterns(state)
    pattern = result["pattern_summaries"][0]

    assert pattern["pattern_id"] == "PAT_A"
    assert pattern["snapshot_id"] == "snapshot_test"
    assert [item["function_id"] for item in pattern["core_function_chain"]] == ["F_1", "F_2", "F_3", "F_4"]
    assert pattern["evidence"] == state["motif_clusters"][0]["evidence"]
    assert result["skipped_clusters"] == []
    assert state == before
    assert '"cluster_id": "MCL_A"' in captured["messages"][1]["content"]


def test_v3_summary_carries_function_contract_into_pattern(monkeypatch):
    def fake_chat(_messages, schema):
        return schema(
            pattern_name="合同模式",
            abstract_definition="状态推进",
            core_function_names=["FUNCTION_1", "FUNCTION_2", "FUNCTION_3", "FUNCTION_4"],
            optional_steps=[], applicability_conditions=[], counterexamples_limitations=[],
        )

    monkeypatch.setattr(summaries, "chat_structured", fake_chat)
    state = _state()
    state["snapshot_manifest"]["schema_version"] = 3
    state["function_contract_by_id"] = {
        f"F_{index}": {"function_id": f"F_{index}", "function_name": f"FUNCTION_{index}"}
        for index in range(1, 5)
    }

    result = summaries.summarize_story_patterns(state)

    chain = result["pattern_summaries"][0]["core_function_chain"]
    assert [item["contract"]["function_id"] for item in chain] == [
        "F_1", "F_2", "F_3", "F_4",
    ]


def test_summary_carries_pattern_ending_spec(monkeypatch):
    def fake_chat(_messages, schema):
        return schema(
            pattern_name="可闭合模式",
            abstract_definition="状态推进并解决核心冲突",
            core_function_names=["FUNCTION_1", "FUNCTION_2", "FUNCTION_3", "FUNCTION_4"],
            optional_steps=[], applicability_conditions=[], counterexamples_limitations=[],
            ending_spec={
                "resolves": "压迫关系",
                "must_show": ["公开证据", "压迫者承担后果"],
                "final_state": "主角脱离压迫并恢复稳定生活",
            },
        )

    monkeypatch.setattr(summaries, "chat_structured", fake_chat)

    result = summaries.summarize_story_patterns(_state())

    assert result["pattern_summaries"][0]["ending_spec"] == {
        "resolves": "压迫关系",
        "must_show": ["公开证据", "压迫者承担后果"],
        "final_state": "主角脱离压迫并恢复稳定生活",
    }


def test_skips_needs_review_without_calling_llm(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "chat_structured",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不应调用 LLM")),
    )
    result = summaries.summarize_story_patterns(_state(needs_review=True))

    assert result["pattern_summaries"] == []
    assert result["skipped_clusters"] == ["MCL_A"]


def test_skips_cluster_when_summary_generation_fails(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "chat_structured",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("结构化输出 2 次重试后仍失败")),
    )
    with pytest.raises(ValueError):
        summaries.summarize_story_patterns(_state())


def test_rejects_unknown_core_function(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "chat_structured",
        lambda _messages, schema: schema(
            pattern_name="模式",
            abstract_definition="定义",
            core_function_names=["UNKNOWN", "FUNCTION_2", "FUNCTION_3", "FUNCTION_4"],
            optional_steps=[],
            applicability_conditions=[],
            counterexamples_limitations=[],
        ),
    )
    with pytest.raises(ValueError, match="核心 Function 无效"):
        summaries.summarize_story_patterns(_state())


@pytest.mark.parametrize("change, message", [
    ({"snapshot_manifest": None}, "Snapshot ID"),
    ({"motif_clusters": []}, "motif_clusters"),
    ({"motif_candidates": []}, "functions 和 motif_candidates"),
])
def test_rejects_invalid_inputs(change, message):
    state = _state()
    state.update(change)
    with pytest.raises(ValueError, match=message):
        summaries.summarize_story_patterns(state)
