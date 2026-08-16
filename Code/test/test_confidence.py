"""
测试置信度计算（新签名）
覆盖：supporting 集合口径、bootstrap 豁免 confusable、近义"保留最高置信度"。
"""

import shutil
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Bank import ObservationBank
from Agent.Inducer.confidence import calculate_confidence_detailed
from Agent.Inducer.inducer import merge_candidates


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
            "story_id": "storyA",
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
            "story_id": "storyA",
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
            "story_id": "storyB",
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
            "story_id": "storyB",
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
            "story_id": "storyC",
        },
    ]


def test_confidence_new_signature():
    print("\n" + "=" * 60)
    print("测试置信度计算（新签名）")
    print("=" * 60)

    _bank_tmp = tempfile.mkdtemp(prefix="bank_test_conf_")
    bank = ObservationBank(persist_dir=_bank_tmp)
    bank.clear()
    bank.add(make_test_observations())

    supporting = ["storyA_obs_001", "storyB_obs_001", "storyB_obs_002"]
    cand_def = "此前未知的能力被相关人物认识到"

    # 1) 默认 apply_confusable=True
    result = calculate_confidence_detailed(supporting, cand_def, bank)
    print(f"\n[默认] conf={result['confidence']:.3f} factors={result['factors']}")
    assert "confidence" in result and "factors" in result

    # 2) bootstrap 豁免：penalty=0，分数不低于默认
    result2 = calculate_confidence_detailed(supporting, cand_def, bank, apply_confusable=False)
    print(f"[豁免] conf={result2['confidence']:.3f} factors={result2['factors']}")
    assert result2["factors"]["confusability_penalty"] == 0.0
    assert result2["confidence"] >= result["confidence"] - 1e-9

    # 3) supporting 集合口径：surface 只取决于 supporting obs 的去重 surface_form
    result3 = calculate_confidence_detailed(
        ["storyA_obs_001", "storyB_obs_001"], cand_def, bank, apply_confusable=False
    )
    print(f"[2-obs] conf={result3['confidence']:.3f} surface={result3['factors']['surface_diversity']}")
    assert abs(result3["factors"]["surface_diversity"] - 2.0 / 3.0) < 0.01

    # 4) 近义"保留最高置信度"（merge_candidates，纯内存）
    embedder = bank.embedder
    live: list[dict] = []
    cand_lo = {
        "function_name": "SACRIFICE_FOR_OTHERS",
        "definition": "为他人自愿牺牲珍贵资源或生命",
        "confidence": 0.51,
    }
    cand_hi = {
        "function_name": "SACRIFICE_FOR_GOAL",
        "definition": "为他人自愿牺牲珍贵资源或生命",
        "confidence": 0.55,
    }
    live, written = merge_candidates(live, [cand_lo], embedder)
    assert len(live) == 1 and len(written) == 1
    live, written2 = merge_candidates(live, [cand_hi], embedder)
    assert len(live) == 1, "近义应合并为 1 条"
    assert live[0]["function_name"] == "SACRIFICE_FOR_GOAL"
    assert abs(live[0]["confidence"] - 0.55) < 1e-9
    print(f"\n[近义合并] 保留: {live[0]['function_name']} conf={live[0]['confidence']}")

    # 5) 同名但置信度更低 → 不替换
    cand_low2 = {
        "function_name": "SACRIFICE_FOR_GOAL",
        "definition": "完全不同的另一个定义",
        "confidence": 0.52,
    }
    live, written3 = merge_candidates(live, [cand_low2], embedder)
    assert len(live) == 1
    assert abs(live[0]["confidence"] - 0.55) < 1e-9
    print(f"[同名低分] 未替换: {live[0]['function_name']} conf={live[0]['confidence']}")

    print("\n所有断言通过!")
    shutil.rmtree(_bank_tmp, ignore_errors=True)


if __name__ == "__main__":
    test_confidence_new_signature()