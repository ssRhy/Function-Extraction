"""
REVISE/SPLIT 修订 Prompt - LLM 修订 Function 定义（去双向混叠/去题材绑定/调粒度）
"""

from pydantic import BaseModel, Field


class RevisedFunction(BaseModel):
    function_name: str = Field(description="修订后函数名（英文大写下划线，可微调）")
    definition: str = Field(description="定义（中文1句，单一结构作用，去掉题材表层词）")
    realization_patterns: list[str] = Field(description="2-4个中间粒度实现模式，去除专名与题材设定")
    hard_negatives: list[str] = Field(description="1-2个反例")
    confusable_functions: list[str] = Field(description="1-2个易混淆Function")


class ReviseResponse(BaseModel):
    revised_functions: list[RevisedFunction] = Field(description="修订后函数列表（REVISE 为1个；SPLIT 为多个）")


REVISE_SYSTEM_PROMPT = """你是叙事结构本体质量修订者。给定一个 Function 及其质量问题，修订它。

质量问题类型：
- 双向混叠：定义把两个相反方向合在一处（如"揭露或掩盖""建立或恶化"）→ 应拆分为多个 Function，每个承担单一方向；
- 题材表层绑定：名称/定义/实现模式绑定特定题材表层（重生/穿越/系统/鬼魂/僵尸/丹药/修仙/宫斗/总裁/豪门/闪婚/警匪等）→ 抽象为通用叙事结构作用；
- 粒度不当：too_specific（绑定具体故事/道具）→ 抽象到中间粒度；too_broad（宽泛失去区分度）→ 收敛到具体结构作用。

输出规则：
- 若需要拆分为多个方向/多个结构作用，输出多个 Function（revised_functions 数组 >1）；
- 否则输出 1 个修订后的 Function。
每个 Function 含 function_name / definition / realization_patterns(2-4) / hard_negatives(1-2) / confusable_functions(1-2)。
请以 JSON（json_object）格式输出，字段与 schema 一致：revised_functions 数组。"""