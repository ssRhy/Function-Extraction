"""批后统一归纳聚类逻辑测试（纯函数，无 LLM）。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Agent.Inducer.cluster import (
    cluster_similar_pairs,
    split_oversized,
    BATCH_EDGE_SIM,
    BATCH_MAX_OBS_PER_CALL,
)


def _pair(a: str, b: str, sim: float) -> dict:
    return {
        "reference": {"obs_id": a, "story_id": a.split("_")[0]},
        "retrieved": {"obs_id": b, "story_id": b.split("_")[0]},
        "similarity": sim,
    }


def test_edge_threshold_filter():
    pairs = [
        _pair("s1_obs1", "s2_obs1", 0.9),
        _pair("s1_obs1", "s3_obs1", 0.5),   # 弱边应被过滤
    ]
    comps = cluster_similar_pairs(pairs)
    assert len(comps) == 1
    assert len(comps[0]) == 1


def test_connected_components():
    pairs = [
        _pair("s1_obs1", "s2_obs1", 0.9),
        _pair("s2_obs1", "s3_obs1", 0.88),
        _pair("s4_obs1", "s5_obs1", 0.91),
    ]
    comps = cluster_similar_pairs(pairs)
    assert sorted(len(c) for c in comps) == [1, 2]


def test_split_oversized():
    # 45 个 obs 的团，超过 max_obs=40，应拆成 >=2 组且每组 <=40 obs
    pairs = []
    for i in range(1, 46):
        for j in range(i + 1, 46):
            pairs.append(_pair(f"s{i}_obs", f"s{j}_obs", 0.9))
    groups = split_oversized(pairs, max_obs=40)
    assert len(groups) >= 2
    for g in groups:
        obs = set()
        for p in g:
            obs.add(p["reference"]["obs_id"])
            obs.add(p["retrieved"]["obs_id"])
        assert len(obs) <= 40


def test_split_oversized_within_limit():
    pairs = [_pair("s1_o", "s2_o", 0.9), _pair("s2_o", "s3_o", 0.9)]
    groups = split_oversized(pairs, max_obs=40)
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_empty_and_single():
    assert cluster_similar_pairs([]) == []
    comps = cluster_similar_pairs([_pair("s1_o", "s2_o", 0.5)])
    assert comps == []


def test_constants():
    assert BATCH_EDGE_SIM == 0.60
    assert BATCH_MAX_OBS_PER_CALL == 40


if __name__ == "__main__":
    import traceback
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"\n{'全部通过' if failed == 0 else f'{failed} 个失败'}")
    sys.exit(1 if failed else 0)
