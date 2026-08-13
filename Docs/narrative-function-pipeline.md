# Narrative Function 自动构建 Pipeline

> LangGraph 驱动的叙事功能发现多智能体框架。此 Rule 指导 AI 在 Cursor 中构建、执行和维护一个自动化叙事本体构建系统。

---

## 1. 核心概念映射

| LangGraph 概念 | 叙事框架对应 |
|----------------|-------------|
| **State** | `NarrativeState` — 包含 observations、candidate_functions、registry |
| **Node** | 各处理模块（Observer、Matcher、Curator 等） |
| **Edge** | 模块间的数据流路由 |
| **ConditionalEdge** | Matcher/ Critic 的分类决策路由 |
| **Checkpointer** | Registry 持久化（function_registry.json） |
| **Memory** | observation_bank 观测库 |
| **Human-in-the-loop** | Human Review 人工审核节点 |
| **Subgraph** | Bootstrap subgraph（初始化子图） |

---

## 2. Pipeline 架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              Bootstrap Phase（一次性）                        │   │
│  │                                                             │   │
│  │  stories_corpus → Observer → observation_bank               │   │
│  │                              ↓                               │   │
│  │                    Retrieval (Mode A)                        │   │
│  │                              ↓                               │   │
│  │                        Inducer                              │   │
│  │                              ↓                               │   │
│  │              Candidate Functions → Evaluator_v0             │   │
│  │                              ↓ (pass)                        │   │
│  │                    function_registry_v0                      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              ↓                                     │
│                              ↓                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              Evolve Phase（永久循环）                         │   │
│  │                                                             │   │
│  │  new_story → Observer → observation_bank                    │   │
│  │                        ↓                                    │   │
│  │              Retrieval (Mode B)                             │   │
│  │                        ↓                                    │   │
│  │                   Matcher                                   │   │
│  │         ↓         ↓         ↓                            │   │
│  │      MATCH/     CONFLICT/    NOVEL                        │   │
│  │      EXTEND     UNCERTAIN                                  │   │
│  │         ↓            ↓            ↓                        │   │
│  │   Update      Critic → 4类   novelty_pool                 │   │
│  │   Registry     判定        ↓                              │   │
│  │                         (resolved → challenge_pool)        │   │
│  │                                                             │   │
│  │  [每20-30条] → Evaluator_mid                              │   │
│  │         ↓ (异常)                                           │   │
│  │       Curator ← pools 达到阈值                            │   │
│  │         ↓                                                 │   │
│  │    Human Review                                           │   │
│  │         ↓                                                 │   │
│  │   Apply Registry                                          │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. State 定义

```python
from typing import TypedDict, Annotated, Sequence
from langgraph.graph import add_messages
from pydantic import BaseModel, Field
from datetime import datetime
import operator

# ── Narrative Observation ──────────────────────────────────────────────

class NarrativeObservation(TypedDict):
    """单条叙事观测的结构化表示"""
    obs_id: str
    source_story: str
    prior_context: str
    event: str
    participants: list[str]
    before_state: str
    after_state: str
    affected_aspect: str
    narrative_effect: str
    created_at: str

# ── Function Card ────────────────────────────────────────────────────────

class FunctionCard(BaseModel):
    """叙事功能的完整定义卡片"""
    function_id: str
    name: str
    definition: str
    structural_significance: str
    typical_contexts: list[str]
    consequences: list[str]
    surface_realizations: list[str]  # EXTEND 扩展的表层案例
    supporting_observations: list[str]
    hard_negatives: list[str]        # 边界反例
    confusable_functions: list[str]   # 易混淆功能
    confidence: float = 0.5
    version: int = 1
    updated_at: str = ""

# ── Pipeline State ──────────────────────────────────────────────────────

class NarrativeState(TypedDict):
    """LangGraph Pipeline 的全局状态"""
    messages: Annotated[list, add_messages]
    observations: list[NarrativeObservation]
    candidate_functions: list[FunctionCard]
    function_registry: list[FunctionCard]
    novelty_pool: list[NarrativeObservation]
    challenge_pool: list[dict]  # {obs, candidates, confusion_reason}
    evaluation_report: dict | None
    curator_proposal: dict | None
    human_review_decision: str | None  # APPROVE / MODIFY / REJECT
    processed_count: int
    last_evaluation_trigger: int
```

---

## 4. Node 实现模板

### 4.1 Observer Node

```python
def observer_node(state: NarrativeState, config) -> NarrativeState:
    """
    输入：原始 story 文本
    输出：多条结构化 Narrative Observations

    核心职责：从单篇故事中提取具备叙事意义的事件单元

    关键规则：
    1. 禁止为 Observation 标注 Function 标签
    2. 仅单故事处理，不跨故事对比
    3. 聚焦叙事结构，忽略表层动作
    """
    story = state["messages"][-1].content
    story_id = extract_story_id(story)

    # 调用 LLM 提取叙事结构
    raw_events = extract_events_from_story(story)

    new_observations = []
    for event in raw_events:
        obs = {
            "obs_id": generate_obs_id(),
            "source_story": story_id,
            "prior_context": event.get("prior_context", ""),
            "event": event.get("event", ""),
            "participants": event.get("participants", []),
            "before_state": event.get("before_state", ""),
            "after_state": event.get("after_state", ""),
            "affected_aspect": event.get("affected_aspect", ""),
            "narrative_effect": event.get("narrative_effect", ""),
            "created_at": datetime.now().isoformat(),
        }
        new_observations.append(obs)

    return {
        "observations": state["observations"] + new_observations,
        "messages": state["messages"] + [HumanMessage(
            content=f"提取了 {len(new_observations)} 条 Narrative Observations"
        )],
    }
```

### 4.2 Retrieval Node

```python
def retrieval_node(state: NarrativeState, config) -> NarrativeState:
    """
    输入：单条 Observation 或候选 Function
    输出：Top-k 结构相似对象

    两种运行模式：
    - Mode A (Bootstrap)：检索跨故事相似观测，供给 Inducer
    - Mode B (Evolve)：检索注册表内相似 Function，供给 Matcher
    """
    mode = config.get("configurable", {}).get("retrieval_mode", "B")

    if mode == "A":
        # Bootstrap: 从 observation_bank 检索相似观测
        # 用于 Inducer 归纳初始 Function
        results = vector_search_observations(
            query=state.get("induction_query", ""),
            top_k=config.get("configurable", {}).get("top_k", 10),
            collection="observation_bank",
        )
    else:
        # Evolve: 从 function_registry 检索相似 Function
        # 用于 Matcher 匹配
        results = vector_search_functions(
            query=state.get("matcher_query", ""),
            top_k=config.get("configurable", {}).get("top_k", 5),
            collection="function_registry",
        )

    return {"retrieval_results": results}
```

### 4.3 Inducer Node

```python
def inducer_node(state: NarrativeState, config) -> NarrativeState:
    """
    输入：多份跨故事、结构近似的 Observation 集合
    输出：候选 Function（附带完整 Function Card 草稿）

    核心职责：剥离人物、世界观、表层动作，抽象统一叙事结构性作用

    关键规则：
    1. 必须依托多条不同故事证据，禁止单样本生成 Function
    2. 抽象粒度适中（避免过细如 ACQUIRE_SWORD，过泛如 IMPORTANT_CHANGE）
    3. 必须配套 Hard Negatives 反例界定边界
    """
    obs_set = state.get("induction_observations", [])

    if len(obs_set) < 2:
        return {"messages": state["messages"] + [AIMessage(
            content="Inducer 需要至少 2 条跨故事观测才能归纳 Function"
        )]}

    # 调用 LLM 抽象归纳
    candidate = abstract_function_from_observations(obs_set)

    return {
        "candidate_functions": state["candidate_functions"] + [candidate],
        "messages": state["messages"] + [AIMessage(
            content=f"归纳了候选 Function: {candidate.name}"
        )],
    }
```

### 4.4 Matcher Node

```python
from enum import Enum

class MatchDecision(str, Enum):
    MATCH = "MATCH"
    EXTEND = "EXTEND"
    CONFLICT = "CONFLICT"
    UNCERTAIN = "UNCERTAIN"
    NOVEL = "NOVEL"

def matcher_node(state: NarrativeState, config) -> NarrativeState:
    """
    输入：新 Observation + 检索得到的 top-k 候选 Function
    输出：5 类决策

    核心职责：对比观测与现有叙事功能，给出初步归类
    """
    obs = state.get("current_observation", {})
    candidates = state.get("retrieval_results", [])

    # 调用 LLM 做分类决策
    decision = classify_observation(obs, candidates)

    # 路由决策
    if decision == MatchDecision.MATCH:
        action = "update_registry"
        pool_update = {}
    elif decision == MatchDecision.EXTEND:
        action = "update_registry_extend"
        pool_update = {}
    elif decision == MatchDecision.CONFLICT:
        action = "send_to_critic"
        pool_update = {}
    elif decision == MatchDecision.UNCERTAIN:
        action = "send_to_critic"
        pool_update = {}
    elif decision == MatchDecision.NOVEL:
        action = "add_to_novelty_pool"
        pool_update = {"novelty_pool": state["novelty_pool"] + [obs]}

    return {
        "match_decision": decision,
        "next_action": action,
        "novelty_pool": pool_update.get("novelty_pool", state["novelty_pool"]),
        "messages": state["messages"] + [AIMessage(
            content=f"Matcher 决策: {decision.value} → {action}"
        )],
    }
```

### 4.5 Critic Node

```python
class CriticDecision(str, Enum):
    MATCH = "match"
    EXTEND = "extend"
    NOVEL = "novel"
    RESOLVED = "resolved"

def critic_node(state: NarrativeState, config) -> NarrativeState:
    """
    输入：CONFLICT/UNCERTAIN 观测 + 对应候选 Function
    输出：match / extend / novel / resolved 四类最终判定

    核心职责：Matcher 二次校验单元，处理边界模糊、冲突案例

    关键规则：
    1. match：初次匹配判断无误
    2. extend：需扩充功能表层案例
    3. novel：无适配功能
    4. resolved：厘清边界即可归类，送入 challenge_pool
    """
    obs = state.get("current_observation", {})
    candidates = state.get("retrieval_results", [])
    match_decision = state.get("match_decision", "")

    # 查阅 Function Card 中的 Hard Negatives 和 Confusable Functions
    decision = second_opinion_verification(
        obs=obs,
        candidates=candidates,
        original_decision=match_decision,
    )

    if decision == CriticDecision.RESOLVED:
        challenge = {
            "obs": obs,
            "candidates": candidates,
            "confusion_reason": "厘清边界后归类",
            "resolved_to": "challenge_pool",
        }
        pool_update = {"challenge_pool": state["challenge_pool"] + [challenge]}
    else:
        pool_update = {}

    return {
        "critic_decision": decision,
        "challenge_pool": pool_update.get("challenge_pool", state["challenge_pool"]),
        "messages": state["messages"] + [AIMessage(
            content=f"Critic 最终判定: {decision.value}"
        )],
    }
```

### 4.6 Evaluator_v0 Node

```python
EVALUATION_DIMENSIONS = [
    "coverage",       # 覆盖率：Bootstrap corpus 中能被解释的比例
    "cohesion",      # 内聚度：Function 内部 embedding 相似度
    "separation",    # 分离度：不同 Function 之间区分度
    "abstraction_quality",  # 抽象质量：是否忽略表层动作
    "evidence_count",       # 证据量：每个 Function 的跨故事证据数
    "diversity",            # 语料多样性：Bootstrap corpus 是否跨类型
]

def evaluator_v0_node(state: NarrativeState, config) -> NarrativeState:
    """
    输入：Bootstrap 阶段全部候选 Function 集合
    输出：通过/不通过判定，不通过则输出优化建议

    核心职责：校验初始本体 O₀ 质量，达标后进入迭代演化阶段

    通过条件：≥ 4/6 维度达标
    """
    candidates = state.get("candidate_functions", [])
    corpus = state.get("bootstrap_corpus", [])

    report = evaluate_function_set(
        functions=candidates,
        corpus=corpus,
        dimensions=EVALUATION_DIMENSIONS,
    )

    passed = sum(report["dimension_scores"].values()) >= 4

    if passed:
        decision = "PASS"
        next_node = "registry_init"
    else:
        decision = "FAIL"
        next_node = "inducer_retry"
        report["recommendations"] = generate_recommendations(report)

    return {
        "evaluation_report": report,
        "evaluator_decision": decision,
        "next_node": next_node,
        "messages": state["messages"] + [AIMessage(
            content=f"Evaluator_v0: {decision} ({sum(report['dimension_scores'].values())}/6 维度达标)"
        )],
    }
```

### 4.7 Update Registry Node

```python
def update_registry_node(state: NarrativeState, config) -> NarrativeState:
    """
    输入：Matcher/Critic 输出 MATCH、EXTEND 分类结果
    输出：版本更新后的 function_registry

    核心职责：增量更新已有叙事功能卡片，仅做补充不改动核心定义

    MATCH 更新：增加支撑观测、正例、提升置信度、记录版本
    EXTEND 更新：新增表层实现案例、扩充适用场景、记录版本

    禁止操作：新增/删除/合并/拆分 Function（归 Curator 负责）
    """
    decision = state.get("match_decision", "")
    obs = state.get("current_observation", {})
    candidates = state.get("retrieval_results", [])

    updated_registry = state["function_registry"].copy()

    if decision == MatchDecision.MATCH:
        # MATCH：补充证据，提升置信度
        for func in updated_registry:
            if func.function_id == candidates[0].function_id:
                func.supporting_observations.append(obs["obs_id"])
                func.confidence = min(func.confidence + 0.05, 1.0)
                func.version += 1
                func.updated_at = datetime.now().isoformat()

    elif decision == MatchDecision.EXTEND:
        # EXTEND：扩充表层案例
        for func in updated_registry:
            if func.function_id == candidates[0].function_id:
                if obs.get("surface_form"):
                    func.surface_realizations.append(obs["surface_form"])
                func.version += 1
                func.updated_at = datetime.now().isoformat()

    return {
        "function_registry": updated_registry,
        "messages": state["messages"] + [AIMessage(
            content="Registry 已更新"
        )],
    }
```

### 4.8 Evaluator_mid Node

```python
def evaluator_mid_node(state: NarrativeState, config) -> NarrativeState:
    """
    输入：累计批量观测数据 + 当前完整 Function 注册表
    输出：健康度判定，指标异常则触发 Curator

    核心职责：迭代阶段周期性体检，监控本体整体健康程度

    触发时机：每处理 20-30 条新观测
    """
    processed = state.get("processed_count", 0)
    last_trigger = state.get("last_evaluation_trigger", 0)

    # 每 20-30 条触发一次评估
    if processed - last_trigger < 20:
        return {"messages": state["messages"] + [AIMessage(
            content="Evaluator_mid: 未达到触发阈值"
        )]}

    report = evaluate_function_set(
        functions=state["function_registry"],
        corpus=state["observations"],
        dimensions=["coverage", "novelty_rate", "cohesion", "separation",
                    "stability", "compression_rate"],
        mode="mid",
    )

    # 检查异常指标
    anomalies = []
    thresholds = {
        "coverage": 0.8,
        "novelty_rate": 0.15,
        "cohesion": 0.7,
        "separation": 0.7,
    }
    for dim, score in report["dimension_scores"].items():
        if dim in thresholds and score < thresholds[dim]:
            anomalies.append(f"{dim} 低于阈值 ({score:.2f} < {thresholds[dim]})")

    if anomalies:
        return {
            "evaluation_report": report,
            "anomalies": anomalies,
            "last_evaluation_trigger": processed,
            "next_action": "trigger_curator",
            "messages": state["messages"] + [AIMessage(
                content=f"Evaluator_mid: 发现 {len(anomalies)} 项异常指标 → 触发 Curator"
            )],
        }

    return {
        "evaluation_report": report,
        "last_evaluation_trigger": processed,
        "next_action": "continue",
        "messages": state["messages"] + [AIMessage(
            content=f"Evaluator_mid: 本体健康 (processed={processed})"
        )],
    }
```

### 4.9 Curator Node

```python
from enum import Enum

class CuratorAction(str, Enum):
    ADD = "ADD"           # 新增 Function
    MERGE = "MERGE"       # 合并 Function
    SPLIT = "SPLIT"       # 拆分 Function
    REVISE = "REVISE"     # 修订 Function 定义
    DEPRECATE = "DEPRECATE"  # 废弃 Function
    ADD_VALIDATOR = "ADD_VALIDATOR"  # 补充边界反例

def curator_node(state: NarrativeState, config) -> NarrativeState:
    """
    输入：novelty_pool、challenge_pool、Evaluator_mid 异常报告
    输出：包含理由、预期效果、风险评估的 Function 修改方案

    核心职责：统筹全局本体优化

    触发条件满足其一：
    - novelty_pool ≥ 5
    - challenge_pool ≥ 5
    - 中期评估指标异常
    """
    novelty = state.get("novelty_pool", [])
    challenge = state.get("challenge_pool", [])
    anomalies = state.get("anomalies", [])

    # 分析池内观测
    proposals = []

    if len(novelty) >= 5:
        # 聚类分析 novelty_pool
        clusters = cluster_observations(novelty)
        for cluster in clusters:
            proposals.append({
                "action": CuratorAction.ADD,
                "evidence": cluster,
                "reason": f"novelty_pool 有 {len(cluster)} 个相似观测",
                "expected_effect": "Coverage ↑, Novelty Rate ↓",
                "risk": "需验证是否与现有 Function 重叠",
            })

    if len(challenge) >= 5:
        # 分析 challenge_pool 中的混淆模式
        conflicts = analyze_confusion_patterns(challenge)
        for conflict in conflicts:
            proposals.append({
                "action": conflict["recommended_action"],
                "target_function": conflict["function_id"],
                "reason": conflict["confusion_type"],
                "expected_effect": conflict["expected_improvement"],
                "risk": conflict["risk_assessment"],
            })

    if anomalies:
        for anomaly in anomalies:
            proposals.append({
                "action": resolve_anomaly(anomaly),
                "reason": anomaly,
                "expected_effect": f"修复 {anomaly}",
                "risk": "修改可能影响现有分类结果",
            })

    return {
        "curator_proposals": proposals,
        "messages": state["messages"] + [AIMessage(
            content=f"Curator 生成 {len(proposals)} 个维护方案"
        )],
    }
```

### 4.10 Human Review Node

```python
def human_review_node(state: NarrativeState, config) -> NarrativeState:
    """
    输入：Curator 生成的本体修改方案
    输出：APPROVE 通过 / MODIFY 修改 / REJECT 驳回

    核心职责：人在回路终审，把控叙事本体理论质量

    审核要点：
    1. 修改依据充分性
    2. 优化预期合理性
    3. 变更风险
    4. Function Card 规范度
    """
    proposals = state.get("curator_proposals", [])

    if not proposals:
        return {"human_review_decision": None}

    # 格式化方案供人工审核
    formatted_proposals = format_proposals_for_review(proposals)

    # 等待人工输入（在实际实现中是外部触发）
    # 模拟返回待审核状态
    return {
        "pending_review": formatted_proposals,
        "messages": state["messages"] + [AIMessage(
            content=f"等待 Human Review: {len(proposals)} 个方案待审核"
        )],
    }
```

---

## 5. Conditional Edges（条件路由）

```python
from langgraph.graph import StateGraph, END

# ── Matcher 条件路由 ────────────────────────────────────────────────

def route_matcher(state: NarrativeState) -> str:
    """Matcher 决策 → 下一节点路由"""
    decision = state.get("match_decision", "")

    if decision in [MatchDecision.MATCH, MatchDecision.EXTEND]:
        return "update_registry"
    elif decision in [MatchDecision.CONFLICT, MatchDecision.UNCERTAIN]:
        return "critic"
    elif decision == MatchDecision.NOVEL:
        return "novelty_pool"
    return END

# ── Critic 条件路由 ─────────────────────────────────────────────────

def route_critic(state: NarrativeState) -> str:
    """Critic 最终判定 → 下一节点路由"""
    decision = state.get("critic_decision", "")

    if decision == CriticDecision.MATCH:
        return "update_registry"
    elif decision == CriticDecision.EXTEND:
        return "update_registry"
    elif decision == CriticDecision.NOVEL:
        return "novelty_pool"
    elif decision == CriticDecision.RESOLVED:
        return "challenge_pool"
    return END

# ── Evaluator_mid 条件路由 ──────────────────────────────────────────

def route_evaluation(state: NarrativeState) -> str:
    """Evaluator_mid 判定 → 下一节点路由"""
    action = state.get("next_action", "")

    if action == "trigger_curator":
        return "curator"
    return "observer"  # 继续处理下一条

# ── Curator 条件路由 ────────────────────────────────────────────────

def route_curator(state: NarrativeState) -> str:
    """Curator → Human Review 或结束"""
    proposals = state.get("curator_proposals", [])

    if proposals:
        return "human_review"
    return END

# ── Human Review 条件路由 ───────────────────────────────────────────

def route_human_review(state: NarrativeState) -> str:
    """Human Review 决策 → 执行或驳回"""
    decision = state.get("human_review_decision", "")

    if decision == "APPROVE":
        return "apply_registry"
    elif decision == "MODIFY":
        return "curator"  # 退回修改
    elif decision == "REJECT":
        return END
    return END
```

---

## 6. 图构建与编译

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent

def build_narrative_pipeline() -> StateGraph:
    """构建完整的 Narrative Function Pipeline"""

    # ── 创建图 ────────────────────────────────────────────────────

    workflow = StateGraph(NarrativeState)

    # ── 注册节点 ──────────────────────────────────────────────────

    workflow.add_node("observer", observer_node)
    workflow.add_node("retrieval", retrieval_node)
    workflow.add_node("inducer", inducer_node)
    workflow.add_node("evaluator_v0", evaluator_v0_node)
    workflow.add_node("matcher", matcher_node)
    workflow.add_node("critic", critic_node)
    workflow.add_node("update_registry", update_registry_node)
    workflow.add_node("evaluator_mid", evaluator_mid_node)
    workflow.add_node("curator", curator_node)
    workflow.add_node("human_review", human_review_node)
    workflow.add_node("novelty_pool_node", novelty_pool_node)
    workflow.add_node("challenge_pool_node", challenge_pool_node)

    # ── Bootstrap 边 ──────────────────────────────────────────────

    workflow.add_edge(START, "observer")
    workflow.add_edge("observer", "retrieval")
    workflow.add_edge("retrieval", "inducer")
    workflow.add_edge("inducer", "evaluator_v0")

    workflow.add_conditional_edges(
        "evaluator_v0",
        lambda state: state.get("evaluator_decision", "FAIL"),
        {
            "PASS": "update_registry",
            "FAIL": "inducer",  # 退回重试
        }
    )

    workflow.add_edge("update_registry", END)  # Bootstrap 结束

    # ── Evolve 边 ───────────────────────────────────────────────

    workflow.add_edge("matcher", route_matcher)
    workflow.add_edge("critic", route_critic)
    workflow.add_edge("update_registry", "evaluator_mid")

    workflow.add_conditional_edges(
        "evaluator_mid",
        route_evaluation,
        {
            "trigger_curator": "curator",
            "continue": "observer",
        }
    )

    workflow.add_conditional_edges(
        "curator",
        route_curator,
        {
            "human_review": "human_review",
            "END": END,
        }
    )

    workflow.add_conditional_edges(
        "human_review",
        route_human_review,
        {
            "apply_registry": "update_registry",
            "curator": "curator",
            "END": END,
        }
    )

    # ── 编译 ──────────────────────────────────────────────────────

    checkpointer = InMemorySaver()

    app = workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],  # 人工审核前中断
    )

    return app
```

---

## 7. 使用示例

```python
# ── 初始化 ─────────────────────────────────────────────────────────

app = build_narrative_pipeline()

# ── Bootstrap Phase ────────────────────────────────────────────────

# 加载初始语料
corpus = load_story_corpus("data/folktales/*.txt")

# 批量注入 stories
for story in corpus:
    app.invoke(
        {"messages": [HumanMessage(content=story)]},
        config={
            "configurable": {
                "retrieval_mode": "A",
                "thread_id": "bootstrap",
            }
        }
    )

# 检查 Bootstrap 结果
state = app.get_state({"configurable": {"thread_id": "bootstrap"}})
print(f"初始 Function 数量: {len(state['candidate_functions'])}")

# ── Evolve Phase ───────────────────────────────────────────────────

# 持续处理新故事
new_story = load_new_story("data/new_story.txt")

app.invoke(
    {"messages": [HumanMessage(content=new_story)]},
    config={
        "configurable": {
            "retrieval_mode": "B",
            "thread_id": "evolve",
        }
    }
)

# ── 人工审核触发 ─────────────────────────────────────────────────

# 查看待审核方案
pending = app.get_state(
    config={"configurable": {"thread_id": "evolve"}}
)
print(pending["pending_review"])

# 提交审核决策
app.update_state(
    config={"configurable": {"thread_id": "evolve"}},
    values={"human_review_decision": "APPROVE"},
)
```

---

## 8. 与 Cursor AI 的集成

### 8.1 Cursor Rules 配置

```markdown
# .cursor/rules/narrative-function-pipeline.md

你正在参与构建一个自动化叙事功能发现系统。

核心概念：
- Narrative Observation：单条叙事结构化记录
- Function Card：叙事功能的完整定义
- function_registry：所有已注册功能的集合

处理原则：
1. 始终保持 Function 的抽象层次，避免混入具体角色名/物品名
2. 禁止在 Observation 阶段标注 Function
3. Matcher 的 MATCH 决策只补充证据，不修改 Function 定义
4. Curator 的 ADD 操作必须基于多条跨故事证据
5. 任何 Function 修改都必须经过 Human Review

模块职责边界：
- Observer：提取，不分类
- Matcher：初步分类，不确定时送 Critic
- Critic：最终判定，不修改 Registry
- Curator：提出方案，不直接执行
- Human Review：终审决策
```

### 8.2 在 Cursor 中运行 Pipeline

```python
# pipeline_runner.py

from langgraph.checkpoint.sqlite import SqliteSaver
from your_pipeline import build_narrative_pipeline

# 持久化检查点
checkpointer = SqliteSaver.from_conn_string("data/checkpoints.db")

app = build_narrative_pipeline()
app = app.compile(checkpointer=checkpointer)

# 启动 Evolve 循环
while True:
    new_story = watch_for_new_stories("data/inbox/")
    if new_story:
        app.invoke({"messages": [HumanMessage(content=new_story)]})
        print("Processed:", new_story)

    # 检查是否需要人工审核
    state = app.get_state(config={"configurable": {"thread_id": "evolve"}})
    if state.get("pending_review"):
        print("⚠️ 待人工审核:", state["pending_review"])
        break  # 等待人工介入
```

---

## 9. 检查点与持久化

```python
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.memory import InMemorySaver
import json

# ── 检查点策略 ────────────────────────────────────────────────────

CHECKPOINT_CONFIG = {
    "bootstrap": {
        "checkpointer": SqliteSaver.from_conn_string("data/checkpoints/bootstrap.db"),
        "interrupt_before": [],  # Bootstrap 不中断
    },
    "evolve": {
        "checkpointer": SqliteSaver.from_conn_string("data/checkpoints/evolve.db"),
        "interrupt_before": ["human_review"],  # 人工审核前必须中断
    }
}

# ── Registry 导出/导入 ─────────────────────────────────────────────

def export_registry(registry: list[FunctionCard], path: str):
    """导出 function_registry 到 JSON"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump([func.model_dump() for func in registry], f, ensure_ascii=False, indent=2)

def import_registry(path: str) -> list[FunctionCard]:
    """从 JSON 导入 function_registry"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [FunctionCard(**item) for item in data]
```

---

## 10. 关键实现要点

### 10.1 向量化与检索

```python
# embedding_model.py

from langchain_ollama import OllamaEmbeddings

embedding_model = OllamaEmbeddings(
    model="nomic-embed-text",
    base_url="http://localhost:11434",
)

def vector_search_observations(query: str, top_k: int, collection: str):
    """向量相似度检索"""
    query_embedding = embedding_model.embed_query(query)

    if collection == "observation_bank":
        # 检索 observation_bank
        results = milvus_client.search(
            collection_name="observations",
            vectors=[query_embedding],
            top_k=top_k,
        )
    else:
        # 检索 function_registry
        results = milvus_client.search(
            collection_name="functions",
            vectors=[query_embedding],
            top_k=top_k,
        )

    return results
```

### 10.2 LLM 调用封装

```python
# llm_utils.py

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

llm = ChatOpenAI(
    model="gpt-4o",
    temperature=0,
)

def extract_events_from_story(story: str) -> list[dict]:
    """从故事中提取叙事事件"""
    prompt = f"""
    从以下故事中提取叙事事件。每个事件应包含：
    - prior_context: 事件发生前的情境
    - event: 核心事件描述
    - participants: 参与者列表
    - before_state: 事件前状态
    - after_state: 事件后状态
    - affected_aspect: 受影响的叙事方面
    - narrative_effect: 叙事效果

    故事：
    {story}
    """

    response = llm.with_structured_output(list[dict]).invoke(prompt)
    return response

def abstract_function_from_observations(observations: list[dict]) -> FunctionCard:
    """从多个观测中归纳叙事功能"""
    prompt = f"""
    分析以下跨故事的叙事观测，抽象出共同的叙事功能：

    观测列表：
    {json.dumps(observations, ensure_ascii=False, indent=2)}

    请输出一个 Function Card，包含：
    - name: 功能名称（使用 SCREAMING_SNAKE_CASE）
    - definition: 精确定义
    - structural_significance: 结构意义
    - typical_contexts: 典型上下文
    - consequences: 叙事后果
    - surface_realizations: 表层实现变体
    - hard_negatives: 边界反例
    - confusable_functions: 易混淆功能
    """

    response = llm.with_structured_output(FunctionCard).invoke(prompt)
    return response
```

---

## 11. 调试与监控

```python
# debug_utils.py

def print_pipeline_state(state: NarrativeState):
    """格式化打印 Pipeline 状态"""
    print("=" * 60)
    print(f"observations: {len(state.get('observations', []))}")
    print(f"function_registry: {len(state.get('function_registry', []))}")
    print(f"novelty_pool: {len(state.get('novelty_pool', []))}")
    print(f"challenge_pool: {len(state.get('challenge_pool', []))}")
    print(f"processed_count: {state.get('processed_count', 0)}")
    print(f"last_evaluation_trigger: {state.get('last_evaluation_trigger', 0)}")

    if state.get("evaluation_report"):
        print("\nevaluation_report:")
        for k, v in state["evaluation_report"].items():
            print(f"  {k}: {v}")

    if state.get("curator_proposals"):
        print(f"\ncurator_proposals: {len(state['curator_proposals'])}")
        for p in state["curator_proposals"]:
            print(f"  - {p['action']}: {p['reason']}")

    print("=" * 60)
```

---

## 12. 文件结构建议

```
narrative-function-pipeline/
├── __init__.py
├── pipeline.py              # 图构建与编译
├── nodes/
│   ├── __init__.py
│   ├── observer.py
│   ├── retrieval.py
│   ├── inducer.py
│   ├── matcher.py
│   ├── critic.py
│   ├── evaluator_v0.py
│   ├── evaluator_mid.py
│   ├── update_registry.py
│   ├── curator.py
│   └── human_review.py
├── state.py                # State 定义
├── edges.py                # Conditional Edges
├── llm_utils.py            # LLM 调用封装
├── embedding_model.py       # 向量化模型
├── checkpointer.py         # 检查点管理
├── registry_io.py          # Registry 导入导出
├── debug_utils.py
└── examples/
    ├── bootstrap_example.py
    ├── evolve_example.py
    └── human_review_example.py
```

---

## 13. 测试策略

```python
# test_pipeline.py

def test_observer_extracts_correctly():
    """测试 Observer 能正确提取叙事事件"""
    state = NarrativeState(
        messages=[HumanMessage(content="主角张凡突然一剑击败了内门第一强者")],
        observations=[],
        function_registry=[],
    )
    result = observer_node(state, {})

    assert len(result["observations"]) > 0
    obs = result["observations"][0]
    assert "event" in obs
    assert "prior_context" in obs
    assert obs.get("participants") == ["张凡", "内门第一"]


def test_matcher_rejects_function_tagging():
    """测试 Matcher 禁止为 Observation 标注 Function"""
    # ... 测试逻辑


def test_curator_requires_minimum_evidence():
    """测试 Curator ADD 操作需要最低证据量"""
    state = NarrativeState(
        novelty_pool=[{"obs_id": "1"}, {"obs_id": "2"}],  # 不足 5 个
        challenge_pool=[],
    )
    result = curator_node(state, {})
    # 应该不生成 ADD 提案
    assert not any(p["action"] == CuratorAction.ADD for p in result.get("curator_proposals", []))


def test_evaluator_v0_requires_4_of_6_dimensions():
    """测试 Evaluator_v0 需要 4/6 维度达标"""
    # ... 测试逻辑
```

---

## 14. 与现有研究计划的对应

| Pipeline 组件 | 研究计划模块 | 核心职责 |
|-------------|------------|---------|
| `observer_node` | Observer | 从故事提取 Narrative Observations |
| `retrieval_node` | Retrieval | 向量检索相似对象 |
| `inducer_node` | Inducer | 从跨故事观测归纳 Function |
| `evaluator_v0_node` | Evaluator_v0 | Bootstrap 阶段质量校验 |
| `matcher_node` | Matcher | 5 类分类决策 |
| `critic_node` | Critic | 边界复检 |
| `update_registry_node` | Update Registry | 增量更新 Registry |
| `evaluator_mid_node` | Evaluator_mid | 周期性健康度评估 |
| `curator_node` | Curator | 本体维护方案生成 |
| `human_review_node` | Human Review | 人工终审 |

---

## 15. 依赖

```txt
# requirements.txt

langgraph>=0.2.0
langchain-core>=0.3.0
langchain-openai>=0.2.0
langchain-ollama>=0.1.0
pydantic>=2.0.0
pymilvus>=2.4.0
langgraph-checkpoint-sqlite>=2.0.0
```
