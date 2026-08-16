"""Evaluator_v0 测试：六维纯函数（无 LLM）+ 节点测试（mock chat_structured）"""

import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Agent.Evaluator import dimensions as dim
from Agent.Evaluator.evaluator import evaluator_node
from Agent.Evaluator import evaluator as ev_module
from Prompt.Evaluator_prompt import EvaluatorReviewResponse, FunctionQualityReview

_embedder = None


def get_embedder():
    global _embedder
    if _embedder is None:
        from Embedding.embedding import Embedder
        _embedder = Embedder()
    return _embedder


def _obs(sid, oid, text="角色发现关键线索，改变了对局面的认知，决定采取新行动"):
    return {
        "obs_id": oid,
        "story_id": sid,
        "before_state": text,
        "event": text,
        "after_state": text,
        "surface_form": "发现线索",
    }


def make_set():
    """2 函数 / 8 obs，覆盖 6 故事：F_A=obs_001..004（s1,s1,s2,s3），F_B=obs_005..008（s4,s5,s5,s6）。"""
    stories = ["s1", "s1", "s2", "s3", "s4", "s5", "s5", "s6"]
    obs = [_obs(stories[i], f"obs_{i + 1:03d}") for i in range(8)]
    funcs = [
        {
            "function_name": "F_A",
            "definition": "角色获知关键信息，改变认知或推动行动",
            "supporting_obs_ids": [f"obs_{i:03d}" for i in range(1, 5)],
            "realization_patterns": ["发现线索", "获得情报"],
            "hard_negatives": [],
            "confusable_functions": [],
        },
        {
            "function_name": "F_B",
            "definition": "角色与重要人物建立互助合作关系并获得支持",
            "supporting_obs_ids": [f"obs_{i:03d}" for i in range(5, 9)],
            "realization_patterns": ["达成合作", "接受庇护"],
            "hard_negatives": [],
            "confusable_functions": [],
        },
    ]
    return obs, funcs


def make_reviews(funcs, ok=True):
    return [
        {
            "function_name": f["function_name"],
            "bidirectional_conflation": False,
            "conflation_reason": "",
            "genre_surface_binding": False,
            "binding_reason": "",
            "granularity": "ok" if ok else "too_broad",
            "recommendation": "OK" if ok else "REVISE",
        }
        for f in funcs
    ]


def test_bidirectional_rule():
    hits = dim.detect_bidirectional_conflation([
        "隐藏的身份或真相被揭露或掩盖",
        "角色获得关键信息，改变认知",
        "双方关系建立、改善或恶化",
    ])
    assert hits[0] == ["揭露↔掩盖"], hits[0]
    assert hits[1] == [], hits[1]
    assert "建立↔恶化" in hits[2], hits[2]
    print("规则双向混叠预筛: OK")


def test_coverage():
    obs, funcs = make_set()
    emb = get_embedder()
    r = dim.compute_coverage(funcs, obs, emb)
    assert r["score"] == 1.0 and r["pass"] is True, r
    # 高阈值下非 supporting obs 不被解释 -> 覆盖率下降
    partial = obs[:2] + [_obs("s7", "extra_001", "完全无关的日常琐碎描述内容填充"), _obs("s8", "extra_002", "另一条完全无关的平淡叙述")]
    r2 = dim.compute_coverage(funcs, partial, emb, sim_threshold=0.99)
    assert r2["covered_obs"] == 2 and r2["pass"] is False, r2
    print("Coverage: OK")


def test_cohesion_weak_fit():
    obs, funcs = make_set()
    emb = get_embedder()
    obs_by_id = {o["obs_id"]: o for o in obs}
    r = dim.compute_cohesion(funcs, obs_by_id, emb)
    assert 0.0 <= r["score"] <= 1.0
    # 把一个 obs 换成语义无关的文本 -> 与 centroid 贴合低，被默认阈值标记 weak-fit
    outlier = _obs("s1", "obs_001", "窗外的雨下了一整夜，院子里的积水没过了台阶，邻居家的小孩在门口玩泥巴")
    obs_by_id["obs_001"] = outlier
    r2 = dim.compute_cohesion(funcs, obs_by_id, emb)
    flagged = [w["obs_id"] for w in r2["weak_fit_obs"]]
    assert flagged == ["obs_001"], flagged
    print("Cohesion + weak-fit: OK")


def test_separation():
    funcs = [
        {"function_name": "A", "definition": "角色获知关键信息改变认知"},
        {"function_name": "B", "definition": "角色获知关键信息改变认知"},
        {"function_name": "C", "definition": "角色与重要人物建立互助合作关系"},
    ]
    emb = get_embedder()
    r = dim.compute_separation(funcs, emb)
    assert r["pass"] is False and len(r["groups"]) == 1, r
    assert set(r["groups"][0]) == {"A", "B"}, r["groups"]
    assert any(p["a"] == "A" and p["b"] == "B" for p in r["pairs"])
    # A/B 相似度 1.0 已构成分组 -> 不进 0.78-0.85 复核列表
    assert r["review_pairs"] == [], r["review_pairs"]
    r2 = dim.compute_separation(funcs[:1], emb)
    assert r2["pass"] is True and r2["groups"] == [], r2
    print("Separation 近义分组: OK")


def test_evidence():
    obs, funcs = make_set()
    obs_by_id = {o["obs_id"]: o for o in obs}
    r = dim.compute_evidence(funcs, obs_by_id)
    assert r["pass"] is True and r["mean_stories"] == 3.0 and r["mean_obs"] == 4.0, r
    # 单故事函数 -> 不达标 + 标记
    funcs2 = [{"function_name": "F_X", "supporting_obs_ids": ["obs_001", "obs_002"]}]
    r2 = dim.compute_evidence(funcs2, obs_by_id)
    assert r2["pass"] is False and r2["low_evidence"] == [{"function_name": "F_X", "stories": 1}], r2
    print("Evidence Count: OK")


def test_diversity():
    obs, funcs = make_set()
    obs_by_id = {o["obs_id"]: o for o in obs}
    cats = {"s1": "g1", "s2": "g1", "s3": "g2", "s4": "g2", "s5": "g3", "s6": "g3"}
    r = dim.compute_diversity(funcs, obs_by_id, cats)
    assert r["pass"] is True and r["score"] == 3, r
    r1 = dim.compute_diversity(funcs, obs_by_id, {k: "g1" for k in cats})
    assert r1["pass"] is False and r1["score"] == 1, r1
    # 无题材映射回退去重故事数
    r2 = dim.compute_diversity(funcs, obs_by_id)
    assert r2["score"] == 6 and r2["pass"] is False, r2
    many_obs = [_obs(f"s{i}", f"m_obs_{i:03d}") for i in range(25)]
    many_funcs = [{"function_name": "F_M", "supporting_obs_ids": [o["obs_id"] for o in many_obs]}]
    r3 = dim.compute_diversity(many_funcs, {o["obs_id"]: o for o in many_obs})
    assert r3["score"] == 25 and r3["pass"] is True, r3
    print("Diversity（题材/回退）: OK")


def test_pass_and_fail_logic():
    obs, funcs = make_set()
    emb = get_embedder()
    cats = {"s1": "g1", "s2": "g1", "s3": "g2", "s4": "g2", "s5": "g3", "s6": "g3"}
    report = dim.evaluate_function_set(funcs, obs, emb, story_to_category=cats, abstraction_reviews=make_reviews(funcs, ok=True))
    assert report["verdict"] == "PASS", report["passed_dimensions"]
    assert len(report["passed_dimensions"]) >= 4, report["passed_dimensions"]
    # FAIL：同义重复 + 单题材 + 抽象质量全不合格 -> 3/6
    dup_funcs = [dict(funcs[0], function_name="F_A2"), funcs[1]]
    dup_funcs[0]["definition"] = funcs[1]["definition"]
    report2 = dim.evaluate_function_set(dup_funcs, obs, emb, story_to_category={k: "g1" for k in cats}, abstraction_reviews=make_reviews(dup_funcs, ok=False))
    assert report2["verdict"] == "FAIL", report2["passed_dimensions"]
    assert len(report2["passed_dimensions"]) < 4, report2["passed_dimensions"]
    assert "merge_groups" in report2["recommendations"], report2["recommendations"]
    print("≥4/6 判定逻辑: OK")


def _with_mock_llm(fake, fn):
    original = ev_module.chat_structured
    ev_module.chat_structured = lambda messages, schema, **kw: fake
    try:
        return fn()
    finally:
        ev_module.chat_structured = original


def test_evaluator_node():
    obs, funcs = make_set()
    with tempfile.TemporaryDirectory() as tmp:
        reg_path = os.path.join(tmp, "functions.jsonl")
        bank_path = os.path.join(tmp, "observations.jsonl")
        report_path = os.path.join(tmp, "report.json")
        with open(reg_path, "w", encoding="utf-8") as f:
            for func in funcs:
                f.write(json.dumps(func, ensure_ascii=False) + "\n")
        with open(bank_path, "w", encoding="utf-8") as f:
            for o in obs:
                f.write(json.dumps(o, ensure_ascii=False) + "\n")
        fake = EvaluatorReviewResponse(reviews=[
            FunctionQualityReview(
                function_name=f["function_name"],
                bidirectional_conflation=False,
                conflation_reason="",
                genre_surface_binding=False,
                binding_reason="",
                granularity="ok",
                recommendation="OK",
            ) for f in funcs
        ])
        result = _with_mock_llm(fake, lambda: evaluator_node({
            "messages": [],
            "evaluation_context": {
                "registry_file": reg_path,
                "bank_file": bank_path,
                "report_path": report_path,
            },
        }))
        assert result["evaluator_decision"] in ("PASS", "FAIL"), result
        report = result["evaluation_report"]
        assert set(report["dimensions"].keys()) == {
            "coverage", "cohesion", "separation", "abstraction_quality", "evidence_count", "diversity"
        }, report["dimensions"].keys()
        assert os.path.exists(report_path), report_path
        with open(report_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["verdict"] == report["verdict"]
        assert result["next_node"] in ("registry_init", "inducer_retry")
        print("evaluator_node（mock LLM）: OK")


def test_incremental_abstraction_review():
    obs, funcs = make_set()
    prev = make_reviews(funcs, ok=True)
    calls = {"n": 0}

    def fake(messages, schema, **kw):
        calls["n"] += 1
        cards = json.loads(messages[1]["content"].split("\n", 1)[1])
        return EvaluatorReviewResponse(reviews=[
            FunctionQualityReview(
                function_name=c["function_name"], bidirectional_conflation=False, conflation_reason="",
                genre_surface_binding=False, binding_reason="", granularity="ok", recommendation="OK",
            ) for c in cards
        ])

    orig = ev_module.chat_structured
    ev_module.chat_structured = fake
    try:
        reviews, errors, reviewed_n, reused_n = ev_module._review_abstraction(
            funcs, review_targets=["F_B"], prev_reviews=prev)
    finally:
        ev_module.chat_structured = orig
    assert calls["n"] == 1, calls  # 只复评 F_B（一批）
    assert len(reviews) == 2 and not errors, (reviews, errors)
    by_name = {r["function_name"]: r for r in reviews}
    assert by_name["F_A"] == prev[0], by_name  # 未变更函数沿用旧评审
    assert by_name["F_B"]["recommendation"] == "OK", by_name
    assert reviewed_n == 1 and reused_n == 1, (reviewed_n, reused_n)
    print("增量 Abstraction 复核（只评变更集）: OK")


def test_incremental_review_empty_targets():
    obs, funcs = make_set()
    prev = make_reviews(funcs, ok=True)
    calls = {"n": 0}

    def fake(messages, schema, **kw):
        calls["n"] += 1
        raise AssertionError("空变更集不应调用 LLM")

    orig = ev_module.chat_structured
    ev_module.chat_structured = fake
    try:
        reviews, errors, reviewed_n, reused_n = ev_module._review_abstraction(
            funcs, review_targets=[], prev_reviews=prev)
    finally:
        ev_module.chat_structured = orig
    assert calls["n"] == 0, calls
    assert len(reviews) == 2 and reviewed_n == 0 and reused_n == 2, (reviewed_n, reused_n)
    print("增量复核空变更集（零 LLM 调用）: OK")


def test_empty_registry():
    with tempfile.TemporaryDirectory() as tmp:
        bank_path = os.path.join(tmp, "observations.jsonl")
        report_path = os.path.join(tmp, "report.json")
        with open(bank_path, "w", encoding="utf-8") as f:
            pass
        result = evaluator_node({
            "messages": [],
            "evaluation_context": {"registry_file": os.path.join(tmp, "none.jsonl"), "bank_file": bank_path, "report_path": report_path},
        })
        assert result["evaluator_decision"] == "FAIL" and result["next_node"] == "inducer_retry"
        print("空 Registry 兜底: OK")


if __name__ == "__main__":
    test_bidirectional_rule()
    test_coverage()
    test_cohesion_weak_fit()
    test_separation()
    test_evidence()
    test_diversity()
    test_pass_and_fail_logic()
    test_evaluator_node()
    test_empty_registry()
    test_incremental_abstraction_review()
    test_incremental_review_empty_targets()
    print("\n全部 Evaluator_v0 测试通过")