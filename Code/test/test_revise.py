"""Revise 节点测试：无 LLM 纯函数 + mock chat_structured 节点测试 + curate_app 闭环图测试"""

import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from Agent.Evaluator import revise
from Agent.Evaluator import evaluator as ev_module
from Prompt.Merge_prompt import MergeResponse, MergedFunction
from Prompt.Revise_prompt import ReviseResponse, RevisedFunction
from Prompt.Evaluator_prompt import EvaluatorReviewResponse, FunctionQualityReview


# ---------- Fake Embedder（纯函数测试用） ----------

class FakeEmbedder:
    """字符袋向量：共享字符越多余弦越高（模拟语义相似，无真实模型）。"""

    def __init__(self, dim=4096):
        self.dim = dim

    def _vec(self, text):
        v = np.zeros(self.dim)
        for ch in text:
            v[ord(ch) % self.dim] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def encode(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        return np.array([self._vec(t) for t in texts])

    def encode_single(self, text):
        return self._vec(text)


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
    """2 函数 / 8 obs / 6 故事（与 test_evaluator 同构）。"""
    stories = ["s1", "s1", "s2", "s3", "s4", "s5", "s5", "s6"]
    obs = [_obs(stories[i], f"obs_{i + 1:03d}") for i in range(8)]
    funcs = [
        {
            "function_name": "F_A",
            "definition": "角色获知关键信息，改变认知或推动行动",
            "supporting_obs_ids": [f"obs_{i:03d}" for i in range(1, 5)],
            "realization_patterns": ["发现线索", "获得情报"],
            "hard_negatives": [], "confusable_functions": [],
        },
        {
            "function_name": "F_B",
            "definition": "角色与重要人物建立互助合作关系并获得支持",
            "supporting_obs_ids": [f"obs_{i:03d}" for i in range(5, 9)],
            "realization_patterns": ["达成合作", "接受庇护"],
            "hard_negatives": [], "confusable_functions": [],
        },
    ]
    return obs, funcs


# ---------- 纯函数 ----------

def test_union_supporting():
    members = [{"supporting_obs_ids": ["a", "b"]}, {"supporting_obs_ids": ["b", "c"]}]
    assert revise._union_supporting(members) == ["a", "b", "c"]
    print("supporting 程序并集: OK")


def test_assign_split_obs():
    obs_by_id = {f"d{i:02d}": _obs(f"s{i}", f"d{i:02d}", "角色发现关键线索并告知同伴，局势随之改变") for i in range(3)}
    sub_funcs = [
        {"function_name": "D_REVEAL", "definition": "角色发现关键线索并传递信息"},
        {"function_name": "D_HIDE", "definition": "角色隐瞒关键线索独自行动"},
    ]
    kept, dropped = revise._assign_split_obs(list(obs_by_id), obs_by_id, [dict(s) for s in sub_funcs], FakeEmbedder())
    assert len(kept) >= 1, kept
    assigned = sum(len(f["supporting_obs_ids"]) for f in kept)
    assert assigned + len(dropped) == 3, (assigned, dropped)
    assert all("confidence" in f for f in kept), kept
    print("SPLIT obs 确定性分配: OK")


def test_dedup_names():
    funcs = [
        {"function_name": "A", "definition": "一"},
        {"function_name": "B", "definition": "二"},
        {"function_name": "A", "definition": "三（撞名）"},
        {"function_name": "A", "definition": "四（再撞名）"},
    ]
    out, renames = revise._dedup_names(funcs)
    names = [f["function_name"] for f in out]
    assert names == ["A", "B", "A_2", "A_3"], names
    assert renames == {"A": "A_2"}, renames  # 同名多次出现时保留首次映射
    assert out[2]["definition"] == "三（撞名）" and out[3]["definition"] == "四（再撞名）"
    print("同名去重（_N 后缀 + 映射）: OK")


def test_story_count():
    obs_by_id = {"o1": _obs("s1", "o1"), "o2": _obs("s1", "o2"), "o3": _obs("s2", "o3")}
    assert revise._story_count(["o1", "o2", "o3"], obs_by_id) == 2
    assert revise._story_count(["o1", "o2"], obs_by_id) == 1
    print("story 计数: OK")


def test_recalc_confidence_stub():
    obs_by_id = {f"c{i:02d}": _obs(f"s{i % 3 + 1}", f"c{i:02d}") for i in range(6)}
    func = {"supporting_obs_ids": list(obs_by_id), "definition": "角色获得关键资源并改变处境"}
    revise._recalc_confidence(func, obs_by_id, FakeEmbedder())
    assert 0.0 <= func["confidence"] <= 1.0 and "confidence_factors" in func
    print("confidence 重算桩: OK")


# ---------- 节点测试（mock LLM + 真实 Embedder） ----------

def _write_lines(path, items):
    with open(path, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")


def test_revise_node_actions():
    obs = []
    for i, (sid, oid) in enumerate([
        ("s1", "a1"), ("s1", "a2"), ("s2", "a3"), ("s3", "a4"),
        ("s4", "b1"), ("s5", "b2"), ("s5", "b3"), ("s6", "b4"),
        ("s7", "c1"), ("s8", "c2"), ("s9", "c3"),
        ("s10", "d1"), ("s11", "d2"), ("s12", "d3"),
        ("s13", "e1"), ("s13", "e2"),
        ("s13", "f1"), ("s13", "f2"), ("s14", "f3"), ("s15", "f4"),
    ]):
        if oid.startswith("d"):
            obs.append({"obs_id": oid, "story_id": sid,
                        "before_state": "角色发现关键线索",
                        "event": "角色把关键线索告知同伴",
                        "after_state": "局势随之改变",
                        "surface_form": "传递线索"})
        else:
            obs.append(_obs(sid, oid, "角色获得关键信息，改变了对局面的认知"))
    funcs = [
        {"function_name": "F_A", "definition": "角色获知关键信息，改变认知或推动行动", "supporting_obs_ids": ["a1", "a2", "a3", "a4"], "realization_patterns": ["发现线索"], "hard_negatives": [], "confusable_functions": []},
        {"function_name": "F_B", "definition": "角色获知关键信息并据此行动", "supporting_obs_ids": ["b1", "b2", "b3", "b4"], "realization_patterns": ["获得情报"], "hard_negatives": [], "confusable_functions": []},
        {"function_name": "F_C", "definition": "女主重生后获得上一世记忆，改变命运", "supporting_obs_ids": ["c1", "c2", "c3"], "realization_patterns": ["重生记忆"], "hard_negatives": [], "confusable_functions": []},
        {"function_name": "F_D", "definition": "隐藏的真相被揭露或掩盖", "supporting_obs_ids": ["d1", "d2", "d3"], "realization_patterns": ["发现秘密"], "hard_negatives": [], "confusable_functions": []},
        {"function_name": "F_E", "definition": "孤立事件中的一次性变化", "supporting_obs_ids": ["e1", "e2"], "realization_patterns": ["偶然变化"], "hard_negatives": [], "confusable_functions": []},
        {"function_name": "F_F", "definition": "角色与重要人物建立互助合作关系并获得支持", "supporting_obs_ids": ["f1", "f2", "f3", "f4"], "realization_patterns": ["达成合作"], "hard_negatives": [], "confusable_functions": []},
    ]
    report = {
        "verdict": "FAIL",
        "recommendations": {
            "merge_groups": [["F_A", "F_B"]],
            "low_evidence_functions": [{"function_name": "F_E", "stories": 1}],
            "weak_fit_obs": [{"obs_id": "f1", "function_name": "F_F", "similarity": 0.3}],
        },
        "dimensions": {"abstraction_quality": {"issues": {
            "conflation": [],
            "genre_bound": [{"function_name": "F_C", "reason": "定义绑定重生题材"}],
            "too_specific": [], "too_broad": [],
        }}},
        "abstraction_reviews": [
            {"function_name": "F_D", "recommendation": "SPLIT"},
        ],
    }

    def fake_llm(messages, schema, **kw):
        sys_msg = messages[0]["content"]
        if "本体维护者" in sys_msg:
            return MergeResponse(merged_functions=[MergedFunction(
                function_name="F_AB",
                definition="角色获知关键信息并据此调整认知或行动",
                realization_patterns=["发现线索", "获得情报"],
                hard_negatives=["无关的日常变化"], confusable_functions=["角色隐瞒信息"],
            )])
        user = json.loads(messages[1]["content"].split("\n", 1)[1])
        name = user["function"]["function_name"]
        if name == "F_D":
            return ReviseResponse(revised_functions=[
                RevisedFunction(function_name="D_REVEAL", definition="角色发现关键线索并传递信息", realization_patterns=["发现秘密"], hard_negatives=[], confusable_functions=[]),
                RevisedFunction(function_name="D_HIDE", definition="角色隐瞒关键线索独自行动", realization_patterns=["隐藏秘密"], hard_negatives=[], confusable_functions=[]),
            ])
        return ReviseResponse(revised_functions=[
            RevisedFunction(function_name="F_C2", definition="角色获得关键资源或信息，推动行动", realization_patterns=["获取资源"], hard_negatives=[], confusable_functions=[]),
        ])

    with tempfile.TemporaryDirectory() as tmp:
        reg = os.path.join(tmp, "functions.jsonl")
        bank = os.path.join(tmp, "observations.jsonl")
        report_path = os.path.join(tmp, "report.json")
        _write_lines(reg, funcs)
        _write_lines(bank, obs)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False)

        orig = revise.chat_structured
        revise.chat_structured = fake_llm
        try:
            result = revise.revise_node({
                "messages": [],
                "evaluation_context": {"registry_file": reg, "bank_file": bank, "report_path": report_path},
                "evaluation_round": 0,
            })
        finally:
            revise.chat_structured = orig

        actions = result["revise_report"]
        assert len(actions["merged"]) == 1 and actions["merged"][0]["merged_as"] == "F_AB", actions["merged"]
        assert len(actions["revised"]) == 1 and actions["revised"][0]["revised_as"] == "F_C2", actions["revised"]
        assert len(actions["split"]) == 1, actions["split"]
        assert any(r["function_name"] == "F_E" for r in actions["removed"]), actions["removed"]
        assert actions["weak_fit_removed"] == 1, actions
        assert result["evaluation_round"] == 1
        expected_targets = {"F_AB", "F_C2"}.union({n for s in actions["split"] for n in s["split_into"]})
        assert set(result["review_targets"]) == expected_targets, result["review_targets"]

        with open(reg, "r", encoding="utf-8") as f:
            written = [json.loads(l) for l in f if l.strip()]
        names = {w["function_name"] for w in written}
        assert "F_AB" in names and "F_C2" in names and "F_E" not in names and "F_F" in names, names
        assert any(n.startswith("D_") for n in names), names
        ff = next(w for w in written if w["function_name"] == "F_F")
        assert "f1" not in ff["supporting_obs_ids"], ff
        assert os.path.exists(reg + ".pre_revise.jsonl")
        print("revise_node 全动作（合并/修订/拆分/剔除/移除/写回）: OK")


# ---------- curate_app 闭环图 ----------

def test_curate_max_rounds():
    from Agent.app import curate_app
    orig = revise.MAX_EVAL_ROUNDS
    revise.MAX_EVAL_ROUNDS = 2
    try:
        with tempfile.TemporaryDirectory() as tmp:
            reg = os.path.join(tmp, "functions.jsonl")
            bank = os.path.join(tmp, "observations.jsonl")
            report_path = os.path.join(tmp, "report.json")
            with open(reg, "w", encoding="utf-8") as f:
                pass
            with open(bank, "w", encoding="utf-8") as f:
                pass
            result = curate_app.invoke({
                "messages": [],
                "evaluation_context": {"registry_file": reg, "bank_file": bank, "report_path": report_path},
                "evaluation_round": 0,
            }, config={"configurable": {"thread_id": "curate-maxrounds"}})
            assert result["evaluator_decision"] == "FAIL", result
            assert result["evaluation_round"] == 2, result
    finally:
        revise.MAX_EVAL_ROUNDS = orig
    print("curate_app 达上限强制终止: OK")


def test_curate_incremental_review():
    from Agent.app import curate_app
    obs = []
    for sid, oid in [("s1","a1"),("s1","a2"),("s2","a3"),("s3","a4"),
                     ("s4","b1"),("s5","b2"),("s5","b3"),("s6","b4")]:
        obs.append(_obs(sid, oid, "角色获知关键信息，改变了对局面的认知"))
    funcs = [
        {"function_name": "F_A", "definition": "角色获知关键信息并据此行动",
         "supporting_obs_ids": ["a1","a2","a3","a4"], "realization_patterns": ["发现线索"],
         "hard_negatives": [], "confusable_functions": []},
        {"function_name": "F_B", "definition": "角色获知关键信息并据此行动",
         "supporting_obs_ids": ["b1","b2","b3","b4"], "realization_patterns": ["获得情报"],
         "hard_negatives": [], "confusable_functions": []},
    ]
    calls = {"n": 0}

    def fake_eval(messages, schema, **kw):
        cards = json.loads(messages[1]["content"].split("\n", 1)[1])
        calls["n"] += 1
        calls[calls["n"]] = [c["function_name"] for c in cards]
        return EvaluatorReviewResponse(reviews=[
            FunctionQualityReview(
                function_name=c["function_name"], bidirectional_conflation=False, conflation_reason="",
                genre_surface_binding=False, binding_reason="", granularity="ok", recommendation="OK",
            ) for c in cards
        ])

    def fake_revise(messages, schema, **kw):
        return MergeResponse(merged_functions=[MergedFunction(
            function_name="F_AB", definition="角色获知关键信息并据此行动",
            realization_patterns=["发现线索", "获得情报"],
            hard_negatives=[], confusable_functions=[],
        )])

    orig_eval, orig_revise = ev_module.chat_structured, revise.chat_structured
    max_rounds = revise.MAX_EVAL_ROUNDS
    revise.MAX_EVAL_ROUNDS = 1
    try:
        with tempfile.TemporaryDirectory() as tmp:
            reg = os.path.join(tmp, "functions.jsonl")
            bank = os.path.join(tmp, "observations.jsonl")
            report_path = os.path.join(tmp, "report.json")
            _write_lines(reg, funcs)
            _write_lines(bank, obs)
            ev_module.chat_structured, revise.chat_structured = fake_eval, fake_revise
            result = curate_app.invoke({
                "messages": [],
                "evaluation_context": {"registry_file": reg, "bank_file": bank, "report_path": report_path},
                "evaluation_round": 0,
            }, config={"configurable": {"thread_id": "curate-inc"}})
            assert result["evaluation_round"] == 1, result
            assert calls["n"] == 2, calls  # 第 1 轮全量 + 第 2 轮增量
            assert calls[1] == ["F_A", "F_B"], calls
            assert calls[2] == ["F_AB"], calls
            with open(reg, "r", encoding="utf-8") as f:
                names = {json.loads(l)["function_name"] for l in f if l.strip()}
            assert names == {"F_AB"}, names
            # curate_run 落盘依赖：checkpointer 历史可回溯每轮 revise_report
            rounds = []
            for snap in curate_app.get_state_history({"configurable": {"thread_id": "curate-inc"}}):
                rr = (snap.values or {}).get("revise_report")
                if rr and rr.get("before_count") is not None and rr not in rounds:
                    rounds.append(rr)
            assert len(rounds) == 1, rounds
            assert rounds[0]["merged"][0]["merged_as"] == "F_AB", rounds
            assert rounds[0]["changed"] == ["F_AB"], rounds
    finally:
        ev_module.chat_structured, revise.chat_structured = orig_eval, orig_revise
        revise.MAX_EVAL_ROUNDS = max_rounds
    print("curate_app 增量复核（第 2 轮只评 merge 产物）+ 轮次历史回溯: OK")


def test_curate_pass_early():
    from Agent.app import curate_app
    obs, funcs = make_set()
    fake = EvaluatorReviewResponse(reviews=[
        FunctionQualityReview(
            function_name=f["function_name"], bidirectional_conflation=False, conflation_reason="",
            genre_surface_binding=False, binding_reason="", granularity="ok", recommendation="OK",
        )
        for f in funcs
    ])
    with tempfile.TemporaryDirectory() as tmp:
        reg = os.path.join(tmp, "functions.jsonl")
        bank = os.path.join(tmp, "observations.jsonl")
        report_path = os.path.join(tmp, "report.json")
        _write_lines(reg, funcs)
        _write_lines(bank, obs)
        orig = ev_module.chat_structured
        ev_module.chat_structured = lambda messages, schema, **kw: fake
        try:
            result = curate_app.invoke({
                "messages": [],
                "evaluation_context": {"registry_file": reg, "bank_file": bank, "report_path": report_path},
                "evaluation_round": 0,
            }, config={"configurable": {"thread_id": "curate-pass"}})
        finally:
            ev_module.chat_structured = orig
        assert result["evaluator_decision"] == "PASS", result.get("evaluation_report", {}).get("dimensions")
        assert result["evaluation_round"] == 0, result
    print("curate_app PASS 提前终止: OK")


if __name__ == "__main__":
    test_union_supporting()
    test_assign_split_obs()
    test_dedup_names()
    test_story_count()
    test_recalc_confidence_stub()
    test_revise_node_actions()
    test_curate_max_rounds()
    test_curate_pass_early()
    test_curate_incremental_review()
    print("\n全部 Revise/curate_app 测试通过")