"""
Confidence Calculator - 多因子加权置信度计算
用可量化指标替代 LLM 主观判断
"""

import json
import os
import numpy as np

from Embedding.embedding import Embedder
from Bank.bank import ObservationBank

# 权重配置
W_DIVERSITY = 0.3       # cross_story_diversity
W_COHERENCE = 0.3       # semantic_coherence
W_SURFACE = 0.2        # surface_diversity
W_CONFUSABLE = 0.2      # confusability_penalty

def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """计算余弦相似度"""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


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


def _compute_semantic_coherence(obs_cluster: list[dict], embedder: Embedder) -> float:
    """
    因子2: semantic_coherence
    obs cluster 内 pairwise similarity 均值
    衡量归纳的 Function 是否语义一致
    """
    if len(obs_cluster) < 2:
        return 0.0

    texts = [
        f"{o.get('before_state', '')} | {o.get('event', '')} | {o.get('after_state', '')}"
        for o in obs_cluster
    ]
    embeddings = embedder.encode(texts)

    n = len(embeddings)
    similarities = []
    for i in range(n):
        for j in range(i + 1, n):
            sim = _cosine_similarity(embeddings[i], embeddings[j])
            similarities.append(sim)

    return float(np.mean(similarities)) if similarities else 0.0


def _compute_surface_diversity(obs_cluster: list[dict]) -> float:
    """
    因子3: surface_diversity
    surface_form 跨领域变体数归一化
    衡量表面实现是否来自不同领域（如仙侠/都市/现实）
    """
    if not obs_cluster:
        return 0.0

    surface_forms = [o.get("surface_form", "") for o in obs_cluster if o.get("surface_form")]
    if not surface_forms:
        return 0.0

    # 简单策略：不同 surface_form 的去重数量
    unique_forms = set(surface_forms)
    # 归一化：至少有 3 种不同形式才能得满分
    return min(len(unique_forms) / 3.0, 1.0)


def _load_existing_functions() -> list[dict]:
    """加载已有 Functions"""
    registry_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "registry", "functions.jsonl"
    )
    if not os.path.exists(registry_path):
        return []

    functions = []
    with open(registry_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    functions.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return functions


def _compute_confusability_penalty(
    candidate_def: str,
    embedder: Embedder
) -> float:
    """
    因子4: confusability_penalty
    与已有 Function definition 的最大相似度
    返回惩罚值（越高表示越容易与已有 Function 混淆）
    """
    existing = _load_existing_functions()
    if not existing or not candidate_def:
        return 0.0

    candidate_emb = embedder.encode_single(candidate_def)
    max_similarity = 0.0

    for func in existing:
        existing_def = func.get("definition", "")
        if not existing_def:
            continue
        existing_emb = embedder.encode_single(existing_def)
        sim = _cosine_similarity(candidate_emb, existing_emb)
        max_similarity = max(max_similarity, sim)

    return max_similarity


def calculate_confidence_detailed(
    supporting_obs_ids: list[str],
    candidate_def: str,
    bank: ObservationBank,
    obs_cluster: list[dict],
) -> dict:
    """
    带详细因子的置信度计算（用于调试和分析）
    """
    embedder = bank.embedder
    diversity = _compute_cross_story_diversity(supporting_obs_ids, bank)
    coherence = _compute_semantic_coherence(obs_cluster, embedder)
    surface = _compute_surface_diversity(obs_cluster)
    confusable = _compute_confusability_penalty(candidate_def, embedder)
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
