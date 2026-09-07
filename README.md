# Story Morphology - 故事形态学分析系统

基于 Vladimir Propp 的"故事形态学"理论，使用 LLM + 向量检索自动归纳故事的结构功能（Functions）。

## 系统架构

系统分为 **Bootstrap** 和 **Evolve** 两个阶段。

### Bootstrap（仅首次运行）

```
python -m FunctionExtract_Agent  （bootstrap_app 单图，一次运行全流程）
  story_loader →（逐篇 preprocessor→observer→bank_adder→retrieval→pairs_collector 循环）
  → cluster →（induce_step 循环）→ evaluator →（revise 循环 / final_review）→ export
  → Registry(O_0) + 快照 → Evolve
```

1. **Pre-Processor** — 读取清洗后故事文本，调用 LLM 按叙事结构分句分段（V2 prompt：`segments` 只输出句子索引、不重复全文，输出量 -40%；LLM 缺 `sentences`/解析失败/分句塌缩时用规则 `。！？` 切句兜底）
2. **Observer** — 逐句分析，提取 `NarrativeObservation`（叙事观察）：前因、事件、结果、影响维度
3. **Observation Bank** — 持久化存储 + 向量索引（ChromaDB + JSONL）
4. **Retrieval** — 跨故事语义检索
5. **Inducer** — 从跨故事相似 Observation 归纳 Function，多因子置信度过滤后 upsert 写入 Registry（同名/近义只保留最高置信度）
6. **Evaluator_v0 + 自动修订闭环** — 批后六维本体评估（Coverage / Cohesion / Separation / Abstraction Quality / Evidence Count / Diversity），>=4/6 达标；FAIL 或仍有可执行问题（近义合并组、待修订定义、题材绑定、粒度、weak-fit obs、低证据函数）时由 `revise_node` 全自动修订（MERGE / REVISE / SPLIT / 剔除 / 移除）并写回 O_0，再评估直到 PASS 或达 3 轮上限；作为 `bootstrap_app` 单图的节点（evaluator → revise 循环 → final_review）

## 目录结构

```
Code/
├── FunctionExtract_Agent/   # Bootstrap / Evolve 及其内部节点
│   ├── Bank/                # ObservationBank：ChromaDB + JSONL
│   ├── Contract/            # FunctionContract 构建与校验
│   ├── Embedding/           # Embedder：sentence-transformers 封装
│   ├── Evaluator/           # 六维评估、修订与抽象归并
│   ├── Inducer/             # 聚类、归纳与置信度计算
│   ├── Matcher/             # Observation → Function 分类
│   ├── Observer/            # 从句子提取 NarrativeObservation
│   ├── Pre_pro/             # 分句、分段与预处理
│   ├── Prompt/              # Function 流程提示词
│   ├── Registry/            # RegistryStore
│   ├── Retrieval/           # 向量语义检索
│   ├── app.py               # Bootstrap 入口（python -m FunctionExtract_Agent）
│   └── evolve.py            # Evolve 入口（python -m FunctionExtract_Agent.evolve）
├── Contracts/               # Snapshot、Occurrence、版本与合同 schema
├── KnowledgeBase/           # 统一 SQLite 知识库
├── StoryPattern_Agent/      # Pattern 增量流程
├── Outline_Agent/           # 大纲生成
├── Story_Agent/             # 正文生成
├── StoryCLI/                # Function → Pattern → Outline → Story 编排入口
├── Pipeline_Agent/          # Outline → Story 编排入口
├── FunctionCoordinator_Agent/ # Bootstrap/Evolve → Pattern 调度入口
├── data/                    # 运行时产物（默认 gitignored）
├── vendor/                  # langgraph-checkpoint-sqlite 本地依赖
├── test/
│   ├── clean_corpus.py     # 语料清洗（脚注/促销/碎片行/数字标记）
│   ├── test_evaluator.py   # Evaluator_v0 六维评估测试（单元 + mock LLM 节点）
│   ├── test_revise.py      # 修订节点 + bootstrap_app 修订闭环测试（mock LLM）
│   ├── test_bootstrap_app.py # bootstrap_app 单图全流程测试（mock LLM + FakeEmbedder）
│   ├── test_registry.py    # RegistryStore 单元测试（CRUD/隔离/字段无损/JSONL 往返）
│   ├── test_matcher.py     # Matcher 单元测试（召回/直写/occurrence，mock LLM）
│   ├── test_batch_induction.py  # 批后归纳聚类纯函数测试（无 LLM）
│   ├── test_preprocessor.py # Pre-Processor 测试（mock LLM）
│   ├── test_confidence.py  # 置信度计算测试
│   └── test_clean_corpus.py # 语料清洗回归测试
├── zhihu_story_subset_120_20260815/  # 知乎 120 篇原始语料（3 题材 × 40）
└── zhihu_story_subset_120_20260815_clean/  # 清洗后语料（Bootstrap 实际输入）
```

## 安装

```bash
pip install sentence-transformers chromadb openai pydantic langgraph
```

Embedding 模型（`BAAI/bge-small-zh-v1.5`）离线加载，无需额外下载配置。

`langgraph-checkpoint-sqlite`（SQLite 持久化 checkpoint）因当前环境全局 site-packages 不可写，装在本地 `Code/vendor/`（已被 gitignore）：

```bash
cd Code
python -m pip install --no-deps --target vendor langgraph-checkpoint-sqlite sqlite-vec aiosqlite
```

若全局环境可直接 `pip install langgraph-checkpoint-sqlite`，`vendor/` 目录可省略（`FunctionExtract_Agent/app.py` 仅在 `vendor/` 存在时加入 `sys.path`）。

## 使用

### 一键全流程（bootstrap_app 单图）

```bash
cd Code
python -m FunctionExtract_Agent                              # 全量：清洗语料 120 篇（缺省）
python -m FunctionExtract_Agent --limit 10                   # 只处理前 10 个（按自然序）
python -m FunctionExtract_Agent --stories "01_悬疑惊悚/a.txt,03_现代情感家庭/b.txt"  # 显式选篇（支持纯文件名）
python -m FunctionExtract_Agent --no-revise                 # 仅评估，不进入修订闭环
python -m FunctionExtract_Agent --resume                    # 跳过清空，从 checkpoint 续跑（同一 thread）
python -m FunctionExtract_Agent --namespace o0 --out-dir data/o0  # 自定义命名空间 / 快照目录
```

- 一次运行完成全流程（单图 `bootstrap_app`）：清空 Bank + 本命名空间 + checkpoint（无 `--resume` 时）→ 逐篇提取 obs（story_loader→preprocessor→observer→bank_adder→retrieval→pairs_collector 循环，每篇 Function=0）→ 跨题材统一聚类归纳（`cluster_similar_pairs` 阈值 0.60 + `split_oversized` + `inducer_node`，≥2 故事分量）→ 六维评估 + 自动修订闭环（evaluator → 发现问题 LLM 修订 → 再评估，直到 PASS 或 3 轮上限 → final_review 全量复核）→ 快照 `data/bootstrap/functions_<ns>.jsonl` / `bank_<ns>.jsonl`
- **逐函数舍弃**：导出前按 `final_review` 报告逐函数移除不达标函数（双向混叠/题材绑定/粒度过细过宽/低证据；`merge_groups` 每组保留支持证据最多者），幸存者照常导出为 O_0，被移除函数完整 payload 写入 `discarded_<ns>.jsonl` 留档。仅当全部函数都被移除（无幸存者）才判定"无 O_0"（退出码 1）。聚合维度（coverage/evidence/diversity）不达标不影响单个函数入库。
- `--resume`：持久化 checkpoint（`data/checkpoints/bootstrap-<ns>.sqlite3`，thread_id=`bootstrap-<ns>`）中断/崩溃后重跑同一命令续跑（Bank 按 `obs_id` 去重幂等）；不带 `--resume` 则 fresh 清空
- 不做题材过滤：跨题材 obs 直接一起归纳，函数天然题材无关（替代旧的"按题材分批 + 并集合并"流程；`--genre` 与并集工具已删除）
- `--corpus`：默认 `zhihu_story_subset_120_20260815_clean`；存在 `manifest.json` 时自动注入 category / question_title 元数据（Diversity 维度按题材计）
- 修订动作：近义 MERGE（supporting obs 程序并集）、定义 REVISE、SPLIT（obs 按向量余弦确定性分配）、weak-fit 剔除、低证据移除；写回前备份 `<registry>.pre_revise.<ns>.jsonl`
- Abstraction 复核为“首轮全量 + 后续轮增量”：只重评 `revise_node` 标记的变更集，未变更函数按 function_name 沿用旧评审；确定性五维每轮全量（向量秒级）
- LLM 统一 `reasoning_effort="none"`（`FunctionExtract_Agent/llm.py` 硬编码）；设 `LLM_USAGE=1` 可打印按调用方归因的 usage/耗时

### Function 调度（Bootstrap/Evolve → Pattern）

```bash
cd Code
python -m FunctionCoordinator_Agent --mode evolve --corpus <新语料目录> \
  --namespace <namespace> --base-snapshot <父 Snapshot> \
  --knowledge-db data/knowledge/story_knowledge.db \
  --snapshot-root data/ontology_snapshots
```

- Coordinator 使用 LangGraph 条件边读取子 Agent 的 `run_result`：Function `PASS` 且有 `snapshot_id` 才进入 Pattern，Pattern `SUCCESS` 才完成。
- 进程级暂时错误最多按 `--max-retries` 重试（默认 1 次）；业务质量失败直接停止，不自动修改 Function 或 Snapshot。
- Coordinator 对每个子 Agent 默认设置 1800 秒阶段超时，可用 `--stage-timeout` 调整；超时只终止当前子进程并按有限重试规则处理。
- Evolve 自动从 `--base-snapshot` 读取父 Snapshot 的 namespace；即使命令行传入其他 namespace，也以父 Snapshot 为准，保证子 Snapshot 能被 Pattern 接续。
- 不新增数据库或第二套持久状态；正式 Run 和 Snapshot 仍由 Bootstrap、Evolve、Pattern 写入统一 SQLite。
- 三个子 Agent 的失败结果统一为 `status=FAILED`，并包含 `stage`、`workflow`、`run_id`、`namespace`、`snapshot_id`、`parent_snapshot_id`、`error_code`、`error` 和 `retryable`；数据库内部仍按各自表的 `FAIL/FAILED` 状态记录。
- Coordinator 测试包含真实 Python 子进程协议：实际读取 stdout 的 `run_result`，并验证非零退出码会覆盖子 Agent 报告的成功状态。

### Snapshot 与 Serving

默认读取统一 SQLite 中的 serving Snapshot；用 `--snapshot-id` 可显式读取其他已发布 Snapshot。查看当前库状态和 serving 指针：

```bash
cd Code
python -X utf8 -m StoryCLI library status
python -X utf8 -c 'from KnowledgeBase.store import StoryKnowledgeStore; print(StoryKnowledgeStore().serving_snapshot())'
```

只有完成成功的 Pattern Run 且存在 Published Pattern 的 Snapshot 才能 promote；切换指针前先复制完整 Snapshot ID：

```bash
python -X utf8 -c 'from KnowledgeBase.store import StoryKnowledgeStore; print(StoryKnowledgeStore().promote_snapshot("SNAPSHOT_ID"))'
```

### 一键生成故事（Outline_Agent → Story_Agent）

```bash
cd Code
python -X utf8 -m Pipeline_Agent --genre 现代情感
python -X utf8 -m Pipeline_Agent --genre 现代情感 --pattern "拯救之恋"
python -X utf8 -m Pipeline_Agent --genre 悬疑惊悚 --out-dir data/pipeline_runs/demo
```

- 从统一 SQLite 中默认 serving Snapshot 的 published PatternSet 开始，自动完成 Pattern 选择、大纲生成、场景计划、场景发展和正文生成；可用 `--snapshot-id` 显式指定其他 Snapshot。
- 大纲校验未通过时保留大纲并停止，不启动正文。
- 完整大纲以 `outline_id` 写入 `Code/data/knowledge/story_knowledge.db`；Story_Agent 按 ID 从库中读取，JSON/Markdown 只作为导出物。
- 默认输出到 `Code/data/pipeline_runs/<时间戳>/`，包含 `outline/`、`story/` 和 `pipeline_manifest.json`。

单独复用库中大纲生成正文：

```bash
cd Code
python -X utf8 -m Story_Agent --outline-id OUT_xxx
```

### 统一 CLI：Function、模板和正文

```bash
cd Code

# 1. 批量提取 Function（--input 可重复，也可传目录）
python -X utf8 -m StoryCLI function bootstrap --input <文本文件或目录> --namespace demo
python -X utf8 -m StoryCLI function evolve --input <新文本目录> --namespace demo

# 2. 从 Function 运行已发布到 DB 的 PatternSet 生成 Outline，导出 Template Bundle
python -X utf8 -m StoryCLI template build --function-run data/story_cli/functions/<时间戳>/function_run.json --genre 现代情感

# 3. 使用 Template Bundle 写正文
python -X utf8 -m StoryCLI story write --template data/story_cli/templates/<时间戳>/template_bundle.json
python -X utf8 -m StoryCLI story write --template data/story_cli/templates/<时间戳>/template_bundle.json --request "现实克制，突出人物共同承担压力后的关系变化"

# 4. 批量生成大纲（同一批次内不重复，跨批次可复用）
python -X utf8 -m StoryCLI outline --genre 现代情感 --count 3
python -X utf8 -m StoryCLI outline batch --genre 现代情感 --count 3
python -X utf8 -m StoryCLI outline batch --genre 悬疑惊悚 --count 3 --pattern "危局援手与连环深渊" --pattern "悬念升级式调查推进"
```

- `function bootstrap/evolve` 支持多个文件和递归目录输入；Function Snapshot 发布后自动运行 Pattern Evolve。`function_run.json` 只记录运行结果，Pattern 节点不读取它。
- `template build` 从统一 DB 中指定 Snapshot 的 published PatternSet 选择 Pattern；Pattern 与一次具体 Outline 一起写入 `template_bundle.json`。
- `story write` 没有 `--request` 时复用 Bundle 中的 `outline_id`；有 `--request` 时固定 Pattern、重新生成 Outline 入库，再交给 Story_Agent 写正文。
- `outline` 是批量生成大纲的简洁入口，`outline batch` 为等价的显式写法；两者只运行 Outline_Agent，不生成正文。`--count` 表示目标有效大纲数量。候选按当前 Snapshot 的 `generation_outcomes` 反馈排序；同一批次内不重复消费 Pattern，校验失败仍记录 Outcome 并继续尝试其他 Pattern，后续批次仍可复用。
- Pattern 使用记录保存在 `Code/data/knowledge/story_knowledge.db` 的 `pattern_usage` 审计表；它不再作为跨批次禁用名单，同名但不同 `pattern_id` 的 Pattern 可分别使用。
- 默认产物分别位于 `Code/data/story_cli/functions/`、`Code/data/story_cli/templates/` 和 `Code/data/story_cli/stories/`；每次运行另有对应的 `function_run.json`、`template_bundle.json` 或 `story_run.json` manifest。
- StoryPattern 的生产入口为 `python -X utf8 -m StoryPattern_Agent --snapshot <snapshot_id>`。正式 LangGraph 只读写统一 SQLite，不读取 Catalog、review、summary JSON，也不使用旧目录 fallback。
- Pattern Evolve 节点为 `load_pattern_delta → update_story_sequences → update_motif_evidence → retrieve_variant_pairs → review_changed_pairs → rebuild_clusters → summarize_changed_clusters → publish_pattern_set`。输入以当前 Snapshot 的完整故事清单为准；没有 Observation 的故事保留空 sequence，不从 Pattern 输入中静默丢弃。未变化故事继承父 sequence；只有新签名的候选 pair 调用 LLM；发布节点单事务写入 PatternSet。

### Evolve（增量匹配，Bootstrap 之后持续运行）

```bash
cd Code
python -m FunctionExtract_Agent.evolve --corpus <新文本目录>                          # 全量匹配
python -m FunctionExtract_Agent.evolve --corpus <dir> --namespace smoke --out-dir data/evolve_smoke  # 独立命名空间（演示/防污染）
python -m FunctionExtract_Agent.evolve --corpus <dir> --stories "a.txt,b.txt" --limit 5
python -m FunctionExtract_Agent.evolve --corpus <dir> --batch-size 10 --top-k 5
```

- 一次运行完成（单图 `evolve_app`）：逐篇 `story_loader→preprocessor→observer→bank_adder→matcher→critic→collector` 循环 → `report`；新 obs 写入 Bank（按 `obs_id` 幂等），不新建/清空命名空间。
- **Matcher 五分类**：obs 结构化向量 vs 函数 definition 余弦召回 top-k 候选（默认 5）→ LLM 按批判定（默认 10 obs/批，共享函数卡片）→ `MATCH/EXTEND` 证据进 **待应用区 `pending_evidence`**（不直写 Registry，由 Curator 统一应用 exemplars）、`NOVEL` 进 `novelty_pool`、`CONFLICT/UNCERTAIN` 交给 **Critic 复检**。
- **Critic 边界复检器**：对 `CONFLICT/UNCERTAIN` 观测做二次校验（函数卡片含 `hard_negatives` 边界反例），输出四类最终判定——`match/extend` → 归函数并进 `pending_evidence`（`resolved_by="critic"`）、`novel` → 进 `novelty_pool`、`resolved` → 进 `challenge_pool`；复检失败保持原始 label 留 `challenge_pool`。
- 每个 obs 落一条 **FunctionOccurrence**（`occurrences.jsonl`：function_name/label/story_id/category/事件/参与者/前后状态/表层/原文下标/story_stage/top_candidates/reason），NOVEL 记为 `OTHER` 不强行分类（对齐 Plan.md：OTHER/低置信度是发现新 Function 的来源）。
- **Evaluator_mid 周期体检**：每累计 `MID_OBS_THRESHOLD`（默认 20）个新 obs 触发一次六维评估（复用 `evaluator_node`；评估对象 = 当前 Registry + **pending 证据的"应用后视图"临时快照** + Bank）；体检只记录问题不触发修订，报告落盘 `evaluation_mid_<n>.json`，`match_report.json` 的 `mid_evaluations` 汇总各轮判定（含 `pending_applied`）。
- **Curator 收尾维护**（图末尾 `report → curator → END`）：整合 pending（应用 exemplars）、novelty（跨故事 ≥2 且 ≥3 obs 才归纳新函数）、challenge/体检问题（合并/修订/剔除/移除）——**按动作分门槛**（`APPLY_EVIDENCE` 无门槛、`ADD_MIN_NOVEL=3`、`REVISE_MIN_SUPPORTING=3`），不足记 `SKIP_SMALL_SAMPLE` 保留累积；方案写 `curator_plan.jsonl`（Human Review 自动留档）后自动 Apply 写回 Registry（追加 `version_history`），清空已消费 pending。
- **Evaluator_final 终期评估**（图末尾 `curator → evaluator_final → END`）：复用 `evaluator_node` 对最终 Registry + Bank 做全量六维终评（`force_full_review=True`），Final Report（`evaluation_final.json`）含**演化前后对比**（基线 `functions_<ns>_start.jsonl` → 最终，新增/移除/保留 + supporting/confidence 分布），并导出最终 Ontology 快照 `functions_<ns>.jsonl` + `bank_<ns>.jsonl`；verdict 仅作验收报告，不阻断导出。
- 产物在 `data/evolve/`：`occurrences.jsonl` / `novelty_pool.jsonl` / `challenge_pool.jsonl`（含复检 RESOLVED）/ `pending_evidence.jsonl` / `curator_plan.jsonl` / `evaluation_final.json` / `match_report.json`（分类计数 + `coverage` + `novelty_rate` + `curator` + `final_evaluation` 汇总）。
- `--namespace` 默认 `bootstrap`（读函数库 + 证据落区目标）；演示请用独立命名空间避免污染 O_0。不做 checkpoint（Bank.add 幂等，可整批重跑）。

### 语料清洗

```bash
cd Code
python test/clean_corpus.py   # 清洗 zhihu_story_subset_120_20260815 -> ..._clean（不修改原文）
```

- 头部剔除完结标记（`【已完结】`/`（已完结）` 等：纯标记行删除、带正文保留正文）、作者签名/催更/慎入行（manifest.author_name 精确匹配）；尾部迭代截断 CTA/END/URL 促销块与读者催更提问（34/120 篇）；剔除孤立章节数字标记（含全角）；碎片式行合并为完整段落。
- 输出目录含 `manifest.json`/`manifest.csv` 复制与 `clean_report.json`（逐篇统计）；幂等（对输出重跑逐字节一致），120 篇无促销/URL/孤立引号残留。

### 端到端 Pipeline（bootstrap_app）

```python
from FunctionExtract_Agent.app import _new_app

bootstrap_app = _new_app("bootstrap")

initial_state = {
    "messages": [],
    "story_files": ["01_悬疑惊悚/1593863773_352776383.txt"],  # 相对语料目录
    "corpus_dir": "zhihu_story_subset_120_20260815_clean",
    "story_meta": {},                       # manifest: txt_file -> entry
    "current_story_index": 0,
    "total_stories": 1,
    "no_revise": False,
    "namespace": "bootstrap",
    "out_dir": "data/bootstrap",
    "evaluation_context": {},
}

config = {"configurable": {"thread_id": "bootstrap-bootstrap"}}
result = bootstrap_app.invoke(initial_state, config=config)
# 全流程：story 循环 → cluster → induce_step 循环 → evaluator/revise → export
```

### 运行测试

```bash
cd Code
python -m pytest test -q   # 全部离线回归（mock LLM / 无 LLM）
```

## NarrativeObservation 数据结构

| 字段 | 说明 |
|------|------|
| `obs_id` | 稳定逻辑标识，格式 `{story_id}_obs_<12 位小写十六进制>`；不依赖抽取顺序或句子下标 |
| `before_state` | 事件之前的情况/背景 |
| `event` | 具体发生了什么事 |
| `participants` | 参与角色类型，如 `["英雄", "对手"]` |
| `after_state` | 事件之后发生的变化 |
| `affected_aspect` | 影响的维度（能力/身份/关系/资源等） |
| `narrative_effect` | 对故事发展的影响 |
| `surface_form` | 表层实现（如"比武获胜""治病救人"） |
| `source_sentence_indices` | 支撑此观察的句子下标（`normalized_story.sentences`） |
| `source_text` | 根据 `source_sentence_indices` 从原文句子拼接出的证据文本 |
| `story_id` | 所属故事 ID |

> 提示：`obs_id` 由故事 ID 与原文锚点/语义锚点生成；`observation_version_id` 另行标识不可变内容版本。旧 `_obs_001` 等数字型 Observation ID 不属于当前 Snapshot 架构，旧数据需先重建。

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

## OntologySnapshot 发布契约

Bootstrap 在最终抽象归并并重新全量终评后，Evolve 在 Curator 稳定 Function 并完成 `Evaluator_final` 后，使用当前 Function 的驻留 Observation 生成 `FunctionContract`；只有终评 `PASS` 才自动发布不可变快照：

```text
Code/data/ontology_snapshots/<snapshot_id>/
├── manifest.json
├── functions.jsonl
├── occurrences.jsonl
├── function_contracts.jsonl
└── evaluation.json
```

Story Pattern Agent 通过统一 loader 只读消费快照，不直接依赖持续变化的 Registry：

```python
from Contracts.snapshot import load_function_contracts, load_occurrences, load_snapshot

manifest, functions, evaluation = load_snapshot(snapshot_path)
occurrences = load_occurrences(snapshot_path)
contracts = load_function_contracts(snapshot_path)
```

当前 Snapshot schema 为 v4。每个 Function 发布一份类型级 `FunctionContract`：角色槽位、状态前置条件、状态效果及义务的开启/推进/解除。发布时验证 Function ID/名称一一对应、定义哈希、证据引用属于该 Function 的驻留 supporting Observation、角色槽位引用及全部文件 SHA-256；Function 定义变化会使旧合同失效并重新生成。内容完全相同的重复发布返回已有目录；旧 v1/v2 Snapshot 不再兼容读取，需在当前架构下重建。

当前消费链为 `Snapshot loader → StoryPattern Pattern → Outline Planner → Mechanism Plan → Contract Ledger → Validator`：StoryPattern 只读当前 Snapshot 的冻结 Functions、FunctionOccurrence 和 Contracts；Outline 以同一 Snapshot 的合同为权威输入，Planner 检查相邻状态效果，Mechanism 绑定角色槽位并生成状态/义务账本，Validator 将合同断裂合并为失败项。

PatternCatalog schema v2 可在 Pattern 摘要中携带可选的模板级 `ending_spec`：它描述需要解决的核心冲突、结局必须出现的抽象动作和稳定终态，不是新的 Function。Outline 将其传给 Seed、Realizer 和 Validator，并在结果中保留结构化 `ending`；没有 `ending_spec` 的历史 Pattern 继续兼容。

真实 `evolve_250` 验收已生成 Snapshot `evolve_250_contracts_20260827T100511324434Z_670b7cbb13d1`：62/62 个 Function 合同、2193 条 Observation，Snapshot 校验 PASS。合同词汇统计为 94 个 aspect、398 个 state、139 个 obligation key；以同一 Function 集合的历史 71 个 Pattern 做严格相邻链扫描，226 条边中 0 条达到 exact compatibility。该结果说明当前合同词汇仍存在离散化和命名漂移，不能据此直接重发布 PatternCatalog 或重跑盲评；下一步需先建立证据约束下的状态词汇规范化与链边语义规则。

## Evaluator_v0 六维评估

批后六维本体评估（`FunctionExtract_Agent/Evaluator/`）：`evaluator_node` 评估初始本体 O_0，`revise_node` 消费报告全自动修订并写回，两者作为 `bootstrap_app` 单图的节点连成闭环（`evaluator → conditional → revise → evaluator … → final_review → export`）：FAIL 或报告仍有可执行问题（`merge_groups`/`revise_definitions`/`genre_bound_functions`/`granularity_issues`/`weak_fit_obs`/`low_evidence_functions`）时进入修订，再评估直到 PASS 或达 `MAX_EVAL_ROUNDS`（3 轮）；**PASS 或达上限后强制一次 `final_review`（全新全量 Abstraction 复核，不增量复用旧评审）**，最终判定基于真实测量，若仍有可执行问题继续修订（≤3 轮）。评估对象 = 当次 Registry + Bank，`FunctionExtract_Agent`（CLI）自动传 manifest；`evaluation_context`（`registry_file`/`bank_file`/`manifest_path`/`report_path`）仍可覆盖路径、对任意快照评估。报告落盘 `Code/data/evaluation/evaluation_report.json`；PASS = 达标维度 ≥ 4/6；修订写回前备份 `<registry>.pre_revise.jsonl`。`revise_node` 是 bootstrap 内嵌 Curator-lite（O_0 内部质量收敛，≤3 轮即止），不替代 Evolve 阶段的 Matcher/Critic/Curator。Abstraction 复核为"首轮全量 + 后续轮增量"（只重评变更集，未变更函数沿用旧评审），确定性五维每轮全量。

| 维度 | 含义 | 达标条件（默认阈值） |
|------|------|----------------------|
| Coverage 覆盖率 | 能被 ≥1 个 Function 解释的 obs 占比（supporting 集，或 obs 文本向量与任一 definition 余弦 ≥ 0.65） | ≥ 0.60 |
| Cohesion 内聚度 | supporting obs 与其 centroid 余弦的总体均值；单 obs 贴合 < 0.70 标 weak-fit | ≥ 0.60 |
| Separation 分离度 | LLM 判定的近义合并组数（不设余弦阈值） | = 0（非 0 即进修订合并） |
| Abstraction Quality 抽象质量 | LLM 逐批复核（20 函数/次）：双向混叠 / 题材绑定 / 粒度 | OK 比例 ≥ 0.80 |
| Evidence Count 证据量 | 无 <2 故事函数、平均支持故事 ≥ 2.5、平均 obs ≥ 3（按 120 篇真实分布校准：实测 2.892/3.048、中位数 3/3） | 三项全满足 |
| Diversity 语料多样性 | 支持故事覆盖题材数（经 manifest 解析）；无题材映射回退去重故事数 | ≥ 2 题材（回退 ≥ 20 故事） |

- 阈值集中在 `dimensions.py` 顶部，按 MiniLM 中文分布校准：Coverage 相似 0.65（中文基线 0.5-0.6）、Cohesion 0.60、weak-fit 0.70（0.80 在 76 函数真实集标 49 条过噪，<0.70 仅 5 条真离群）。**Separation 不再用余弦阈值**：近义合并组由抽象复核 LLM 直接产出（`EvaluatorReviewResponse.merge_groups`），0 组达标。
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
| `surface_diversity` | 表层多样性（embedding 语义去重，`SURFACE_SIM_THRESHOLD=0.80`） | 表层形式单一（领域偏见） | 多领域变体（去偏） |
| `confusability_penalty` | 与已有 Function 的相似度（惩罚项） | 与已有 Function 重复 | 全新结构 |

- `diversity` = supporting obs 中 story_id 去重数 / obs 总数
- `coherence` / `surface` 均基于 `supporting_obs_ids` 从 Bank 取实际 obs 计算（同口径）
- `confusable` = 与 Registry 中所有 Function 的最大 definition 相似度；bootstrap 阶段通过 `APPLY_CONFUSABLE=False` 豁免（近义由 Registry 硬去重承担）
- **阈值**：置信度 >= 0.5 才写入 Registry
- **调试接口**：`from FunctionExtract_Agent.Inducer.confidence import calculate_confidence_detailed` 可查看各因子得分

## 设计原则

- **观察层与归纳层分离**：Observer 只负责"看到"事件，不做归纳；归纳由 Inducer 专门处理
- **可复现**：story_id 从文件名派生；缺省 story_id 用 `sha256(原文前50字符)[:8]` 稳定回退
- **可插拔存储**：Bank 支持 JSONL（精确查询）和 ChromaDB（语义检索）双存储；Registry 为 SQLite（RegistryStore，按批次命名空间隔离，payload 整存字段无损），JSONL 仅作快照/交换格式
- **LangGraph 状态流**：所有 Agent 节点通过统一 State 通信
- **表层词汇去偏**：Observation 转换为检索文本时，用结构化字段拼接代替原始句子
- **客观置信度**：Function 置信度由多因子加权计算，替代 LLM 主观判断，确保可复现、可解释、可调参


## 当前进展（2026-08-16 续 9）：数据目录统一（单一 data 根）

- **统一为单一 `Code/data/` 根目录**：Registry DB → `data/registry/functions.db`；Bank 运行时存储 → `data/bank/`；快照 `data/bootstrap/` 与评估 `data/evaluation/` 不变。`registry.py` 默认 DB 路径与 `bank.py` 默认 `persist_dir`（`"data/bank"`）已同步；`.gitignore` 收敛为一条 `Code/data/`。
- **删除无用产物**：已清空命名空间的 4 个 `.pre_revise.*` 备份、`data/bank_test_conf/`（测试临时产物）；保留 `functions.db.pre_revise.bootstrap.jsonl`（curate 83→82 修订前备份）。
- 验证：`bootstrap` 命名空间 82 函数完整迁移；回归测试通过。

## 当前进展（2026-08-16 续 8）：LangGraph 范式审查 + 仓库清理 + 修订历史落盘

- **LangGraph 范式审查（$langgraph-coding skill）**：合规——`state.py` 用 `TypedDict + Annotated[list, add_messages]`；node 返回字段更新；图"先节点→边→compile"；条件边字符串路由与映射一致；`MemorySaver` + 稳定 `thread_id`；curate 闭环有界（`MAX_EVAL_ROUNDS=3`，`final_review` 出口），无死循环。重试沿用库内既有循环模式（`revise.py`/`pre_processor.py`），未额外引入 tenacity。
- **删除过期文件与测试**：`test_app.py`（依赖已删 `story.txt`）、`test_bank.py`（及其路径 bug 产物 `Code/Code/data/bank_test`，git 跟踪）、`test/stories/`（30 篇）、`draw_graph.py` + `langgraph_overall.mmd/.png`、`nf_llm_result.json` / `nf_rule_result.json` / `_enc_probe.txt`、旧日志 `batch_run_v2.log` / `batch_run_zhihu_v5.log`。
- **清理旧产物**：`data/` 下旧分批/试跑目录（`genre_functions` / `trial3_*` / `trial5*` / `trial_none` / `trial_usage_probe.json`）与 `data/evaluation/` 旧 union 快照已删除；保留 `data/bootstrap/` 快照与当前 `evaluation_report.json`。
- **旧命名空间清空**：`functions.db` 中 `01_悬疑惊悚`(31) / `02_古风穿越重生`(32) / `03_现代情感家庭`(39) / `union`(75) 已清空，仅保留 `bootstrap`(82)。
- **修订历史落盘**：`revise.py` 的 `revise_node` 每轮修订后追加 `data/evaluation/revise_rounds.jsonl`（`round` / `ts` / `actions`，含 merged/revised/split/removed/backup）。
- **`.env` 去跟踪**：`git rm --cached Code/FunctionExtract_Agent/.env`（工作区文件保留，`.gitignore` 已含 `.env`）。

## 当前进展（2026-08-17 续 10）：JSON 层加固 + source_sentence_indices 后 120 篇全量复验

- **全量运行（120 篇，llm.py JSON 层重试 + 新字段）**：**120/120 全部成功、0 跳过**（observer 121 次调用 = 120 篇 + 1 次 JSON 重试成功；对比修复前 3 篇跳过）；978 obs（**全部含非空 `source_sentence_indices`**）→ **85 functions**。耗时 2365.3s ≈ 39.4 分钟（19.7s/篇）；LLM 314 次 / 1.96M tok。
- **Evaluator：PASS 4/6**——coverage 0.7474 / cohesion 0.8762 / separation 0 / diversity 3（99 故事三题材）；未达标 abstraction 0.7647（3 轮修订上限内未收敛，残差 7 题材绑定 / 2 双向混叠 REVISE / 4 粒度，写入报告）+ evidence 2.788/2.929（贴线）。
- 对比上一版 120 篇（61 funcs / 3 篇跳过 / 51.9min）：本次 0 跳过、85 funcs、39.4min——函数数与速度差异来自 LLM 非确定性 + 语料完整性（3 篇补回）+ 本次顺带修复的 JSON 层。
- 产物：DB `bootstrap`（85）+ 快照 `data/bootstrap/functions_bootstrap.jsonl`（85）/ `bank_bootstrap.jsonl`（978）；报告 `data/evaluation/evaluation_report.json`；日志 `test/logs/bootstrap_full_20260817.log`。

## 当前进展（2026-08-17 续 9）：bootstrap_app 单图 120 篇全量验收

- **全量运行（120 篇，单图 + story_process 子图）**：117/120 篇成功（3 篇因 observer LLM 坏 JSON 跳过，不中断）；1006 obs → 45 个归纳分量 → **61 functions**（conf [0.528, 0.749]，mean 0.663；24 个恰 2 故事 / 37 个 ≥3 故事）。耗时 3112.9s ≈ 51.9 分钟（25.9s/篇）；LLM 307 次 / 1.97M tok。
- **Evaluator：PASS 4/6**——coverage 0.695 / cohesion 0.888 / separation 0 / diversity 3（87 故事三题材）；未达标 abstraction 0.7541（<0.80，3 轮修订上限内未收敛，残差 9 题材绑定 / 3 双向混叠 REVISE / 粒度，写入报告）+ evidence 2.721/2.885（贴线）。
- **修复**：不新增节点——加固 `llm.py` 的 `chat_structured` JSON 数据层（解析/校验失败附错误反馈自动重试 ≤2 次 + 轻量修复控制字符/尾逗号），从根因避免 observer 坏 JSON 崩溃（首跑第 2 篇曾因此中断）。
- 对比历史（run_bootstrap.py 全量：83 funcs / PASS 5/6 / 37.8min）：函数更少、abstraction 未收敛——差异来自跨题材统一归纳的 LLM 非确定性 + 3 轮上限；语义已随单图重构变化。
- 产物：DB `bootstrap`（61）+ 快照 `data/bootstrap/functions_bootstrap.jsonl`（61）/ `bank_bootstrap.jsonl`（1006）；日志 `test/logs/bootstrap_full_20260816.log`。

## 当前进展（2026-08-16 续 8）：Bootstrap 单图重构 bootstrap_app + checkpoint/--resume

- **收敛为唯一编译图 `bootstrap_app`**：删除 `run_bootstrap.py` 与 `pipeline_app`/`extract_app`/`curate_app` 三图，CLI 收敛到 `python -m FunctionExtract_Agent`（仅 `--corpus/--namespace/--out-dir/--limit/--stories/--no-revise` + 新增 `--resume`）。逐篇/每分量/判定打印移入图内节点（`story_loader`/`pairs_collector`/`induce_step`/`export`）。
- **持久化 checkpoint**：`SqliteSaver`（`data/checkpoints/bootstrap-<ns>.sqlite3`，thread_id=`bootstrap-<ns>`）；无 `--resume` 时 fresh（清空 Bank/Registry/checkpoint），`--resume` 跳过清理从同一 thread 续跑。`langgraph-checkpoint-sqlite` 因全局 site-packages 不可写装在 `Code/vendor/`（gitignore）。
- **State 扩展**：`story_files/corpus_dir/story_meta/induction_components/induction_index/errors/no_revise/namespace/out_dir`；累计相似对和归纳分量只保存 pair 引用，累计相似对写入 `pairs_<ns>.jsonl` 工作文件，不进入 checkpoint；`cluster_node` 内完成聚类+拆分+≥2 故事过滤。
- **测试**：`test_revise.py` 3 个闭环用例改为编译 `bootstrap_app`（临时 in-memory SqliteSaver）；新增 `test_bootstrap_app.py`（全流程 no-revise / checkpoint 续跑 / 单篇失败跳过 / 空 story 直达评估）。
- 说明：本轮验证受环境阻塞——沙箱用户无法加载 `torch_python.dll`（torch 相关测试无法运行），图逻辑用 Embedding 桩 + FakeEmbedder 验证通过（13 项），torch-free 回归 33 项通过。

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

- **RegistryStore（SQLite）**：`Code/FunctionExtract_Agent/Registry/registry.py`，表 `functions(namespace, function_name, definition, payload, updated_at)`，主键 `(namespace, function_name)`；按批次命名空间隔离，payload 整存保证未来 Evolve 加字段无需迁移存储层。
- **读写点收敛**：Inducer/Confidence/Evaluator/Revise 全部改走活跃 store（`get_active_store`/`set_active_store`）；JSONL 仅在有显式 registry_file（快照/并集评估）时使用；Revise 修订写回 store 模式前自动导出 `<db>.pre_revise.<ns>.jsonl` 备份。
- **5 篇跨题材试跑验收（2026-08-16）**：悬疑 2 + 古风 2 + 现代 1，`--batch-induction --out-dir data/trial5`；40 obs / 5 functions（均 ≥2 故事支持）；闭环 PASS 5/6；耗时 1282s（256.4s/篇）；DB 命名空间 `all` 与导出快照逐字段一致。
- **测试**：新增 `test/test_registry.py` 5 项（CRUD/整批事务/命名空间隔离/字段无损/JSONL 往返）；相关回归共 49 项全过；`_REGISTRY_FILE` 零残留。
## 当前进展（2026-08-16 续 3）：120 篇全量重跑（V3 定版）验收

- **三批全量重跑（V3 混合切句 + reasoning_effort=none）**：悬疑 638.9s / 335 obs / 31 funcs；古风 670.9s / 304 obs / 32 funcs；现代 832.9s / 372 obs / 39 funcs；**合计 2142.7s ≈ 36 分钟（17.8s/篇）**，对比旧配置约 8h → 约 13 倍提速。每批 Evaluator PASS 4/6（单题材 diversity=1 与 evidence 略低为预期）。
- **并集评估（102 funcs / 1011 obs）**：PASS 4/6（separation 16 组跨题材近义为 FAIL 主因）。
- **并集修订闭环（curate_app 3 轮）**：102 → **75 funcs**，separation 16→0、abstraction 0.987、coverage 0.797、cohesion 0.874、diversity 3，**最终 PASS 5/6**（唯一未达标 evidence mean_obs 3.79<4，接近阈值）。`_llm_merge` 19 次 / `_llm_revise` 10 次 / `_review_abstraction` 10 次，LLM 墙钟 115s。
- **产物**：DB 命名空间 `01_悬疑惊悚`(31) / `02_古风穿越重生`(32) / `03_现代情感家庭`(39) / `union`(75)；快照 `data/genre_functions/`（functions+bank 三份 + `genre_functions_summary.md`）与 `data/evaluation/`（union_functions/union_obs/evaluation_report/revise_report/revise_rounds）。

## 当前进展（2026-08-16 续 2）：Bootstrap 提速 ~13.6 倍 + 5 篇新配置试跑

- **根因定位（隐藏推理 token）**：耗时大头不是 Pre-Processor"全文回显"，而是模型隐藏推理 token——单次切句 completion 8220 tok 中 8207（99.8%）为 reasoning，可见输出仅 28 字符 JSON；同调用 `reasoning_effort=low` 31.4s/3925 tok vs `none` 1.6s/248 tok（约 20 倍）。
- **对策（两处最小改动）**：① `FunctionExtract_Agent/llm.py` `chat/chat_structured` 默认 `reasoning_effort="none"`；② `pre_processor.py` 默认走 **V3 混合切句**（规则切句生成候选句子 → LLM 只输出 merges/splits 修正、不回显全文，输出从 ~21k token 降到几百），质量仍由 LLM 把关。
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
- **Evaluator_v0 批后六维评估（2026-08-16）**：新增 `FunctionExtract_Agent/Evaluator/`（dimensions.py 纯函数 + evaluator.py 节点 + `Prompt/Evaluator_prompt.py`），batch_run 阶段 3 归纳后自动调用；集成验收（三题材快照并集 76 funcs / 831 obs）PASS 5/6：coverage 0.83 / cohesion 0.88 / separation 13（FAIL）/ abstraction 0.83 / evidence 3.78 / diversity 3；输出 13 近义组、4 题材绑定、7 双向混叠建议；报告 `Code/data/evaluation/evaluation_report.json`。
- **3 篇跨题材全流程（LLM 分句模式）**：现代/悬疑/古风各 1 篇，608.0s（202.7s/篇）；18 obs / 2 functions（均跨故事支撑）；验证跨故事 Function 归纳链路打通；修复 Pre-Processor 偶发 LLM 输出失控（重试 1 次 + 规则切句兜底）。
- **数据清洗**：`clean_corpus.py` 生成 `zhihu_story_subset_120_20260815_clean/`（120 篇、34 篇截断脚注、剔除噪音 1035 行、内容守恒 -5443 字符、幂等 0 违规、促销/URL/孤立引号残留 0）。

## 已知问题 / 待优化

1. **近义合并已改为 LLM 判定（2026-08-17）**：删除了 Separation 的余弦阈值（原 0.85 漏检近义、0.78 串假簇）；近义合并组由抽象复核 LLM 直接输出，0 组达标。残留风险：按批（20/批）检测时跨批近义对可能漏，且 LLM 偶发过度合并（如方向相反的函数被并入一组），由再评估 + 轮数上限兜底。
2. **逐函数舍弃（2026-08-17）**：导出前按 `final_review` 报告移除标记函数（`merge_groups` 每组保留证据最多者），幸存者照常导出，被移除函数留档 `discarded_<ns>.jsonl`；仅当全部被移除（无幸存者）才判定无 O_0（退出码 1）。聚合维度不达标不影响入库。
2. **作者脚注噪音（已处理）**：约 41/120 篇尾部带 `－END－`、`作者｜`、`编辑于` 等 CTA/版权脚注；已由 `clean_corpus.py` 清洗（输出 `..._clean/`），全量 Bootstrap 改用清洗后语料。头部误删（M1）与幂等（M3）已修复并补回归测试。
3. **Schema drift（已修复）**：Observer 提示词要求的 `source_sentence_indices` 已由 schema 采集（2026-08-17，缺省 `[]`）；历史 obs 未含该字段，需重跑回填。
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

1. **Observation 可追溯**：`source_sentence_indices` 已采集（2026-08-17）；历史 obs（120 篇快照）未含该字段，如需回填则重跑 obs 提取。
2. **Function Card 补字段**：`function_id`（稳定身份，供跨 run 对齐 `F_i^A ↔ F_j^B`）、`status`（provisional/stable/deprecated）、`version_history`（版本管理，文档 16 交付物 2）。
3. **卡片成熟内容**：Structural Significance / Typical Context / Typical Consequences / Participant Roles / Typical Before-After State 由 Curator 在 Evolve 中生成，不在 O0 强填。
4. **命名统一**：`realization_patterns` 与文档 `Surface Realizations` 对齐。
5. **Evolve 核心**：Matcher（MATCH/EXTEND/NOVEL/CONFLICT/UNCERTAIN）、Critic（hard cases）、Curator（ADD/MERGE/SPLIT/REVISE/DEPRECATE）。
6. **可复现**：Inducer 非确定性 → 固定候选池或 Run A/B/C 对齐；近义阈值 0.85 调参实验。
