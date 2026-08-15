"""
Retrieval 模块 - 向量检索接口
基于 ObservationBank 提供语义相似度搜索
"""

from typing import Optional
from Bank.bank import ObservationBank


class RetrievedObservation:
    """
    检索结果封装，方便调用方使用。
    """

    def __init__(self, obs: dict, distance: float):
        self.obs = obs
        self.distance = distance
        self.similarity = 1 - distance  # cosine distance → similarity

    def __repr__(self):
        return (
            f"<RetrievedObservation id={self.obs.get('obs_id')} "
            f"similarity={self.similarity:.3f} event={self.obs.get('event', '')[:30]}>"
        )


class Retriever:
    """
    向量检索接口。

    用法：
        bank = ObservationBank()
        retriever = Retriever(bank)

        results = retriever.query_similar("某角色展示隐藏能力，让其他人认识到其实力很强", top_k=5)
        for r in results:
            print(r.obs["event"], r.similarity)
    """

    def __init__(self, bank: ObservationBank):
        self.bank = bank

    def query_similar(
        self,
        text: str,
        top_k: int = 10,
        story_id: Optional[str] = None,
        exclude_obs_ids: Optional[list[str]] = None
    ) -> list[RetrievedObservation]:
        """
        根据文本描述检索语义相似的 Observations。

        Args:
            text: 检索文本（可以是自然语言描述、结构化描述、或单个字段）
            top_k: 返回数量
            story_id: 可选，仅检索指定 story_id 的结果
            exclude_obs_ids: 可选，排除的 obs_id 列表

        Returns:
            RetrievedObservation 列表，按 similarity 降序排列
        """
        if self.bank.count() == 0:
            return []

        query_embedding = self.bank.embedder.encode_single(text).tolist()
        seen_ids = set(exclude_obs_ids or [])

        where_filter = None
        if story_id:
            where_filter = {"story_id": story_id}

        results = self.bank.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(self.bank.count(), top_k + len(seen_ids)),
            where=where_filter,
            include=["distances", "documents", "metadatas"]
        )

        retrieved = []

        ids = results["ids"][0]
        distances = results["distances"][0]
        documents = results["documents"][0]

        for i, obs_id in enumerate(ids):
            if obs_id in seen_ids:
                continue
            seen_ids.add(obs_id)

            obs = self.bank.get(obs_id)
            if obs is None:
                continue

            retrieved.append(RetrievedObservation(obs=obs, distance=distances[i]))

            if len(retrieved) >= top_k:
                break

        retrieved.sort(key=lambda x: x.similarity, reverse=True)
        return retrieved

    def query_by_observation(
        self,
        obs: dict,
        top_k: int = 10,
        exclude_same_story: bool = True,
        exclude_obs_ids: Optional[list[str]] = None,
    ) -> list[RetrievedObservation]:
        """
        根据一个 Observation 检索相似的其他 Observations。

        主要用于 Inducer 寻找候选比较集。

        Args:
            obs: 参考 Observation 字典
            top_k: 返回数量
            exclude_same_story: 是否排除同 story_id 的结果
            exclude_obs_ids: 额外排除的 obs_id 列表

        Returns:
            RetrievedObservation 列表
        """
        # 用 Observation 的结构化字段构造检索文本
        text = " | ".join([
            obs.get("before_state", ""),
            obs.get("event", ""),
            obs.get("after_state", ""),
            obs.get("affected_aspect", ""),
            obs.get("narrative_effect", ""),
        ])

        exclude_ids = list(exclude_obs_ids or [])
        if exclude_same_story:
            exclude_ids.extend(
                o["obs_id"] for o in self.bank.get_by_story(obs["story_id"])
            )

        return self.query_similar(
            text=text,
            top_k=top_k,
            exclude_obs_ids=exclude_ids + [obs["obs_id"]]
        )
