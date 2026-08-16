# Story Morphology - 故事形态学分析系统

基于 Vladimir Propp 的"故事形态学"理论，使用 LLM + 向量检索自动归纳故事的结构功能（Functions）。

## 系统架构

系统分为 **Bootstrap** 和 **Evolve** 两个阶段。

### Bootstrap（仅首次运行）

```
Corpus → Pre-Processor → Observer → Observation Bank
                                       ↓
                                 Retrieval → Inducer → Function Registry (O_0)
                                                            ↓
                                          Evaluator_v0 ⇄ Revise（curate_app 闭环）
                                                            ↓
                                                         Evolve
```

1. **Pre-Processor** — 读取清洗后故事文本，调用 LLM 按叙事结构分句分段（V2 prompt：`segments` 只输出句子索引、不重复全文，输出量 -40%；LLM 缺 `sentences`/解析失败/分句塌缩时用规则 `。！？` 切句兜底）
2. **Observer** — 逐句分析，提取 `NarrativeObservation`（叙事观察）：前因、事件、结果、影响维度
3. **Observation Bank** — 持久化存储 + 向量索引（ChromaDB + JSONL）
4. **Retrieval** — 跨故事语义检索
5. **Inducer** — 从跨故事相似 Observation 归纳 Function，多因子置信度过滤后 upsert 写入 Registry（同名/近义只保留最高置信度）
6. **Evaluator_v0 + 自动修订闭环（curate_app）** — 批后六维本体评估（Coverage / Cohesion / Separation / Abstraction Quality / Evidence Count / Diversity），>=4/6 达标；FAIL 或仍有可执行问题（近义合并组、待修订定义、题材绑定、粒度、weak-fit obs、低证据函数）时由 `revise_node` 全自动修订（MERGE / REVISE / SPLIT / 剔除 / 移除）并写回 O_0，再评估直到 PASS 或达 3 轮上限；由 `run_bootstrap.py` 一键串联（阶段 3）

## 目录结构

```
Code/
├── Agent/
│   ├── app.py              # LangGraph 图定义（pipeline_app / extract_app / curate_app）
│   ├── llm.py              # DeepSeek API 统一封装
│   ├── state.py            # LangGraph State 定义
│   ├── Pre_pro/pre_processor.py   # Pre-Processor 节点：LLM 分句分段（规则兜底）
│   ├── Observer/observer.py       # Observer 节点：从句子提取 NarrativeObservation
│   ├── Inducer/inducer.py         # Inducer 节点：跨故事归纳 Function（upsert 去重）
│   ├── Inducer/cluster.py         # 批后归纳相似 obs 聚类（边阈值 + 连通分量 + 拆分）
│   ├── Inducer/confidence.py      # 多因子加权置信度计算
│   ├── Evaluator/evaluator.py     # Evaluator 节点：六维评估 + PASS/FAIL + 建议清单
│   ├── Evaluator/dimensions.py    # 六维纯函数与阈值（无 LLM、可复现）
│   ├── Evaluator/revise.py        # 修订节点：MERGE/REVISE/SPLIT + weak-fit 剔除 + 写回
│   └── Registry/registry.py     # RegistryStore：SQLite 存储（命名空间隔离，payload 整存）
├── Bank/
│   └── bank.py             # ObservationBank：ChromaDB + JSONL 双存储（data/bank/observations.jsonl）
├── Embedding/
│   └── embedding.py        # Embedder：sentence-transformers 封装（all-MiniLM-L6-v2）
├── Retrieval/
│   └── retrieval.py        # Retriever：向量语义检索
├── Prompt/
│   ├── Pre_prompt.py       # Pre-Processor 系统提示词
│   ├── Observer_prompt.py  # Observer 系统提示词
│   ├── Inducer_prompt.py   # Inducer 系统提示词
│   ├── Evaluator_prompt.py # Evaluator 抽象质量复核提示词
│   ├── Merge_prompt.py     # 近义组合并提示词
│   └── Revise_prompt.py    # 定义修订/拆分提示词
├── data/                    # 统一数据根目录（全部 gitignored 运行时产物）
│   ├── registry/functions.db # Registry（SQLite，命名空间隔离）
│   ├── bank/                # ObservationBank 运行时存储（JSONL + ChromaDB）
│   ├── bootstrap/           # run_bootstrap.py 快照（functions_<ns>.jsonl / bank_<ns>.jsonl）
│   └── evaluation/          # 评估报告与修订历史（evaluation_report.json / revise_rounds.jsonl）
├── run_bootstrap.py        # 一键全流程入口（清空→全量提取→统一归纳→评估修订闭环→快照）
├── test/
│   ├── clean_corpus.py     # 语料清洗（脚注/促销/碎片行/数字标记）
│   ├── test_evaluator.py   # Evaluator_v0 六维评估测试（单元 + mock LLM 节点）
│   ├── test_revise.py      # 修订节点 + curate_app 闭环测试（mock LLM）
│   ├── test_registry.py    # RegistryStore 单元测试（CRUD/隔离/字段无损/JSONL 往返）
│   ├── test_batch_induction.py  # 批后归纳聚类纯函数测试（无 LLM）
│   ├── test_preprocessor.py # Pre-Processor 测试（mock LLM）
│   ├── test_confidence.py  # 置信度计算测试
│   ├── test_clean_corpus.py # 语料清洗回归测试
│   └── logs/               # 运行日志
├── zhihu_story_subset_120_20260815/  # 知乎 120 篇原始语料（3 题材 × 40）
└── zhihu_story_subset_120_20260815_clean/  # 清洗后语料（Bootstrap 实际输入）
```

## 安装

```bash
pip install sentence-transformers chromadb openai pydantic langgraph
```

Embedding 模型（`all-MiniLM-L6-v2`）离线加载，无需额外下载配置。

## 使用

### 一键全流程（run_bootstrap.py）

```bash
cd Code
python run_bootstrap.py                                   # 全量：清洗语料 120 篇（缺省）
python run_bootstrap.py --limit 10                        # 只处理前 10 个（按自然序）
python run_bootstrap.py --stories "01_悬疑惊悚/a.txt,03_现代情感家庭/b.txt"  # 显式选篇（支持纯文件名）
python run_bootstrap.py --no-revise                       # 仅评估，不进入修订闭环
python run_bootstrap.py --evaluate-only                     # 非破坏性评估现有快照（不清空/不提取/不归纳/不修订）
python run_bootstrap.py --curate-only                       # 在现有命名空间上跑评估+修订闭环（最终全量复核判定）
python run_bootstrap.py --namespace o0 --out-dir data/o0  # 自定义命名空间 / 快照目录
```

- 一次运行完成全流程：清空 Bank + 本命名空间 → 阶段 1 逐篇提取 obs（`extract_app`，Function=0）→ 阶段 2 跨题材统一聚类归纳（`cluster_similar_pairs` 阈值 0.60 + `inducer_node`，≥2 故事分量）→ 阶段 3 `curate_app` 六维评估 + 自动修订闭环（评估 → 发现问题 LLM 修订 → 再评估，直到 PASS 或 3 轮上限）→ 快照 `data/bootstrap/functions_<ns>.jsonl` / `bank_<ns>.jsonl`
- 不做题材过滤：跨题材 obs 直接一起归纳，函数天然题材无关（替代旧的"按题材分批 + 并集合并"流程；`--genre` 与并集工具已删除）
- `--corpus`：默认 `zhihu_story_subset_120_20260815_clean`；存在 `manifest.json` 时自动注入 category / question_title 元数据（Diversity 维度按题材计）
- 修订动作：近义 MERGE（supporting obs 程序并集）、定义 REVISE、SPLIT（obs 按向量余弦确定性分配）、weak-fit 剔除、低证据移除；写回前备份 `<registry>.pre_revise.<ns>.jsonl`
- Abstraction 复核为"首轮全量 + 后续轮增量"：只重评 `revise_node` 标记的变更集，未变更函数按 function_name 沿用旧评审；确定性五维每轮全量（向量秒级）
- LLM 统一 `reasoning_effort="none"`（`Agent/llm.py` 硬编码）；设 `LLM_USAGE=1` 可打印按调用方归因的 usage/耗时

### 语料清洗

```bash
cd Code
python test/clean_corpus.py   # 清洗 zhihu_story_subset_120_20260815 -> ..._clean（不修改原文）
```

- 头部剔除完结标记（`【已完结】`/`（已完结）` 等：纯标记行删除、带正文保留正文）、作者签名/催更/慎入行（manifest.author_name 精确匹配）；尾部迭代截断 CTA/END/URL 促销块与读者催更提问（34/120 篇）；剔除孤立章节数字标记（含全角）；碎片式行合并为完整段落。
- 输出目录含 `manifest.json`/`manifest.csv` 复制与 `clean_report.json`（逐篇统计）；幂等（对输出重跑逐字节一致），120 篇无促销/URL/孤立引号残留。

### 端到端 Pipeline

```python
from Agent.app import pipeline_app

initial_state = {
    "messages": [],
    "raw_text": story_text,
    "story_config": {"story_type": "folktale", "story_id": "story1"},
    "normalized_story": None,
    "observations": [],
    "added_obs_ids": [],
    "similar_observations": [],
    "induced_functions": [],
    "current_story_index": 1,
    "total_stories": 1,
}

config = {"configurable": {"thread_id": "run-1"}}
result = pipeline_app.invoke(initial_state, config=config)

for obs in result["observations"]:
    print(f"[{obs['obs_id']}] {obs['event']}")
```

### 运行测试

```bash
cd Code
python -m pytest test/test_preprocessor.py test/test_confidence.py test/test_evaluator.py \
    test/test_revise.py test/test_registry.py test/test_batch_induction.py \
    test/test_clean_corpus.py -q   # 全部离线回归（mock LLM / 无 LLM）
```

## NarrativeObservation 数据结构

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
| `story_id` | 所属故事 ID |

> 提示：Observer 提示词中已要求输出 `source_sentence_indices`，但当前 Pydantic schema 尚未采集（schema drift，待 Evolve 阶段处理）。

## Function Registry 数据结构

| 字段 | 说明 |
|------|------|
| `schema_version` | Schema 版本（当前 2） |
| `function_name` | 函数名（英文大写下划线，如 `CAPABILITY_REVELATION`） |
| `definition` | 定义（中文，术语式精炼） |
| `realization_patterns` | 中间粒度的实现模式，去除专名和具体道具但保留动作机制 |
| `positive_examples` | 从 Observation Bank 自动回填的原始事件与 `surface_form` 证据 |
| `hard_negatives` | 反例（相似但不属于此 Function） |
| `confusable_functions` | 易混淆的 Function |
| `supporting_obs_ids` | 支持此 Function 的 obs_id 列表 |
| `confidence` | 置信度 0.0-1.0（多因子计算） |

**去重规则**：同名 `function_name`，或 `definition` 余弦相似度 > `NEAR_DUP_THRESHOLD`（0.85），视为重复，只保留置信度最高者。

## Evaluator_v0 六维评估

批后六维本体评估（`Agent/Evaluator/`）：`evaluator_node` 评估初始本体 O_0，`revise_node` 消费报告全自动修订并写回，`curate_app` 编译图把两者连成闭环（`START → evaluator → conditional → revise → evaluator … → END`）：FAIL 或报告仍有可执行问题（`merge_groups`/`revise_definitions`/`genre_bound_functions`/`granularity_issues`/`weak_fit_obs`/`low_evidence_functions`）时进入修订，再评估直到 PASS 或达 `MAX_EVAL_ROUNDS`（3 轮）；**PASS 或达上限后强制一次 `final_review`（全新全量 Abstraction 复核，不增量复用旧评审）**，最终判定基于真实测量，若仍有可执行问题继续修订（≤3 轮）。评估对象 = 当次 Registry + Bank，`run_bootstrap.py` 自动传 manifest；`evaluation_context`（`registry_file`/`bank_file`/`manifest_path`/`report_path`）仍可覆盖路径、对任意快照评估。报告落盘 `Code/data/evaluation/evaluation_report.json`；PASS = 达标维度 ≥ 4/6；修订写回前备份 `<registry>.pre_revise.jsonl`。`revise_node` 是 bootstrap 内嵌 Curator-lite（O_0 内部质量收敛，≤3 轮即止），不替代 Evolve 阶段的 Matcher/Critic/Curator。Abstraction 复核为"首轮全量 + 后续轮增量"（只重评变更集，未变更函数沿用旧评审），确定性五维每轮全量。

| 维度 | 含义 | 达标条件（默认阈值） |
|------|------|----------------------|
| Coverage 覆盖率 | 能被 ≥1 个 Function 解释的 obs 占比（supporting 集，或 obs 文本向量与任一 definition 余弦 ≥ 0.65） | ≥ 0.60 |
| Cohesion 内聚度 | supporting obs 与其 centroid 余弦的总体均值；单 obs 贴合 < 0.70 标 weak-fit | ≥ 0.60 |
| Separation 分离度 | definition 两两余弦 ≥ 0.85 的并查集近义组数 | = 0（非 0 输出合并建议） |
| Abstraction Quality 抽象质量 | LLM 逐批复核（20 函数/次）：双向混叠 / 题材绑定 / 粒度 | OK 比例 ≥ 0.80 |
| Evidence Count 证据量 | 无 <2 故事函数、平均支持故事 ≥ 2.5、平均 obs ≥ 3（按 120 篇真实分布校准：实测 2.892/3.048、中位数 3/3） | 三项全满足 |
| Diversity 语料多样性 | 支持故事覆盖题材数（经 manifest 解析）；无题材映射回退去重故事数 | ≥ 2 题材（回退 ≥ 20 故事） |

- 阈值集中在 `dimensions.py` 顶部，按 MiniLM 中文分布校准：Coverage 相似 0.65（中文基线 0.5-0.6）、Cohesion 0.60、weak-fit 0.70（0.80 在 76 函数真实集标 49 条过噪，<0.70 仅 5 条真离群）、Separation 分组 0.85（对齐 `NEAR_DUP_THRESHOLD`）+ 复核列表 0.78（0.78 分组会串出巨型连通分量，故降级为建议列表）。
- 双向混叠规则预筛（方向词对检测）作为 LLM 复核 prompt 种子；Abstraction 用 LLM（与 Inducer 一致的非确定性），其余 5 维确定性可复现。
- 集成验收一（三题材快照并集 76 funcs / 831 obs + manifest，2026-08-16）：PASS 5/6（Separation FAIL）；coverage=0.83、cohesion=0.88、separation=13、abstraction=0.83、evidence=3.78、diversity=3。建议清单含 13 组近义（如 `INFORMATION_REVELATION`≈`RELATIONSHIP_BREAKDOWN` 0.908、`CONFLICT_RESOLUTION`≈`RELATIONSHIP_STRENGTHENING` 0.995）、4 个题材绑定函数（`SUPERNATURAL_ENCOUNTER`/`FATE_REWRITING`/`SECOND_CHANCE`/`FATE_CHANGE_DECISION`）、7 个双向混叠 REVISE、5 条 weak-fit 离群 obs。
- 闭环验收（curate_app 并集 3 轮，2026-08-16 增量复核 + 同名去重后）：76 → 57 funcs（同名 0）；Separation 13 → 0；题材绑定/粒度/weak-fit/低证据全部清零；Abstraction 0.965、evidence mean_obs 4.65；coverage 0.81 / cohesion 0.87 / diversity 3；耗时 515s（增量复核实测：Abstraction LLM 调用 13–16 → 8 次，680s → 515s，-24%）；最终 PASS 6/6。报告 `evaluation_report.json` + `revise_report.json` + 每轮 `revise_rounds.jsonl`（含 renamed_duplicates）。（历史：全量复核版 76 → 56 / PASS 6/6 / 680s；增量版 76 → 59 / PASS 6/6 / 535s；首采样 76 → 57 / PASS 5/6 残留 2 组 SPLIT 镜像近义；LLM 非确定性，交付物以最新为准。）

## 置信度计算

```
confidence = 0.3 × diversity + 0.3 × coherence + 0.2 × surface - 0.2 × confusable
```

| 因子 | 含义 | 低分意味着 | 高分意味着 |
|------|------|-----------|-----------|
| `cross_story_diversity` | 跨故事证据充分性 | 证据来自同一故事（可能巧合） | 跨多个故事（结构通用） |
| `semantic_coherence` | 语义一致性（基于 `supporting_obs_ids` 实际 obs） | obs 之间语义不一致 | obs 确实是同一结构 |
| `surface_diversity` | 表层多样性 | 表层形式单一（领域偏见） | 多领域变体（去偏） |
| `confusability_penalty` | 与已有 Function 的相似度（惩罚项） | 与已有 Function 重复 | 全新结构 |

- `diversity` = supporting obs 中 story_id 去重数 / obs 总数
- `coherence` / `surface` 均基于 `supporting_obs_ids` 从 Bank 取实际 obs 计算（同口径）
- `confusable` = 与 Registry 中所有 Function 的最大 definition 相似度；bootstrap 阶段通过 `APPLY_CONFUSABLE=False` 豁免（近义由 Registry 硬去重承担）
- **阈值**：置信度 >= 0.5 才写入 Registry
- **调试接口**：`from Agent.Inducer.confidence import calculate_confidence_detailed` 可查看各因子得分

## 设计原则

- **观察层与归纳层分离**：Observer 只负责"看到"事件，不做归纳；归纳由 Inducer 专门处理
- **可复现**：story_id 从文件名派生；缺省 story_id 用 `sha256(原文前50字符)[:8]` 稳定回退
- **可插拔存储**：Bank 支持 JSONL（精确查询）和 ChromaDB（语义检索）双存储；Registry 为 SQLite（RegistryStore，按批次命名空间隔离，payload 整存字段无损），JSONL 仅作快照/交换格式
- **LangGraph 状态流**：所有 Agent 节点通过统一 State 通信
- **表层词汇去偏**：Observation 转换为检索文本时，用结构化字段拼接代替原始句子
- **客观置信度**：Function 置信度由多因子加权计算，替代 LLM 主观判断，确保可复现、可解释、可调参


## 当前进展（2026-08-16 续 9）：数据目录统一（单一 data 根）

- **统一为单一 `Code/data/` 根目录**：Registry DB（原 `Code/Agent/data/registry/functions.db`）→ `data/registry/functions.db`；Bank 运行时存储（原 `Code/Bank/data/`）→ `data/bank/`；快照 `data/bootstrap/` 与评估 `data/evaluation/` 不变。`registry.py` 默认 DB 路径与 `bank.py` 默认 `persist_dir`（`"data/bank"`）已同步；`.gitignore` 收敛为一条 `Code/data/`。
- **删除无用产物**：已清空命名空间的 4 个 `.pre_revise.*` 备份、`data/bank_test_conf/`（测试临时产物）；保留 `functions.db.pre_revise.bootstrap.jsonl`（curate 83→82 修订前备份）。
- 验证：`bootstrap` 命名空间 82 函数完整迁移；回归测试通过。

## 当前进展（2026-08-16 续 8）：LangGraph 范式审查 + 仓库清理 + 修订历史落盘

- **LangGraph 范式审查（$langgraph-coding skill）**：合规——`state.py` 用 `TypedDict + Annotated[list, add_messages]`；node 返回字段更新；图"先节点→边→compile"；条件边字符串路由与映射一致；`MemorySaver` + 稳定 `thread_id`；curate 闭环有界（`MAX_EVAL_ROUNDS=3`，`final_review` 出口），无死循环。重试沿用库内既有循环模式（`revise.py`/`pre_processor.py`），未额外引入 tenacity。
- **删除过期文件与测试**：`test_app.py`（依赖已删 `story.txt`）、`test_bank.py`（及其路径 bug 产物 `Code/Code/data/bank_test`，git 跟踪）、`test/stories/`（30 篇）、`draw_graph.py` + `langgraph_overall.mmd/.png`、`nf_llm_result.json` / `nf_rule_result.json` / `_enc_probe.txt`、旧日志 `batch_run_v2.log` / `batch_run_zhihu_v5.log`。
- **清理旧产物**：`data/` 下旧分批/试跑目录（`genre_functions` / `trial3_*` / `trial5*` / `trial_none` / `trial_usage_probe.json`）与 `data/evaluation/` 旧 union 快照已删除；保留 `data/bootstrap/` 快照与当前 `evaluation_report.json`。
- **旧命名空间清空**：`functions.db` 中 `01_悬疑惊悚`(31) / `02_古风穿越重生`(32) / `03_现代情感家庭`(39) / `union`(75) 已清空，仅保留 `bootstrap`(82)。
- **修订历史落盘**：`revise.py` 的 `revise_node` 每轮修订后追加 `data/evaluation/revise_rounds.jsonl`（`round` / `ts` / `actions`，含 merged/revised/split/removed/backup）。
- **`.env` 去跟踪**：`git rm --cached Code/Agent/.env`（工作区文件保留，`.gitignore` 已含 `.env`）。

## 当前进展（2026-08-16 续 7）：curate 最终全量复核 + --curate-only 闭环验收

- **流程修复**：`curate_app` 新增 `final_review` 节点——PASS 或达 3 轮上限后强制全新全量 Abstraction 复核（`force_full_review`，不增量复用），最终判定基于真实测量；最终复核仍有可执行问题则继续修订（受轮数上限约束）。修复前最终判定混着旧评审（同一 O0 复用路径 1.0 vs 全新路径 0.7952）。
- **新增 `--curate-only`**：在现有命名空间上跑评估+修订闭环（不清空/不提取/不归纳），修订写回 DB 并同步快照。
- **bootstrap 命名空间闭环验收（2026-08-16）**：83 → **82 functions**（拆分 5 / 移除 2，合并/修订 0）；3 轮修订；最终 **PASS 6/6**（coverage 0.761 / cohesion 0.884 / separation 0 / abstraction **0.890（全量最终复核）** / evidence 2.89 / diversity 3）。残留建议（4 REVISE / 3 题材绑定 / 1 粒度）写入报告供 Evolve 参考；快照与 DB 一致（82）。

## 当前进展（2026-08-16 续 6）：Evidence 阈值校准 + --evaluate-only

- **校准**：`EVIDENCE_MEAN_STORIES 3.0→2.5`、`EVIDENCE_MEAN_OBS 4→3`（`dimensions.py`，保留 ≥2 故事硬下限）；依据 = 3/4 为计划默认且"验收时校准"从未执行，历次真实运行（union 3.79、bootstrap 2.892/3.048）从未达到 mean_obs≥4，实测中位数 3/3。
- **新增 `--evaluate-only`**：`run_bootstrap.py` 非破坏性评估现有快照（不清空/不提取/不归纳/不修订），`evaluation_context` 指向 `functions_<ns>.jsonl`/`bank_<ns>.jsonl`/manifest。
- **重评结果（2026-08-16）**：evidence `score=2.892` **pass=True**；但全新全量 Abstraction 复核（83 个全评、0 复用）给出 `abstraction_quality 0.7952`（<0.80 临界）→ 整体 PASS 5/6。原全量跑 abstraction 1.0 来自增量复用旧评审；全新复核暴露约 17 个函数可执行问题（4 REVISE / 2 too_broad / 6 题材绑定），体现 LLM 非确定性，需决定是否跑一轮 curate 修订后复评。

## 当前进展（2026-08-16 续 5）：120 篇全量一键验收（run_bootstrap.py）

- **全量运行（120 篇，跨题材统一归纳）**：2265.6s ≈ 37.8 分钟（18.9s/篇）；1027 obs / 102 个相似分量 → Inducer 写入 116 个 → curate 修订（修订 4 / 拆分 13 / 移除 11）→ **最终 83 functions**（全部 ≥2 故事支持，conf [0.546, 0.749]）。Evaluator **PASS 5/6**：coverage 0.731 / cohesion 0.882 / separation 0 / abstraction 1.0 / diversity 3（题材全 3 类，103 故事）；唯一未达标 evidence（mean_stories 2.892<3、mean_obs 3.048<4，接近阈值，属证据量问题而非质量问题）。LLM 306 次 / 1.93M tok / 墙钟 1852.6s。
- **产物**：DB 命名空间 `bootstrap`（83 条）+ 快照 `data/bootstrap/functions_bootstrap.jsonl`（83）/ `bank_bootstrap.jsonl`（1027 obs）。日志 `test/logs/run_bootstrap_full.log`。
- **对比旧并集**：旧 union 75（三批 102 → curate → 75，PASS 5/6）vs 新 bootstrap 83——数量与六维形态相近（均 evidence 临界），跨题材直接归纳语义下 83 为当前 O_0。

## 当前进展（2026-08-16 续 4）：统一全流程 run_bootstrap.py（一次过全量）

- **新增 `run_bootstrap.py` 一键入口**：清空 Bank + 本命名空间 → 全量提取 obs（`extract_app`）→ 跨题材统一聚类归纳（阈值 0.60，≥2 故事分量）→ `curate_app` 评估 + 修订闭环 → 单一命名空间 + 快照；不再按题材分批、不再需要并集合并。删除旧工具 `test/batch_run.py` / `genre_extract.py` / `gen_evaluation_report.py` / `curate_run.py` / `import_registry.py`；`llm.py` 删除 `reasoning_effort` 参数、硬编码 `"none"`。
- **3 篇跨题材冒烟（2026-08-16）**：悬疑/古风/现代各 1 篇，52.7s（17.6s/篇）；30 obs → 1 个跨题材分量 → 归纳 6 个 → 修订移除 3 个低证据（<2 故事）→ 最终 3 functions（RELATIONSHIP_BREAKDOWN / TRUST_FORGING / ESCALATION_TO_REALITY），Evaluator 最终 PASS 4/6（evidence 小样本不达标为预期）；LLM 8 次 / 50,298 tok / 48.7s。快照 `data/bootstrap/functions_bootstrap.jsonl` + `bank_bootstrap.jsonl`。
- **语义变化**：函数由跨题材 obs 直接聚类产生（题材无关），替代"分题材归纳 + 并集合并"；旧命名空间（01/02/03/union）作为历史数据保留、不再使用。

## 当前进展（2026-08-16 续）：Registry SQLite 化 + 5 篇试跑

- **RegistryStore（SQLite）**：Code/Agent/Registry/registry.py，表 unctions(namespace, function_name, definition, payload, updated_at)，主键 (namespace, function_name)；按批次命名空间隔离（atch_run 启动只清当前批），payload 整存保证未来 Evolve 加字段无需迁移存储层。
- **读写点收敛**：Inducer/Confidence/Evaluator/Revise 全部改走活跃 store（get_active_store/set_active_store）；JSONL 仅在有显式 
egistry_file（快照/并集评估）时使用；
evise 修订写回 store 模式前自动 export_jsonl(<db>.pre_revise.<ns>.jsonl) 备份。
- **5 篇跨题材试跑验收（2026-08-16）**：悬疑 2 + 古风 2 + 现代 1，--batch-induction --out-dir data/trial5；40 obs / 5 functions（均 ≥2 故事支持）；闭环 PASS 5/6（第 1 轮 4/6 → 修订 3 个题材绑定/粒度函数 → 第 2 轮 5/6；evidence 2.2 因样本仅 5 篇不达标，属小样本预期）；耗时 1282s（256.4s/篇）；DB 命名空间 ll 与导出快照逐字段一致。
- **测试**：新增 	est/test_registry.py 5 项（CRUD/整批事务/命名空间隔离/字段无损/JSONL 往返）；回归 test_revise/test_evaluator/test_batch_induction/test_confidence/test_preprocessor/test_clean_corpus 共 49 项全过；_REGISTRY_FILE 零残留。
## 当前进展（2026-08-16 续 3）：120 篇全量重跑（V3 定版）验收

- **三批全量重跑（V3 混合切句 + reasoning_effort=none）**：悬疑 638.9s / 335 obs / 31 funcs；古风 670.9s / 304 obs / 32 funcs；现代 832.9s / 372 obs / 39 funcs；**合计 2142.7s ≈ 36 分钟（17.8s/篇）**，对比旧配置约 8h → 约 13 倍提速。每批 Evaluator PASS 4/6（单题材 diversity=1 与 evidence 略低为预期）。
- **并集评估（102 funcs / 1011 obs）**：PASS 4/6（separation 16 组跨题材近义为 FAIL 主因）。
- **并集修订闭环（curate_app 3 轮）**：102 → **75 funcs**，separation 16→0、abstraction 0.987、coverage 0.797、cohesion 0.874、diversity 3，**最终 PASS 5/6**（唯一未达标 evidence mean_obs 3.79<4，接近阈值）。`_llm_merge` 19 次 / `_llm_revise` 10 次 / `_review_abstraction` 10 次，LLM 墙钟 115s。
- **产物**：DB 命名空间 `01_悬疑惊悚`(31) / `02_古风穿越重生`(32) / `03_现代情感家庭`(39) / `union`(75)；快照 `data/genre_functions/`（functions+bank 三份 + `genre_functions_summary.md`）与 `data/evaluation/`（union_functions/union_obs/evaluation_report/revise_report/revise_rounds）。

## 当前进展（2026-08-16 续 2）：Bootstrap 提速 ~13.6 倍 + 5 篇新配置试跑

- **根因定位（隐藏推理 token）**：耗时大头不是 Pre-Processor"全文回显"，而是模型隐藏推理 token——单次切句 completion 8220 tok 中 8207（99.8%）为 reasoning，可见输出仅 28 字符 JSON；同调用 `reasoning_effort=low` 31.4s/3925 tok vs `none` 1.6s/248 tok（约 20 倍）。
- **对策（两处最小改动）**：① `Agent/llm.py` `chat/chat_structured` 默认 `reasoning_effort="none"`；② `pre_processor.py` 默认走 **V3 混合切句**（规则切句生成候选句子 → LLM 只输出 merges/splits 修正、不回显全文，输出从 ~21k token 降到几百），质量仍由 LLM 把关。
- **trial5_none 试跑验收（2026-08-16）**：同 trial5 的 5 篇跨题材，`--batch-induction --out-dir data/trial5_none`；**93.9s（18.8s/篇）vs 基线 1282s（256.4s/篇）→ 提速约 13.6 倍**；47 obs / 5 functions（与基线数量一致）；闭环 PASS 5/6（第 1 轮 4/6 → 修订 1 / 拆分 1 → 第 2 轮 5/6；evidence 因 5 篇小样本不达标，符合预期）；LLM 15 次调用 / 89,791 tok / 88.8s。
- **3 篇样本量警告**：同配置 3 篇试跑（trial_none）只归纳出 1 个 function（34 obs）——跨故事相似分量过少导致，非配置退化；5 篇即恢复 5 个 function，支撑"质量持平"结论。
- **删除 `positive_examples`**：inducer.py / revise.py / Inducer_prompt.py 已清理（零读取字段）；回归测试全过。
- **V2 vs V3 同篇对照（2026-08-16 定案）**：同 3 篇跨题材（trial3_v2 vs trial3_v3）——V2 85.1s/篇 vs V3 18.4s/篇（4.6 倍）；V2 3/3 篇首轮 JSON 失败、1 篇掉规则兜底，V3 0 失败；两者均产出 4 个 Function 且全部 ≥2 故事支持；Evaluator V3 PASS 5/6（0 轮修订）vs V2 PASS 4/6（需移除 2 个低证据/题材绑定函数）。**决策：保留 V3 混合切句**（LLM 仍把关合并/拆分质量）。
- **待决策**：是否清空 `all` 命名空间 + Bank，以新配置全量重跑三批（预计 ~1h，Observer 每篇 ~10s 为主）。

## 当前进展（2026-08-15）

- **10 篇短篇验收**：595.7 秒（≈59.6 秒/篇）；44 obs / 13 functions；Evaluator = HEALTHY；置信度带 [0.54, 0.71]。
- **zhihu 5 篇跨题材验证**（悬疑 2 + 古风 2 + 现代 1，含 1 篇碎片式）：307.5 秒（61.5 秒/篇）；27 obs / 8 functions；Evaluator = HEALTHY；obs 覆盖完整叙事弧、无脚注污染。
- **决策**：120 篇全部作为 Bootstrap 语料，按 3 题材分 3 批运行。
- **Pre-Processor prompt V2（去重复输出，2026-08-16）**：`segments` 不再输出 `content`，输出量 -40%；3 篇同批冒烟 117.1s/篇（V1 208.0s/篇，-44%），句子粒度与文本守恒不变。 批量实测（2026-08-16）：V1 悬疑 275.6s/篇 vs V2 古风 240.1 / 现代 195.2s/篇（-13%~-29%）；输出量 -40% 为确定性节省，墙钟受 DeepSeek 延迟波动，冒烟 -44% 未全量复现。
- **悬疑 40 篇批后统一归纳（第一批）**：`--batch-induction` 两阶段（先提取后归纳）；254 obs / 23 functions；Evaluator = HEALTHY；置信度 [0.591, 0.757]；耗时 3.06h（275.6s/篇）；快照在 `Code/data/genre_functions/`。
- **古风 40 篇批后统一归纳（第二批，V2 分句）**：293 obs / 23 functions；Evaluator = HEALTHY；置信度 [0.626, 0.750]；耗时 9603s（240.1s/篇）；快照 `functions_02_古风穿越重生.jsonl` / `bank_02_古风穿越重生.jsonl`。
- **现代 40 篇批后统一归纳（第三批，V2 分句）**：284 obs / 30 functions；Evaluator = HEALTHY；置信度 [0.533, 0.737]；耗时 7807s（195.2s/篇）；快照 `functions_03_现代情感家庭.jsonl` / `bank_03_现代情感家庭.jsonl`。
- **三题材对比（120 篇全量，2026-08-16）**：悬疑 23 / 古风 23 / 现代 30；跨题材近义组 20（>0.85，跨题材暂不合并，作为 Evolve 阈值调参证据）；摘要 `Code/data/genre_functions/genre_functions_summary.md`。
- **Evaluator_v0 批后六维评估（2026-08-16）**：新增 `Agent/Evaluator/`（dimensions.py 纯函数 + evaluator.py 节点 + `Prompt/Evaluator_prompt.py`），batch_run 阶段 3 归纳后自动调用；集成验收（三题材快照并集 76 funcs / 831 obs）PASS 5/6：coverage 0.83 / cohesion 0.88 / separation 13（FAIL）/ abstraction 0.83 / evidence 3.78 / diversity 3；输出 13 近义组、4 题材绑定、7 双向混叠建议；报告 `Code/data/evaluation/evaluation_report.json`。
- **3 篇跨题材全流程（LLM 分句模式）**：现代/悬疑/古风各 1 篇，608.0s（202.7s/篇）；18 obs / 2 functions（均跨故事支撑）；验证跨故事 Function 归纳链路打通；修复 Pre-Processor 偶发 LLM 输出失控（重试 1 次 + 规则切句兜底）。
- **数据清洗**：`clean_corpus.py` 生成 `zhihu_story_subset_120_20260815_clean/`（120 篇、34 篇截断脚注、剔除噪音 1035 行、内容守恒 -5443 字符、幂等 0 违规、促销/URL/孤立引号残留 0）。

## 已知问题 / 待优化

1. **近义阈值偏严 / 分组阈值降级**：`NEAR_DUP_THRESHOLD=0.85` 对中文 definition 偏保守；Evaluator 验收中 0.85 分组抓到 13 组近义（最高 `CONFLICT_RESOLUTION`≈`RELATIONSHIP_STRENGTHENING` 0.995），0.78 分组会串出巨型连通分量（已降级为复核列表）。`IDENTITY_SHIFT` / `IDENTITY_REVELATION_OR_SUSPICION` 等概念重叠函数未被合并；Evolve 阶段需定调（降阈值 vs 人工合并规则 vs Curator MERGE）。
2. **作者脚注噪音（已处理）**：约 41/120 篇尾部带 `－END－`、`作者｜`、`编辑于` 等 CTA/版权脚注；已由 `clean_corpus.py` 清洗（输出 `..._clean/`），全量 Bootstrap 改用清洗后语料。头部误删（M1）与幂等（M3）已修复并补回归测试。
3. **Schema drift**：Observer 提示词要求输出 `source_sentence_indices`，但 schema 未采集（Evolve 阶段需补）。
4. **过期测试已删除**：`test_app.py` / `test_bank.py` / `test/stories/`（30 篇）等过期测试与旧日志已在本轮清理（见续 8）。
5. **旧分批/并集工具已删除**：`test/batch_run.py`（`--genre` 三批）与并集工具（`genre_extract`/`gen_evaluation_report`/`curate_run`/`import_registry`）已由 `run_bootstrap.py` 一键全流程取代；历史命名空间 `01_悬疑惊悚`/`02_古风穿越重生`/`03_现代情感家庭`/`union` 已清空，`functions.db` 仅保留 `bootstrap`。
5. **历史问题已修复**：早前"5 个故事 Registry 写入 0 个 Function"的根因（diversity 分母过大、confusable 与 Registry 耦合、候选互比缺失）已在 2026-08-15 修复（口径统一 + bootstrap 豁免 + 候选统一算分后写入）。
6. **Inducer 非确定性**：同一批语料两次运行 Function 名称/数量不同（LLM 候选生成随机），影响可复现；评价阶段需固定候选池或 Run A/B/C 对齐。
7. **LLM 分句偶发塌缩为 1 句（已兜底）**：`sentences=[全文]` 时 Observer 仍能提取 obs 但粒度变粗；2026-08-16 已加塌缩检测（LLM 返回句子数 < 文本句末标点数/3 时改用规则切句），`test_preprocessor.py` 新增回归用例。
8. **跨题材近义组（三题材对比，2026-08-16）**：120 篇快照间定义相似度 >0.85 的跨题材 Function 对 20 组（如 `REVELATION_OF_HIDDEN_TRUTH` ≈ `SECRET_DISCOVERY` sim=0.970），多为题材语义交叠；bootstrap 按题材隔离不合并，Evolve 阶段需决策跨题材统一与 0.85 阈值调参。
9. **Evaluator_v0 验收发现（2026-08-16）**：三题材并集评估 PASS 5/6（Separation FAIL）——13 组同题材近义、4 个题材绑定函数、7 个双向混叠 REVISE、5 条 weak-fit 离群 obs；已由 curate_app 闭环自动修订（76 → 57 funcs、同名 0，题材绑定/粒度/weak-fit/低证据清零，最终 PASS 6/6）。
10. **SPLIT 镜像近义风险（2026-08-16）**：首采样闭环第 2/3 轮出现 SPLIT 拆出的正/负镜像对（`POSITIVE_TURNING_POINT`≈`NEGATIVE_TURNING_POINT` 0.982、`THREAT_ENCOUNTER`≈`RELATIONSHIP_IMPROVEMENT` 0.901）被 Separation 标为近义；重跑采样未复现（Separation 归零、PASS 6/6），但 LLM 非确定性下该风险仍在，Evolve 阶段可考虑同源 SPLIT 对豁免名单。
11. **同名碰撞（2026-08-16）**：并集存在同名但定义相似度 <0.85 的函数对（如 `RELATIONSHIP_FORMATION`、`INFORMATION_REVELATION`），低于分组阈值未触发合并，落在 `near_dup_review_pairs`；Evolve 阶段需决策同名唯一化规则。


## Evolve 阶段待补清单（bootstrap 后一次性补齐）

进入 Evolve（Matcher/Critic/Curator）与评价阶段前补齐（决策背景见 THINKING.md #6；bootstrap 阶段刻意不补）：

1. **Observation 可追溯**：Observer schema 采集 `source_sentence_indices`（prompt 已要求输出，当前未存储）；补后需对全量语料重跑 obs 提取回填，三批快照同步重建。
2. **Function Card 补字段**：`function_id`（稳定身份，供跨 run 对齐 `F_i^A ↔ F_j^B`）、`status`（provisional/stable/deprecated）、`version_history`（版本管理，文档 16 交付物 2）。
3. **卡片成熟内容**：Structural Significance / Typical Context / Typical Consequences / Participant Roles / Typical Before-After State 由 Curator 在 Evolve 中生成，不在 O0 强填。
4. **命名统一**：`realization_patterns` 与文档 `Surface Realizations` 对齐。
5. **Evolve 核心**：Matcher（MATCH/EXTEND/NOVEL/CONFLICT/UNCERTAIN）、Critic（hard cases）、Curator（ADD/MERGE/SPLIT/REVISE/DEPRECATE）。
6. **可复现**：Inducer 非确定性 → 固定候选池或 Run A/B/C 对齐；近义阈值 0.85 调参实验。