"""abstract_merge 全量抽象归并测试：识别近义组 + 复用 _llm_merge 重新归纳统一函数。"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from Agent.Evaluator import abstract_merge as am
from Agent.Evaluator import revise as revise_module
from Agent.Evaluator.abstract_merge import MAX_MERGE_OBS
from Prompt.Abstract_merge_prompt import AbstractMergeResponse


def _func(name, supporting, definition="角色获得关键资源或信息"):
    return {
        "schema_version": 2, "function_name": name, "definition": definition,
        "realization_patterns": ["发现线索"], "hard_negatives": [], "confusable_functions": [],
        "supporting_obs_ids": supporting,
    }


def _obs(oid, sid="s1"):
    return {"obs_id": oid, "story_id": sid, "before_state": "x", "event": "x", "after_state": "x",
            "affected_aspect": "x", "narrative_effect": "x", "surface_form": "x"}


class _FakeEmbedder:
    def encode(self, texts):
        return np.zeros((len(texts), 8))

    def encode_single(self, text):
        return np.zeros(8)

    def encode_observation(self, obs):
        return np.zeros(8)

    def encode_observations(self, observations):
        return np.zeros((len(observations), 8))


class _FakeBank:
    def __init__(self, obs_by_id):
        self.embedder = _FakeEmbedder()
        self._m = obs_by_id

    def get(self, oid):
        return self._m.get(oid)

    def get_all(self):
        return list(self._m.values())


def _patch(fake_id, fake_merge):
    """同时 patch 识别调用（chat_structured）与合并调用（revise._llm_merge）。"""
    orig_id = am.chat_structured
    orig_merge = revise_module._llm_merge
    am.chat_structured = fake_id
    revise_module._llm_merge = fake_merge
    return orig_id, orig_merge


def _fake_merge(name):
    def fake(members, obs_by_id):
        merged = {
            "function_name": name, "definition": "d", "realization_patterns": ["x"],
            "hard_negatives": [], "confusable_functions": [],
            "supporting_obs_ids": [oid for m in members for oid in m.get("supporting_obs_ids", [])],
        }
        return merged, None
    return fake


def test_merge_one_group():
    funcs = [_func("F_A", ["a1", "a2"]), _func("F_B", ["b1", "b2"]), _func("F_C", ["c1"])]
    bank = _FakeBank({oid: _obs(oid) for oid in ["a1", "a2", "b1", "b2", "c1"]})
    fake_id = lambda messages, schema, **kw: AbstractMergeResponse(merge_groups=[["F_A", "F_B"]])
    orig_id, orig_merge = _patch(fake_id, _fake_merge("F_AB"))
    try:
        out = am.abstract_merge(funcs, bank)
    finally:
        am.chat_structured, revise_module._llm_merge = orig_id, orig_merge
    names = {f["function_name"] for f in out}
    assert names == {"F_AB", "F_C"}, names
    ab = next(f for f in out if f["function_name"] == "F_AB")
    assert ab["supporting_obs_ids"] == ["a1", "a2", "b1", "b2"], ab["supporting_obs_ids"]
    assert 0.0 <= ab.get("confidence", -1) <= 1.0 and "confidence_factors" in ab, ab
    print("归并 1 组（_llm_merge 新函数 + supporting 并集 + confidence 重算）: OK")


def test_merge_failure_keeps_group():
    funcs = [_func("F_A", ["a1"]), _func("F_B", ["b1"])]
    fake_id = lambda messages, schema, **kw: AbstractMergeResponse(merge_groups=[["F_A", "F_B"]])
    fake_merge = lambda members, obs_by_id: (None, "方向相反，拒绝合并")
    orig_id, orig_merge = _patch(fake_id, fake_merge)
    try:
        out = am.abstract_merge(funcs, _FakeBank({}))
    finally:
        am.chat_structured, revise_module._llm_merge = orig_id, orig_merge
    assert {f["function_name"] for f in out} == {"F_A", "F_B"}, out
    print("合并失败（None）→ 该组保持原样: OK")


def test_filter_invalid_and_overlap():
    funcs = [_func("F_A", ["a1"]), _func("F_B", ["b1"]), _func("F_C", ["c1"])]

    def fake_id(messages, schema, **kw):
        return AbstractMergeResponse(merge_groups=[
            ["F_A", "F_MISSING"],
            ["F_B", "F_C"],
            ["F_B", "F_C"],
        ])

    orig_id, orig_merge = _patch(fake_id, _fake_merge("G2"))
    try:
        out = am.abstract_merge(funcs, _FakeBank({}))
    finally:
        am.chat_structured, revise_module._llm_merge = orig_id, orig_merge
    names = {f["function_name"] for f in out}
    assert names == {"F_A", "G2"}, names  # 非法组跳过；重叠组不重复消费
    print("非法/重叠组过滤: OK")


def test_merged_name_collision():
    funcs = [_func("F_A", ["a1"]), _func("F_B", ["b1"]), _func("G", ["c1"])]
    fake_id = lambda messages, schema, **kw: AbstractMergeResponse(merge_groups=[["F_A", "F_B"]])
    orig_id, orig_merge = _patch(fake_id, _fake_merge("G"))
    try:
        out = am.abstract_merge(funcs, _FakeBank({}))
    finally:
        am.chat_structured, revise_module._llm_merge = orig_id, orig_merge
    names = {f["function_name"] for f in out}
    assert "G" in names and "G_2" in names, names
    print("新函数与存量重名加 _N 后缀: OK")


def test_identification_failure_noop():
    funcs = [_func("F_A", ["a1"]), _func("F_B", ["b1"])]

    def fake_id(messages, schema, **kw):
        raise ValueError("识别失败")

    orig_id, orig_merge = _patch(fake_id, _fake_merge("F_AB"))
    try:
        out = am.abstract_merge(funcs, _FakeBank({}))
    finally:
        am.chat_structured, revise_module._llm_merge = orig_id, orig_merge
    assert out == funcs, out
    print("识别失败 → 原样返回（不阻塞导出）: OK")


def test_single_function_skips_llm():
    funcs = [_func("F_A", ["a1"])]
    called = []

    def fake_id(messages, schema, **kw):
        called.append(1)
        return AbstractMergeResponse(merge_groups=[])

    orig_id, orig_merge = _patch(fake_id, _fake_merge("X"))
    try:
        out = am.abstract_merge(funcs, _FakeBank({}))
    finally:
        am.chat_structured, revise_module._llm_merge = orig_id, orig_merge
    assert out == funcs and not called
    print("少于 2 个函数不调用 LLM: OK")


def test_over_limit_group_skipped():
    """supporting 并集超过 MAX_MERGE_OBS 的组被跳过（不合并、不调 _llm_merge）。"""
    funcs = [
        _func("F_BIG1", [f"b1_o{i}" for i in range(12)]),
        _func("F_BIG2", [f"b2_o{i}" for i in range(12)]),
    ]
    merge_calls = []

    def fake_id(messages, schema, **kw):
        return AbstractMergeResponse(merge_groups=[["F_BIG1", "F_BIG2"]])

    def fake_merge(members, obs_by_id):
        merge_calls.append(1)
        return _fake_merge("F_BIG")(members, obs_by_id)

    orig_id, orig_merge = _patch(fake_id, fake_merge)
    try:
        out = am.abstract_merge(funcs, _FakeBank({}))
    finally:
        am.chat_structured, revise_module._llm_merge = orig_id, orig_merge
    assert {f["function_name"] for f in out} == {"F_BIG1", "F_BIG2"}, out
    assert merge_calls == [], merge_calls  # 超上限组不调合并
    print(f"超过粒度上限（{MAX_MERGE_OBS} obs）的组被跳过: OK")


if __name__ == "__main__":
    test_merge_one_group()
    test_merge_failure_keeps_group()
    test_filter_invalid_and_overlap()
    test_merged_name_collision()
    test_identification_failure_noop()
    test_single_function_skips_llm()
    test_over_limit_group_skipped()
    print("\n全部 abstract_merge 测试通过")
