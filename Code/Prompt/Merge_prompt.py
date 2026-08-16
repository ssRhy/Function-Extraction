"""
MERGE 近义组 Prompt - LLM 把一组近义 Function 合并为一个统一 Function
"""

from pydantic import BaseModel, Field


class MergedFunction(BaseModel):
    function_name: str = Field(description="合并后函数名（英文大写下划线）")
    definition: str = Field(description="定义（中文1句，概括全组共同结构作用，去掉题材表层词）")
    realization_patterns: list[str] = Field(description="2-4个中间粒度实现模式，去除专名与题材设定")
    hard_negatives: list[str] = Field(description="1-2个反例")
    confusable_functions: list[str] = Field(description="1-2个易混淆Function（不能是组内成员）")


class MergeResponse(BaseModel):
    merged_functions: list[MergedFunction] = Field(description="合并后的函数列表（本任务为1个）")


MERGE_SYSTEM_PROMPT = """你是叙事结构本体维护者。以下是一组近义 Function（definition 语义几乎相同、概念重叠），请把它们合并为一个统一的 Function。

要求：
- 函数名用英文大写下划线，能代表这组函数共同的叙事结构作用；
- definition 用中文 1 句，概括全部成员的核心结构作用，去掉题材表层词（重生/穿越/系统/鬼魂/修仙/总裁/豪门等）；
- realization_patterns 2-4 个，保留动作机制、去专名与题材设定；
- hard_negatives 1-2 个；
- confusable_functions 1-2 个（不能是组内成员）。

只输出合并后的 1 个函数。请以 JSON（json_object）格式输出，字段与 schema 一致：merged_functions 数组。"""