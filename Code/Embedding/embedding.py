"""
Embedding 模块 - 统一管理 embedding 模型
使用 sentence-transformers + hf-mirror 镜像
"""

import os
import time
import numpy as np

# 必须最先设置，强制离线读缓存
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ.pop("HF_ENDPOINT", None)  # 清除可能冲突的镜像设置

from sentence_transformers import SentenceTransformer


# 结构化 Observation 字段权重：核心结构字段高、表层字段低（可调）
OBS_FIELD_WEIGHTS = [
    ("before_state", 1.0),
    ("event", 1.5),
    ("after_state", 1.5),
    ("affected_aspect", 0.8),
    ("narrative_effect", 1.0),
    ("surface_form", 0.6),
]


class Embedder:
    """
    统一 embedding 接口，封装 sentence-transformers。
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: str = "cpu",
    ):
        self.model_name = model_name
        self.device = device
        self.model = self._load_with_retry(max_retries=5, base_delay=3)
        self._dim = self.model.get_embedding_dimension()

    def _load_with_retry(self, max_retries=5, base_delay=3):
        """带重试的模型加载，强制读本地缓存"""
        os.environ["HF_HUB_OFFLINE"] = "1"
        for attempt in range(max_retries):
            try:
                return SentenceTransformer(self.model_name, device=self.device)
            except Exception as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    print(f"[Embedding] 加载失败 (尝试 {attempt+1}/{max_retries}): {e}")
                    print(f"[Embedding] {delay}s 后重试...")
                    time.sleep(delay)
                else:
                    raise RuntimeError(f"Embedding 模型加载失败 ({max_retries} 次尝试): {e}") from e

    @property
    def dimension(self) -> int:
        """返回向量维度"""
        return self._dim

    def encode(self, texts: list[str]) -> np.ndarray:
        """
        批量编码。

        Args:
            texts: 文本列表

        Returns:
            np.ndarray, shape (n, dimension)
        """
        return self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

    def encode_single(self, text: str) -> np.ndarray:
        """
        单条编码。

        Args:
            text: 单条文本

        Returns:
            np.ndarray, shape (dimension,)
        """
        return self.model.encode([text], convert_to_numpy=True, show_progress_bar=False)[0]

    def encode_observation(self, obs: dict) -> np.ndarray:
        """结构化 Observation 编码：逐字段编码 + 加权平均（L2 归一化）。

        空字段跳过；全空返回零向量。比"拼串再编码"更尊重字段语义权重。
        """
        vecs, weights = [], []
        for field, weight in OBS_FIELD_WEIGHTS:
            text = (obs or {}).get(field, "")
            if text and text.strip():
                vecs.append(self.encode_single(text))
                weights.append(weight)
        if not vecs:
            return np.zeros(self._dim)
        pooled = np.average(np.array(vecs), axis=0, weights=np.array(weights))
        norm = np.linalg.norm(pooled)
        return pooled / norm if norm > 0 else pooled

    def encode_observations(self, observations: list[dict]) -> np.ndarray:
        """批量结构化编码（供 bank.add / evaluator 全量用）。"""
        if not observations:
            return np.zeros((0, self._dim))
        return np.array([self.encode_observation(o) for o in observations])
