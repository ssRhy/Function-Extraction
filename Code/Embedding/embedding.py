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
