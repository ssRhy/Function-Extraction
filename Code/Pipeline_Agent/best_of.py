"""Best-of-2 候选筛选、硬门禁和正文比较。"""

import json
import os
from typing import Literal

from pydantic import BaseModel, Field

from FunctionExtract_Agent.llm import chat_structured


class BestOfReview(BaseModel):
    winner: Literal[1, 2]
    reason: str = Field(min_length=1)


BEST_OF_REVIEW_PROMPT = """你是两篇中文短篇的最终比较者。只比较以下四项：
1. 用户创作要求是否兑现；2. 因果是否连贯；3. 结局是否兑现；4. 正文质量。
不要重新抽取、判断或比较 Function，不使用 Planner 分数或其他维度，不输出数字评分。
只能返回符合 json schema 的对象：winner=1 或 winner=2，以及一句简短理由。"""


def _best_of(state):
    value = state.get("best_of", 1)
    if value not in (1, 2):
        raise ValueError("best_of 只支持 1 或 2")
    if value == 2 and state.get("planner_mode", "published") != "dynamic":
        raise ValueError("Best-of-2 只支持 planner_mode=dynamic")
    return value


def _dynamic_candidates(candidates, limit=2):
    selected = []
    seen = set()
    for candidate in candidates or []:
        if (candidate.get("validation") or {}).get("valid") is not True:
            continue
        function_ids = tuple(candidate.get("function_ids") or [
            step.get("function_id") for step in candidate.get("chain", [])
        ])
        if not function_ids or function_ids in seen:
            continue
        seen.add(function_ids)
        selected.append(candidate)
        if len(selected) == limit:
            break
    return selected


def _candidate_summary(index, outline, candidate=None):
    outline = outline or {}
    candidate = candidate or outline.get("dynamic_candidate") or {}
    steps = candidate.get("chain") or outline.get("chain") or []
    function_ids = candidate.get("function_ids") or [
        step.get("function_id") for step in steps if step.get("function_id")
    ]
    function_chain = candidate.get("function_names") or [
        step.get("function_name") for step in steps if step.get("function_name")
    ]
    outline_path = outline.get("result_path")
    validation = outline.get("validation") or {}
    return {
        "candidate_index": index,
        "candidate_id": candidate.get("candidate_id") or outline.get("pattern_name") or f"candidate_{index}",
        "beam_score": candidate.get("score"),
        "operations": candidate.get("operations", []),
        "function_ids": function_ids,
        "function_chain": function_chain,
        "outline_id": outline.get("outline_id"),
        "outline_json": os.path.abspath(str(outline_path)) if outline_path else None,
        "outline_validation": validation,
        "outline_ok": validation.get("overall_ok") is True,
        "story_json": None,
        "story_status": "not_run",
        "story_validation": None,
        "story_repair_count": 0,
        "function_execution_evidence": [],
        "function_evidence_coverage": {"passed": 0, "total": len(function_chain)},
        "hard_gate": False,
    }


def _story_hard_gate(candidate):
    validation = candidate.get("story_validation") or {}
    evidence = validation.get("function_execution_evidence") or []
    chain = candidate.get("function_chain") or []
    required = (
        "user_request_ok", "causal_constraints_ok", "character_consistency_ok",
        "ending_ok", "unsupported_solution_ok",
    )
    evidence_ok = len(evidence) == len(chain) and all(
        item.get("status") == "PASS"
        and item.get("segment_index") == index
        and item.get("function_name") == name
        for index, (name, item) in enumerate(zip(chain, evidence), 1)
    )
    return (
        candidate.get("story_status") in {"accepted", "rewritten"}
        and validation.get("overall_ok") is True
        and all(validation.get(key) is True for key in required)
        and evidence_ok
        and validation.get("length_ok", True) is True
    )


def _story_body(exported):
    story = exported.get("story") or {}
    return {"title": story.get("title", ""), "scenes": story.get("scenes", [])}


def _compare_candidates(request, candidates):
    result = chat_structured([
        {"role": "system", "content": BEST_OF_REVIEW_PROMPT},
        {"role": "user", "content": json.dumps({
            "user_request": request,
            "candidates": [
                {"candidate_id": f"candidate_{item['candidate_index']}", "story": _story_body(item["_story"])}
                for item in candidates
            ],
        }, ensure_ascii=False)},
    ], BestOfReview)
    return result.model_dump()


def _select_best_of(request, candidates):
    passed = [item for item in candidates if item["hard_gate"]]
    if len(passed) == 1:
        winner = passed[0]
        return {
            "mode": "best_of_2",
            "status": "selected",
            "winner": winner["candidate_id"],
            "winner_index": winner["candidate_index"],
            "reason": f"仅候选 {winner['candidate_index']} 通过 Story Validator 硬门禁，直接选用。",
            "review": None,
        }
    if not passed:
        return {
            "mode": "best_of_2",
            "status": "rejected",
            "winner": None,
            "winner_index": None,
            "reason": "两个候选均未通过 Story Validator 硬门禁。",
            "review": None,
        }
    review = _compare_candidates(request, passed)
    winner = next(item for item in passed if item["candidate_index"] == review["winner"])
    return {
        "mode": "best_of_2",
        "status": "selected",
        "winner": winner["candidate_id"],
        "winner_index": winner["candidate_index"],
        "reason": review["reason"],
        "review": review,
    }
