"""bootstrap_app 单图全流程测试：mock LLM + FakeEmbedder，验证 story 循环 / 归纳循环 / 续跑 / 错误跳过 / no-revise。"""

import os
import json
import re
import sys
import tempfile
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from Agent import app as app_module
from Agent.Pre_pro import pre_processor as pp
from Agent.Observer import observer as ob
from Agent.Inducer import inducer as ind
from Agent.Evaluator import evaluator as ev_module
from Agent.Evaluator import revise as rev
from Agent.Contract import contract as fc
from Agent.Pre_pro.pre_processor import PreCorrection
from Agent.Observer.observer import ObservationResponse, ObservationItem
from Agent.Inducer.inducer import InducerResponse, CandidateFunction
from Prompt.Evaluator_prompt import EvaluatorReviewResponse, FunctionQualityReview
from Contracts.function_contract import (
    FunctionContractBody, ObligationEffects, StateCondition, StateEffect,
)


class FakeEmbedder:
    """字符袋向量：共享字符越多余弦越高（模拟语义相似，无真实模型）。
    维度 384 与真实 all-MiniLM-L6-v2 一致（ChromaDB 持久化 collection 维度固定）。"""

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


def _cfg(thread_id):
    return {"configurable": {"thread_id": thread_id}}


def _make_saver(db_path=None):
    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver
    if db_path is None:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
    else:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def _compile_graph(saver, interrupt_before=None):
    from Agent.app import _build_bootstrap_graph
    kwargs = {"interrupt_before": interrupt_before} if interrupt_before else {}
    return _build_bootstrap_graph().compile(checkpointer=saver, **kwargs)


def _write_story(tmp, name, text="角色发现关键线索。角色决定采取新行动。"):
    with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
        f.write(text)


@contextmanager
def _setup_env(tmp):
    """真实 Bank（FakeEmbedder 替换模型）+ 临时 Registry 命名空间；退出时恢复全局活跃 store。"""
    from Agent.app import get_bank
    from Agent.Registry import registry as reg_mod
    from Agent.Registry.registry import RegistryStore, set_active_store
    prev = reg_mod._active_store
    bank = get_bank()
    bank.clear()
    bank.embedder = FakeEmbedder()
    store = RegistryStore(db_path=os.path.join(tmp, "functions.db"), namespace="bootstrap_test")
    store.clear()
    set_active_store(store)
    ind.APPLY_CONFUSABLE = False
    try:
        yield bank, store
    finally:
        set_active_store(prev)
        ind.APPLY_CONFUSABLE = True


def _initial(tmp, story_files, no_revise=True):
    return {
        "messages": [],
        "raw_text": None,
        "story_config": None,
        "normalized_story": None,
        "observations": [],
        "added_obs_ids": [],
        "similar_observations": [],
        "induced_functions": [],
        "evaluation_round": 0,
        "current_story_index": 0,
        "total_stories": len(story_files),
        "story_files": story_files,
        "corpus_dir": tmp,
        "story_meta": {},
        "all_pairs": [],
        "induction_components": [],
        "induction_index": 0,
        "errors": [],
        "no_revise": no_revise,
        "namespace": "test_ns",
        "out_dir": tmp,
        "snapshot_root": os.path.join(tmp, "ontology_snapshots"),
        "ontology_snapshot": None,
        "evaluation_context": {},
    }


@contextmanager
def _patched_llm(calls):
    originals = {
        "pp": pp.chat_structured,
        "ob": ob.chat_structured,
        "ind": ind.chat_structured,
        "ev": ev_module.chat_structured,
        "rev": rev.chat_structured,
        "fc": fc.chat_structured,
        "am": app_module.abstract_merge,
    }

    def fake_pre(messages, schema, **kw):
        calls["pre"] += 1
        return PreCorrection(merges=[], splits=[])

    def fake_obs(messages, schema, **kw):
        calls["obs"] += 1
        return ObservationResponse(observations=[
            ObservationItem(
                before_state="局面保持平静",
                event="角色发现关键线索，改变了对局面的认知，决定采取新行动",
                participants=["角色"],
                after_state="角色掌握了关键信息",
                affected_aspect="认知",
                narrative_effect="推动后续行动",
                surface_form="发现线索",
                source_sentence_indices=[0],
            )
        ])

    def fake_ind(messages, schema, **kw):
        calls["ind"] += 1
        obs_ids = re.findall(r"Obs ID:\s*([^\s]+)", messages[1]["content"])
        return InducerResponse(candidate_functions=[
            CandidateFunction(
                function_name="INFO_REVELATION",
                definition="角色获知关键信息，改变认知或推动行动",
                realization_patterns=["发现线索"],
                hard_negatives=["无关日常"],
                confusable_functions=["角色隐瞒信息"],
                supporting_obs_ids=sorted(set(obs_ids)),
            )
        ])

    def fake_eval(messages, schema, **kw):
        calls["eval"] += 1
        cards = json.loads(messages[1]["content"].split("\n", 1)[1])
        return EvaluatorReviewResponse(reviews=[
            FunctionQualityReview(
                function_name=c["function_name"],
                bidirectional_conflation=False, conflation_reason="",
                genre_surface_binding=False, binding_reason="",
                granularity="ok", recommendation="OK",
            )
            for c in cards
        ])

    def fake_rev(messages, schema, **kw):
        calls["rev"] += 1
        raise AssertionError("no_revise 模式下 revise 不应被调用")

    def fake_contract(messages, schema, **kw):
        calls["contract"] += 1
        return FunctionContractBody(
            role_slots=["行动者"],
            preconditions=[StateCondition(
                role_slots=["行动者"], aspect="KNOWLEDGE", state="UNKNOWN",
            )],
            effects=[StateEffect(
                role_slots=["行动者"], aspect="KNOWLEDGE", before="UNKNOWN", after="KNOWN",
            )],
            obligation_effects=ObligationEffects(),
        )

    pp.chat_structured = fake_pre
    ob.chat_structured = fake_obs
    ind.chat_structured = fake_ind
    ev_module.chat_structured = fake_eval
    rev.chat_structured = fake_rev
    fc.chat_structured = fake_contract
    app_module.abstract_merge = lambda funcs, bank: funcs
    try:
        yield
    finally:
        pp.chat_structured = originals["pp"]
        ob.chat_structured = originals["ob"]
        ind.chat_structured = originals["ind"]
        ev_module.chat_structured = originals["ev"]
        rev.chat_structured = originals["rev"]
        fc.chat_structured = originals["fc"]
        app_module.abstract_merge = originals["am"]


def _calls():
    return {"pre": 0, "obs": 0, "ind": 0, "eval": 0, "rev": 0, "contract": 0}


def test_full_flow_no_revise():
    """全链路：两篇跨故事 obs → 相似对 → 归纳 → 评估(final_review) → 导出；no_revise 跳过 revise。"""
    calls = _calls()
    with tempfile.TemporaryDirectory() as tmp:
        _write_story(tmp, "s1.txt")
        _write_story(tmp, "s2.txt")
        with _setup_env(tmp):
            app = _compile_graph(_make_saver())
            with _patched_llm(calls):
                result = app.invoke(_initial(tmp, ["s1.txt", "s2.txt"]), config=_cfg("t-full"))
        assert result["current_story_index"] == 2, result["current_story_index"]
        assert result["errors"] == [], result["errors"]
        assert len(result["all_pairs"]) >= 1, result["all_pairs"]
        assert calls["obs"] == 2, calls
        assert calls["ind"] >= 1, calls
        assert calls["eval"] >= 1 and calls["rev"] == 0, calls
        assert result["evaluation_round"] == 0, result
        assert result["evaluator_decision"] in ("PASS", "FAIL"), result
        assert os.path.exists(os.path.join(tmp, "functions_test_ns.jsonl"))
        assert os.path.exists(os.path.join(tmp, "bank_test_ns.jsonl"))
        assert os.path.exists(os.path.join(tmp, "evaluation_final.json"))
        if result["evaluator_decision"] == "PASS":
            assert result["ontology_snapshot"]
    print("bootstrap_app 全流程（story 循环 + 归纳 + 评估 + 导出，no_revise）: OK")


def test_resume_from_checkpoint():
    """checkpoint 持久化：interrupt 后新实例同 DB 续跑完成。"""
    calls = _calls()
    with tempfile.TemporaryDirectory() as tmp:
        _write_story(tmp, "s1.txt")
        _write_story(tmp, "s2.txt")
        with _setup_env(tmp):
            cpt_db = os.path.join(tmp, "cpt.sqlite3")
            app1 = _compile_graph(_make_saver(cpt_db), interrupt_before=["cluster"])
            try:
                with _patched_llm(calls):
                    partial = app1.invoke(_initial(tmp, ["s1.txt", "s2.txt"]), config=_cfg("t-resume"))
                assert partial["current_story_index"] == 2, partial["current_story_index"]
                assert "cluster" in app1.get_state(_cfg("t-resume")).next
                # 模拟重启：新编译实例 + 同一 checkpoint 文件
                app2 = _compile_graph(_make_saver(cpt_db))
                with _patched_llm(calls):
                    result = app2.invoke({}, config=_cfg("t-resume"))
            finally:
                app1.checkpointer.conn.close()
                if "app2" in dir():
                    app2.checkpointer.conn.close()
        assert result["current_story_index"] == 2, result["current_story_index"]
        assert result["evaluator_decision"] in ("PASS", "FAIL"), result
        assert calls["ind"] >= 1, calls
        assert os.path.exists(os.path.join(tmp, "functions_test_ns.jsonl"))
    print("bootstrap_app checkpoint 续跑（同 DB 新实例 resume）: OK")


def test_error_story_skipped():
    """单篇失败记 errors 不中断，其余故事正常处理。"""
    calls = _calls()
    with tempfile.TemporaryDirectory() as tmp:
        _write_story(tmp, "s1.txt")
        _write_story(tmp, "s2.txt")  # 与 fake 候选 supporting（s1/s2）对齐，确保归纳出函数
        with _setup_env(tmp):
            app = _compile_graph(_make_saver())
            with _patched_llm(calls):
                result = app.invoke(
                    _initial(tmp, ["s1.txt", "missing.txt", "s2.txt"]),
                    config=_cfg("t-err"),
                )
        assert result["current_story_index"] == 3, result["current_story_index"]
        assert len(result["errors"]) == 1 and "missing.txt" in result["errors"][0], result["errors"]
        assert calls["obs"] == 2, calls  # 两篇有效故事各提取一次
        assert os.path.exists(os.path.join(tmp, "functions_test_ns.jsonl"))
    print("bootstrap_app 单篇失败跳过（errors 记录，不中断）: OK")


def test_empty_story_list_goes_straight_to_evaluator():
    """空 story 列表（无提取）→ 直接进入评估修订闭环（供纯评估/闭环复用）。"""
    calls = _calls()
    with tempfile.TemporaryDirectory() as tmp:
        with _setup_env(tmp):
            app = _compile_graph(_make_saver())
            with _patched_llm(calls):
                result = app.invoke(
                    {
                        "messages": [],
                        "evaluation_round": 0,
                        "no_revise": True,
                        "namespace": "test_ns",
                        "out_dir": tmp,
                        "snapshot_root": os.path.join(tmp, "ontology_snapshots"),
                        "ontology_snapshot": None,
                        "evaluation_context": {},
                    },
                    config=_cfg("t-empty"),
                )
        assert result.get("current_story_index", 0) == 0, result
        assert calls["obs"] == 0 and calls["ind"] == 0, calls
        assert result["evaluator_decision"] == "FAIL", result  # Registry 为空
        assert result.get("discarded") is True, result  # no_revise + FAIL → 舍弃
        assert not os.path.exists(os.path.join(tmp, "functions_test_ns.jsonl"))
    print("bootstrap_app 空 story 列表直达评估（FAIL → 舍弃、不导出）: OK")


def test_export_rechecks_abstract_merged_registry(monkeypatch, tmp_path):
    """abstract_merge 后必须重评最终 Registry，PASS 才发布该集合。"""
    from Agent.Registry import registry as reg_mod
    from Agent.Registry.registry import RegistryStore, set_active_store
    from Contracts.snapshot import load_occurrences, load_snapshot

    prev = reg_mod._active_store
    store = RegistryStore(db_path=str(tmp_path / "functions.db"), namespace="test_ns")
    store.replace_all([{
        "function_id": "F_ORIGINAL",
        "function_name": "ORIGINAL",
        "definition": "原始定义",
        "supporting_obs_ids": ["story_1_obs_001"],
        "confidence": 0.8,
    }])
    set_active_store(store)
    evaluated = []

    def fake_merge(functions, _bank):
        merged = dict(functions[0])
        merged["function_name"] = "MERGED"
        merged["definition"] = "归并后的定义"
        return [merged]

    def fake_evaluator(_state):
        evaluated.append([f["function_name"] for f in store.load_all()])
        report = {"verdict": "PASS", "passed_dimensions": ["coverage"]}
        return {"evaluation_report": report, "evaluator_decision": "PASS"}

    monkeypatch.setattr(app_module, "abstract_merge", fake_merge)
    monkeypatch.setattr(app_module, "evaluator_node", fake_evaluator)
    def fake_contracts(functions, _observations, _out_dir):
        from Contracts.function_contract import definition_sha256
        function = functions[0]
        return [{
            "function_id": function["function_id"],
            "function_name": function["function_name"],
            "definition_sha256": definition_sha256(function),
            "evidence_refs": ["story_1_obs_001"],
            "role_slots": ["行动者"],
            "preconditions": [{"role_slots": ["行动者"], "aspect": "STATE", "state": "BEFORE"}],
            "effects": [{
                "role_slots": ["行动者"], "aspect": "STATE", "before": "BEFORE", "after": "AFTER",
            }],
            "obligation_effects": {"opens": [], "advances": [], "resolves": []},
        }]
    monkeypatch.setattr(app_module, "build_function_contracts", fake_contracts)
    observation = {
        "obs_id": "story_1_obs_001",
        "story_id": "story_1",
        "event": "事件",
        "before_state": "之前",
        "after_state": "之后",
    }
    monkeypatch.setattr(app_module, "get_bank", lambda: type("Bank", (), {"get_all": lambda _self: [observation]})())
    try:
        result = app_module.export_node({
            "namespace": "test_ns",
            "out_dir": str(tmp_path),
            "snapshot_root": str(tmp_path / "snapshots"),
            "evaluation_report": {},
            "total_stories": 1,
        })
    finally:
        set_active_store(prev)

    assert evaluated == [["MERGED"]]
    assert result["ontology_snapshot"]
    from Contracts.snapshot import load_function_contracts
    manifest, functions, _evaluation = load_snapshot(result["ontology_snapshot"])
    assert manifest["schema_version"] == 4
    assert [f["function_name"] for f in functions] == ["MERGED"]
    occurrences = load_occurrences(result["ontology_snapshot"])
    assert occurrences[0]["function_id"] == functions[0]["function_id"]
    assert occurrences[0]["function_name"] == "MERGED"
    assert load_function_contracts(result["ontology_snapshot"])[0]["function_name"] == "MERGED"


def test_export_final_fail_keeps_work_files_without_snapshot(monkeypatch, tmp_path):
    """合并后终评 FAIL 仍保留工作产物，但不得发布。"""
    from Agent.Registry import registry as reg_mod
    from Agent.Registry.registry import RegistryStore, set_active_store

    prev = reg_mod._active_store
    store = RegistryStore(db_path=str(tmp_path / "functions.db"), namespace="test_ns")
    store.replace_all([{
        "function_id": "F_ORIGINAL",
        "function_name": "ORIGINAL",
        "definition": "原始定义",
        "supporting_obs_ids": [],
        "confidence": 0.8,
    }])
    set_active_store(store)
    monkeypatch.setattr(app_module, "abstract_merge", lambda functions, _bank: functions)

    def fake_evaluator(state):
        report = {"verdict": "FAIL"}
        with open(state["evaluation_context"]["report_path"], "w", encoding="utf-8") as f:
            json.dump(report, f)
        return {"evaluation_report": report, "evaluator_decision": "FAIL"}

    monkeypatch.setattr(app_module, "evaluator_node", fake_evaluator)
    try:
        result = app_module.export_node({
            "namespace": "test_ns",
            "out_dir": str(tmp_path),
            "snapshot_root": str(tmp_path / "snapshots"),
            "evaluation_report": {},
            "total_stories": 1,
        })
    finally:
        set_active_store(prev)

    assert os.path.exists(tmp_path / "functions_test_ns.jsonl")
    assert os.path.exists(tmp_path / "evaluation_final.json")
    assert result["ontology_snapshot"] is None
    assert not os.path.exists(tmp_path / "snapshots")


if __name__ == "__main__":
    test_full_flow_no_revise()
    test_resume_from_checkpoint()
    test_error_story_skipped()
    test_empty_story_list_goes_straight_to_evaluator()
    print("\n全部 bootstrap_app 测试通过")
