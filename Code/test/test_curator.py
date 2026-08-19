"""Curator 收尾维护测试：应用 pending / novelty 门槛 / 修订门槛 / 移除 / 留档 / 无累积跳过。"""

import os
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from Agent.Curator import curator as cu
from Agent.Curator.curator import curator_node
from Agent.Registry.registry import RegistryStore, get_active_store, set_active_store
from Agent.Evaluator import revise as rev
from Prompt.Abstract_merge_prompt import AbstractMergeResponse


class FakeEmbedder:
    """字符袋向量（与 test_evolve 同模式）。"""

    def __init__(self, dim=768):
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


def _func(name, sup=None, **extra):
    f = {
        "schema_version": 2, "function_name": name, "definition": f"定义{name}",
        "realization_patterns": ["模式"], "hard_negatives": ["反例"],
        "supporting_obs_ids": list(sup or []), "confidence": 0.6,
    }
    f.update(extra)
    return f


def _novel_obs(sid, oid, text):
    return {
        "obs_id": oid, "story_id": sid, "event": text, "participants": ["角色"],
        "before_state": text, "after_state": text, "affected_aspect": "认知",
        "narrative_effect": "推动", "surface_form": "表层", "source_sentence_indices": [0],
    }


def _occ(oid, label="NOVEL"):
    return {"occurrence_id": oid, "label": label, "function_name": "OTHER" if label == "NOVEL" else ""}


def _setup(tmp, funcs):
    from Agent.app import get_bank
    bank = get_bank()
    bank.clear()
    bank.embedder = FakeEmbedder()
    prev = get_active_store()
    store = RegistryStore(db_path=os.path.join(tmp, "f.db"), namespace="curator_test")
    store.replace_all(funcs)
    set_active_store(store)
    return bank, store, prev


def _teardown(prev):
    from Agent.app import get_bank
    set_active_store(prev)
    get_bank().clear()


@contextmanager
def _no_merge_scan():
    """近义扫描返回空组（避免测试触发真实识别 LLM）。"""
    orig = cu.chat_structured
    cu.chat_structured = lambda messages, schema, **kw: AbstractMergeResponse(merge_groups=[])
    try:
        yield
    finally:
        cu.chat_structured = orig


def test_apply_pending(tmp_path):
    bank, store, prev = _setup(str(tmp_path), [_func("F_A")])
    try:
        with _no_merge_scan():
            out = curator_node({
                "pending_evidence": [{"function_name": "F_A", "obs_id": "o1", "source": "matcher"}],
                "occurrences": [], "mid_reports": [], "out_dir": str(tmp_path),
            })
    finally:
        _teardown(prev)
    fa = store.load_all()[0]
    assert "o1" in fa["supporting_obs_ids"]
    assert len(fa["version_history"]) == 2  # v1 CREATE + v2 APPLY_EVIDENCE
    assert out["pending_evidence"] == []
    assert any(p["action"] == "APPLY_EVIDENCE" for p in out["curator_plan"])
    assert os.path.exists(os.path.join(tmp_path, "curator_plan.jsonl"))
    print("curator 应用 pending: OK")


def test_novelty_threshold(tmp_path):
    bank, store, prev = _setup(str(tmp_path), [_func("F_A")])
    obs = [
        _novel_obs("s1", "n1", "角色遭遇超自然现象"),
        _novel_obs("s2", "n2", "角色遭遇超自然现象"),
        _novel_obs("s3", "n3", "角色遭遇超自然现象"),
        _novel_obs("s4", "n4", "角色被诬陷入狱"),
        _novel_obs("s5", "n5", "角色被诬陷入狱"),
        _novel_obs("s6", "n6", "角色独自流浪远走他乡"),
    ]
    bank.add(obs)
    orig_ind = cu.inducer_node
    cu.inducer_node = lambda state: {"induced_functions": [{
        "function_name": "NEW_FUNC", "supporting_obs_ids": ["n1", "n2", "n3"],
    }]}
    try:
        with _no_merge_scan():
            out = curator_node({
                "pending_evidence": [],
                "occurrences": [_occ(o["obs_id"]) for o in obs],
                "mid_reports": [], "out_dir": str(tmp_path),
            })
    finally:
        cu.inducer_node = orig_ind
        _teardown(prev)
    actions = [p["action"] for p in out["curator_plan"]]
    assert "ADD_FUNCTION" in actions, actions          # 3 obs / 3 故事 → 归纳
    assert actions.count("SKIP_SMALL_SAMPLE") == 1, actions  # 2 obs / 2 故事 → 样本不足
    targets = [p["target"] for p in out["curator_plan"] if p["action"] == "ADD_FUNCTION"]
    assert targets == ["NEW_FUNC"]
    print("curator novelty 门槛: OK")


def test_merge_threshold(tmp_path):
    bank, store, prev = _setup(str(tmp_path), [
        _func("F_A", ["x1", "x2"]), _func("F_B", ["x3"]),
        _func("F_C", ["x1", "x2", "x3"]), _func("F_D", ["x4", "x5", "x6"]),
    ])
    merged = {
        "function_name": "F_CD", "definition": "合并定义",
        "realization_patterns": [], "hard_negatives": [],
        "supporting_obs_ids": ["x1", "x2", "x3", "x4", "x5", "x6"],
    }
    orig_merge, orig_revise = rev._llm_merge, rev._llm_revise
    rev._llm_merge = lambda members, obs_by_id: (dict(merged), None)
    rev._llm_revise = lambda func, reasons: None  # 不应被调用
    try:
        with _no_merge_scan():
            out = curator_node({
                "pending_evidence": [], "occurrences": [], "out_dir": str(tmp_path),
                "mid_reports": [{"recommendations": {"merge_groups": [["F_A", "F_B"], ["F_C", "F_D"]]}}],
            })
    finally:
        rev._llm_merge, rev._llm_revise = orig_merge, orig_revise
        _teardown(prev)
    names = {f["function_name"] for f in store.load_all()}
    assert "F_CD" in names and "F_C" not in names and "F_D" not in names
    assert "F_A" in names and "F_B" in names  # supporting <3 → 未动
    actions = [p["action"] for p in out["curator_plan"]]
    assert actions.count("SKIP_SMALL_SAMPLE") == 1, actions
    assert "MERGE" in actions, actions
    print("curator 合并门槛: OK")


def test_low_evidence_removed(tmp_path):
    bank, store, prev = _setup(str(tmp_path), [_func("F_E"), _func("F_KEEP")])
    try:
        with _no_merge_scan():
            out = curator_node({
                "pending_evidence": [], "occurrences": [], "out_dir": str(tmp_path),
                "mid_reports": [{"recommendations": {"low_evidence_functions": [{"function_name": "F_E"}]}}],
            })
    finally:
        _teardown(prev)
    names = {f["function_name"] for f in store.load_all()}
    assert "F_E" not in names and "F_KEEP" in names
    assert any(p["action"] == "REMOVE" for p in out["curator_plan"])
    print("curator 低证据移除: OK")


def test_no_accumulation(tmp_path):
    bank, store, prev = _setup(str(tmp_path), [_func("F_A")])
    orig = (cu.inducer_node, rev._llm_merge)
    cu.inducer_node = lambda s: (_ for _ in ()).throw(AssertionError("不应调用 inducer"))
    rev._llm_merge = lambda m, o: (_ for _ in ()).throw(AssertionError("不应调用 merge"))
    try:
        out = curator_node({"pending_evidence": [], "occurrences": [], "mid_reports": [],
                            "out_dir": str(tmp_path)})
    finally:
        cu.inducer_node, rev._llm_merge = orig
        _teardown(prev)
    assert out["curator_plan"] == []
    assert out["pending_evidence"] == []
    print("curator 无累积跳过: OK")


def test_merge_near_dups_prescreen(tmp_path):
    """近义预筛：definition 余弦 > 阈值 的近义组经 _llm_merge 合并，不同函数保留。"""
    bank, store, prev = _setup(str(tmp_path), [
        _func("F_A", ["x1", "x2", "x3"], definition="角色获得外部资源改善自身处境"),
        _func("F_B", ["x1", "x2", "x3"], definition="角色获得外部资源改善自身状况"),
        _func("F_C", ["x1", "x2", "x3"], definition="角色遭遇致命意外引发紧张氛围"),
    ])
    merged = {
        "function_name": "F_AB", "definition": "获得外部资源改善处境",
        "realization_patterns": [], "hard_negatives": [],
        "supporting_obs_ids": ["x1", "x2", "x3", "x4", "x5", "x6"],
    }
    orig = (cu.chat_structured, rev._llm_merge)
    cu.chat_structured = lambda messages, schema, **kw: AbstractMergeResponse(merge_groups=[["F_A", "F_B"]])
    rev._llm_merge = lambda members, obs_by_id: (dict(merged), None)
    try:
        plan = []
        changed = cu._revise_from_report({}, store, bank, plan)  # 无报告也跑预筛
    finally:
        cu.chat_structured, rev._llm_merge = orig
        _teardown(prev)
    assert changed, plan
    names = {f["function_name"] for f in store.load_all()}
    assert "F_AB" in names and "F_A" not in names and "F_B" not in names
    assert "F_C" in names
    assert any(p["action"] == "MERGE" and p.get("source") == "full_merge_scan" for p in plan)
    print("近义预筛合并: OK")


def test_merge_near_dups_threshold(tmp_path):
    """近义组成员 supporting < REVISE_MIN_SUPPORTING → SKIP，不合并。"""
    bank, store, prev = _setup(str(tmp_path), [
        _func("F_A", ["x1", "x2", "x3"], definition="角色获得外部资源改善自身处境"),
        _func("F_D", ["x1", "x2"], definition="角色获得外部资源改善自身状况"),
    ])
    orig = (cu.chat_structured, rev._llm_merge)
    cu.chat_structured = lambda messages, schema, **kw: AbstractMergeResponse(merge_groups=[["F_A", "F_D"]])
    rev._llm_merge = lambda m, o: (_ for _ in ()).throw(AssertionError("门槛不足不应合并"))
    try:
        plan = []
        changed = cu._revise_from_report({}, store, bank, plan)
    finally:
        cu.chat_structured, rev._llm_merge = orig
        _teardown(prev)
    assert not changed
    assert any(p["action"] == "SKIP_SMALL_SAMPLE" for p in plan)
    names = {f["function_name"] for f in store.load_all()}
    assert "F_A" in names and "F_D" in names
    print("近义预筛门槛 SKIP: OK")


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        test_apply_pending(tmp)
        test_novelty_threshold(tmp)
        test_merge_threshold(tmp)
        test_low_evidence_removed(tmp)
        test_no_accumulation(tmp)
    print("curator 测试通过")
