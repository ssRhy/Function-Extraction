"""
Confidence Calculator - 多因子加权置信度计算
用可量化指标替代 LLM 主观判断
"""

import numpy as np

from Embedding.embedding import Embedder
from Bank.bank import ObservationBank
from Agent.Registry.registry import get_active_store

# 权重配置
W_DIVERSITY = 0.3       # cross_story_diversity
W_COHERENCE = 0.3       # semantic_coherence
W_SURFACE = 0.2        # surface_diversity
W_CONFUSABLE = 0.2      # confusability_penalty

# 近义判定阈值（definition embedding 余弦相似度）
NEAR_DUP_THRESHOLD = 0.85


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """计算余弦相似度"""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def load_registry_functions() -> list[dict]:
    """加载当前活跃 Registry（SQLite）中的 Functions"""
    return get_active_store().load_all()


def max_definition_similarity(
    candidate_def: str,
    existing_functions: list[dict],
    embedder: Embedder,
) -> float:
    """候选 definition 与已有 Functions definition 的最大余弦相似度"""
    if not existing_functions or not candidate_def:
        return 0.0
    candidate_emb = embedder.encode_single(candidate_def)
    max_sim = 0.0
    for func in existing_functions:
        existing_def = func.get("definition", "")
        if not existing_def:
            continue
        sim = _cosine_similarity(candidate_emb, embedder.encode_single(existing_def))
        max_sim = max(max_sim, sim)
    return float(max_sim)


def _load_supporting_obs(supporting_obs_ids: list[str], bank: ObservationBank) -> list[dict]:
    """从 Bank 取回 supporting obs 的实际记录（跳过不存在的 id）"""
    return [obs for obs in (bank.get(oid) for oid in supporting_obs_ids) if obs]


def _compute_cross_story_diversity(supporting_obs_ids: list[str], bank: ObservationBank) -> float:
    """
    因子1: cross_story_diversity
    不同 story_id 数 / supporting_obs_ids 长度
    越高表示跨故事证据越强
    """
    if not supporting_obs_ids:
        return 0.0
    story_ids = set()
    for oid in supporting_obs_ids:
        obs = bank.get(oid)
        if obs:
            story_ids.add(obs.get("story_id", ""))
    return len(story_ids) / len(supporting_obs_ids)


def _compute_semantic_coherence(supporting_obs: list[dict], embedder: Embedder) -> float:
    """
    因子2: semantic_coherence
    supporting obs 内 pairwise similarity 均值
    衡量归纳的 Function 是否语义一致
    """
    if len(supporting_obs) < 2:
        return 0.0
    texts = [
        f"{o.get('before_state', '')} | {o.get('event', '')} | {o.get('after_state', '')}"
        for o in supporting_obs
    ]
    embeddings = embedder.encode(texts)
    n = len(embeddings)
    similarities = []
    for i in range(n):
        for j in range(i + 1, n):
            similarities.append(_cosine_similarity(embeddings[i], embeddings[j]))
    return float(np.mean(similarities)) if similarities else 0.0


def _compute_surface_diversity(supporting_obs: list[dict]) -> float:
    """
    因子3: surface_diversity
    supporting obs 的 surface_form 跨领域变体数归一化
    """
    if not supporting_obs:
        return 0.0
    surface_forms = [o.get("surface_form", "") for o in supporting_obs if o.get("surface_form")]
    if not surface_forms:
        return 0.0
    unique_forms = set(surface_forms)
    return min(len(unique_forms) / 3.0, 1.0)


def calculate_confidence_detailed(
    supporting_obs_ids: list[str],
    candidate_def: str,
    bank: ObservationBank,
    apply_confusable: bool = True,
) -> dict:
    """
    带详细因子的置信度计算（coherence/surface 基于 supporting obs，与 diversity 同口径）。

    apply_confusable=False 时豁免与已有 Registry 的软惩罚
    （bootstrap 阶段使用，近义由 Registry 硬去重处理）。
    """
    embedder = bank.embedder
    supporting_obs = _load_supporting_obs(supporting_obs_ids, bank)
    diversity = _compute_cross_story_diversity(supporting_obs_ids, bank)
    coherence = _compute_semantic_coherence(supporting_obs, embedder)
    surface = _compute_surface_diversity(supporting_obs)
    if apply_confusable:
        confusable = max_definition_similarity(candidate_def, load_registry_functions(), embedder)
    else:
        confusable = 0.0
    confidence = max(0.0, min(1.0, (
        W_DIVERSITY * diversity +
        W_COHERENCE * coherence +
        W_SURFACE * surface -
        W_CONFUSABLE * confusable
    )))
    return {
        "confidence": confidence,
        "factors": {
            "cross_story_diversity": round(diversity, 3),
            "semantic_coherence": round(coherence, 3),
            "surface_diversity": round(surface, 3),
            "confusability_penalty": round(confusable, 3),
        },
        "weights": {
            "cross_story_diversity": W_DIVERSITY,
            "semantic_coherence": W_COHERENCE,
            "surface_diversity": W_SURFACE,
            "confusability_penalty": W_CONFUSABLE,
        }
    }