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

ending_spec 是模板级的结局要求，不是额外 Function。只有当输入 cluster 的证据明确支持从核心冲突走向解决并稳定终态时才输出；如果 cluster 只是局部过程 motif，或没有足够结局证据，必须输出 null，不要替故事补写不存在的结局。非空时必须说明解决什么冲突、结局中必须出现哪些抽象动作、主角或核心关系最终处于什么稳定状态。

只输出 JSON，不要 Markdown，不要输出 cluster_id、Snapshot ID 或 evidence ID，这些字段由调用节点绑定。JSON 结构如下：
{"pattern_name": "模式名", "abstract_definition": "抽象定义", "optional_steps": [], "applicability_conditions": [], "counterexamples_limitations": [], "ending_spec": {"resolves": "待解决的核心冲突", "must_show": ["必须出现的解决动作"], "final_state": "稳定终态"}}
没有结局证据时将 ending_spec 设为 null。
"""
