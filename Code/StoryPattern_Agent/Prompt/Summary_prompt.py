"""Story Pattern summary 的 LLM schema 与提示词。"""

from pydantic import BaseModel, Field


class EndingSpec(BaseModel):
    resolves: str = Field(min_length=1)
    must_show: list[str] = Field(min_length=1)
    final_state: str = Field(min_length=1)


class StoryPatternSummary(BaseModel):
    pattern_name: str = Field(min_length=1)
    abstract_definition: str = Field(min_length=1)
    optional_steps: list[str]
    applicability_conditions: list[str]
    counterexamples_limitations: list[str]
    ending_spec: EndingSpec | None = None


SUMMARY_SYSTEM_PROMPT = """你是故事结构模式总结器。请根据一个已经通过规则检查的 motif cluster，生成可审计的候选故事套路摘要。

只总结输入 cluster 已经支持的结构，不新增输入中没有的 Function，不把题材表层动作写成套路本体。核心 Function 链必须保持原有顺序，长度至少为 4；cluster 中不同 motif 的长度差异、重复或额外步骤可以写入 optional_steps。适用条件描述该结构何时适用，反例/限制必须基于输入中真实存在的差异或证据边界，不要凭空编造故事。

pattern_name 应简洁、抽象、可查询；abstract_definition 用一句到两句说明核心叙事变化。核心 Function 链由调用节点根据 anchor motif 自动绑定，模型不要输出 Function 选择字段。optional_steps、applicability_conditions、counterexamples_limitations 都输出字符串数组；没有内容时返回空数组。

ending_spec 暂停由 Pattern 归纳，固定返回 null；故事的具体结局仍由下游 Outline 的 ending 生成。

只输出 JSON，不要 Markdown，不要输出 cluster_id、Snapshot ID 或 evidence ID，这些字段由调用节点绑定。JSON 结构如下：
{"pattern_name": "模式名", "abstract_definition": "抽象定义", "optional_steps": [], "applicability_conditions": [], "counterexamples_limitations": [], "ending_spec": null}
"""
