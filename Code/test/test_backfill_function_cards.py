"""backfill_function_cards 测试：dangling 记账 / 多支持双计 / story 去重 /
频次排序与平局 / 0 证据边界 / LLM 紧凑输入（mock）。"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backfill_function_cards as bc


def _func(name, obs_ids):
    return {"function_id": "F_X", "function_name": name, "definition": "定义", "supporting_obs_ids": obs_ids}


def _bank():
    return {
        "s1_obs_1": {"obs_id": "s1_obs_1", "story_id": "s1", "participants": ["主角", "太子"],
                     "before_state": "b1", "after_state": "a1", "affected_aspect": "关系"},
        "s1_obs_2": {"obs_id": "s1_obs_2", "story_id": "s1", "participants": ["主角", "皇后"],
                     "before_state": "b2", "after_state": "a2", "affected_aspect": "关系"},
        "s2_obs_1": {"obs_id": "s2_obs_1", "story_id": "s2", "participants": ["主角", "竹马"],
                     "before_state": "b3", "after_state": "a3", "affected_aspect": "情感状态"},
        "s3_obs_1": {"obs_id": "s3_obs_1", "story_id": "s3", "participants": ["主角", "丈夫"],
                     "before_state": "b4", "after_state": "a4", "affected_aspect": "信任"},
    }


def test_dangling_accounting():
    bank = _bank()
    func = _func("F", ["s1_obs_1", "s1_obs_2", "ghost_obs"])
    ev = bc.aggregate_evidence(func, bank)
    assert ev["declared_supporting_count"] == 3
    assert ev["bank_resident_count"] == 2
    assert ev["dangling_count"] == 1
    assert ev["evidence_refs"] == ["s1_obs_1", "s1_obs_2"]


def test_multi_support_counted_per_function():
    bank = _bank()
    shared = "s1_obs_1"
    ev_a = bc.aggregate_evidence(_func("A", [shared, "s1_obs_2"]), bank)
    ev_b = bc.aggregate_evidence(_func("B", [shared]), bank)
    assert shared in ev_a["evidence_refs"] and shared in ev_b["evidence_refs"]
    assert ev_a["bank_resident_count"] == 2 and ev_b["bank_resident_count"] == 1


def test_support_story_count_distinct():
    bank = _bank()
    ev = bc.aggregate_evidence(_func("F", ["s1_obs_1", "s1_obs_2", "s2_obs_1"]), bank)
    assert ev["support_story_count"] == 2


def test_participant_labels_frequency_and_tie_break():
    bank = _bank()
    ev = bc.aggregate_evidence(_func("F", ["s1_obs_1", "s1_obs_2", "s2_obs_1", "s3_obs_1"]), bank)
    labels = [item["label"] for item in ev["participant_labels"]]
    counts = {item["label"]: item["count"] for item in ev["participant_labels"]}
    assert labels[0] == "主角" and counts["主角"] == 4
    assert counts["太子"] == counts["皇后"] == counts["竹马"] == counts["丈夫"] == 1
    assert labels[1:] == sorted(labels[1:])  # 同频按字典序


def test_common_affected_aspects_top3_tie_break():
    bank = _bank()
    ev = bc.aggregate_evidence(_func("F", ["s1_obs_1", "s1_obs_2", "s2_obs_1", "s3_obs_1"]), bank)
    assert ev["common_affected_aspects"][0] == {"value": "关系", "count": 2}
    assert len(ev["common_affected_aspects"]) == 3
    values = [item["value"] for item in ev["common_affected_aspects"]]
    assert values[1:] == sorted(values[1:])  # 同频按字典序


def test_zero_evidence_boundary():
    bank = _bank()
    ev = bc.aggregate_evidence(_func("F", ["ghost_1", "ghost_2"]), bank)
    assert ev["declared_supporting_count"] == 2
    assert ev["bank_resident_count"] == 0
    assert ev["dangling_count"] == 2
    assert ev["support_story_count"] == 0
    assert ev["participant_labels"] == []
    assert ev["common_affected_aspects"] == []
    assert ev["evidence_refs"] == []


def test_abstract_function_compact_input():
    captured = {}
    orig = bc.chat_structured
    assert "json" in bc._SYSTEM_PROMPT.lower()  # json_object 模式要求提示词含 "json"

    def fake_chat_structured(messages, output_schema, **kwargs):
        captured["messages"] = messages
        return output_schema(
            preconditions=["存在未公开信息"],
            role_slots=["隐瞒者", "发现者"],
            state_transition=bc.StateTransition(before="秘密隐藏", after="秘密被知晓"),
        )

    bc.chat_structured = fake_chat_structured
    try:
        bank = _bank()
        bank["s1_obs_1"]["event"] = "具体事件"
        bank["s1_obs_1"]["surface_form"] = "表层实现"
        result = bc.abstract_function(_func("SECRET_REVELATION", ["s1_obs_1"]), ["s1_obs_1"], bank)
    finally:
        bc.chat_structured = orig
    user = captured["messages"][1]["content"]
    assert "before_state" in user and "affected_aspect" in user
    assert "event" not in user and "surface_form" not in user
    assert result == {
        "preconditions": ["存在未公开信息"],
        "role_slots": ["隐瞒者", "发现者"],
        "state_transition": {"before": "秘密隐藏", "after": "秘密被知晓"},
    }
