"""
Observation Bank - 持久化存储 + 向量检索
使用 ChromaDB 存储向量 + JSONL 存储完整数据
"""

import os
import json
from typing import Optional
import chromadb

from Embedding.embedding import Embedder


def _observation_to_text(obs: dict) -> str:
    """
    将 Observation 字典转换为用于 embedding 的文本。

    策略：拼接结构化字段，减少表层词汇（如"修为""灵气"）对语义的干扰。
    """
    fields = [
        obs.get("before_state", ""),
        obs.get("event", ""),
        obs.get("after_state", ""),
        obs.get("affected_aspect", ""),
        obs.get("narrative_effect", ""),
        obs.get("surface_form", ""),
    ]
    return " | ".join(f for f in fields if f)


class ObservationBank:
    """
    Observation 持久化存储模块。

    - ChromaDB: 向量索引，支持相似度检索
    - JSONL: 完整数据备份，支持精确查询

    目录结构:
        persist_dir/
            observations.jsonl   # 完整数据
            chroma_db/          # ChromaDB 向量索引
    """

    COLLECTION_NAME = "observations"

    def __init__(self, persist_dir: str = "Bank/data"):
        self.persist_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), persist_dir)
        self.jsonl_path = os.path.join(self.persist_dir, "observations.jsonl")
        self.chroma_dir = os.path.join(self.persist_dir, "chroma_db")

        os.makedirs(self.persist_dir, exist_ok=True)
        self._records_by_id = self._read_jsonl_index()

        self.embedder = Embedder()

        self._chroma_client = chromadb.PersistentClient(path=self.chroma_dir)
        self.collection = self._chroma_client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )

        # 清理不在 sqlite 索引里的孤儿 UUID 目录（防御性，避免启动时
        # PersistentClient 扫描到 "Collection [uuid] does not exist" 报错）
        self._prune_orphan_collections()

    def _prune_orphan_collections(self):
        """删除 chroma_db 目录里未被 sqlite 索引的孤儿 UUID 目录。
        ChromaDB 偶尔会留下未清理的物理目录，PersistentClient 启动时扫描
        到它们会抛 'Collection [uuid] does not exist'。"""
        import uuid as _uuid
        valid_ids = set()
        try:
            for c in self._chroma_client.list_collections():
                cid = getattr(c, "id", None)
                if cid:
                    valid_ids.add(str(cid))
        except Exception:
            return
        if not os.path.isdir(self.chroma_dir):
            return
        for name in os.listdir(self.chroma_dir):
            full = os.path.join(self.chroma_dir, name)
            if not os.path.isdir(full):
                continue
            try:
                _uuid.UUID(name)
            except ValueError:
                continue
            if name not in valid_ids:
                import shutil
                shutil.rmtree(full, ignore_errors=True)

    def _read_jsonl_index(self) -> dict[str, dict]:
        """启动时读取 JSONL，建立 obs_id 到 Observation 的内存索引。"""
        records = {}
        if os.path.exists(self.jsonl_path):
            with open(self.jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            obs = json.loads(line)
                            records[obs["obs_id"]] = obs
                        except (json.JSONDecodeError, KeyError):
                            pass
        return records

    def _obs_id_set(self) -> set:
        """返回内存索引中的全部 obs_id。"""
        return set(self._records_by_id)

    def _append_jsonl(self, obs: dict):
        """追加单条到 JSONL"""
        with open(self.jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obs, ensure_ascii=False) + "\n")

    def _load_jsonl(self) -> list[dict]:
        """从内存索引返回全部记录。"""
        return list(self._records_by_id.values())

    def add(self, observations: list[dict]) -> list[str]:
        """
        添加 Observation 列表到 Bank。

        Args:
            observations: NarrativeObservation 字典列表

        Returns:
            新增的 obs_id 列表（已存在的跳过）
        """
        if not observations:
            return []

        existing = self._obs_id_set()
        to_add = [obs for obs in observations if obs.get("obs_id") not in existing]

        if not to_add:
            return []

        texts = [_observation_to_text(obs) for obs in to_add]
        embeddings = self.embedder.encode(texts)

        ids = []
        vectors = []
        metadatas = []
        documents = []

        for i, obs in enumerate(to_add):
            obs_id = obs["obs_id"]
            ids.append(obs_id)
            vectors.append(embeddings[i].tolist())
            metadatas.append({
                "story_id": obs.get("story_id", ""),
                "surface_form": obs.get("surface_form", ""),
                "affected_aspect": obs.get("affected_aspect", ""),
            })
            documents.append(texts[i])

        self.collection.add(ids=ids, embeddings=vectors, metadatas=metadatas, documents=documents)

        for obs in to_add:
            self._append_jsonl(obs)
            self._records_by_id[obs["obs_id"]] = obs

        return [obs["obs_id"] for obs in to_add]

    def get(self, obs_id: str) -> Optional[dict]:
        """通过 obs_id 精确查询完整记录"""
        return self._records_by_id.get(obs_id)

    def exists(self, obs_id: str) -> bool:
        """检查 obs_id 是否已存在"""
        return obs_id in self._records_by_id

    def count(self) -> int:
        """返回总 Observation 数量"""
        return self.collection.count()

    def get_all(self, limit: Optional[int] = None) -> list[dict]:
        """
        导出所有 Observation。

        Args:
            limit: 可选，限制返回数量
        """
        records = self._load_jsonl()
        if limit:
            records = records[:limit]
        return records

    def get_by_story(self, story_id: str) -> list[dict]:
        """查询指定 story_id 的所有 Observation"""
        records = self._load_jsonl()
        return [r for r in records if r.get("story_id") == story_id]

    def clear(self):
        """清空 Bank（仅测试用）"""
        # 通过集合 API 删除记录，避免 Windows 下删除当前客户端仍打开的
        # sqlite 文件导致 PermissionError。
        ids = self.collection.get(include=[]).get("ids", [])
        if ids:
            self.collection.delete(ids=ids)
        if os.path.exists(self.jsonl_path):
            os.remove(self.jsonl_path)
        self._records_by_id.clear()
