"""
Matcher System Prompt - 新 Observation 与现有 Function Registry 五分类匹配（Evolve 阶段）
"""

from typing import Literal

from pydantic import BaseModel, Field


class MatchDecision(BaseModel):
    obs_id: str = Field(description="被判定 Observation 的 obs_id")
    label: Literal["MATCH", "EXTEND", "CONFLICT", "UNCERTAIN", "NOVEL"] = Field(
        description="MATCH=完美匹配；EXTEND=匹配但出现全新表层；CONFLICT=结构近似但与定义冲突；"
                    "UNCERTAIN=多个函数均可解释；NOVEL=无匹配",
    )
    matched_function: str | None = Field(default=None, description="MATCH/EXTEND/CONFLICT 时命中的函数名；否则为 null")
    candidate_functions: list[str] | None = Field(default=None, description="UNCERTAIN 时均可解释的函数名列表；否则为 null")
    reason: str | None = Field(default=None, description="一句话判定理由")


class MatchResponse(BaseModel):
    decisions: list[MatchDecision] = Field(description="每个 obs 一条判定")


MATCHER_SYSTEM_PROMPT = """你是一个叙事结构匹配器。你的任务是把一个 Observation（叙事观察）与现有 Function（叙事功能）Registry 比较，给出五分类决策。

## 五个类别
1. MATCH：该 Observation 可以由某个现有 Function 很好解释（结构作用一致）→ 补充该 Function 的证据。
2. EXTEND：Function 是对的，但该 Observation 出现了全新的表层实现形式（surface_form 与已知 realization_patterns 明显不同）→ 仍归入该 Function，更新 exemplars。
3. CONFLICT：与某个 Function 结构近似，但存在明显冲突（如方向相反、前置/后置状态矛盾）→ 送入挑战池复检。
4. UNCERTAIN：多个 Function 都能部分解释，无法确定唯一归属 → 送入挑战池复检。
5. NOVEL：现有 Function 都解释不了 → 存入新颖池，等待跨故事累积后归纳新 Function。

## 判定原则
- 只看结构作用（before/after 变化、narrative_effect），忽略表层动作差异（法宝/丹药/金钱都是"获得资源"）。
- 不要为了归类而强行 MATCH；把握不准时选 UNCERTAIN；明显冲突选 CONFLICT；确实无匹配选 NOVEL。
- 宁可把边界案例交给复检（CONFLICT/UNCERTAIN），也不要误 MATCH。
- 每批内所有 obs_id 都必须输出判定，不要遗漏。

## 输出格式
输出 JSON（json_object），字段与 schema 一致：
{"decisions": [{"obs_id": "...", "label": "MATCH", "matched_function": "函数名", "candidate_functions": [], "reason": "..."}]}"""
