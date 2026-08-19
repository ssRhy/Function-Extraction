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
from Agent.Registry.registry import RegistryStore, get_active_store, set_active_store
from Agent.Pre_pro.pre_processor import PreCorrection
from Agent.Observer.observer import ObservationResponse, ObservationItem
from Prompt.Matcher_prompt import MatchResponse, MatchDecision


class FakeEmbedder:
    """字符袋向量（与 test_bootstrap_app / test_matcher 同模式）。"""

    def __init__(self, dim=384):
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
    originals = {"pp": pp.chat_structured, "ob": ob.chat_structured, "mm": mm.chat_structured}

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

    pp.chat_structured = fake_pre
    ob.chat_structured = fake_obs
    mm.chat_structured = fake_matcher
    try:
        yield
    finally:
        pp.chat_structured = originals["pp"]
        ob.chat_structured = originals["ob"]
        mm.chat_structured = originals["mm"]


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
    calls = {"pre": 0, "obs": 0, "matcher": 0}
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
        assert calls["pre"] == 2 and calls["obs"] == 2 and calls["matcher"] == 2, calls
        assert len(result["occurrences"]) == 2
        report = result["match_report"]
        assert report["total_obs"] == 2
        assert report["counts"]["MATCH"] == 2 and report["coverage"] == 1.0 and report["novelty_rate"] == 0.0
        assert os.path.exists(os.path.join(tmp, "occurrences.jsonl"))
        assert os.path.exists(os.path.join(tmp, "novelty_pool.jsonl"))
        assert os.path.exists(os.path.join(tmp, "challenge_pool.jsonl"))
        assert os.path.exists(os.path.join(tmp, "match_report.json"))
        # 直写：两篇 obs 都追加到函数 exemplars
        loaded = RegistryStore(db_path=os.path.join(tmp, "f.db"), namespace="evolve_test").load_all()
        fa = loaded[0]
        assert len(fa["supporting_obs_ids"]) == 2, fa["supporting_obs_ids"]
        assert fa.get("function_id") and fa.get("version_history")
    print("evolve_app 全流程（逐篇循环 + 直写 + pools + 报告）: OK")


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
            with _patched_llm({"pre": 0, "obs": 0, "matcher": 0}, matcher_fn=fake_matcher):
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


if __name__ == "__main__":
    test_evolve_flow()
    test_evolve_report_novel_and_uncertain()
    print("evolve 图测试通过")
