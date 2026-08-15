# Story Morphology - 故事形态学分析系统

基于 Vladimir Propp 的"故事形态学"理论，使用 LLM + 向量检索自动归纳民间故事的结构功能（Functions）。

## 系统架构

系统分为 **Bootstrap** 和 **Evolve** 两个阶段。

### Bootstrap（仅首次运行）

```
Corpus → Pre-Processor → Observer → Observation Bank
                                       ↓
                                 Retrieval → Inducer → Function Registry (O_0)
                                                            ↓
                                                   Evaluator_v0 → Evolve
```

1. **Pre-Processor** — 读取原始故事文本，LLM 分句分段
2. **Observer** — 逐句分析，提取 `NarrativeObservation`（叙事观察）：前因、事件、结果、影响维度
3. **Observation Bank** — 持久化存储 + 向量索引（ChromaDB + JSONL）
4. **Retrieval** — 跨故事语义检索




## 目录结构

```
Code/
├── Agent/
│   ├── app.py              # LangGraph 图定义（pipeline_app）
│   ├── llm.py              # DeepSeek API 统一封装
│   ├── observer.py         # Observer 节点：从句子提取 NarrativeObservation
│   ├── pre_processor.py    # Pre-Processor 节点：分句分段
│   ├── confidence.py       # 多因子加权置信度计算
│   ├── inducer.py          # Inducer 节点：跨故事归纳 Function
│   └── state.py            # LangGraph State 定义
├── Bank/
│   ├── __init__.py
│   └── bank.py             # ObservationBank：ChromaDB + JSONL 双存储
├── Embedding/
│   ├── __init__.py
│   └── embedding.py        # Embedder：sentence-transformers 封装
├── Retrieval/
│   ├── __init__.py
│   └── retrieval.py        # Retriever：向量语义检索
├── Prompt/
│   ├── Pre_prompt.py       # Pre-Processor 系统提示词
│   ├── Observer_prompt.py  # Observer 系统提示词
│   └── Inducer_prompt.py   # Inducer 系统提示词
├── test/
│   ├── test_app.py         # Pipeline 端到端测试
│   ├── test_bank.py        # Bank + Retrieval 集成测试
│   └── story.txt           # 示例故事文本
└── data/
    ├── bank/               # Observation Bank 持久化
    │   ├── observations.jsonl
    │   └── chroma_db/
    └── registry/           # Function Registry 持久化
        └── functions.jsonl
```

## 安装

```bash
pip install sentence-transformers chromadb openai pydantic langgraph
```

Embedding 模型通过 `hf-mirror.com` 镜像自动下载，无需额外配置。

## 使用

### 端到端 Pipeline

```python
from Agent.app import pipeline_app

story_text = open("test/story.txt").read()

initial_state = {
    "messages": [],
    "raw_text": story_text,
    "story_config": {"story_type": "folktale"},
    "normalized_story": None,
    "observations": [],
    "current_phase": "bootstrap",
    "current_story_index": 0,
    "total_stories": 1
}

config = {"configurable": {"thread_id": "run-1"}}
result = pipeline_app.invoke(initial_state, config=config)

for obs in result["observations"]:
    print(f"[{obs['obs_id']}] {obs['event']}")
    print(f"  前因: {obs['before_state']}")
    print(f"  结果: {obs['after_state']}")
```

### Bank + Retrieval

```python
from Bank import ObservationBank
from Retrieval import Retriever

bank = ObservationBank()
bank.add(observations)  # 添加 NarrativeObservation 列表

retriever = Retriever(bank)
results = retriever.query_similar("角色展示隐藏能力，让其他人认识到其真实实力", top_k=5)

for r in results:
    print(f"相似度={r.similarity:.3f} | {r.obs['event']}")
```

### 运行测试

```bash
cd Code
python test/test_bank.py   # Bank + Retrieval 集成测试
python test/test_app.py    # Pipeline 端到端测试
```

## NarrativeObservation 数据结构

每个 Observation 包含：

| 字段 | 说明 |
|------|------|
| `obs_id` | 唯一标识，格式 `{story_id}_obs_{N:03d}` |
| `before_state` | 事件之前的情况/背景 |
| `event` | 具体发生了什么事 |
| `participants` | 参与角色类型，如 `["英雄", "对手"]` |
| `after_state` | 事件之后发生的变化 |
| `affected_aspect` | 影响的维度（能力/身份/关系/资源等） |
| `narrative_effect` | 对故事发展的影响 |
| `surface_form` | 表层实现（如"比武获胜""治病救人"） |
| `source_sentence_indices` | 来源句子索引 |
| `story_id` | 所属故事 ID |
| `extracted_at` | 提取时间 |

## Function Registry 数据结构

每个 Function 包含：

| 字段 | 说明 |
|------|------|
| `function_name` | 函数名（英文大写下划线，如 `CAPABILITY_REVELATION`） |
| `definition` | 定义（中文，术语式精炼） |
| `realization_patterns` | 中间粒度的实现模式，去除专名和具体道具但保留动作机制 |
| `positive_examples` | 从 Observation Bank 自动回填的原始事件与 `surface_form` 证据 |
| `hard_negatives` | 反例（相似但不属于此 Function） |
| `confusable_functions` | 易混淆的 Function |
| `supporting_obs_ids` | 支持此 Function 的 obs_id 列表 |
| `confidence` | 置信度 0.0-1.0（多因子计算） |

## 置信度计算

Function 的置信度由多因子加权计算，替代 LLM 主观判断：

```
confidence = 0.3 × diversity
           + 0.3 × coherence
           + 0.2 × surface
           - 0.2 × confusable
```

### 四因子详解

| 因子 | 含义 | 低分意味着 | 高分意味着 |
|------|------|-----------|-----------|
| `cross_story_diversity` | 跨故事证据充分性 | 证据来自同一故事（可能巧合） | 跨多个故事（结构通用） |
| `semantic_coherence` | 语义一致性 | obs 之间语义不一致 | obs 确实是同一结构 |
| `surface_diversity` | 表层多样性 | 表层形式单一（领域偏见） | 多领域变体（去偏） |
| `confusability_penalty` | 与已有 Function 的相似度（惩罚项） | 与已有 Function 重复 | 全新结构 |

**计算方式**：
- `diversity` = story_id 去重数 / obs 总数
- `coherence` = obs cluster 内所有两两组合的余弦相似度均值
- `surface` = 去重 surface_form 数 / 3（上限归一化）
- `confusable` = 与 Registry 中所有 Function 的最大 definition 相似度

**阈值**：置信度 >= 0.5 才写入 Registry

**调试接口**：`from Agent.Inducer.confidence import calculate_confidence_detailed` 可查看各因子得分。

## 设计原则

- **观察层与归纳层分离**：Observer 只负责"看到"事件，不做归纳；归纳由 Inducer 专门处理
- **可插拔存储**：Bank 支持 JSONL（精确查询）和 ChromaDB（语义检索）双存储
- **LangGraph 状态流**：所有 Agent 节点通过统一 State 通信，支持断点续传
- **表层词汇去偏**：Observation 转换为检索文本时，用结构化字段拼接代替原始句子，减少表层词汇对语义的干扰
- **客观置信度**：Function 置信度由多因子加权计算（cross_story_diversity + semantic_coherence + surface_diversity - confusability_penalty），替代 LLM 主观判断，确保可复现、可解释、可调参

## 已知问题 / 待优化（2026-08-14 batch_run 实证）

### 问题：5 个故事跑完，Registry 写入 0 个 Function

实测数据（`python test/batch_run.py` 跑完 5 个故事后）：

| Story | obs | 候选 Function | cross_div | sem_coh | surf_div | conf_pen | 总分 | 结果 |
|-------|-----|---------------|-----------|---------|----------|----------|------|------|
| 4 | 6 | CHALLENGE_INTRODUCTION | 0.577 | 0.565 | 1.0 | 0.496 | 0.443 | ✗ |
| 4 | 6 | HERO_VICTORY_OVER_FOE | 0.577 | 0.565 | 1.0 | 0.457 | 0.451 | ✗ |
| 5 | 8 | PROPHECY_AVOIDANCE_ATTEMPT | 0.238 | 0.613 | 1.0 | 0.514 | 0.353 | ✗ |

### 根因分析（待修复）

1. **`cross_story_diversity` 分母过大**
   - 定义：`story_id 去重数 / obs 总数`
   - story5 有 6 个 supporting obs 来自 5 个不同 story → 5/6 ≈ 0.83
   - 但实测只有 0.238 → 说明分母远大于 6，可能是检索阶段把所有 obs 全捞进聚类了
   - **应改为**：只统计 `supporting_obs_ids` 中 story_id 的去重数 / 总 obs 数

2. **`confusability_penalty` 与 Registry 状态耦合**
   - Registry 已有 1 个 Function（来自单故事测试残留）
   - 所有新候选与它 definition 相似 → 一律扣分
   - **应改为**：bootstrap 阶段禁用惩罚，或提高阈值容忍度

3. **候选之间互相对比缺失**
   - LLM 一次返回 2-3 个候选
   - 当前循环：候选 A 算分 → 写入 → 候选 B 算分（Registry 已有 A）→ 扣分
   - **应改为**：候选全部算分后再统一写入，避免"早写晚到"效应

### 临时绕过方案

- 把 `confusable` 权重从 0.2 降到 0.05
- 把阈值从 0.5 降到 0.35
- 跑完 bootstrap 后再调回

**状态**：⚠️ 待修复，证据已留 terminal 输出（terminals/915815.txt）
