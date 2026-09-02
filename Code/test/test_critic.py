"""Critic 边界复检器测试：四类分流 / 函数卡片含 hard_negatives / LLM 失败保持 / 无目标跳过。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from FunctionExtract_Agent.Critic import critic as cc
from FunctionExtract_Agent.Critic.critic import critic_node
from FunctionExtract_Agent.Registry.registry import RegistryStore, get_active_store, set_active_store
from FunctionExtract_Agent.Prompt.Critic_prompt import CriticResponse, CriticReview


def _occ(oid, label, matched="", candidates=None):
    return {
        "occurrence_id": oid,
        "function_name": "" if label in ("CONFLICT", "UNCERTAIN") else ("OTHER" if label == "NOVEL" else matched),
        "label": label,
        "story_id": "s1",
        "category": None,
        "event": "事件",
        "participants": ["角色"],
        "before_state": "前",
        "after_state": "后",
        "surface_form": "表层",
        "source_sentence_indices": [0],
        "story_stage": "beginning",
        "matched_function": matched,
        "candidate_functions": candidates or [],
        "top_candidates": [{"function_name": "F_A", "similarity": 0.7}],
        "reason": "原因",
        "ts": "t",
    }


def _func(name, definition="测试定义", hard_negatives=("反例",)):
    return {
        "schema_version": 2,
        "function_name": name,
        "definition": definition,
        "realization_patterns": ["模式"],
        "hard_negatives": list(hard_negatives),
        "supporting_obs_ids": [],
        "confidence": 0.6,
    }


def test_critic_routes(tmp_path):
    """四类分流：match/extend→pending、novel→NOVEL、resolved→RESOLVED；非边界保持。"""
    store = RegistryStore(db_path=str(tmp_path / "f.db"), namespace="critic_test")
    store.replace_all([_func("F_A", "角色获得资源"), _func("F_B", "角色关系破裂")])
    prev = get_active_store()
    set_active_store(store)

    def fake_llm(messages, schema, **kw):
        assert "hard_negatives" in messages[0]["content"]  # 函数卡片含边界反例
        return CriticResponse(decisions=[
            CriticReview(obs_id="c1", final_label="resolved", matched_function="F_A", reason="边界差异"),
            CriticReview(obs_id="u1", final_label="match", matched_function="F_A", reason="确认归函数"),
            CriticReview(obs_id="u2", final_label="extend", matched_function="F_B", reason="新表层"),
            CriticReview(obs_id="u3", final_label="novel", reason="无适配"),
        ])

    orig = cc.chat_structured
    cc.chat_structured = fake_llm
    try:
        out = critic_node({
            "match_occurrences": [
                _occ("m1", "MATCH", "F_A"),
                _occ("n1", "NOVEL"),
                _occ("c1", "CONFLICT", "F_A"),
                _occ("u1", "UNCERTAIN", candidates=["F_A", "F_B"]),
                _occ("u2", "UNCERTAIN", candidates=["F_B"]),
                _occ("u3", "UNCERTAIN", candidates=["F_A"]),
            ],
            "match_pending": [{"function_name": "F_A", "obs_id": "m1", "source": "matcher"}],
        })
    finally:
        cc.chat_structured = orig
        set_active_store(prev)

    by_id = {o["occurrence_id"]: o for o in out["match_occurrences"]}
    assert by_id["m1"]["label"] == "MATCH" and by_id["n1"]["label"] == "NOVEL"  # 非边界保持
    assert by_id["c1"]["label"] == "RESOLVED" and by_id["c1"]["resolved_by"] == "critic"
    assert by_id["u1"]["label"] == "MATCH" and by_id["u1"]["function_name"] == "F_A"
    assert by_id["u2"]["label"] == "EXTEND" and by_id["u2"]["function_name"] == "F_B"
    assert by_id["u3"]["label"] == "NOVEL" and by_id["u3"]["function_name"] == "OTHER"
    pendings = {p["obs_id"]: p for p in out["match_pending"]}
    assert pendings["m1"]["source"] == "matcher"          # 透传 matcher 的 pending
    assert pendings["u1"] == {"function_name": "F_A", "obs_id": "u1", "source": "critic"}
    assert pendings["u2"] == {"function_name": "F_B", "obs_id": "u2", "source": "critic"}
    assert "u3" not in pendings and "c1" not in pendings
    print("critic 四类分流: OK")


def test_critic_llm_failure_keeps_original(tmp_path):
    """LLM 复检失败 → 边界 obs 保持原始 label，errors 记录。"""
    store = RegistryStore(db_path=str(tmp_path / "f.db"), namespace="critic_test")
    store.replace_all([_func("F_A")])
    prev = get_active_store()
    set_active_store(store)

    def fake_llm(messages, schema, **kw):
        raise ValueError("LLM 复检失败")

    orig = cc.chat_structured
    cc.chat_structured = fake_llm
    try:
        out = critic_node({
            "match_occurrences": [_occ("u1", "UNCERTAIN", candidates=["F_A"]), _occ("m1", "MATCH", "F_A")],
            "match_pending": [],
        })
    finally:
        cc.chat_structured = orig
        set_active_store(prev)
    by_id = {o["occurrence_id"]: o for o in out["match_occurrences"]}
    assert by_id["u1"]["label"] == "UNCERTAIN"  # 复检失败保持
    assert by_id["m1"]["label"] == "MATCH"
    assert out["errors"] and "resolved_by" not in by_id["u1"]
    print("critic LLM 失败保持原始 label: OK")


def test_critic_no_targets_passthrough():
    """无 CONFLICT/UNCERTAIN → 跳过复检，pending 透传。"""
    out = critic_node({
        "match_occurrences": [_occ("m1", "MATCH", "F_A"), _occ("n1", "NOVEL")],
        "match_pending": [{"function_name": "F_A", "obs_id": "m1", "source": "matcher"}],
    })
    assert len(out["match_occurrences"]) == 2
    assert out["match_pending"] == [{"function_name": "F_A", "obs_id": "m1", "source": "matcher"}]
    assert out["errors"] == []
    print("critic 无边界跳过: OK")


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        test_critic_routes(tmp)
        test_critic_llm_failure_keeps_original(tmp)
    test_critic_no_targets_passthrough()
    print("critic 测试通过")
