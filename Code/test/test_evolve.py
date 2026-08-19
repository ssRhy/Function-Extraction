"""evolve_app 单图测试：mock LLM + FakeEmbedder，验证逐篇循环 / 直写 / pools / 报告。"""

import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from Agent import evolve as ev
from Agent.Pre_pro import pre_processor as pp
from Agent.Observer import observer as ob
from Agent.Matcher import matcher as mm
from Agent.Evaluator import evaluator as ev_module
from Agent.Critic import critic as cc
from Agent.Registry.registry import RegistryStore, get_active_store, set_active_store
from Agent.Pre_pro.pre_processor import PreCorrection
from Agent.Observer.observer import ObservationResponse, ObservationItem
from Prompt.Matcher_prompt import MatchResponse, MatchDecision
from Prompt.Evaluator_prompt import EvaluatorReviewResponse, FunctionQualityReview
from Prompt.Critic_prompt import CriticResponse, CriticReview


class FakeEmbedder:
    """字符袋向量（与 test_bootstrap_app / test_matcher 同模式）。"""

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


def _write_story(tmp, name, text="角色发现关键线索。角色决定采取新行动。"):
    with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
        f.write(text)


@contextmanager
def _patched_llm(calls, matcher_fn=None):
    originals = {"pp": pp.chat_structured, "ob": ob.chat_structured, "mm": mm.chat_structured,
                 "ev": ev_module.chat_structured, "cc": cc.chat_structured}

    def fake_pre(messages, schema, **kw):
        calls["pre"] += 1
        return PreCorrection(merges=[], splits=[])

    def fake_obs(messages, schema, **kw):
        calls["obs"] += 1
        return ObservationResponse(observations=[
            ObservationItem(
                before_state="局面平静",
                event="角色获得关键资源并改变处境",
                participants=["角色"],
                after_state="角色掌握关键资源",
                affected_aspect="资源",
                narrative_effect="推动行动",
                surface_form="获得资源",
                source_sentence_indices=[0],
            )
        ])

    def fake_matcher(messages, schema, **kw):
        calls["matcher"] += 1
        if matcher_fn is not None:
            return matcher_fn(messages)
        content = messages[1]["content"]
        oids = re.findall(r'"obs_id": "([^"]+)"', content)
        return MatchResponse(decisions=[
            MatchDecision(obs_id=o, label="MATCH", matched_function="RESOURCE_ACQUISITION", reason="结构一致")
            for o in oids
        ])

    def fake_eval(messages, schema, **kw):
        calls["eval"] += 1
        payload = messages[1]["content"].split("\n", 1)[1]
        cards = json.loads(payload)
        return EvaluatorReviewResponse(reviews=[
            FunctionQualityReview(
                function_name=c["function_name"],
                bidirectional_conflation=False, conflation_reason="",
                genre_surface_binding=False, binding_reason="",
                granularity="ok", recommendation="OK",
            )
            for c in cards
        ])

    def fake_critic(messages, schema, **kw):
        calls["critic"] += 1
        content = messages[1]["content"]
        oids = re.findall(r'"obs_id": "([^"]+)"', content)
        return CriticResponse(decisions=[
            CriticReview(obs_id=o, final_label="match", matched_function="RESOURCE_ACQUISITION",
                         reason="复检确认归函数")
            for o in oids
        ])

    pp.chat_structured = fake_pre
    ob.chat_structured = fake_obs
    mm.chat_structured = fake_matcher
    ev_module.chat_structured = fake_eval
    cc.chat_structured = fake_critic
    try:
        yield
    finally:
        pp.chat_structured = originals["pp"]
        ob.chat_structured = originals["ob"]
        mm.chat_structured = originals["mm"]
        ev_module.chat_structured = originals["ev"]
        cc.chat_structured = originals["cc"]


def _initial(tmp, story_files):
    return {
        "messages": [],
        "raw_text": None,
        "story_config": None,
        "normalized_story": None,
        "observations": [],
        "added_obs_ids": [],
        "similar_observations": [],
        "match_decisions": [],
        "match_occurrences": [],
        "occurrences": [],
        "match_report": None,
        "obs_since_eval": 0,
        "mid_reports": [],
        "curator_plan": [],
        "current_story_index": 0,
        "total_stories": len(story_files),
        "story_files": story_files,
        "corpus_dir": tmp,
        "story_meta": {},
        "errors": [],
        "namespace": "evolve_test",
        "out_dir": tmp,
    }


def test_evolve_flow():
    calls = {"pre": 0, "obs": 0, "matcher": 0, "eval": 0, "critic": 0}
    with tempfile.TemporaryDirectory() as tmp:
        _write_story(tmp, "s1.txt")
        _write_story(tmp, "s2.txt")
        from Agent.app import get_bank
        bank = get_bank()
        bank.clear()
        bank.embedder = FakeEmbedder()
        prev = get_active_store()
        store = RegistryStore(db_path=os.path.join(tmp, "f.db"), namespace="evolve_test")
        store.replace_all([{
            "schema_version": 2,
            "function_name": "RESOURCE_ACQUISITION",
            "definition": "角色获得关键资源或助力",
            "realization_patterns": ["获得资源"],
            "supporting_obs_ids": [],
            "confidence": 0.6,
        }])
        set_active_store(store)
        try:
            app = ev._build_evolve_graph().compile()
            with _patched_llm(calls):
                result = app.invoke(_initial(tmp, ["s1.txt", "s2.txt"]))
        finally:
            set_active_store(prev)
            bank.clear()

        assert result["current_story_index"] == 2, result["current_story_index"]
        assert result["errors"] == [], result["errors"]
        assert calls["pre"] == 2 and calls["obs"] == 2 and calls["matcher"] == 2 and calls["critic"] == 0, calls
        assert len(result["occurrences"]) == 2
        report = result["match_report"]
        assert report["total_obs"] == 2
        assert report["counts"]["MATCH"] == 2 and report["coverage"] == 1.0 and report["novelty_rate"] == 0.0
        assert os.path.exists(os.path.join(tmp, "occurrences.jsonl"))
        assert os.path.exists(os.path.join(tmp, "novelty_pool.jsonl"))
        assert os.path.exists(os.path.join(tmp, "challenge_pool.jsonl"))
        assert os.path.exists(os.path.join(tmp, "match_report.json"))
        # 证据进待应用区（不直写 Registry）
        loaded = RegistryStore(db_path=os.path.join(tmp, "f.db"), namespace="evolve_test").load_all()
        fa = loaded[0]
        assert set(fa["supporting_obs_ids"]) == {"s1_obs_001", "s2_obs_001"}, fa["supporting_obs_ids"]
        assert fa.get("function_id") and fa.get("version_history")
        assert result["pending_evidence"] == [], result["pending_evidence"]  # curator 已应用并清空
        assert os.path.exists(os.path.join(tmp, "pending_evidence.jsonl"))
        assert len(result["curator_plan"]) >= 2, result["curator_plan"]  # 2 条 APPLY_EVIDENCE
        with open(os.path.join(tmp, "match_report.json"), "r", encoding="utf-8") as f:
            mr = json.load(f)
        assert "curator" in mr and mr["curator"]["actions"] >= 2, mr.get("curator")
        # Evaluator_final：终评报告 + 最终 Ontology 快照 + 前后对比
        assert os.path.exists(os.path.join(tmp, "evaluation_final.json"))
        assert os.path.exists(os.path.join(tmp, "functions_evolve_test.jsonl"))
        fr = result["final_report"]
        assert fr["verdict"] in ("PASS", "FAIL")
        assert fr["comparison"]["baseline_count"] == 0 and fr["comparison"]["final_count"] == 1
    print("evolve_app 全流程（逐篇循环 + pending + pools + 报告 + curator）: OK")


def test_evolve_report_novel_and_uncertain(tmp_path):
    """NOVEL/CONFLICT/UNCERTAIN 分流到 pools，报告计数正确。"""
    with tempfile.TemporaryDirectory() as tmp:
        _write_story(tmp, "s1.txt")
        from Agent.app import get_bank
        bank = get_bank()
        bank.clear()
        bank.embedder = FakeEmbedder()
        prev = get_active_store()
        store = RegistryStore(db_path=os.path.join(tmp, "f.db"), namespace="evolve_test")
        store.replace_all([{
            "schema_version": 2,
            "function_name": "RESOURCE_ACQUISITION",
            "definition": "角色获得关键资源或助力",
            "realization_patterns": ["获得资源"],
            "supporting_obs_ids": [],
            "confidence": 0.6,
        }])
        set_active_store(store)

        def fake_matcher(messages):
            return MatchResponse(decisions=[
                MatchDecision(obs_id="s1_obs_001", label="NOVEL", reason="无匹配"),
            ])

        try:
            app = ev._build_evolve_graph().compile()
            with _patched_llm({"pre": 0, "obs": 0, "matcher": 0, "eval": 0, "critic": 0}, matcher_fn=fake_matcher):
                result = app.invoke(_initial(tmp, ["s1.txt"]))
        finally:
            set_active_store(prev)
            bank.clear()
        report = result["match_report"]
        assert report["counts"]["NOVEL"] == 1 and report["novelty_rate"] == 1.0
        with open(os.path.join(tmp, "novelty_pool.jsonl"), "r", encoding="utf-8") as f:
            pool = [json.loads(line) for line in f if line.strip()]
        assert len(pool) == 1 and pool[0]["function_name"] == "OTHER"
    print("evolve NOVEL 分流与报告计数: OK")


def _mid_func():
    return {
        "schema_version": 2,
        "function_name": "RESOURCE_ACQUISITION",
        "definition": "角色获得关键资源或助力",
        "realization_patterns": ["获得资源"],
        "supporting_obs_ids": [],
        "confidence": 0.6,
    }


def test_evolve_mid_triggered(tmp_path, monkeypatch):
    """累计 obs 达阈值触发 Evaluator_mid：体检一次、计数归零、报告落盘、match_report 汇总。"""
    monkeypatch.setattr(ev, "MID_OBS_THRESHOLD", 2)
    calls = {"pre": 0, "obs": 0, "matcher": 0, "eval": 0, "critic": 0}
    with tempfile.TemporaryDirectory() as tmp:
        _write_story(tmp, "s1.txt")
        _write_story(tmp, "s2.txt")
        from Agent.app import get_bank
        bank = get_bank()
        bank.clear()
        bank.embedder = FakeEmbedder()
        prev = get_active_store()
        store = RegistryStore(db_path=os.path.join(tmp, "f.db"), namespace="evolve_test")
        store.replace_all([_mid_func()])
        set_active_store(store)
        try:
            app = ev._build_evolve_graph().compile()
            with _patched_llm(calls):
                result = app.invoke(_initial(tmp, ["s1.txt", "s2.txt"]))
        finally:
            set_active_store(prev)
            bank.clear()
        assert calls["eval"] >= 1, calls
        assert len(result["mid_reports"]) == 1, result["mid_reports"]
        assert result["obs_since_eval"] == 0
        assert os.path.exists(os.path.join(tmp, "evaluation_mid_1.json"))
        mids = result["match_report"]["mid_evaluations"]
        assert len(mids) == 1 and mids[0]["verdict"] in ("PASS", "FAIL")
        assert mids[0]["pending_applied"] == 2, mids[0]  # Evaluator_mid 纳入 pending 评估
        assert "dimensions" in mids[0] and "issue_counts" in mids[0]
    print("evolve Evaluator_mid 触发（2 篇 ≥ 阈值）: OK")


def test_evolve_mid_rollover(tmp_path, monkeypatch):
    """滚动触发：每达阈值体检一次，多轮累积 mid_reports。"""
    monkeypatch.setattr(ev, "MID_OBS_THRESHOLD", 2)
    calls = {"pre": 0, "obs": 0, "matcher": 0, "eval": 0, "critic": 0}
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("s1.txt", "s2.txt", "s3.txt", "s4.txt"):
            _write_story(tmp, name)
        from Agent.app import get_bank
        bank = get_bank()
        bank.clear()
        bank.embedder = FakeEmbedder()
        prev = get_active_store()
        store = RegistryStore(db_path=os.path.join(tmp, "f.db"), namespace="evolve_test")
        store.replace_all([_mid_func()])
        set_active_store(store)
        try:
            app = ev._build_evolve_graph().compile()
            with _patched_llm(calls):
                result = app.invoke(_initial(tmp, ["s1.txt", "s2.txt", "s3.txt", "s4.txt"]))
        finally:
            set_active_store(prev)
            bank.clear()
        assert len(result["mid_reports"]) == 2, result["mid_reports"]
        assert [m["round"] for m in result["mid_reports"]] == [1, 2]
        assert os.path.exists(os.path.join(tmp, "evaluation_mid_2.json"))
    print("evolve Evaluator_mid 滚动触发（4 篇 → 2 次体检）: OK")


def test_evolve_mid_not_triggered(tmp_path, monkeypatch):
    """不足阈值不触发体检。"""
    monkeypatch.setattr(ev, "MID_OBS_THRESHOLD", 10)
    calls = {"pre": 0, "obs": 0, "matcher": 0, "eval": 0, "critic": 0}
    with tempfile.TemporaryDirectory() as tmp:
        _write_story(tmp, "s1.txt")
        _write_story(tmp, "s2.txt")
        from Agent.app import get_bank
        bank = get_bank()
        bank.clear()
        bank.embedder = FakeEmbedder()
        prev = get_active_store()
        store = RegistryStore(db_path=os.path.join(tmp, "f.db"), namespace="evolve_test")
        store.replace_all([_mid_func()])
        set_active_store(store)
        try:
            app = ev._build_evolve_graph().compile()
            with _patched_llm(calls):
                result = app.invoke(_initial(tmp, ["s1.txt", "s2.txt"]))
        finally:
            set_active_store(prev)
            bank.clear()
        assert calls["eval"] == 1, calls  # 仅 Evaluator_final 一次（mid 未触发）
        assert result["mid_reports"] == []
        assert result["match_report"]["mid_evaluations"] == []
        assert not os.path.exists(os.path.join(tmp, "evaluation_mid_1.json"))
    print("evolve Evaluator_mid 不足阈值不触发: OK")


def test_evaluator_final_with_baseline(tmp_path):
    """evaluator_final：六维终评 + 前后对比（基线快照存在 → kept/added 正确）。"""
    calls = {"pre": 0, "obs": 0, "matcher": 0, "eval": 0, "critic": 0}
    with tempfile.TemporaryDirectory() as tmp:
        from Agent.app import get_bank
        bank = get_bank()
        bank.clear()
        bank.embedder = FakeEmbedder()
        prev = get_active_store()
        store = RegistryStore(db_path=os.path.join(tmp, "f.db"), namespace="evolve_test")
        store.replace_all([
            _mid_func(),
            {"schema_version": 2, "function_name": "OLD_FUNC", "definition": "旧函数定义",
             "realization_patterns": ["旧模式"], "supporting_obs_ids": [], "confidence": 0.6},
        ])
        set_active_store(store)
        # 基线快照：只有 OLD_FUNC（模拟演化前）
        with open(os.path.join(tmp, "functions_evolve_test_start.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "schema_version": 2, "function_name": "OLD_FUNC", "definition": "旧函数定义",
                "realization_patterns": ["旧模式"], "supporting_obs_ids": [], "confidence": 0.6,
            }, ensure_ascii=False) + "\n")
        try:
            app = ev._build_evolve_graph().compile()
            with _patched_llm(calls):
                result = app.invoke(_initial(tmp, []))  # 空故事 → 直达 report/curator/final
        finally:
            set_active_store(prev)
            bank.clear()
        fr = result["final_report"]
        cmp = fr["comparison"]
        assert cmp["baseline_count"] == 1 and cmp["final_count"] == 2, cmp
        assert "RESOURCE_ACQUISITION" in cmp["added"] and "OLD_FUNC" in cmp["kept"], cmp
        assert fr["verdict"] in ("PASS", "FAIL")
        assert "confidence" in cmp and "supporting" in cmp
    print("evaluator_final 前后对比（基线存在）: OK")


if __name__ == "__main__":
    test_evolve_flow()
    test_evolve_report_novel_and_uncertain()
    print("evolve 图测试通过")
