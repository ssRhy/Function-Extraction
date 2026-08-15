"""
测试置信度计算 - 完整流程测试
从测试数据 -> Bank -> Retrieval -> Inducer -> 置信度输出
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Bank import ObservationBank
from Retrieval import Retriever
from Agent.Inducer.confidence import calculate_confidence_detailed


def make_test_observations():
    """构造跨故事的测试 Observations"""
    return [
        # Story A - 仙侠能力展示
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
        # Story B - 都市能力展示（不同领域）
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
        # Story C - 关系类（作为对比，不应该与能力展示归为一类）
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


def test_confidence_calculation():
    """测试置信度计算"""
    print("\n" + "=" * 60)
    print("测试置信度计算")
    print("=" * 60)

    # 1. Prepare data
    obs_list = make_test_observations()

    # Capability obs (storyA + storyB, cross-story)
    capability_obs = [o for o in obs_list if o["story_id"] in ("storyA", "storyB")]

    # Relation obs (storyC)
    relation_obs = [o for o in obs_list if o["story_id"] == "storyC"]

    print(f"\n[Data] Capability obs: {len(capability_obs)} items")

    print(f"\n[Data] Relation obs: {len(relation_obs)} items")

    # 2. 候选 Function 定义（模拟 LLM 归纳结果）
    capability_def = "此前未知的能力被相关人物认识到"
    relation_def = "两个陌生人通过互动建立初步信任关系"

    print("-" * 60)
    print("Scenario 1: Capability Function")
    print("-" * 60)
    result = calculate_confidence_detailed(capability_obs, capability_def)
    print_confidence_result(result)

    print("\n" + "-" * 60)
    print("Scenario 2: Relation Function")
    print("-" * 60)
    result = calculate_confidence_detailed(relation_obs, relation_def)
    print_confidence_result(result)

    # 3. Test edge case: single story
    print("\n" + "-" * 60)
    print("Scenario 3: Single story (should have low diversity)")
    print("-" * 60)
    single_story = [o for o in obs_list if o["story_id"] == "storyA"]
    result = calculate_confidence_detailed(single_story, capability_def)
    print_confidence_result(result)

    # 4. Analysis
    print("\n" + "=" * 60)
    print("Analysis")
    print("=" * 60)

    cap_result = calculate_confidence_detailed(capability_obs, capability_def)
    rel_result = calculate_confidence_detailed(relation_obs, relation_def)
    single_result = calculate_confidence_detailed(single_story, capability_def)

    print(f"""
Cross-story capability confidence: {cap_result['confidence']:.3f}
  - cross_story_diversity: {cap_result['factors']['cross_story_diversity']:.3f}
  - semantic_coherence: {cap_result['factors']['semantic_coherence']:.3f}
  - surface_diversity: {cap_result['factors']['surface_diversity']:.3f}

Single-story confidence: {single_result['confidence']:.3f}
  - cross_story_diversity: {single_result['factors']['cross_story_diversity']:.3f}

[OK] Expected: cross-story > single-story (diversity factor)
""")

    return cap_result, rel_result, single_result


def print_confidence_result(result: dict):
    """Print confidence result"""
    print(f"\nFinal confidence: {result['confidence']:.3f}")
    print("\nFactor scores:")
    for name, value in result['factors'].items():
        print(f"  {name}: {value:.3f}")

    print("\nWeight config:")
    for name, value in result['weights'].items():
        print(f"  {name}: {value}")

    print("\nCalculation:")
    total = 0
    details = []
    for name, value in result['factors'].items():
        w = result['weights'].get(name, 0)
        contribution = value * w
        sign = "+" if contribution >= 0 else ""
        total += contribution
        details.append(f"  {value:.3f} * {w} = {sign}{contribution:.3f}")

    for d in details:
        print(d)
    print(f"  = {total:.3f}")
    print(f"  Clamp to [0,1]: {max(0.0, min(1.0, total)):.3f}")


def test_bank_retrieval_confidence():
    """Test Bank + Retrieval + Confidence pipeline"""
    print("\n" + "=" * 60)
    print("Test pipeline: Bank -> Retrieval -> Confidence")
    print("=" * 60)

    # 1. Init Bank
    bank = ObservationBank(persist_dir="Code/data/bank_test")
    bank.clear()

    # 2. Add test data
    obs_list = make_test_observations()
    added = bank.add(obs_list)
    print(f"\nBank added {len(added)} Observations")

    # 3. Retrieval
    retriever = Retriever(bank)

    ref_obs = bank.get("storyA_obs_001")
    print(f"\nReference: [{ref_obs['obs_id']}] {ref_obs['surface_form']}")

    results = retriever.query_by_observation(ref_obs, top_k=5, exclude_same_story=True)
    print(f"Found {len(results)} cross-story similar Observations:")

    similar_pairs = []
    for r in results:
        similar_pairs.append({
            "reference": ref_obs,
            "retrieved": r.obs,
            "similarity": r.similarity
        })
        print(f"  [{r.obs['obs_id']}] sim={r.similarity:.3f} | {r.obs['surface_form']}")

    # 5. Build cluster
    seen = {}
    for pair in similar_pairs:
        for role in ("reference", "retrieved"):
            obs = pair.get(role)
            if not obs:
                continue
            obs_id = obs.get("obs_id", "")
            if obs_id and obs_id not in seen:
                seen[obs_id] = obs

    cluster = list(seen.values())
    print(f"\nCluster has {len(cluster)} Observations:")

    for o in cluster:
        print(f"  - [{o['obs_id']}] {o['surface_form']}")

    # 6. Calculate confidence
    if len(cluster) >= 2:
        story_ids = set(o.get("story_id", "") for o in cluster)
        if len(story_ids) >= 2:
            candidate_def = "Previously unknown capability is recognized by relevant characters"
            result = calculate_confidence_detailed(cluster, candidate_def)
            print(f"\nConfidence based on Retrieval:")
            print_confidence_result(result)
        else:
            print("\n[WARN] Cluster spans < 2 stories")
    else:
        print("\n[WARN] Cluster has insufficient observations")


if __name__ == "__main__":
    test_confidence_calculation()
    test_bank_retrieval_confidence()

    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
