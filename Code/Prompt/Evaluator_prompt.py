"""
Evaluator_v0 抽象质量复核 Prompt - LLM 逐函数判定抽象质量
覆盖：定义双向混叠、题材表层绑定、抽象粒度；输出处置建议。
"""

from pydantic import BaseModel, Field


class FunctionQualityReview(BaseModel):
    function_name: str = Field(description="被评估的函数名")
    bidirectional_conflation: bool = Field(description="定义是否把两个相反方向混在一个 Function 中（如“揭露或掩盖”“建立或恶化”）")
    conflation_reason: str = Field(description="若双向混叠，说明具体是哪两个方向；否则为空字符串")
    genre_surface_binding: bool = Field(description="名称/定义/实现模式是否绑定特定题材表层（如重生/穿越/系统/鬼魂/僵尸/丹药/修仙/宫斗/总裁/豪门/闪婚），而非常见叙事结构")
    binding_reason: str = Field(description="若题材绑定，说明绑定词与应抽象的方向；否则为空字符串")
    granularity: str = Field(description="抽象粒度：too_specific（太具体）/ ok（中间粒度合适）/ too_broad（太宽泛）")
    recommendation: str = Field(description="处置建议：OK / REVISE（修订定义）/ SPLIT（把相反方向拆开）；近义合并统一走 merge_groups 字段")


class EvaluatorReviewResponse(BaseModel):
    reviews: list[FunctionQualityReview]
    merge_groups: list[list[str]] = Field(
        default_factory=list,
        description="本批函数中语义重复或近义、应合并为一组的函数名分组（每组 ≥2 个，组间不重叠）",
    )


EVALUATOR_SYSTEM_PROMPT = """你是叙事结构本体质量评审。对每个候选 Function（叙事功能）做抽象质量检查。

Function 应满足：去掉人物、世界观和具体动作后，描述“事件在故事发展中起的结构性作用”，粒度处于中间层次。

逐函数检查三件事：

1. 双向混叠（bidirectional_conflation）：定义是否把两个相反方向合在一个函数里，例如“被揭露或掩盖”“身份转变或揭示”“建立、改善或恶化”。一个 Function 只应承担单一结构作用；反方向应拆分（SPLIT）或重新定义（REVISE）。

2. 题材表层绑定（genre_surface_binding）：名称/定义/realization_patterns 是否绑定特定题材的表层设定（如重生、穿越、系统、鬼魂、僵尸、丹药、修仙、宫斗、总裁、豪门、闪婚、警匪等），而不是抽象为通用叙事结构。题材特有表层应抽象成结构作用。

3. 抽象粒度（granularity）：too_specific（绑定具体故事/道具，如“获得龙剑”“鬼魂现身搭话”）、ok（中间粒度，如“获得关键资源”“遭遇超自然现象”）、too_broad（宽泛到失去区分度，如“重要变化”“关系变化”）。

输出 recommendation：OK（无需处理）/ REVISE（修订定义或抽象化）/ SPLIT（把相反方向拆成多个函数）。

近义合并（定义语义重复或近义、应合并为一个 Function 的函数）请**填在 merge_groups 字段**：每组为函数名列表（≥2 个、组间不重叠、只收确定近义的组）；不要在 recommendation 里标 MERGE。

不要修改函数名，不要改 Function 数量，只做判断。请以 JSON（json_object）格式输出，字段与上面 schema 一致：{"reviews": [每项含 function_name / bidirectional_conflation / conflation_reason / genre_surface_binding / binding_reason / granularity / recommendation], "merge_groups": [["函数名A", "函数名B"], ...]}。"""
