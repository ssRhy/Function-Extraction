"""结构化 Observation embedding 与语义化 surface_diversity 测试。"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from FunctionExtract_Agent.Embedding.embedding import Embedder
from FunctionExtract_Agent.Inducer.confidence import _compute_surface_diversity, calculate_confidence_detailed


class _VecEmbedder:
    """可控向量 embedder：按文本返回预设向量（测聚类逻辑，不加载模型）。"""

    def __init__(self, vec_of):
        self._v = vec_of

    def encode(self, texts):
        return np.array([self._v[t] for t in texts])

    def encode_single(self, text):
        return self._v[text]


def _unit(vec):
    n = np.linalg.norm(vec)
    return vec / n if n else vec


def test_surface_diversity_semantic():
    """同义改写算 1 个模式，不同模式才累计（替换精确字符串去重）。"""
    a = _unit(np.array([1.0, 0.0]))
    a2 = _unit(np.array([0.99, 0.01]))  # 与 a 近同义
    b = _unit(np.array([0.0, 1.0]))     # 不同模式
    emb = _VecEmbedder({"比武获胜": a, "斗法获胜": a2, "背叛密谋": b})
    obs = lambda sf: {"surface_form": sf}
    same = _compute_surface_diversity([obs("比武获胜"), obs("斗法获胜")], emb)
    diff = _compute_surface_diversity([obs("比武获胜"), obs("背叛密谋")], emb)
    assert same == 1 / 3, same  # 同义 → 1 个模式
    assert diff == 2 / 3, diff  # 不同 → 2 个模式
    print("surface_diversity 语义去重: OK")


def test_encode_observation():
    emb = Embedder()
    o = {"before_state": "对手低估", "event": "公开战胜强者", "after_state": "对手认清实力",
         "affected_aspect": "能力认知", "narrative_effect": "声望改变", "surface_form": "比武获胜"}
    v = emb.encode_observation(o)
    assert v.shape == (emb.dimension,) and abs(np.linalg.norm(v) - 1.0) < 1e-4
    assert np.all(emb.encode_observation({}) == 0)          # 全空 → 零向量
    only = emb.encode_observation({"event": "公开战胜强者"})
    ev = emb.encode_single("公开战胜强者")
    assert np.allclose(only, ev / np.linalg.norm(ev), atol=1e-4)  # 单字段与 encode_single 等价
    print("encode_observation（维度/归一化/空字段/单字段等价）: OK")


class _FakeBank:
    def __init__(self, embedder, obs_by_id):
        self.embedder = embedder
        self._m = obs_by_id

    def get(self, oid):
        return self._m.get(oid)


def _obs(sid, oid, text="角色获得关键信息并改变认知"):
    return {"obs_id": oid, "story_id": sid, "before_state": text, "event": text,
            "after_state": text, "affected_aspect": "认知", "narrative_effect": "推动行动",
            "surface_form": "发现线索"}


def test_confidence_recalc_structured():
    emb = Embedder()
    bank = _FakeBank(emb, {"a1": _obs("s1", "a1"), "b1": _obs("s2", "b1"), "c1": _obs("s3", "c1")})
    detail = calculate_confidence_detailed(["a1", "b1", "c1"], "角色获知关键信息并行动",
                                           bank, apply_confusable=False)
    assert 0.0 <= detail["confidence"] <= 1.0
    assert detail["factors"]["semantic_coherence"] >= 0.0
    assert detail["factors"]["surface_diversity"] >= 0.0
    print("confidence 结构化重算（coherence/surface 有效）: OK")


if __name__ == "__main__":
    test_surface_diversity_semantic()
    test_encode_observation()
    test_confidence_recalc_structured()
    print("\n全部 embedding 结构化测试通过")
