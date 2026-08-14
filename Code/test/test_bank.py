"""
Bank + Retrieval 集成测试
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Bank import ObservationBank
from Retrieval import Retriever


def make_test_observations():
    """构造两个不同 story 的测试 Observation"""
    return [
        # Story A - 能力展示类
        {
            "obs_id": "storyA_obs_001",
            "before_state": "其他角色一直低估张凡的实力",
            "event": "张凡公开击败宗门内门第一",
            "participants": ["主角", "对手", "旁观者"],
            "after_state": "其他角色认识到张凡实际实力很强",
            "affected_aspect": "其他角色对主角能力的认知",
            "narrative_effect": "主角的能力评价与声望发生改变",
            "surface_form": "比武获胜",
            "source_sentence_indices": [1, 2, 3],
            "source_segment_id": "storyA_seg_1",
            "story_id": "storyA",
            "extracted_at": "2026-01-01T00:00:00"
        },
        {
            "obs_id": "storyA_obs_002",
            "before_state": "宗门弟子认为张凡炼丹水平一般",
            "event": "张凡炼制出极品丹药，众人震惊",
            "participants": ["主角", "宗门弟子"],
            "after_state": "宗门弟子认识到张凡炼丹能力很强",
            "affected_aspect": "对主角炼丹水平的认知",
            "narrative_effect": "主角炼丹声望提升",
            "surface_form": "炼制丹药",
            "source_sentence_indices": [10, 11],
            "source_segment_id": "storyA_seg_2",
            "story_id": "storyA",
            "extracted_at": "2026-01-01T00:00:01"
        },
        # Story B - 能力展示类（不同表层实现，同一结构）
        {
            "obs_id": "storyB_obs_001",
            "before_state": "医院同事一直认为李医生医术普通",
            "event": "李医生成功完成所有人都无法处理的手术",
            "participants": ["主角", "同事", "患者"],
            "after_state": "同事们认识到李医生医术非常高明",
            "affected_aspect": "对主角医术的认知",
            "narrative_effect": "主角获得同事认可",
            "surface_form": "成功手术",
            "source_sentence_indices": [5, 6],
            "source_segment_id": "storyB_seg_1",
            "story_id": "storyB",
            "extracted_at": "2026-01-01T00:02:00"
        },
        {
            "obs_id": "storyB_obs_002",
            "before_state": "学校师生认为王同学成绩一般",
            "event": "王同学在竞赛中解决了所有教授都不会的难题",
            "participants": ["主角", "教授", "同学"],
            "after_state": "师生们认识到王同学智力超群",
            "affected_aspect": "对主角智力的认知",
            "narrative_effect": "主角获得尊重",
            "surface_form": "解题",
            "source_sentence_indices": [20, 21],
            "source_segment_id": "storyB_seg_2",
            "story_id": "storyB",
            "extracted_at": "2026-01-01T00:02:01"
        },
        # Story C - 关系类（不同结构，作为对比）
        {
            "obs_id": "storyC_obs_001",
            "before_state": "两人初次见面，彼此陌生",
            "event": "外来军官为本地女子包扎伤口，两人交谈",
            "participants": ["外来军官", "本地女子"],
            "after_state": "女子放下戒心，建立初步友谊",
            "affected_aspect": "关系与信任",
            "narrative_effect": "开启两人交集",
            "surface_form": "疗伤与对话",
            "source_sentence_indices": [3, 4],
            "source_segment_id": "storyC_seg_1",
            "story_id": "storyC",
            "extracted_at": "2026-01-01T00:03:00"
        },
    ]


def test_embedder():
    """测试 Embedder"""
    print("\n" + "=" * 50)
    print("测试 Embedder")
    print("=" * 50)

    from Embedding import Embedder
    embedder = Embedder()

    texts = ["测试文本一", "测试文本二"]
    vectors = embedder.encode(texts)
    print(f"维度: {embedder.dimension}")
    print(f"批量编码 shape: {vectors.shape}")
    print(f"单条编码 shape: {embedder.encode_single('单条测试').shape}")
    print("PASS")


def test_bank_add():
    """测试 Bank.add()"""
    print("\n" + "=" * 50)
    print("测试 Bank.add()")
    print("=" * 50)

    bank = ObservationBank(persist_dir="Code/data/bank_test")
    bank.clear()  # 每次测试清空

    obs_list = make_test_observations()

    # 单条添加
    added = bank.add([obs_list[0]])
    print(f"添加 obs: {added}")
    assert len(added) == 1
    assert added[0] == "storyA_obs_001"

    # 批量添加
    added = bank.add(obs_list[1:])
    print(f"批量添加 obs: {added}")
    assert len(added) == 4

    # 重复添加（应跳过）
    added = bank.add([obs_list[0]])
    print(f"重复添加 obs: {added}")
    assert len(added) == 0

    assert bank.count() == 5
    print(f"Bank 中共有 {bank.count()} 条 Observation")
    print("PASS")


def test_bank_query():
    """测试 Bank.get() / exists()"""
    print("\n" + "=" * 50)
    print("测试 Bank 查询")
    print("=" * 50)

    bank = ObservationBank(persist_dir="Code/data/bank_test")

    # 精确查询
    obs = bank.get("storyA_obs_001")
    assert obs is not None
    assert obs["obs_id"] == "storyA_obs_001"
    assert obs["event"] == "张凡公开击败宗门内门第一"
    print(f"get: {obs['obs_id']} - {obs['event'][:20]}...")

    # 存在检查
    assert bank.exists("storyA_obs_001")
    assert not bank.exists("nonexistent_id")
    print("exists: True / False")

    # 按 story 查询
    story_b_obs = bank.get_by_story("storyB")
    assert len(story_b_obs) == 2
    print(f"storyB 有 {len(story_b_obs)} 条 Observation")

    print("PASS")


def test_retrieval_similar():
    """测试 Retrieval.query_similar() - 跨故事检索"""
    print("\n" + "=" * 50)
    print("测试 Retrieval.query_similar() - 跨故事检索")
    print("=" * 50)

    bank = ObservationBank(persist_dir="Code/data/bank_test")
    retriever = Retriever(bank)

    # 检索"展示能力让别人认可"类
    query = "角色展示隐藏的能力，让其他人认识到其真实实力"
    results = retriever.query_similar(query, top_k=5)

    print(f"\n检索词: {query}")
    print(f"找到 {len(results)} 条结果:")
    for r in results:
        print(f"  sim={r.similarity:.3f} [{r.obs['obs_id']}] {r.obs['surface_form']}: {r.obs['event'][:30]}...")

    # 应该能找到来自 storyA 和 storyB 的能力展示类 Observation
    story_ids = set(r.obs["story_id"] for r in results)
    print(f"结果来自 stories: {story_ids}")
    assert len(results) > 0, "应该返回结果"
    # 能力展示类 observations (storyA/B) 应该排名靠前
    capability_obs = [r for r in results if r.obs["story_id"] in ("storyA", "storyB")]
    print(f"其中能力展示类: {len(capability_obs)} 条")

    # 对比检索：关系类
    query2 = "两人通过互动建立信任和友谊"
    results2 = retriever.query_similar(query2, top_k=5)
    print(f"\n检索词: {query2}")
    for r in results2:
        print(f"  sim={r.similarity:.3f} [{r.obs['obs_id']}] {r.obs['surface_form']}")

    print("PASS")


def test_retrieval_by_observation():
    """测试 Retrieval.query_by_observation()"""
    print("\n" + "=" * 50)
    print("测试 Retrieval.query_by_observation()")
    print("=" * 50)

    bank = ObservationBank(persist_dir="Code/data/bank_test")
    retriever = Retriever(bank)

    # 以 storyA_obs_001（比武获胜）为参考，检索相似的其他故事 Observations
    ref_obs = bank.get("storyA_obs_001")
    print(f"参考: [{ref_obs['obs_id']}] {ref_obs['surface_form']}")

    results = retriever.query_by_observation(ref_obs, top_k=5, exclude_same_story=True)
    print(f"\n找到 {len(results)} 条相似 Observation:")
    for r in results:
        print(f"  sim={r.similarity:.3f} [{r.obs['obs_id']}] {r.obs['surface_form']}: {r.obs['event'][:25]}...")

    # 应该找到 storyB 的能力展示类
    assert len(results) > 0
    # storyB 的 observation 应该出现
    storyB_found = any(r.obs["story_id"] == "storyB" for r in results)
    print(f"找到 storyB 的相似 Observation: {storyB_found}")

    print("PASS")


def test_persistence():
    """测试持久化（重新加载后数据仍存在）"""
    print("\n" + "=" * 50)
    print("测试持久化")
    print("=" * 50)

    # 新建实例，应能读取已有数据
    bank = ObservationBank(persist_dir="Code/data/bank_test")
    print(f"重新加载后 Bank 中有 {bank.count()} 条 Observation")
    assert bank.count() == 5

    # Retrieval 仍可正常工作
    retriever = Retriever(bank)
    results = retriever.query_similar("展示能力让其他人认可", top_k=3)
    print(f"检索结果: {len(results)} 条")
    assert len(results) > 0

    print("PASS")


if __name__ == "__main__":
    test_embedder()
    test_bank_add()
    test_bank_query()
    test_retrieval_similar()
    test_retrieval_by_observation()
    test_persistence()

    print("\n" + "=" * 50)
    print("所有测试通过!")
    print("=" * 50)
