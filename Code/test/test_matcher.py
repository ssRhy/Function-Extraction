"""Matcher 单元测试：top-k 召回 / 直写 exemplars / occurrence 组装 / 五分类节点（mock LLM）。"""

import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from FunctionExtract_Agent.Matcher import matcher as mm
from FunctionExtract_Agent.Matcher.matcher import (
    recall_candidates, _apply_evidence, _story_stage, _make_occurrence, matcher_node,
)
from FunctionExtract_Agent.Registry.registry import RegistryStore, get_active_store, set_active_store
from FunctionExtract_Agent.Prompt.Matcher_prompt import MatchDecision, MatchResponse


class FakeEmbedder:
    """字符袋向量：共享字符越多余弦越高（与 test_bootstrap_app 同模式）。"""

    def __init__(self, dim=512):
        self.dim = dim

    def _vec(self, text):
        v = np.zeros(self.dim)
        for ch in text:
            v[ord(ch) % self.dim] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def encode(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        return np.array([self._vec(t) for t in texts])

    def encode_single(self, text):
        return self._vec(text)

    def encode_observation(self, obs):
        vecs = []
        for f in ("before_state", "event", "after_state", "affected_aspect", "narrative_effect", "surface_form"):
            t = (obs or {}).get(f, "")
            if t and t.strip():
                vecs.append(self._vec(t))
        if not vecs:
            return np.zeros(self.dim)
        m = np.mean(vecs, axis=0)
        n = np.linalg.norm(m)
        return m / n if n else m

    def encode_observations(self, observations):
        return np.array([self.encode_observation(o) for o in observations])

    def encode_cached(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        return self.encode(texts)


def _obs(sid, oid, text="角色发现关键线索并改变认知", surface="发现线索", idx=(0,)):
    return {
        "obs_id": oid, "story_id": sid, "event": text, "participants": ["角色"],
        "participant_ids": ["P1"],
        "role_bindings": {
            "actor": ["P1"], "affected": [], "information_provider": [],
            "resource_provider": [], "beneficiary": [], "obstacle": [],
        },
        "relationship_deltas": [],
        "before_state": text, "after_state": text, "affected_aspect": "认知",
        "narrative_effect": "推动行动", "surface_form": surface,
        "source_sentence_indices": list(idx),
    }


def _func(name="INFO_REVELATION", definition="角色获知关键信息，改变认知或推动行动"):
    return {
        "schema_version": 2, "function_name": name, "definition": definition,
        "realization_patterns": ["发现线索"], "hard_negatives": [], "confusable_functions": [],
        "supporting_obs_ids": [], "confidence": 0.6,
    }


def test_recall_top_k():
    emb = FakeEmbedder()
    funcs = [_func("F_A", "角色获得资源"), _func("F_B", "角色身份暴露"), _func("F_C", "角色遭受损害")]
    cands = recall_candidates([_obs("s1", "o1", "角色获得关键资源")], funcs, emb, top_k=2)
    assert cands[0][0]["function_name"] == "F_A", cands
    assert len(cands[0]) <= 2
    assert recall_candidates([_obs("s1", "o1")], [], emb) == [[]]  # 空函数库 → 无候选


def test_story_stage():
    assert _story_stage([0], 10) == "beginning"
    assert _story_stage([5], 10) == "middle"
    assert _story_stage([9], 10) == "end"
    assert _story_stage([], 10) is None
    assert _story_stage([1], None) is None


def test_make_occurrence_novel_is_other():
    d = MatchDecision(obs_id="o1", label="NOVEL", reason="无匹配")
    occ = _make_occurrence(_obs("s1", "o1"), d, [{"function_name": "F_A", "similarity": 0.3}], "悬疑", "beginning")
    assert occ["function_name"] == "OTHER" and occ["label"] == "NOVEL"
    assert occ["top_candidates"] == [{"function_name": "F_A", "similarity": 0.3}]
    assert occ["occurrence_id"] == "o1"


def test_apply_evidence_idempotent():
    emb = FakeEmbedder()
    bank = types.SimpleNamespace(embedder=emb, get=lambda oid: None)
    f = _func()
    func_map = {f["function_name"]: f}
    obs = _obs("s1", "o1")
    changed = _apply_evidence(func_map, [("INFO_REVELATION", obs)], bank)
    assert changed == ["INFO_REVELATION"] and f["supporting_obs_ids"] == ["o1"]
    assert "confidence" in f and "confidence_factors" in f
    changed2 = _apply_evidence(func_map, [("INFO_REVELATION", obs)], bank)  # 幂等
    assert changed2 == [] and f["supporting_obs_ids"] == ["o1"]
    changed3 = _apply_evidence(func_map, [("NO_SUCH_FUNC", obs)], bank)  # 未知函数忽略
    assert changed3 == []


def test_matcher_node_mixed_labels(tmp_path):
    from FunctionExtract_Agent.app import get_bank
    bank = get_bank()
    bank.clear()
    bank.embedder = FakeEmbedder()
    prev = get_active_store()
    store = RegistryStore(db_path=str(tmp_path / "f.db"), namespace="evolve_test")
    function = _func("F_A", "角色获得资源")
    function["hard_negatives"] = ["资源被外力夺走"]
    function["confusable_functions"] = ["RESOURCE_OBTAINMENT"]
    store.replace_all([function])
    set_active_store(store)

    def fake_llm(messages, schema, **kw):
        cards = json.loads(messages[0]["content"].split("\n\n## 现有 Function 卡片\n", 1)[1])
        assert cards[0]["hard_negatives"] == ["资源被外力夺走"]
        assert cards[0]["confusable_functions"] == ["RESOURCE_OBTAINMENT"]
        return MatchResponse(decisions=[
            MatchDecision(obs_id="o1", label="MATCH", matched_function="F_A", reason="结构一致"),
            MatchDecision(obs_id="o2", label="NOVEL", reason="现有函数无法解释"),
        ])

    orig = mm.chat_structured
    mm.chat_structured = fake_llm
    try:
        state = {
            "observations": [_obs("s1", "o1", "角色获得关键资源"), _obs("s1", "o2", "角色被诅咒失去力量")],
            "normalized_story": {"sentences": list(range(10))},
            "story_config": {"story_type": "悬疑"},
        }
        out = matcher_node(state)
    finally:
        mm.chat_structured = orig
        set_active_store(prev)
        bank.clear()
    labels = {d["obs_id"]: d["label"] for d in out["match_decisions"]}
    assert labels == {"o1": "MATCH", "o2": "NOVEL"}, labels
    occs = {o["occurrence_id"]: o for o in out["match_occurrences"]}
    assert occs["o1"]["function_name"] == "F_A" and occs["o2"]["function_name"] == "OTHER"
    assert occs["o1"]["story_stage"] == "beginning" and occs["o1"]["category"] == "悬疑"
    loaded = RegistryStore(db_path=str(tmp_path / "f.db"), namespace="evolve_test").load_all()
    fa = [f for f in loaded if f["function_name"] == "F_A"][0]
    assert "o1" not in fa["supporting_obs_ids"]  # MATCH/EXTEND 不再直写
    assert fa.get("function_id") and fa.get("status") == "provisional" and fa.get("version_history")
    pending = [p for p in out["match_pending"] if p["function_name"] == "F_A"]
    assert pending == [{"function_name": "F_A", "obs_id": "o1", "source": "matcher"}], pending


def test_matcher_node_empty_registry(tmp_path):
    from FunctionExtract_Agent.app import get_bank
    bank = get_bank()
    bank.clear()
    bank.embedder = FakeEmbedder()
    prev = get_active_store()
    store = RegistryStore(db_path=str(tmp_path / "f.db"), namespace="evolve_empty")
    set_active_store(store)
    try:
        out = matcher_node({
            "observations": [_obs("s1", "o1")],
            "normalized_story": {"sentences": []},
            "story_config": {},
        })
    finally:
        set_active_store(prev)
        bank.clear()
    assert out["match_decisions"][0]["label"] == "NOVEL"
    assert out["match_occurrences"][0]["function_name"] == "OTHER"


def test_matcher_prompt_separates_label_from_function_name():
    assert "不得填写 Function 名" in mm.MATCHER_SYSTEM_PROMPT
    assert 'label="MATCH", matched_function="HAZARD_ENCOUNTER"' in mm.MATCHER_SYSTEM_PROMPT


if __name__ == "__main__":
    test_recall_top_k()
    test_story_stage()
    test_make_occurrence_novel_is_other()
    test_apply_evidence_idempotent()
    print("matcher 单元测试通过")
