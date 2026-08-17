"""
批后统一归纳 - 相似 Observation 聚类工具

纯函数模块（无 LLM、无 IO），供 Agent.app（bootstrap_app 阶段 2）使用：
把跨故事相似对按连通分量聚类，超大规模分量按度贪心拆分。
"""

# 相似图边阈值：obs 向量余弦相似度 >= 该值才连边
# 注：all-MiniLM-L6-v2 对中文结构化 obs 的相似度整体偏低（实测 max≈0.69），
# 0.60 作为噪声底线（过滤 top-5 检索里明显无关的弱边）。
BATCH_EDGE_SIM = 0.60
# 单次 Inducer 调用最多容纳的 obs 数（防止上下文过大）
BATCH_MAX_OBS_PER_CALL = 40


def _pair_obs_ids(pair: dict) -> tuple[str, str]:
    a = pair["reference"]["obs_id"]
    b = pair["retrieved"]["obs_id"]
    return (a, b) if a <= b else (b, a)


def cluster_similar_pairs(
    pairs: list[dict],
    sim_threshold: float = BATCH_EDGE_SIM,
) -> list[list[dict]]:
    """把相似对按连通分量聚类。

    只保留 similarity >= sim_threshold 的边；每个连通分量内的全部
    相似对组成一个聚类（供一次 Inducer 调用）。
    """
    adjacency: dict[str, set] = {}
    edge_map: dict[tuple[str, str], dict] = {}
    for pair in pairs:
        if pair.get("similarity", 0.0) < sim_threshold:
            continue
        a, b = _pair_obs_ids(pair)
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
        edge_map[(a, b)] = pair

    seen: set[str] = set()
    components: list[list[dict]] = []
    for node in adjacency:
        if node in seen:
            continue
        nodes: list[str] = []
        stack = [node]
        seen.add(node)
        while stack:
            cur = stack.pop()
            nodes.append(cur)
            for nxt in adjacency.get(cur, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        node_set = set(nodes)
        comp_pairs = [
            pair for (a, b), pair in edge_map.items()
            if a in node_set and b in node_set
        ]
        components.append(comp_pairs)
    return components


def split_oversized(
    component_pairs: list[dict],
    max_obs: int = BATCH_MAX_OBS_PER_CALL,
) -> list[list[dict]]:
    """分量 obs 数超过 max_obs 时按度贪心拆分（BFS 收集，最多 max_obs/组）。"""
    obs_ids: set[str] = set()
    for pair in component_pairs:
        a, b = _pair_obs_ids(pair)
        obs_ids.add(a)
        obs_ids.add(b)
    if len(obs_ids) <= max_obs:
        return [component_pairs]

    adjacency: dict[str, set] = {}
    edge_map: dict[tuple[str, str], dict] = {}
    for pair in component_pairs:
        a, b = _pair_obs_ids(pair)
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
        edge_map[(a, b)] = pair

    remaining = set(obs_ids)
    groups: list[list[dict]] = []
    while remaining:
        center = max(remaining, key=lambda o: len(adjacency.get(o, set()) & remaining))
        chosen: set[str] = set()
        stack = [center]
        while stack and len(chosen) < max_obs:
            cur = stack.pop()
            if cur in chosen or cur not in remaining:
                continue
            chosen.add(cur)
            for nxt in adjacency.get(cur, ()):
                if nxt not in chosen and nxt in remaining:
                    stack.append(nxt)
        remaining -= chosen
        group = [
            pair for (a, b), pair in edge_map.items()
            if a in chosen and b in chosen
        ]
        if group:
            groups.append(group)
    return groups
