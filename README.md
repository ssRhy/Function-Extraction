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
│   └── pre_processor.py    # Pre-Processor 节点：分句分段
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
│   └── Observer_prompt.py  # Observer 系统提示词
├── test/
│   ├── test_app.py         # Pipeline 端到端测试
│   ├── test_bank.py        # Bank + Retrieval 集成测试
│   └── story.txt           # 示例故事文本
└── data/
    └── bank/               # 持久化数据
        ├── observations.jsonl
        └── chroma_db/
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

## 设计原则

- **观察层与归纳层分离**：Observer 只负责"看到"事件，不做归纳；归纳由 Inducer 专门处理
- **可插拔存储**：Bank 支持 JSONL（精确查询）和 ChromaDB（语义检索）双存储
- **LangGraph 状态流**：所有 Agent 节点通过统一 State 通信，支持断点续传
- **表层词汇去偏**：Observation 转换为检索文本时，用结构化字段拼接代替原始句子，减少表层词汇对语义的干扰
