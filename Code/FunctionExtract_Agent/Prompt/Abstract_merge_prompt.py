"""
Abstract Merge Prompt - 全量近义组识别（由 abstract_merge 调用；实际合并复用 revise._llm_merge）
"""

from pydantic import BaseModel, Field


class AbstractMergeResponse(BaseModel):
    merge_groups: list[list[str]] = Field(
        default_factory=list,
        description="承担同一结构作用（近义/同族碎片）、应归并为一个新函数的函数名分组（每组 ≥2 个、组间不重叠）",
    )


ABSTRACT_MERGE_SYSTEM_PROMPT = """你是叙事结构本体整理者。以下是当前全部候选 Function（名称 + 定义 + 实现模式）。

请识别**承担同一结构作用**的函数组（近义或同族碎片，应归并为一个新函数）：
1. 同一结构作用 = 在故事中承担相同的叙事角色，只是表层/子类型/表述不同（如"获得资源/获得助力/获得情报"同属"获得资源或支持"；"危险征兆/异常预感/威胁信号"同属"威胁或异常征兆"）。
2. 每组 ≥2 个函数；一个函数最多归入一组；不确定的不要列出（宁少勿滥）。
3. 不要在这里命名或定义新函数——只输出应归并的旧函数名分组。
4. 合并后新函数的 supporting obs 规模应与现有函数一致；若合并会显著大于现有规模（形成超大类），该组不应合并。

只输出确信的组。请以 JSON（json_object）格式输出：{"merge_groups": [["旧函数名A", "旧函数名B"], ...]}。"""
