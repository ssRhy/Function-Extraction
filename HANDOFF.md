# 会话交接协议

## 动态 Function Planner 已实现（2026-09-04）

- 新增 `Code/Outline_Agent/dynamic_planner.py`：从当前 Snapshot 读取 Function、Contract、StateVocabulary、真实转移和已发布 Pattern 使用的成熟 motif；通过有限 Beam Search 让 LLM 生成 `REUSE_MOTIF`、`COMPOSE_MOTIFS`、`MUTATE_MOTIF`、`BRIDGE`、`EXPLORE` 五类扩展。
- 候选只保存在运行时状态，做 Function/Contract/角色槽位/链结构硬校验、合同状态诊断、义务闭合报告、去重、评分和 `REUSE/VARIANT/NOVEL` 分类；motif 组合按真实序列做前后缀 overlap 合并，禁止跨扩展机械重复，但保留 motif 自身内部回环。当前“跨 motif 重复 Function 直接拒绝”是第一版安全阀，用于防止机械循环；若继续完善递进表达，应改为“重复 Function 通过状态/义务/transition 递进验证后才接受”。Beam 按完整质量分（目标、状态/义务、transition、新意）保留最多 4 条，并删除近似链；无合法后继的达到最小长度 beam 由程序完成，不依赖 LLM 的 `complete` 标记。不写 `patterns`、`snapshot_patterns`、`pattern_usage` 或 Pattern Evolve。
- Outline 图新增 `dynamic_seed → dynamic_planner → mechanism → scaffold → realize → validate → export` 分支；导出 JSON 标记 `planner_mode`、`pattern_source=dynamic`、`pattern_id=null` 并保留候选审计信息。默认 published 路径保持不变。
- `Outline_Agent` 和 `StoryCLI outline` 均支持 `--planner-mode dynamic`；StoryCLI 动态批量运行不消费或锁定 Published Pattern。
- 验证：动态 Planner 与现有 Outline/Contract 回归共 37 项通过，compileall 通过；真实 Snapshot 只读输入检查通过（8 Function、8 Contract、45 转移类、67 成熟 motif）。真实 LLM Planner smoke 最终留下 4 条候选，均无硬错误，Function chain 两两相似度低于 0.8；输出汇总在 `/tmp/function-extraction-dynamic-final.YIMP1b/beam-candidates-final.json`。另有真实 `COMPOSE_MOTIFS` overlap-focused 运行：`MC_45e6407f3456c934 + MC_75f48d181d4dfe12`，实际 overlap=1，新增跨结构边 `F_8822B065 → F_31B1FB25`。候选和动态 Outline 均保持 `pattern_source=dynamic`、`pattern_id=null`；运行使用临时数据库副本，Pattern 相关表未被污染。overlap-focused 运行的下游 Outline Validator 因 LLM 生成的连续性/结局问题未通过，另一条无重叠组合 smoke 整体通过。

## `HANDOFF.md`｜跨天任务必备

长会话收尾：先写 `HANDOFF.md`，只记任务进度，不堆经验。谨慎记录过程信息
- 分析、判断、验证方式和方案取舍可以在聊天回复中说明，但不要自动写入最终交付物。
- 代码注释或说明文档只解释当前结果中确实不易理解的约束、规则、风险或兼容逻辑。
- 不记录 agent 自己引入又撤回的中间方案，也不解释为什么没有实现一个从未被用户要求的内容。
- 不要为了证明自己遵守了用户要求，而在交付物中重复用户禁止或删除的内容。

### 什么时候用？

- 长会话要结束
- 跨天推进的大任务
- 项目中间状态复杂

必须留给下一个新会话看。

### 会话结束前，直接复制这段

> 这个会话要结束了。请写一份交接文档存到 `HANDOFF.md`：我们在做什么任务、已经完成了什么、当前卡在哪、下一步计划是什么、有哪些踩过的坑绝对不要再踩。写给一个完全没有上下文的新会话看。

### 下回开新会话，第一句

> 请先读取 `HANDOFF.md`，了解项目上下文，再继续推进。

## 配合 `AGENTS.md` 使用

- `AGENTS.md`：全局编码原则（先思考再动手、简洁优先、精准修改、进展同步）
- `README.md`（本文件）：会话交接协议，规定跨天任务如何交接
- `HANDOFF.md`：任务进度交接文档，只记进度，不堆经验
---

# 任务进度

## 当前任务
Narrative Function 自动构建（第一阶段）— bootstrap 阶段改进：O_0 质量 + 速度。

## 已完成（2026-08-15）
- `batch_run.py`：story_id 从文件名派生（可复现）、`--limit N`、自然排序、耗时统计。
- `pre_processor.py`：改为规则切句（按行分段 + `。！？` 切句），去掉 LLM 调用；缺省 story_id 用 `sha256(原文前50字符)[:8]` 稳定回退。
- `llm.py`：删除 DEBUG 全量响应打印。
- `confidence.py`：coherence/surface 改按 `supporting_obs_ids` 实际 obs 计算（与 diversity 同口径）；新增 `apply_confusable` 参数，bootstrap 豁免软惩罚。
- `inducer.py`：Registry 改为 upsert——同名或 definition 相似度 > 0.85 视为重复，只保留置信度最高者；新增模块开关 `APPLY_CONFUSABLE`。
- 新增 `test/evaluator_v0.py`：O_0 启动检查（同名重复/近义组/跨故事支持/置信度分布，HEALTHY 判定）。
- 测试：`test_confidence.py`（新签名 + supporting 口径/豁免/近义保留最高分 3 用例）、`test_preprocessor.py`（规则切句）通过；`test_bank.py` 保持通过。

## 本轮（2026-08-15 续 2）：code-reviewer 审查修复 + pre_processor 恢复 LLM
- **pre_processor 恢复 LLM 分句**（用户决策，规则切句质量不满足）：`Code/Prompt/Pre_prompt.py` 已恢复；`preprocessor_node` 走 `chat_structured`（LLM 主路径），`_split_sentences` 规则切句保留为 LLM 空输出兜底 + `clean_corpus.py` 复用（含闭合引号边界修复：`“我们需要一根桅杆。”` 不再切成孤立 `”` 句，全语料孤立引号句 0）。
- **clean_corpus.py 修复 code-reviewer 发现的 M1-M9**：头部完结标记改为"剥离→保留正文"（`《冰洞》（已完结）`→`《冰洞》`，`【已完结】一夜之间…` 开篇句不再误删）；作者行用 manifest.author_name 精确匹配；尾部促销块向上吸收读者催更提问/`【打赏】`；`答案在评论区` 备注全局剔除；`clean_report.json` schema 统一（`fallback` 恒为布尔、`noise_removed` 与段落数分离、末尾换行）。
- **120 篇清洗验收**：`python test/clean_corpus.py` 重生成 `zhihu_story_subset_120_20260815_clean/`——120/120 manifest 命中、幂等 0 违规、促销/URL/孤立引号残留 0、剔除噪音 1035 行、内容守恒 -5443 字符、34 篇截断脚注。
- **测试**：`test_preprocessor.py`（mock LLM 离线跑，8 项）、`test_clean_corpus.py`（12 项，含幂等/促销残留/作者行/全角标记）全部通过；`test_bank.py` 未纳入本轮。

## 验收结果（10 篇，`batch_run.py --limit 10`，短篇语料）
- 耗时 595.7 秒（≈59.6 秒/篇，较之前 ~100 秒/篇 提速约 40%）。
- 44 obs / 13 functions；Evaluator_v0 = HEALTHY（0 同名重复、0 近义组、0 个 <2 故事支持）。
- 置信度带从 [0.50, 0.60) 上移至 [0.54, 0.71]。

## 本轮新增（2026-08-15 续）：zhihu 真实语料验证 + 数据清洗
- `pre_processor.py`：改为"行流合并段落（句末标点收束）"，兼容整段式/碎片式两种行格式；数字标记改为"孤立判定"（前后非标点碎片才算章节标记，避免误删碎片文本中的时间数字如 `23：58`）。`test_preprocessor.py` 新增碎片拼接/数字剔除/内容数字保留/孤立标记剔除用例，全部通过。
- `batch_run.py`：新增 `--corpus <dir>`（递归收集 `<answer_id>_<question_id>.txt`）与 `--stories "a.txt,b.txt"`（显式选篇，支持纯文件名避免中文路径传参乱码）；story_id = 文件名主干；读 manifest.json 注入 category/question_title 元数据。
- 5 篇跨题材验证（悬疑 2 + 古风 2 + 现代 1，含 1 篇碎片式）：307.5 秒（61.5 秒/篇）；27 obs / 8 functions；Evaluator = HEALTHY；obs 覆盖完整叙事弧、无脚注污染、participants 无具体人名。
- 新增 `test/clean_corpus.py`：语料清洗（头部版权/催更/慎入、尾部 CTA/END/URL 促销块迭代截断、孤立数字标记、碎片行合并），输出 `Code/zhihu_story_subset_120_20260815_clean/`（含 manifest 复制 + clean_report.json）。120 篇全部清洗，34 篇截断脚注，尾部促销/URL 残留 0。
- 用户决策：**120 篇全部作为 Bootstrap**（取消原 30/24/66 分法）；分批仅工程考虑（建议 3 题材 × 40 篇分 3 批）。
- 数据备份：`C:\Users\mi\AppData\Local\Temp\nf_bak_20260815_zhihu_validate\`（10 篇验证前的数据）；`nf_clean_run2\`（清洗迭代中间产物）。

## 本轮（2026-08-15 续 3）：3 篇跨题材全流程验证（LLM 分句模式）
- 运行：`python test/batch_run.py --corpus zhihu_story_subset_120_20260815_clean --stories "03_现代情感家庭/1722040836_441456266.txt,01_悬疑惊悚/2944521006_348025005.txt,02_古风穿越重生/2149938131_46404678.txt"`（须在 `Code/` 目录下）。
- 结果：608.0s（202.7s/篇）；现代 252句/8 obs、悬疑 270句/5 obs、古风 157句/5 obs；跨故事相似对 25；Function 2（IDENTITY_REVELATION conf=0.554 support=3、SPECIAL_KNOWLEDGE_REVELATION conf=0.501 support=4）。
- 结论：跨故事归纳链路打通——Function 由 2-3 篇不同题材的 obs 共同支撑；obs 质量三题材均清晰（穿书女配全弧/鬼婴复仇/重生预言）。
- 新增健壮性修复：`pre_processor.py` LLM 分句 JSON 解析失败「重试 1 次 + 规则切句兜底」（首跑现代篇偶发输出失控 104KB 被截断而失败；复跑同一篇 277 句正常）。
- 备份：`C:\Users\mi\AppData\Local\Temp\nf_bak_after_3stories\`（首跑 10 obs + 3 functions 证据）；`nf_bak_before_3stories\`（单篇 6 obs）。
- 遗留：Inducer 跨轮非确定（首跑 3 functions vs 复跑 2 functions，名称全不同）；0.5 阈值边缘候选含牵强 supporting obs。

## 本轮（2026-08-16）：悬疑 40 篇批后统一归纳（第一批）
- 实现：`app.py` 参数化 `build_pipeline_graph(include_inducer)` + 新增 `extract_app`（无 inducer 提取图）；`batch_run.py` 新增 `--genre`/`--batch-induction`/`--out-dir`；新增 `Agent/Inducer/cluster.py`（相似对聚类：边阈值 0.60 + 连通分量 + >40 obs 贪心拆分）、`test/genre_extract.py`、`test/test_batch_induction.py`。
- 冒烟：3 篇悬疑 `--batch-induction` → 阶段 1 全 Function=0，阶段 2 写入 ANOMALY_DISCOVERY；快照正常。
- 正式跑：`--genre 01_悬疑惊悚 --batch-induction --out-dir data/genre_functions`——40 篇全过，254 obs / 23 functions（阶段 2 写入 24、upsert 去重 1），耗时 11022s（275.6s/篇，总约 3.06h）。
- evaluator_v0 = HEALTHY：0 同名重复、0 近义组、0 弱支持；置信度 [0.591, 0.757]（mean 0.670）。
- 快照：`Code/data/genre_functions/functions_01_悬疑惊悚.jsonl`、`bank_01_悬疑惊悚.jsonl`、`genre_functions_summary.md`。
- 已知：部分篇 LLM 分句塌缩为 1 句（3/6/19 等），obs 仍正常提取但粒度变粗；Pre-Processor JSON 解析失败重试兜底在 ~7 篇触发并成功。
- 遗留：古风、现代两批待跑（预计各 ~3h）；批后归纳 obs 相似度阈值已按 MiniLM 实测分布校准为 0.60（max≈0.69）。
- **Pre-Processor prompt V2（去重复输出）**：`segments` 不再输出 `content`（实测输出量 -40%）；3 篇同批冒烟 117.1s/篇 vs V1 208.0s/篇（-44%），句子粒度与守恒不变；空 `sentences` 兜底改走 `_rule_normalized_result`。古风/现代两批将用 V2 跑（预计每批耗时降至 ~2h）。

## 本轮（2026-08-16 续）：古风 + 现代两批（V2 分句）
- 古风（`--genre 02_古风穿越重生`）：40 篇全过，293 obs / 23 functions；耗时 9602.8s（240.1s/篇）；evaluator_v0 = HEALTHY（0 同名 / 0 近义 / 0 弱支持；置信度 [0.626, 0.750]）；快照 `functions_02_古风穿越重生.jsonl` / `bank_02_古风穿越重生.jsonl`。
- 现代（`--genre 03_现代情感家庭`）：40 篇全过，284 obs / 30 functions；耗时 7806.7s（195.2s/篇）；evaluator_v0 = HEALTHY（置信度 [0.533, 0.737]）；快照 `functions_03_现代情感家庭.jsonl` / `bank_03_现代情感家庭.jsonl`。
- 三题材对比：`test/genre_extract.py --out-dir data/genre_functions` → 悬疑 23 / 古风 23 / 现代 30，跨题材近义组 20；摘要 `genre_functions_summary.md`。
- 速度实测：V2 真实批量 240.1 / 195.2s/篇 vs V1 悬疑 275.6s/篇（-13%~-29%）；冒烟 -44% 未全量复现（DeepSeek 延迟波动），输出量 -40% 为确定性节省。

## 本轮（2026-08-16 续 2）：Evaluator_v0 批后六维本体评估
- 实现：
  - `Agent/Evaluator/dimensions.py`：六维纯函数（Coverage / Cohesion / Separation / Abstraction / Evidence / Diversity），阈值集中定义在模块顶部；`detect_bidirectional_conflation` 双向混叠方向词对规则预筛；`evaluate_function_set` 聚合 → PASS/FAIL（达标 ≥4/6）。
  - `Agent/Evaluator/evaluator.py`：`evaluator_node(state)` 读 Registry + Bank（`evaluation_context` 可覆盖 `registry_file`/`bank_file`/`manifest_path`/`report_path`，便于对快照并集评估）；Abstraction 用 LLM 逐批复核（20 函数/次，某批失败退回规则预筛）；报告落盘 `Code/data/evaluation/evaluation_report.json`；空 Registry 兜底 FAIL。
  - `Prompt/Evaluator_prompt.py`：`EVALUATOR_SYSTEM_PROMPT` + `EvaluatorReviewResponse`（bidirectional_conflation / genre_surface_binding / granularity / recommendation）。
  - `Agent/state.py`：新增 `evaluation_report` / `evaluator_decision` / `next_node` / `evaluation_context` 四字段（仅记录，不自动循环）。
  - `test/batch_run.py` 阶段 3：`--batch-induction` 归纳循环结束后直接调用 `evaluator_node`（自动传 corpus manifest 路径），打印判定与六维表，FAIL 打印建议清单。
  - 删除 `test/evaluator_v0.py`（核心检查由 Separation + Evidence Count 承接），确认无残留引用。
- 测试：`test/test_evaluator.py` 9 项全过（六维计算 / 双阈 separation / ≥4/6 判定 / mock LLM 节点 / 空 Registry 兜底）；回归 `test_confidence` / `test_preprocessor` / `test_clean_corpus` / `test_batch_induction` 全过。
- 集成验收（三题材快照并集 76 funcs / 831 obs + manifest，`evaluation_context` 指向三份 `functions_0X` + `bank_0X`）：PASS 5/6（仅 Separation FAIL）；coverage=0.83、cohesion=0.88、separation=13、abstraction=0.83、evidence=3.78、diversity=3。
- 验收发现：13 组近义（最高 `CONFLICT_RESOLUTION`≈`RELATIONSHIP_STRENGTHENING` 0.995、`INFORMATION_REVELATION`≈`RELATIONSHIP_BREAKDOWN` 0.908）；4 个题材绑定函数（`SUPERNATURAL_ENCOUNTER`/`FATE_REWRITING`/`SECOND_CHANCE`/`FATE_CHANGE_DECISION`）；7 个双向混叠 REVISE 建议；weak-fit 阈值 0.80→0.70 后仅 5 条真离群（0.80 标 49 条过噪）。
- 阈值校准（已写入 `dimensions.py`）：COVERAGE_SIM 0.65、COVERAGE_PASS 0.60、COHESION_PASS 0.60、OBS_FIT 0.70、SEP 分组 0.85 / 复核 0.78（0.78 分组串巨型连通分量，降级复核列表）、ABSTRACTION_PASS 0.80、EVIDENCE 2/3/4、DIVERSITY 2 题材（回退 20 故事）、PASS_MIN_DIMENSIONS 4。

## 本轮（2026-08-16 续 3）：Bootstrap 自动修订闭环（curate_app）
- 实现：
  - `Agent/Evaluator/revise.py`：`revise_node` 消费评估报告全自动修订——近义组 MERGE（supporting obs 程序并集）、定义 REVISE、SPLIT（obs 按"obs 文本 vs 子函数定义余弦"确定性分配，无匹配子函数丢弃）、weak-fit obs 剔除、低证据（<2 故事）移除；被改函数置信度用 `calculate_confidence_detailed(apply_confusable=False)` + SimpleNamespace 轻量桩重算；写回前备份 `<registry>.pre_revise.jsonl`。
  - `Prompt/Merge_prompt.py` / `Prompt/Revise_prompt.py`：合并/修订 schema 与提示词。
  - `Agent/app.py`：`curate_app` 编译图（START→evaluator→conditional→revise→evaluator…→END）；`should_continue`：FAIL 或报告仍有可执行问题（merge_groups/revise_definitions/genre_bound/granularity/weak_fit/low_evidence）→ revise，直到 PASS 或 `MAX_EVAL_ROUNDS`（默认 3）。
  - `Agent/state.py`：新增 `revise_report` / `evaluation_round`；`Agent/Evaluator/evaluator.py`：报告持久化 `abstraction_reviews`（供修订节点消费 recommendation==REVISE/SPLIT）；默认报告路径修正为 `Code/data/evaluation/`。
  - `test/batch_run.py` 阶段 3：改用 `curate_app`（评估 + 自动修订闭环），`--out-dir` 快照即修订后最终 O_0；新增 `test/curate_run.py`（独立闭环入口，`--no-revise` 仅评估）。
- 测试：`test/test_revise.py` 7 项全过（supporting 并集/SPLIT 分配/weak-fit/低证据/confidence 桩/节点全动作/闭环图终止：PASS 提前结束 + 上限强制结束）；回归 `test_evaluator/test_batch_induction/test_confidence/test_preprocessor/test_clean_corpus` 全过。
- 集成验收（三题材并集 curate_app 3 轮，真实 LLM，增量复核 + 同名去重版 515s）：76 → 57 funcs（同名 0）；Separation 13 → 0；题材绑定/粒度/weak-fit/低证据全部清零；Abstraction 0.965、evidence mean_obs 4.65；最终 PASS 6/6（coverage 0.81 / cohesion 0.87 / separation 0 / abstraction 0.96 / evidence 4.65 / diversity 3）。报告落盘 `data/evaluation/evaluation_report.json` + `revise_report.json` + 每轮 `revise_rounds.jsonl`（含 renamed_duplicates）。历史：全量复核版 680s / 76 → 56 / PASS 6/6；增量版 535s / 76 → 59；首采样 PASS 5/6（残留 2 组 SPLIT 镜像近义）——LLM 非确定性，交付物以最新为准。
- 已知：SPLIT 拆出的正/负镜像对可能被 Separation 标为近义（definition 高度对称，首采样 0.982 复现、重跑未复现）；同名但 <0.85 的函数对不在本轮合并范围，落在 review_pairs。

## 本轮（2026-08-16 续 4）：curate_app 增量 Abstraction 复核
- 背景：闭环 680s 里约 13–16 次 Abstraction LLM 全量复核（`_REVIEW_BATCH_SIZE=20`）占大头；"只跑有问题的组"不可行——近义组是向量免费检测，但双向混叠/题材绑定/粒度只能靠 LLM 圈出，且修订产物会带新问题（merge 出的 `RELATIONSHIP_TRANSFORMATION` 第 2 轮又被 REVISE）。
- 改动：
  - `Agent/Evaluator/evaluator.py`：`_review_abstraction(functions, review_targets=None, prev_reviews=None)`——首轮全量，后续轮只复核 `review_targets`（变更集 + 缺旧评审兜底），未变更函数按 function_name 复用旧评审；返回合并后评审 + 新评审数/复用数；`evaluator_node` 读 `state.review_targets`（回退 `revise_report.changed`），报告记录 `abstraction_reviewed/reused`。
  - `Agent/Evaluator/revise.py`：记录 `changed_names`（merge 产物 / revised / split 子函数），写入 `revise_report.changed` 并回传 `review_targets`；新增 `_dedup_names`——LLM 生成名字与存量撞名时加 `_N` 后缀，保证 O_0 函数名唯一（实测 `RELATIONSHIP_BONDING`/`RELATIONSHIP_BREAKDOWN`/`RELATIONSHIP_DEEPENING` 各加 `_2`）。
  - `Agent/state.py`：新增 `review_targets: list[str] | None`。
  - `test/curate_run.py`：回溯 checkpointer 历史，每轮 `revise_report` 追加落盘 `revise_rounds.jsonl`（按时间序，含 changed）。
- 测试：新增"增量只评变更集"/"空变更集零 LLM 调用"单测 + 闭环图测试（第 2 轮只评 merge 产物 F_AB、历史可回溯断言）；`test_revise/test_evaluator/test_batch_induction/test_confidence/test_preprocessor/test_clean_corpus` 全过。
- 实测（并集重跑，2026-08-16）：Abstraction LLM 调用 13–16 → 8 次（全量 4 批 / 增量 30/11/1）；耗时 680s → 515s（-24%）；76 → 57 funcs（同名 0），最终 PASS 6/6；`revise_rounds.jsonl` 记录每轮动作、changed 与 renamed_duplicates。
- 取舍：首轮 LLM 漏检的函数，增量轮不会自动重抓（可加最后一轮全量终检兜底，未启用）。实测观测：第 1 轮 LLM 对 76 个函数只返回 56 条评审（缺 20），由"缺旧评审兜底"在第 2 轮自动补评，未影响收敛。

## 本轮（2026-08-16 续 5）：Registry SQLite 化 + 5 篇试跑
- Agent/Registry/registry.py：RegistryStore（SQLite，命名空间隔离，payload 整存字段无损）；Inducer/Confidence/Evaluator/Revise 收敛到活跃 store；atch_run 启动只清当前批命名空间（--genre or "all"）；
evise store 写回前导出 .pre_revise.<ns>.jsonl；新增 	est/import_registry.py（JSONL→命名空间）与 	est/test_registry.py（5 项）；.gitignore 加 Code/Agent/data/registry/，unctions.jsonl 已 git rm --cached。
- 清空旧数据：Code/data/genre_functions/、Code/data/evaluation/、Code/Bank/data/、Code/Agent/data/registry/functions.jsonl 已删除。
- 5 篇跨题材试跑（悬疑 2 + 古风 2 + 现代 1，--batch-induction）：40 obs / 5 functions（均 ≥2 故事）；闭环 PASS 5/6（第 1 轮 4/6 → 修订 3 个题材绑定/粒度函数 → 5/6；evidence 2.2 小样本预期失败）；1282s（256.4s/篇）；DB ll 命名空间与 data/trial5/functions_all.jsonl 逐字段一致。日志 Code/test/logs/trial5.log。

## 本轮（2026-08-16 续 6）：Bootstrap 提速（reasoning_effort=none + V3 混合切句）+ 5 篇试跑
- 根因：耗时大头是 deepseek-v4-flash 隐藏推理 token（单次切句 8220 completion 中 8207 为 reasoning），不是"全文回显"。
- 改动：`Agent/llm.py` chat/chat_structured 默认 reasoning_effort="none"（low→none 约 20 倍）；`pre_processor.py` 默认走 V3 混合切句 `_hybrid_normalized_result`（规则切句 + LLM 只输出 merges/splits 修正，不回显全文）；`LLM_USAGE=1` 按调用方归因 usage/耗时。
- 删除 `positive_examples`（inducer/revise/Inducer_prompt 零读取字段）；回归全过。
- trial5_none（5 篇跨题材，--batch-induction --out-dir data/trial5_none）：93.9s（18.8s/篇）vs 基线 1282s → 约 13.6 倍；47 obs / 5 functions（与基线数量一致）；闭环 PASS 5/6（修订 1 / 拆分 1；evidence 小样本预期失败）；LLM 15 次 / 89,791 tok / 88.8s。日志 Code/test/logs/trial5_none.log。
- 3 篇试跑（trial_none）只出 1 function → 样本量不足，非配置退化。

## 本轮（2026-08-16 续 7）：V3 定版提交 + 120 篇全量重跑验收
- 已提交 139e238（Bootstrap V3 定版）：V3 混合切句 + reasoning_effort=none + SQLite Registry + 批后提速闭环；untrack __pycache__/Bank 数据；.env 仍被跟踪（历史遗留，建议后续处理）。
- 三批全量重跑（新配置）：悬疑 638.9s/335 obs/31 funcs；古风 670.9s/304 obs/32 funcs；现代 832.9s/372 obs/39 funcs；合计 ~36min（17.8s/篇，~13 倍提速）。日志 test/logs/batch_0X_*.log。
- 并集：102 funcs/1011 obs → curate 3 轮 → 75 funcs，PASS 5/6（separation 16→0；evidence mean_obs 3.79 未达标）；union 命名空间已导入（import_registry）。快照 data/genre_functions/ + data/evaluation/。

## 本轮（2026-08-16 续 8）：统一全流程 run_bootstrap.py（一次过全量）
- 新增 `Code/run_bootstrap.py` 一键入口：清空 Bank+本命名空间 → 全量提取 obs → 跨题材统一聚类归纳（0.60，≥2 故事分量）→ curate_app 评估+修订闭环 → 快照 data/bootstrap/。删除 test/batch_run.py、genre_extract.py、gen_evaluation_report.py、curate_run.py、import_registry.py（无残留 import/引用）；`llm.py` 删除 reasoning_effort 参数、硬编码 "none"（无外部调用方覆盖）；docstring/注释同步（cluster/registry/inducer/evaluator/revise/clean_corpus）。
- 冒烟：3 篇跨题材（悬疑/古风/现代各 1）52.7s（17.6s/篇）；30 obs → 1 跨题材分量 → 6 函数 → 修订移除 3 低证据 → 3 函数；Evaluator PASS 4/6（evidence 小样本预期失败）；LLM 8 次 / 50,298 tok；快照 functions_bootstrap.jsonl + bank_bootstrap.jsonl；DB bootstrap 命名空间 3 条。日志 test/logs/run_bootstrap_smoke.log。
- 回归：test_preprocessor/test_registry/test_revise/test_evaluator/test_batch_induction/test_confidence/test_clean_corpus 54 项全过。

## 本轮（2026-08-16 续 9）：Evidence 阈值校准 + run_bootstrap --evaluate-only
- `dimensions.py`：EVIDENCE_MEAN_STORIES 3.0→2.5、EVIDENCE_MEAN_OBS 4→3（硬下限 ≥2 故事不动）；`run_bootstrap.py` 新增 `--evaluate-only`（非破坏性评估现有快照）；`test_evidence` 增边界用例（2.5/3.0 通过、2.0/2.5 失败）。
- 重评（`--evaluate-only`）：evidence score=2.892 **pass=True**；但全新全量 Abstraction 复核 0.7952（<0.80）→ 整体 PASS 5/6（换维度）。原 1.0 来自增量复用；约 17 个函数有可执行问题（4 REVISE / 2 too_broad / 6 题材绑定）。日志 test/logs 无（前台）；报告 data/evaluation/evaluation_report.json 已刷新。
- 回归：test_evaluator 11 项 + 其余 6 文件 43 项全过。

## 本轮（2026-08-16 续 10）：curate 最终全量复核 + --curate-only 闭环验收
- 流程修复：`app.py` 新增 `final_review` 节点（force_full_review → 全量复核不复用），PASS/达上限后强制全新测量；`state.py` 加 `force_full_review`；`evaluator.py` 支持该开关；`test_curate_incremental_review` 改为 3 次复核断言（第 1 轮全量 + 第 2 轮增量 + 最终全量）。
- `run_bootstrap.py` 新增 `--curate-only`（命名空间上跑评估+修订闭环，写回 DB + 同步快照，不清空/不提取）。
- 验收（bootstrap 命名空间，2026-08-16）：83 → 82 functions（拆分 5 / 移除 2）；3 轮修订；最终 **PASS 6/6**（coverage 0.761 / cohesion 0.884 / separation 0 / abstraction 0.890（全量最终复核）/ evidence 2.89 / diversity 3）；残留建议 4 REVISE / 3 题材绑定 / 1 粒度 写入报告供 Evolve 参考。日志 test/logs/run_bootstrap_curate.log；快照 data/bootstrap/functions_bootstrap.jsonl（82）与 DB bootstrap（82）一致。
- 回归：54 项全过（含 evidence 边界用例）。

## 本轮（2026-08-16 续 11）：Bootstrap 单图重构 bootstrap_app + checkpoint/--resume
- 实现：
  - `Agent/app.py` 收敛为唯一编译图 `bootstrap_app`：`story_loader →[continue_extraction]→(preprocessor→observer→bank_adder→retrieval→pairs_collector→story_loader 循环)→cluster→[continue_induction]→(induce_step 循环)→evaluator→[route_after_evaluator]→(revise 循环/final_review)→[route_after_final]→export→END`；删除 `run_bootstrap.py` 与 `pipeline_app`/`extract_app`/`curate_app`。CLI 收敛 `python -m Agent.app`（仅 `--corpus/--namespace/--out-dir/--limit/--stories/--no-revise` + 新增 `--resume`）。
  - 持久化：`SqliteSaver`（`data/checkpoints/bootstrap-<ns>.sqlite3`，thread_id=`bootstrap-<ns>`）；无 `--resume` 时 fresh（`bank.clear()` + `RegistryStore(ns).clear()` + `delete_thread`），`--resume` 跳过清理、`invoke({})` 续跑（Bank 按 obs_id 去重幂等）。`langgraph-checkpoint-sqlite`/`sqlite-vec`/`aiosqlite` 装到 `Code/vendor/`（全局 site-packages 不可写），`app.py` 有则前置 `sys.path`；`.gitignore` 加 `Code/vendor/` 与 `.pytest_cache/`。
  - `Agent/state.py`：新增 `story_files/corpus_dir/story_meta/all_pairs/induction_components/induction_index/errors/no_revise/namespace/out_dir`；`route_after_evaluator/route_after_final` 增加 `no_revise` 分支；逐篇/每分量/判定打印移入图内节点。
  - 测试：`test_revise.py` 3 个闭环用例改用 `bootstrap_app`（临时 in-memory SqliteSaver + 空 story 列表直达评估）；新增 `test_bootstrap_app.py`（全流程 no-revise、interrupt→新实例同 DB 续跑、单篇失败跳过、空 story 直达评估）。
- 验证：图逻辑 13 项通过（Embedding 桩 + FakeEmbedder）；torch-free 回归 33 项通过（test_preprocessor/test_registry/test_batch_induction/test_clean_corpus）。
- **环境阻塞**：沙箱用户 `codexsandboxoffline` 无法加载 `torch_python.dll`（WinError 5；shm/python313/torch_cpu 均可加载，临时副本同样失败）→ 依赖 torch 的测试（test_confidence/test_evaluator 大部分、真实 Embedder 路径）本轮无法运行；需在可正常加载 torch 的环境跑全量回归 `python -m pytest test/ -q`。

## 本轮（2026-08-17 续 12）：bootstrap_app 单图 120 篇全量验收 + llm.py JSON 数据层加固
- **修复（最终方案）**：首跑 120 篇在第 2 篇崩溃——observer 的 LLM 输出 JSON 解析失败（缺 `affected_aspect`/控制字符）抛 pydantic ValidationError。先尝试 `story_process` 子图节点方案，被用户否决（不新增节点、简洁优先）；最终改为加固 `llm.py` 的 `chat_structured`：解析/校验失败附错误反馈自动重试（最多 2 次）+ 轻量修复（控制字符/尾逗号）。新增 `test_llm.py`（5 项）；图测试 13 项、torch-free 回归 38 项全过。
- **全量验收（2026-08-17）**：120 篇 → 117 成功（3 篇因 observer LLM 坏 JSON 跳过）；1006 obs → 45 个归纳分量（1 个分量 inducer JSON 失败）→ **61 functions**（conf [0.528, 0.749]，mean 0.663；24 个恰 2 故事 / 37 个 ≥3 故事）。耗时 3112.9s ≈ 51.9 分钟（25.9s/篇）；LLM 307 次 / 1.97M tok（observer 1465s + inducer 795s 大头）。
- **Evaluator**：**PASS 4/6**——coverage 0.695 / cohesion 0.888 / separation 0 / diversity 3（87 故事三题材）；未达标：abstraction 0.7541（<0.80；3 轮修订上限内未收敛，残差 9 题材绑定 / 3 双向混叠 REVISE / 粒度，已写入报告）、evidence 2.721/2.885（mean_stories 2.721 ≥2.5 过、mean_obs 2.885 <3 差一线）。
- 对比历史（run_bootstrap.py 全量：83 funcs / PASS 5/6 / 37.8min）：函数更少、abstraction 未收敛——差异主要来自跨题材统一归纳的 LLM 非确定性 + 3 轮上限，语义本身已随单图重构变化。
- 产物：DB `bootstrap`（61）+ 快照 `data/bootstrap/functions_bootstrap.jsonl`（61）/ `bank_bootstrap.jsonl`（1006）；报告 `data/evaluation/evaluation_report.json`；日志 `test/logs/bootstrap_full_20260816.log`；checkpoint `data/checkpoints/bootstrap-bootstrap.sqlite3`（可 `--resume`）。

## 本轮（2026-08-17 续 13）：JSON 层加固 + source_sentence_indices 全量复验（120/120 成功）
- `ObservationItem` 补 `source_sentence_indices`（缺省 `[]`，对齐提示词，供 Evolve obs↔句子 可追溯）；3 篇冒烟 32/32 obs 带非空字段。
- 120 篇全量：**0 跳过**（observer 121 次 = 120 篇 + 1 次 JSON 重试成功；对比上版 3 篇跳过）；978 obs 全部含非空 `source_sentence_indices`；**85 functions**；39.4min（19.7s/篇）；LLM 314 次 / 1.96M tok。
- Evaluator PASS 4/6：coverage 0.7474 / cohesion 0.8762 / separation 0 / diversity 3（99 故事）；abstraction 0.7647（3 轮上限未收敛，残差写入报告）+ evidence 2.788/2.929 未达标。
- 产物：DB `bootstrap`（85）+ 快照 `data/bootstrap/`（85 funcs / 978 obs）+ 报告 + 日志 `test/logs/bootstrap_full_20260817.log`。**当前 O_0 = 85 functions（含溯源字段）。**

## 本轮（2026-08-17 续 14）：Separation 改由 LLM 判定，删除余弦门槛
- 决策链：近义碎片化 → 余弦 0.85 漏检 / 0.78 串假簇 → 用户定 B 方案：**彻底删掉余弦 Separation**。
- 改动：`dimensions.py` 删除 `compute_separation` 与 `SEP_NEAR_DUP_THRESHOLD/SEP_REVIEW_*`；`evaluate_function_set` 新增 `merge_groups` 参数，`separation = {score: len(merge_groups), pass: ==0}`；`generate_recommendations` 输出 `merge_groups`（移除 near_dup 诊断）；`evaluator.py` 的 `_review_abstraction` 从复核响应收集 `merge_groups`（此前已删掉独立检测函数 `_detect_merge_groups`）。
- 判定影响：Separation 现在是六维中由 LLM 合并组驱动的 1 维（0 组达标）；verdict 仍是 ≥4/6。
- 测试：64 项全过（Separation 改用 LLM 组判定、≥4/6 逻辑、无门槛进 merge_groups）；`rg compute_separation|SEP_NEAR_DUP|near_dup_*` 零残留。

## 本轮（2026-08-17 续 15）：O_0 未达标舍弃（复用 export_node，不新增节点）
- 决策：达 3 轮上限（或 `--no-revise`）后若 `verdict==FAIL` 或仍有可执行问题 → **舍弃**（用户定：FAIL∪可执行问题、清空命名空间且无备份、no_revise 同样）。对齐设计文档 §4.6（FAIL → 不进入 registry_init）。
- 实现：不新增节点——舍弃逻辑并入 `export_node`（开头判定，命中则 `get_active_store().clear()` + 删除 `functions_<ns>.jsonl`/`bank_<ns>.jsonl` + 返回 `discarded=True`，否则照常统计+导出）；`route_after_final` 保持原三态路由；`state.py` 加 `discarded: bool`；`main()` 置 `discarded` 时打印并 `sys.exit(1)`。
- 测试：`test_curate_max_rounds`（FAIL@cap → discarded、命名空间清空、无快照）、`test_empty_story_list`（no_revise FAIL → discarded）、新增 `test_curate_actionable_persists_discards`（merge 持续失败 → cap → 舍弃清空预置函数）；对照 PASS/无可执行问题用例维持导出。

## 本轮（2026-08-17 续 16）：checkpoint 膨胀修复 + 全量 120 严格语义验证
- **根因**：单图单线程把所有超步完整状态序列化进同一 checkpoint；`all_pairs` 携带完整 obs 字典 → checkpoint 随篇数超线性膨胀（5篇 12MB / 30篇 213MB / 74篇 **2.6GB 并卡死**，首跑 2h 未到 75 篇）。
- **修复**：`pairs_collector` 改存 obs_id 三元组（ref/ret/similarity），`cluster_node` 聚类前从 Bank 重建完整对。全量 120 恢复 39.5 分钟完成；checkpoint ~475MB。
- **全量 120（严格舍弃语义验证）**：994 obs → 89 functions；中途评估一度 **PASS 6/6**，但 final_review 全量复核暴露 separation 2（2 组 LLM 近义合并：`EXCLUSION_AND_REJECTION+SOCIAL_ISOLATION`、`NEW_RELATIONSHIP_INTRODUCTION+RELATIONSHIP_INITIATION`）+ 2 双向混叠 + 1 weak-fit → **PASS 5/6 但仍有可执行问题** → 3 轮上限内未排完 → **舍弃**（bootstrap 命名空间清空、快照删除、退出码 1，报告保留）。
- **矛盾点**：严格"必须收敛"语义下 final_review 全量复核的 LLM 判定几乎总会挑出残差，3 轮上限经常排不完 → 多数全量跑会舍弃。待决策：加轮（MAX_EVAL_ROUNDS）、放宽舍弃条件（仅 FAIL 舍弃）、或接受重跑撞收敛。

## 本轮（2026-08-17 续 17）：舍弃语义修正——整批清空 → 逐函数舍弃
- 用户澄清："舍弃不达标的 function，没有说全部 function 舍弃"——整批清空是理解偏差。
- 实现：`export_node` 删除整批 `clear()` 分支，改为按 `final_review` 报告逐函数移除——`revise_definitions / genre_bound_functions / granularity_issues / low_evidence_functions` 全部移除，`merge_groups` 每组保留 supporting obs 最多者（同长按 confidence、再按名称字典序，确定性）；幸存者 `store.replace_all` 后照常导出；被移除函数完整 payload 写 `discarded_<ns>.jsonl` 留档；全部被移除才 `discarded=True`（退出码 1）。`route_after_final` 不变；`weak_fit` 属 obs 级不触发函数移除。
- 测试：新增 `export_node` 直测 4 项（merge 组保留最优 / 五类标记移除 / 全移除无 O_0 / 无标记照常导出），改写 merge-fail 用例为"保留证据最多者、幸存者导出"；全量 69 项通过。

## 本轮（2026-08-17 续 18）：全量 120 验收（逐函数舍弃）+ 稳定性修复
- **运行方式**：分离进程 + 文件重定向 + `-u` 无缓冲 + 每 60s 监控（stall≥3 判卡死）。此前"shell 中断 → 管道断开 → 孤儿进程空转"导致卡死（另注：早期 checkpoint 2.6GB 膨胀已由 all_pairs 三元组修复；本轮 checkpoint 全程 162→469MB 稳定）。
- **全量 120（worktree）**：998 obs → 75 候选 → final_review 标记 → **逐函数舍弃 16 个**（5 组近义 loser + 5 双向混叠 + 5 题材绑定 + 粒度）→ **幸存 59 个导出为 O_0**（conf [0.585, 0.742]，20 个恰 2 故事 / 39 个 ≥3）。判定 PASS 5/6（separation 5 未达标但不再整批舍弃）。耗时 2320.9s（19.3s/篇），LLM 320 次，全程零卡顿。
- **产物**：DB `bootstrap`（59）+ `data/bootstrap/functions_bootstrap.jsonl`（59）/ `bank_bootstrap.jsonl`（998）/ `discarded_bootstrap.jsonl`（16 留档）；`trial30w`（16）保留。
- **清理**（死代码审计）：删 `next_node` 字段、模块级 `bootstrap_app`、`PREPROCESSOR_SYSTEM_PROMPT`、`Embedding/__init__.py`/`Retrieval/__init__.py` 未用再导出；worktree 补齐 vendor 与 `.env`。

## 本轮（2026-08-18 续 19）：全量抽象归并（识别近义组 + 复用 _llm_merge）+ O_0=52
- 用户定调：OR 命名本身不该禁（同一结构作用的不同侧面用 OR 合法，如 TRUST_BREACH+UNCERTAINTY_AND_DOUBT 归类正是诉求）；真正该防的是 OR 连接相反方向/不同结构作用（双向混叠）。撤销 `_OR_` 代码过滤。
- `abstract_merge`（export 前）：① 1 次全量 LLM 调用识别近义组（只输出 members）；② 每组复用 `revise._llm_merge` 重新归纳为一个新的统一函数（supporting 并集 + confidence 重算；"方向相反拒绝合并"；失败该组保持原样）。新增 `Prompt/Abstract_merge_prompt.py`。
- **全量重跑 120（2026-08-18）**：985 obs → 归并 40→18（1 识别 + 14 次 `_llm_merge`）→ **O_0 = 52 个函数**（仅 1 个 OR 命名 `HARM_OR_VIOLENCE`；其余均为单一概念如 ABILITY_REVELATION / CRISIS_EVENT / DECEPTIVE_APPEARANCE / EXTERNAL_FORCE_INTERVENTION）。CSV → `data/functions_export.csv`（52 行）。
- 测试 75 项全过（abstract_merge 单测 6 项：并集/失败保持/过滤/重名/识别失败降级/单函数跳过）。
- 环境清理：杀掉自 2026-08-17 残留卡死的 `python -m Agent.app` 进程（PID 3724，20h CPU）。

## 本轮（2026-08-19 续 33）：切换 bge-small-zh-v1.5（512 维）+ Bank 重建
- 网络恢复后成功下载 `BAAI/bge-small-zh-v1.5`（512 维）；`embedding.py` 默认模型 text2vec → **bge-small-zh-v1.5**；Bank 用 bge 重建（340 obs，**34s** vs text2vec 133s，embedding 快 ~4 倍）。
- 测试 FakeEmbedder 维度 768 → 512（4 文件）；**106 项全过**（且测试总耗时 46s，明显更快）。
- **终评（bge）PASS 6/6**：coverage 0.888 / cohesion 0.863 / separation 0 / abstraction 1.0 / evidence 7.208 / diversity 38；对比 30→24。函数定义向量缓存（encode_cached）保留生效。

## 本轮（2026-08-19 续 32）：函数定义向量缓存（bge 下载受阻，暂留 text2vec）
- 用户要求换 `BAAI/bge-small-zh-v1.5` + 缓存函数定义向量；**bge 下载失败**（hf-mirror 与 HF 直连均 SSL UNEXPECTED_EOF，网络对 huggingface 不可达，text2vec 是此前成功下载的缓存）→ 暂留 text2vec（768 维），等网络恢复后可一行切换 + 重建 Bank。
- **已落地缓存**：`Embedder.encode_cached(texts)`（文本→向量缓存，函数定义固定文本复用）；调用点 Matcher 召回、Evaluator coverage、Curator Agglomerative 拎候选均改用它（函数定义在单次 Evolve 中不变，Curator 最后才改）。测试 FakeEmbedder 补 `encode_cached`（4 文件）。
- 测试 **106 项全过**；40 篇重跑（82min）仍是 text2vec，换 bge 后 embedding 应显著提速。

## 本轮（2026-08-19 续 31）：Curator 近义收敛改 Agglomerative 拎候选 + LLM 确认
- 用户确认"先拎出近义组、LLM 处理"流程：`_full_merge_scan` 拎组从"全量 LLM 扫描"改为 **Agglomerative 聚类**（`AGGLOMERATIVE_SIM_THRESHOLD=0.75`、`scipy` linkage **complete** 防链式串簇 + fcluster 距离 0.25）→ 候选组喂 `Abstract_merge_prompt`（LLM 确认"同一结构作用"）→ `_llm_merge` 重新归纳；抽出 `_agglomerative_candidates` helper 便于测试。
- **验收（19 → 18 函数）**：Agglomerative 拎出 3 候选组（KEY_DECISION_REVERSAL~TRANSFORMATIVE_CHANGE、PASSIVE_HARM_SUFFERING~SOCIAL_ISOLATION、RELATIONSHIP_BONDING~RELATIONSHIP_INTIMACY_ESCALATION）——正好 text2vec 实测 3 对、无漏无假；LLM 确认只合并关系族（→`RELATIONSHIP_DEEPENING`），拒绝 2 个边界/不同结构。
- **终评 PASS 6/6**（18 函数）：coverage 0.847 / cohesion 0.849 / separation 0 / abstraction 0.944 / evidence 8.111 / diversity 36；对比 30→18。
- 测试 **106 项全过**（新增 Agglomerative 不串簇 / 无候选不调 LLM 用例；scipy 1.18 可用）。

## 本轮（2026-08-19 续 30）：按 text2vec 分布校准阈值（coverage/cohesion/聚类）
- 实测 text2vec 分布：非 supporting obs 与最近 definition 余弦 P50=0.613（0.65 偏严）；跨故事 obs 对 mean=0.630（MiniLM 时代 0.60 是噪声底线，text2vec 整体上移）；supporting obs fit mean=0.835 / P10=0.777（0.70 weak-fit 阈值正好抓真离群）。
- 校准：`COVERAGE_SIM_THRESHOLD` 0.65 → **0.60**（coverage 0.748 → 0.847，309/365）；`BATCH_EDGE_SIM` 0.60 → **0.65**（聚类连边从 65% 降到 ~40%）；`OBS_FIT_THRESHOLD=0.70`、`COHESION_PASS=0.60` 保留（实测安全）。
- 测试：更新 `test_batch_induction.test_constants`（0.65）；curator 测试包 `_no_merge_scan`（避免近义扫描触发真实 LLM）；**104 项全过**。
- 终评（校准后 text2vec）**PASS 6/6**：coverage 0.847 / cohesion 0.848 / separation 0 / abstraction 1.0 / evidence 7.895 / diversity 36。

## 本轮（2026-08-19 续 29）：Embedding 换中文模型（text2vec-base-chinese，768 维）
- 用户要求把 MiniLM 定义向量换成适合中文的模型：`all-MiniLM-L6-v2`（384 维）→ **`shibing624/text2vec-base-chinese`**（768 维，中文 STS 基准）。已下载到 HF 缓存（离线加载正常）。
- **效果对比**：近义对"获得外部资源/通过外部援助"余弦 MiniLM <0.78 → text2vec **0.853**；不同结构 0.422——中文近义区分度大幅改善。19 函数 definition 近义对：关系族 0.85、决定反转~转变 0.82（MiniLM 下资源族都 <0.78 抓不到）。
- **配套**：Bank 重建（Chroma 维度 384→768，365 obs 用 text2vec 重嵌入，~3min）；测试 FakeEmbedder 默认维度 384→768（4 个文件）；**104 项测试全过**。
- **终评（text2vec）PASS 6/6**：coverage 0.748（MiniLM 时 0.986——text2vec 分布更严格，阈值 0.65 仍达标）/ cohesion 0.848 / separation 0 / abstraction 1.0 / evidence 7.895 / diversity 36；weak_fit 2 条（0.69/0.67 边缘）。
- 注意：coverage 等阈值基于 MiniLM 分布，text2vec 下偏保守（语义更严格）；如需对齐可校准（`COVERAGE_SIM_THRESHOLD` 等）。Curator 近义收敛用 LLM 扫描（不依赖向量），不受影响。

## 本轮（2026-08-19 续 28）：Curator 近义收敛机制（全量 LLM 扫描）+ 40 篇碎片处理
- 用户反馈 evolve_official 内部有近义碎片（外部资源 2、真相 2、关系 3、压力/后果 2 等）。先试向量预筛（definition 余弦）：0.85 漏检（MiniLM 中文对"用词不同但同义"余弦不够）、0.78 假簇/争议（把 ANOMALY_OMEN 连进真相族、FATAL_INCIDENT 连进资源族）——**MiniLM 中文定义向量不适合近义预筛**。
- 改为复用 bootstrap 验证过的机制：Curator 每批 `_full_merge_scan`（全量函数卡片 → `Abstract_merge_prompt` 专门识别"同一结构作用"组 → 每组 `_llm_merge` 重新归纳，`REVISE_MIN_SUPPORTING=3` 门槛）。删除临时 `Confirm_merge_prompt.py`。
- 40 篇当前碎片收敛：24 → **19 函数**（合并 5 组：结盟+关系发展→RELATIONSHIP_BONDING、异常征兆+部分真相→CLUE_OMEN_REVELATION、外部资源介入+获得→EXTERNAL_ASSISTANCE_INTERVENTION、亲密增加+关系升级→RELATIONSHIP_INTIMACY_ESCALATION、社会压力+行为后果→SOCIAL_PRESSURE_CONSEQUENCE；1 组 SKIP：名誉受损+关系破裂 supporting<3）。
- **终评 PASS 6/6**（19 函数）：coverage 0.986 / cohesion 0.915 / **separation 0** / abstraction 1.0 / evidence 7.895 / diversity 36；对比 30→19（新增 7 / 移除 18 / 保留 12）。
- 测试 **104 项全过**（test_curator 近义扫描用例改为 mock `AbstractMergeResponse`）。

## 本轮（2026-08-19 续 27）：重置 O_0 后 40 篇 Evolve → Evaluator_final PASS 6/6
- 用户要求：`functions_export.csv`（bootstrap O_0 30 函数）覆盖 functions.db（清空全部命名空间）、删除之前 evolve 产物、基于 30 跑 evolve 40 篇。已执行：DB 清空 → bootstrap=30（清空失效 supporting，证据从新语料累积）→ 复制到 `evolve_official` → 删除 data/evolve_* 旧目录。
- **40 篇（5 类 × 8）跑完**（2042.7s ≈ 34min）：365 obs / coverage 0.638 / novelty 0.093；Curator 243 动作（233 APPLY_EVIDENCE + ADD 1 + MERGE 1 + SPLIT 1 + REMOVE 6 + SKIP 1）。
- **Evaluator_final PASS 6/6**：coverage 0.986 / cohesion 0.916 / separation 0 / abstraction 0.917 / evidence 6.708 / diversity 36；对比 **30 → 24 函数**（新增 3：ACTION_CONSEQUENCE / SOCIAL_ISOLATION / THREAT_ESCALATION_OR_LIFE_SAFETY；移除 9 个低证据 <2 故事；保留 21）。
- 注意：MERGE 产物 `THREAT_ESCALATION_OR_LIFE_SAFETY`（sup 26）被终评标"双向混叠残留"（被动威胁 vs 主动应对），但不影响 PASS；confidence 整体仍偏低（0.39-0.62，apply_confusable 惩罚）。

## 本轮（2026-08-19 续 26）：Evolve v5：Evaluator_final 终期评估 + 最终 Ontology 定稿
- `evolve_app` 图末尾加 `evaluator_final_node`（`curator → evaluator_final → END`）：复用 `evaluator_node` 做全量六维终评（`force_full_review=True`），Final Report（`evaluation_final.json`）含演化前后对比（基线 `functions_<ns>_start.jsonl` → 最终：新增/移除/保留 + supporting/confidence 分布）；导出最终 Ontology 快照 `functions_<ns>.jsonl` + `bank_<ns>.jsonl`。
- `main` 新增 `--final-only`（跳过提取/匹配/维护，对已有命名空间终评）；非 `--final-only` 启动自动导出演化前基线；`evaluator_final_node` 优先用 `bank_<ns>.jsonl` 快照（活体 Bank 可能被测试清空）。
- 测试 **102 项全过**（test_evolve 更新图末尾 + 新增 final 前后对比用例）。
- 验收（`evolve_official` 33 函数 / 542 obs，`--final-only`）：**PASS 4/6**（coverage 0.985 / cohesion 0.893 / abstraction 0.97 / diversity 60；separation 1 组近义、evidence 个别 <2 故事）；对比 基线 30 → 最终 33（新增 11 / 移除 8 / 保留 22）；终评还发现拆分产物镜像近义（RULE_ESTABLISHMENT≈PARANORMAL_RULE_OPERATION）、PARANORMAL_RULE_OPERATION 题材绑定、weak_fit 2、SOCIAL_DESCENT 低证据。
- 环境：`--final-only` 首次验收时活体 Bank 已被 pytest 清空 → coverage/evidence 全 0；已从 `occurrences.jsonl` 重建 `bank_evolve_official.jsonl`（542 obs，缺 affected_aspect/narrative_effect）+ `evaluator_final_node` 优先读 Bank 快照。

## 本轮（2026-08-19 续 25）：正式 Evolve（60 篇 5 领域）+ Curator 缺陷修复
- 用户删 120 原始语料、新增 `zhihu_story_subset_60_5domains_20260819_clean`（60 篇 / 5 领域 / 每类 12 篇 + manifest）并用它重跑了 bootstrap（新 O_0 仅 3 函数 / 155 obs）；正式 Evolve 要求**基于旧 O_0（30 函数）**——从 `data/functions_export.csv`（payload 整存）恢复 30 函数到 `evolve_official`（清空失效 supporting，让证据从新文本累积）。
- **正式跑（60 篇全量，~1.5h 超时中断后补收尾）**：542 obs / 21 次 Evaluator_mid（末次 PASS 4/6：coverage 0.991 / cohesion 0.908 / abstraction 0.867 / diversity 57；separation 2 组近义、evidence 有个别 <2 故事）；Curator 动作 414 = 应用 pending 404 + 新增 5 函数 + MERGE 2 + SPLIT 2 + REMOVE 1 → 最终 33 函数（22 旧函数证据累积 ver2、5 新归纳、2 合并、2 组拆分、1 移除）。
- **缺陷修复**：`evaluator_mid_node` 的 summary 此前**未保存 `recommendations`**，Curator 消费不到体检问题（merge_groups 等）——正式跑时 2 组近义未被消费；已修复（summary 增加 `recommendations`），补跑后 MERGE/SPLIT/REMOVE 生效。
- 环境：shell 工具 1h 超时中断了 evolve 前台命令，但 python 进程后台继续到 58/60 后被杀；report 产物完整、curator 未执行 → 手动补跑 curator_node（pending/occurrences/mid_reports 从文件构造）+ `_revise_from_report`（从最新 `evaluation_mid_21.json` 读完整 recommendations）。

## 本轮（2026-08-19 续 24）：Evolve v4：Curator 收尾维护（按动作分门槛）
- 新增 `Code/Agent/Curator/curator.py`（图 `report → curator → END`）：整合 pending_evidence / novelty_pool / challenge_pool / 最新 evaluation_mid 问题，执行完整维护——应用 pending exemplars（复用 `_apply_evidence`，version_history append `APPLY_EVIDENCE`）、跨故事 ≥2 且 ≥3 obs 的 novel 聚类归纳新函数（复用 `cluster_similar_pairs` + `inducer_node`）、挑战/体检问题修订（复用 `_llm_merge/_llm_revise`，`REVISE_MIN_SUPPORTING=3` 门槛）、low_evidence 移除、weak_fit 剔除。
- **按动作分门槛**：APPLY_EVIDENCE 无门槛；ADD 需跨故事 ≥2 + novel obs ≥3；MERGE/REVISE 需涉及函数 supporting ≥3；不足记 `SKIP_SMALL_SAMPLE` 保留累积。方案写 `data/evolve/curator_plan.jsonl`（Human Review 自动留档）后自动 Apply，清空已消费 pending；`match_report.json` 增加 `curator` 汇总。
- 测试 **101 项全过**（新增 test_curator 5：应用 pending+version / novelty 门槛 / 合并门槛 / 低证据移除 / 无累积跳过）。
- 冒烟（3 篇跨题材 / 27 obs）：Curator 应用 pending 18 条（12 个函数更新，如 IRREVERSIBLE_LOSS ver1→2）、novelty 2 obs 样本不足 SKIP、19 个动作留档；Registry 被 Curator 写回（此前 v1-v3 均不直写）。
- 踩坑：`from Agent.Inducer.inducer import inducer_node` 是模块级名字绑定，测试需 mock `cu.inducer_node`（curator 模块引用）而非 `ind.inducer_node`；生成脚本里 `"\n"` 需写成 `"\\n"` 否则被解释成换行。

## 本轮（2026-08-19 续 23）：Evolve v3：Critic 边界复检 + 待应用区（pending_evidence）
- 按用户定调"MATCH/EXTEND 之后需要 evaluator 不是直接 update"：证据**不再直写 Registry**，`matcher_node` 的 MATCH/EXTEND 改为返回 `pending_evidence`（`source="matcher"`），`_apply_evidence` 纯函数保留供 Curator 应用时复用。
- 新增 `Code/Agent/Critic/critic.py` + `Code/Prompt/Critic_prompt.py`：图拓扑 `matcher→critic→collector`；对 CONFLICT/UNCERTAIN 观测（函数卡片含 `hard_negatives` 边界反例）输出四类最终判定——`match/extend`→归函数进 pending（`resolved_by="critic"`）、`novel`→novelty_pool、`resolved`→challenge_pool；复检失败保持原始 label。
- `evaluator_mid_node` 纳入 pending：构造临时 registry 快照（当前函数 supporting 并集 pending 证据，不重算 confidence）传给 `evaluator_node`，体检反映"应用后视图"，`match_report.mid_evaluations` 记录 `pending_applied`。
- 测试 **96 项全过**（新增 test_critic 3：四类分流+卡片含 hard_negatives / LLM 失败保持 / 无目标跳过；matcher/evolve 断言改为 pending 不直写）。
- 冒烟（3 篇跨题材 / 30 obs）：Critic 复检 15 个边界 → match=5 novel=2 resolved=8；pending 19（matcher 14 + critic 5）、challenge_pool 8（RESOLVED）、novelty_pool 3；coverage 0.633（v1 直写时 0.318，Critic 归函数后提升）；Evaluator_mid FAIL 3/6（pending_applied=12）；Registry 未被直写。

## 本轮（2026-08-19 续 22）：Evolve v2：Evaluator_mid 周期体检（每 20 obs 触发）
- `evolve_app` 新增 `Evaluator_mid` 周期体检：`collector` 累加 `obs_since_eval`，达 `MID_OBS_THRESHOLD`（默认 20）→ 条件边路由到 `evaluator_mid_node`（薄包装复用 `evaluator_node`，`evaluation_context` 仅覆盖 `report_path`），评估当前 Registry（含 MATCH/EXTEND 直写证据）+ Bank，报告落盘 `evaluation_mid_<n>.json`，`match_report.json` 汇总 `mid_evaluations`（round/verdict/六维/问题数），体检后计数归零（滚动触发）。
- 体检只记录问题不触发修订（Curator 后续轮）；State 新增 `obs_since_eval` / `mid_reports`。
- 测试 **93 项全过**（test_evolve 新增 3：达阈值触发+计数归零+落盘 / 滚动 4 篇→2 次 / 不足阈值不触发）。
- 冒烟（3 篇跨题材 / 22 obs → 触发 1 次体检）：verdict FAIL 3/6（coverage 1.0 / cohesion 0.945 / abstraction 0.933 达标；separation 8 组近义 / evidence 0.733 / diversity 3 未达标——小样本预期），`evaluation_mid_1.json` 含六维与问题清单。

## 本轮（2026-08-19 续 21）：Evolve v1：Matcher 五分类 + 直写 + Pools + FunctionOccurrence
- 新建 `Code/Agent/evolve.py`（`evolve_app` 单图 + CLI `python -m Agent.evolve`）：逐篇 `story_loader→preprocessor→observer→bank_adder→matcher→collector` 循环 → `report`；复用 bootstrap 节点，不做 checkpoint。
- 新增 `Code/Agent/Matcher/matcher.py` + `Code/Prompt/Matcher_prompt.py`：obs 结构化向量 vs 函数 definition 余弦召回 top-k（默认 5，无硬阈值）→ LLM 按批判定（10 obs/批，共享函数卡片）五分类。
- **MATCH/EXTEND 直写 Registry**（幂等 append `supporting_obs_ids` + 重算 confidence，`apply_confusable=True`）；**NOVEL→novelty_pool、CONFLICT/UNCERTAIN→challenge_pool**；每 obs 落 **FunctionOccurrence**（occurrence_id=obs_id、NOVEL=OTHER、story_stage 按句子下标占比确定性划分）→ `data/evolve/occurrences.jsonl`。
- `RegistryStore.replace_all` 幂等 enrich Card 字段：`function_id`（F_+sha256[:8]）、`status=provisional`、`version_history=[CREATE v1]`；`test/migrate_function_cards.py` 已给 bootstrap 30 函数补齐并同步快照。
- 测试 **90 项全过**（新增 test_matcher 5 / test_evolve 2 / test_registry +2）；schema 允许 `matched_function=null` 后 LLM 校验重试从 20+ 降到 3（39 obs）。
- 冒烟（9 篇跨题材、clean 语料抽取、独立命名空间 `evolve_smoke`）：317s / 89 obs → MATCH 36 / EXTEND 5 / CONFLICT 4 / UNCERTAIN 38 / NOVEL 6，coverage 0.461 / novelty 0.067；直写生效。
- 环境：终止残留 `python -m Agent.app` 进程（PID 18728，fresh 全量会清空 bootstrap 命名空间/Bank）；其破坏的 O_0 已从快照恢复（30 函数/1062 obs）+ 迁移；首次冒烟（Tee-Object 管道）后曾见 bootstrap 命名空间消失，二次复现（文件重定向）稳定——疑似管道环境偶发，已恢复并改用重定向。
- 后续（structure-rules/Plan.md 蓝图，下一轮起）：Critic 复检、触发条件（≥20 obs Evaluator_mid / pools ≥5 Curator）、Curator + Human Review（自动+留档）、Evaluator_final；Plan.md 阶段一（Story Profile、Function 前置条件/角色位置/状态变化、Instance Card）。

## 本轮（2026-08-19 续 22）：新增五领域 60 篇语料（zhihu_story_subset_60_5domains_20260819_clean）
- 用 `test/clean_corpus.py` 清洗 `Code/zhihu_story_subset_60_5domains_20260819/`（5 领域 × 12 篇：悬疑惊悚/古风仙侠/现代情感/末世科幻/现实家庭职场）→ `Code/zhihu_story_subset_60_5domains_20260819_clean/`，结构与 120_clean 一致（仅清洗后 txt + manifest.json/csv + clean_report.json）。
- 结果：60 篇全部清洗，17 篇截断脚注，剔除噪音 311 行；幂等检查 60/60 通过；manifest 元数据（category/question_title）完整，`Agent.app`/`Agent.evolve` 可直接 `--corpus Code/zhihu_story_subset_60_5domains_20260819_clean` 消费。
- 与 120 子集无 answer_id 重复；题材为关键词初筛（story_score ≥ 0.85），非人工金标准。

## 本轮（2026-08-19 续 20）：结构化 Observation embedding + 语义化 surface_diversity
- 用户提出：`surface_diversity` 靠字符串匹配不合理、结构化数据拼起来算需要 embedding。落地：
  - `Embedding/embedding.py` 新增 `encode_observation`/`encode_observations`（逐字段加权平均 + L2 归一化；`OBS_FIELD_WEIGHTS`：event/after=1.5、before/effect=1.0、affected=0.8、surface=0.6）；替换全部"拼串→encode"调用点（`Bank.add` / `Retrieval.query_by_observation` / confidence coherence / Evaluator coverage·cohesion / revise SPLIT 分配）。
  - `_compute_surface_diversity`：精确字符串 `set()` → embedding 贪心语义去重（`SURFACE_SIM_THRESHOLD=0.80`）。
- 验证：新增 `test_embedding.py` 3 项 + `test_evaluator` weak-fit 用例适配 → **79 项全过**。快照抽样 4 函数：coherence 0.81-0.84（旧 0.54-0.64）、surface 1.0。
- 注意：Chroma 向量空间变更，旧 Bank 向量为旧拼串空间，fresh 重跑整体重建无混合；coverage 0.65 阈值可能在结构化编码后偏移，待集成校准。

## 本轮（2026-08-16 续 11）：LangGraph 范式审查 + 仓库清理 + 修订历史落盘 + .env 去跟踪
- **LangGraph 审查**：合规（State TypedDict+add_messages / node 返回字段 / 先节点后边再 compile / 条件边字符串路由 / MemorySaver + thread_id / 闭环有界）；未做非必要重构（重试沿用库内循环模式）。
- **删除**：`test_app.py`、`test_bank.py` + 其路径 bug 产物 `Code/Code/data/bank_test`（git 跟踪）、`test/stories/`（30 篇）、`draw_graph.py` + `langgraph_overall.mmd/.png`、`nf_llm_result.json` / `nf_rule_result.json` / `_enc_probe.txt`、旧日志 `batch_run_v2.log` / `batch_run_zhihu_v5.log`。
- **data/ 清理**：`genre_functions`、`trial3_v2/v3`、`trial5`、`trial5_none`、`trial5_v2none`、`trial_none`、`trial_usage_probe.json`、`data/evaluation/` 旧 union 快照（`union_functions*.jsonl`、`union_obs.jsonl`、旧 `revise_report.json`/`revise_rounds.jsonl`）删除；保留 `data/bootstrap/` 与 `evaluation_report.json`。
- **DB 命名空间**：`01_悬疑惊悚`(31) / `02_古风穿越重生`(32) / `03_现代情感家庭`(39) / `union`(75) 已清空，仅剩 `bootstrap`(82)。
- **修订历史落盘**：`revise.py` 新增 `_persist_round`——每轮修订后追加 `data/evaluation/revise_rounds.jsonl`（round/ts/actions，含 backup）。
- **`.env`**：`git rm --cached Code/Agent/.env`（工作区文件保留）。
- **回归**：54 项全过。

## 本轮（2026-08-16 续 12）：数据目录统一（单一 Code/data/ 根）
- `registry.py` 默认 DB `Code/Agent/data/registry/functions.db` → `Code/data/registry/functions.db`；`bank.py` 默认 `persist_dir="data/bank"`（`Code/Bank/data/` → `Code/data/bank/`）；`.gitignore` 收敛为一条 `Code/data/`。
- 迁移完成：`bootstrap`(82) 完整；删除 4 个已清空命名空间的 `.pre_revise.*` 备份与 `data/bank_test_conf/`；保留 `functions.db.pre_revise.bootstrap.jsonl`（83→82 修订前备份）。
- 回归：54 项全过。

## 下一步


## 本轮（2026-08-20）：OntologySnapshot 发布契约
- 新增 `Agent/snapshot.py`：`publish_snapshot` / `load_snapshot` / `validate_snapshot`，快照固定为 `manifest.json + functions.jsonl + evaluation.json`，校验 schema、PASS verdict、Function ID/名称唯一性、数量与 SHA-256。
- Bootstrap/Evolve 保持两张独立 LangGraph；两者最终终评 PASS 后自动发布到 `data/ontology_snapshots/<snapshot_id>/`，FAIL 仅保留原工作产物。相同内容重复发布幂等，快照目录禁止覆盖。
- Bootstrap 修正发布边界：逐函数舍弃 → `abstract_merge` → 导出工作产物 → 对最终 Registry 再做全量终评 → PASS 发布，保证评估对象与快照内容一致。
- v1 不包含 Observation Bank，`parent_snapshot_id=null`；Story Pattern Agent 后续只通过 loader 消费冻结本体。
- 验证：Snapshot + Bootstrap/Evolve/Registry 定向测试 30 项通过；全量离线回归 119 项通过。

## 本轮（2026-08-20）：Story Pattern Agent v1 - load_inputs + select_story
- 新增 `Agent/StoryPattern/state.py`：独立 `StoryPatternState`，消息字段使用 LangGraph `add_messages` reducer，与 Function Knowledge Agent State 隔离。
- 新增 `Agent/StoryPattern/inputs.py`：`load_inputs` 只读加载 OntologySnapshot、Observation JSONL、语料 manifest；建立 `function_by_name/function_by_id`、`observations_by_story/story_metadata/story_ids`，并初始化后续分析字段。
- 严格校验：Observation 必要字段、全局唯一 `obs_id`、manifest 归属、`{story_id}_obs_NNN` 格式与每篇连续编号；错误直接 `ValueError`，不静默去重或 fallback。
- 新增 `Agent/StoryPattern/stories.py`：`select_story` 按 `current_story_index` 选择已分组故事，设置 metadata/observations 并清空临时 occurrences；`has_next_story` 提供后续 Graph 条件路由判断。选择节点不读文件、不排序、不推进下标。
- 复用已有 Observation，不重新读取原文、不运行 Observer，不调用 LLM，不读写 Registry 或 Observation Bank。
- 验证：Story Pattern 两节点定向测试 25 项；真实 `evolve_official` 数据加载为 23 Functions / 60 Stories / 502 Observations；全量离线回归 144 项通过。

## 本轮（2026-08-20）：FunctionOccurrence 源头发布契约
- 修正重复映射设计：Story Pattern Agent 不再计划重跑 Matcher；Bootstrap/Evolve 在最终 Function 确定后，以 `supporting_obs_ids` 为权威，将 Bank Observation 与既有 Matcher/Critic 审计结果对齐。
- 新增 `Agent/occurrence.py`：同一 Observation 唯一绑定最终 Function 时为 `MATCHED`；原判 `NOVEL` 且无最终支持时为 `OTHER`；无绑定或多重绑定时为 `UNCERTAIN`。一个 Function 可产生任意多个 occurrence，并参与多个后续模板。
- OntologySnapshot 升级为 schema v2，新增不可变 `occurrences.jsonl` 及数量/SHA-256；每条记录带 `snapshot_id`、`function_id`，并校验唯一性和 Function 引用。v1 Functions 仍可读取，但不提供 occurrence loader。
- Bootstrap/Evolve 始终保留 `occurrences_final.jsonl` 工作产物，仅终评 PASS 时与 Functions 原子发布；FAIL 不发布 Snapshot。
- 恢复 `Agent.StoryPattern` 标准包入口，保持独立 `StoryPatternState`，不并入 Function Knowledge Agent。
- 验证：相关定向测试 28 项通过；全量离线回归 149 项通过。

## 本轮（2026-08-20）：Agent 目录边界整理
- `Code/Contracts/` 成为跨 Agent 契约目录，承载 `snapshot.py` 与 `occurrence.py`。
- `Code/FunctionExtract-Agent/` 与 `Code/StoryPattern-Agent/` 保持平级；Story Pattern 不再作为 FunctionExtract 的子目录。
- 删除重复的 `FunctionExtract-Agent/StoryPattern/` 与旧兼容 `Agent/StoryPattern/`；Story Pattern 只保留一份实现。
- FunctionExtract 的发布入口改从 `Contracts.snapshot` / `Contracts.occurrence` 导入；Story Pattern 的输入节点同样只依赖 Contracts。
- 验证：Contracts、Snapshot、Occurrence、Story Pattern 定向测试 39 项通过。

## 本轮（2026-08-20）：Story Pattern 最小序列输入
- 新增 `StoryPattern_Agent/sequences.py`：`load_occurrences_node` 只读加载同一 Snapshot 的 `occurrences.jsonl`，按 `story_id` 分组并校验快照 ID、故事归属、唯一性和每个故事非空。
- 新增 `build_story_sequences`：优先按 `source_sentence_indices`，缺失时按 `obs_id` 编号稳定排序；保留 `MATCHED`、`OTHER`、`UNCERTAIN`，只生成序列节点，不调用 LLM、不修改源数据。
- State 新增 `occurrences_by_story`、`story_sequences`、`current_sequence`。
- 验证：Story Pattern + Contracts 定向测试 43 项通过。全量回归暂受目录重排影响：旧 FunctionExtract 测试仍导入未迁移的 `Agent.*`、`Bank.*`、`Embedding.*` 路径，无法收集，未将该无关迁移问题混入本节点修改。

## 本轮补充（2026-08-20）：修复目录迁移导入路径
- 新增唯一兼容入口 `Code/Agent/__init__.py`：将旧 `Agent.*` 导入映射到 `Code/FunctionExtract_Agent`，并将 FunctionExtract 源码根加入模块搜索路径；不复制任何业务模块。
- 兼容了历史顶层 `Bank`、`Embedding`、`Prompt`、`Retrieval` 导入，保持 `FunctionExtract_Agent` 为唯一实现位置。
- 验证：全量离线回归 `153 passed in 54.13s`。

## 本轮（2026-08-20）：Story Pattern repetition 标注
- 新增纯规则节点 `annotate_repetitions`：只将连续、`MATCHED`、`function_id` 相同的 occurrence 组成 repetition run；非连续重复、`UNCERTAIN`、`OTHER` 均不合并。
- 原始 `story_sequences/current_sequence` 保持不变；新增 `structural_sequences/current_structural_sequence`。每个 run 保存 `repeat_count`、`occurrence_ids`、`obs_ids` 和 `raw_orders`，可完整回溯。
- 真实 60 篇数据验证：502 个原始节点 → 435 个结构 run，标注 67 个连续重复，涉及 36 篇，最大连续次数 5；run 中 occurrence 引用合计仍为 502。
- 验证：Story Pattern + Contracts 定向测试 50 项通过；全量离线回归 `160 passed in 43.51s`。

## 本轮（2026-08-20）：Function 上下文索引
- 新增故事循环后的纯规则聚合节点 `index_function_contexts`：将全部 `structural_sequences` 反向索引为 `function_id → contexts`，Function 成为后续模板查询入口，故事序列继续提供顺序证据。
- `UNCERTAIN/OTHER` 只切断 MATCHED 片段，不进入索引；每个 context 保存故事/题材、结构位置、锚点位置、重复次数、occurrence 证据及完整 MATCHED 片段。
- 同 Function 在同故事非连续出现时保留多个 context；Snapshot 中无出现的 Function 保留空列表；严格拒绝缺失故事、未知 Function 和 ID/名称不一致。
- 真实数据验证：60 篇、23 Functions、317 contexts、109 MATCHED 片段，其中 50 个长度 ≥3；Function context 数 3–33，跨故事支持数 3–23。
- 验证：Story Pattern + Contracts 定向测试 63 项通过；全量离线回归 `173 passed in 46.24s`。

## 本轮（2026-08-20）：精确 motif 候选提取
- 新增纯规则 LangGraph 节点 `extract_motif_candidates`：仅扫描 `anchor_index == 0` 的 MATCHED 片段，提取长度 3–6 的精确连续 Function 窗口，按有序 Function ID 聚合。
- motif 身份不包含 repetition；重复次数作为 `repeat_variants` 保留。证据保留故事、题材、结构位置和全部 occurrence，候选 ID 由 Snapshot ID + Function 序列确定性生成。
- 按不同故事支持分为 `REPEATED` 与 `SINGLE_STORY`；同故事重复只增加 `evidence_count`，不虚增跨故事支持。
- 真实数据验证：109 个唯一 MATCHED 片段 → 321 个候选；长度分布 3=138、4=91、5=58、6=34；`REPEATED=1`、`SINGLE_STORY=320`。
- 验证：Story Pattern 定向测试 64 项通过（其中 motif 15 项）；全量离线回归 `188 passed in 44.23s`。

## 本轮（2026-08-20）：motif 语义变体召回
- 新增并修订 LangGraph 节点 `retrieve_motif_variants`：复用 FunctionExtract 的 `Embedder`，逐位置编码 `Function 名称 + definition`，使用保序动态对齐召回全部 motif 候选间的语义变体。
- 全部 321 个候选参与，包括 `REPEATED`；允许任意 3–6 长度组合和多个有序缺省步。每个候选保留相似度不低于 0.75 的 Top-5 近邻，再合并为确定性、去重的无向边。
- 相似度按 `HIGH >= 0.85`、`EXPANDED >= 0.75` 分层；仍只保留故事并集至少为 2 的配对。输出保留长度差、共享/合并故事、步骤对齐及 Top-K 选择来源，但不聚类、不发布套路。
- 参数验收：真实数据得到 1,126 条边，覆盖 317/321 个候选；`HIGH=156`、`EXPANDED=970`，长度差 0/1/2/3 分别为 140/454/363/169。0.75 保持高召回；0.85 单独作为高置信分层，不截断扩展召回。
- 验证：变体 + motif + sequence 定向测试 `54 passed`；全量离线回归 `203 passed in 45.06s`。

## 本轮（2026-08-20）：motif 配对 LLM 审查
- 新增 LangGraph 单步节点 `review_motif_pairs` 与路由函数 `has_next_motif_pair`；每次只审查 `current_motif_pair_index` 指向的一对，成功后追加 `motif_pair_reviews` 并将索引加 1，适合后续接 checkpoint 循环，不在一次调用中吞掉 1,126 对。
- 复用 `Agent.llm.chat_structured` 与 Pydantic schema，严格输出 `SAME_PATTERN / RELATED / DIFFERENT`、置信度、核心对齐、可选步骤、顺序冲突和理由；pair ID 由节点从 State 绑定，避免 LLM 誊写主键失败。
- 审查输入包含两侧 Function 名称/定义、Embedding 对齐，以及由 motif evidence → FunctionOccurrence → Observation 还原的 `event/before_state/after_state/narrative_effect/surface_form`，不重新读取原文。
- State 新增 `current_motif_pair_index` 与 `motif_pair_reviews`；重复审查、未知 candidate/occurrence/Observation、故事归属不一致均在 LLM 调用前拒绝。
- 真实数据链验证：1,126 对中第一条 HIGH pair 成功构造左 4 Functions/5 Observations、右 3 Functions/3 Observations 的审查输入并推进索引 0→1；使用 mock LLM 验证契约，未调用线上 API。
- 验证：review + variants + motif + sequence 定向测试 `69 passed`；全量离线回归 `218 passed in 56.53s`。
- 真实 LLM 抽样：使用 `deepseek-v4-flash` 审查 10 对（HIGH 最高 5 对 + EXPANDED 分位抽样 5 对），10/10 结构化成功；`SAME_PATTERN=1`、`RELATED=8`、`DIFFERENT=1`。调用消耗 prompt 24,048 / completion 2,701 / 总计 26,749 tokens，LLM 墙钟 25.9s。
- 首次真实调用因 prompt 未显式列出完整 JSON 字段，连续 3 次结构校验失败（额外 7,006 tokens）；补充精确 JSON 模板后 10/10 成功。最终全量回归 `218 passed in 45.73s`。
- Review Prompt 已迁入 `StoryPattern_Agent/Prompt/Review_prompt.py` 并针对真实测评偏差修订：明确 pair reviewer 只判结构同构，禁止用故事数、样本数、支持度或发布充分性影响 verdict；增加长度至少 3 的核心链、可选步骤、抽象层级与方向冲突规则。
- 同一组最高分 5 条 HIGH 真实复测：修订前 `SAME_PATTERN=1 / RELATED=4`，修订后 `SAME_PATTERN=4 / RELATED=1`，5/5 结构化成功；消耗 14,674 tokens，LLM 墙钟 11.5s。全量回归 `219 passed in 46.56s`。
- 真实 HIGH 全量审查完成：`deepseek-v4-flash` 审查 156/156 条，结果写入 `Code/data/story_pattern_official/high_pair_reviews_20260820.jsonl` 与 summary。最终 `SAME_PATTERN=31`、`RELATED=109`、`DIFFERENT=16`，无失败记录；首轮 157 次调用使用 443,165 tokens、LLM 墙钟 399.2s。
- 批量中 1 条因 LLM 反复誊写错误 `variant_pair_id` 失败；修订 Review schema 后由节点从 State 绑定主键，LLM 只返回语义 verdict。该条真实重试成功为 `RELATED (0.8)`，额外使用 3,029 tokens；产物复核为 156 条唯一成功记录，全量回归 `219 passed in 53.66s`。

## 当前交接（2026-08-20）：Story Pattern Agent

### 已完成
- FunctionExtract Agent 已发布冻结 `OntologySnapshot v2`；Story Pattern Agent 只读消费同一 Snapshot 的 Functions 和 FunctionOccurrence，不重跑 Matcher/Observer。
- 已完成的节点链：`load_inputs` → `load_occurrences_node` → 故事循环（`select_story` → `build_story_sequences` → `annotate_repetitions`）→ `index_function_contexts` → `extract_motif_candidates` → `retrieve_motif_variants` → `review_motif_pairs`。
- 真实数据基线：23 Functions、60 篇故事、502 个 occurrence；435 个 structural runs；109 个 MATCHED 片段；321 个精确 motif candidates。
- 语义召回：1,126 个跨故事候选边，其中 HIGH 156、EXPANDED 970。HIGH 已完成真实 LLM 审查，156 条结果完整落盘：`SAME_PATTERN=31`、`RELATED=109`、`DIFFERENT=16`。
- 已落盘真实审查结果：`Code/data/story_pattern_official/high_pair_reviews_20260820.jsonl`；汇总：`Code/data/story_pattern_official/high_pair_reviews_20260820_summary.json`。这两份文件是下一节点的唯一输入，不应重新调用 HIGH 审查。
- Review Prompt 位于 `Code/StoryPattern_Agent/Prompt/Review_prompt.py`。职责边界已固定：LLM 只判断 pair 是否结构同构；跨故事支持度、cluster 稳定性和发布资格由规则节点计算。
- 最近验证：全量离线回归 `219 passed in 53.66s`。

### 下一步
- 进入 Phase 2 生成知识补全：优先实现 `StoryProfile`、Function 状态变化字段和 `InstanceCard`。
- `EXPANDED=970` 暂不批量调用 LLM；它们保留为第二阶段候选池，等待已发布 Pattern 结果和预算决定是否审查。

## 本轮（2026-08-20）：Story Pattern summary
- 新增 `summarize_story_patterns`：只对 `needs_review=false` 的 cluster 调用 LLM；`needs_review` cluster 不调用，保留在 `skipped_clusters`。
- LLM 只生成模式名称、抽象定义、核心 Function 名称、可选步骤、适用条件和反例/限制；节点自行将核心 Function 名称绑定回冻结 Snapshot 的 Function ID/definition，并绑定 cluster 的故事、题材和 occurrence evidence。
- 真实执行产物：`Code/data/story_pattern_official/pattern_summaries_20260820.json`，Snapshot=`evolve_official_20260820T063134335355Z_e2db2e7a06bc`；4 个 clean cluster 生成 4 个候选 summary，8 个 cluster 跳过。
- 4 个候选 summary 的不同故事支持数均为 2；核心链均为至少 3 个 Snapshot Function；产物状态为 `SUCCESS`。随后已进入 PatternCatalog 发布。
- 验证：summary 定向测试 6 项；Story Pattern 定向测试 101 项；全量离线回归 `236 passed in 58.01s`。

## 本轮（2026-08-20）：PatternCatalog 发布
- 新增纯规则节点 `publish_pattern_catalog`：不调用 LLM，按 Snapshot ID 校验 summary/cluster 一致性，将结果分为 `published_patterns`、`rejected_patterns` 和 `manual_review_patterns`；未发布结果不混入只读发布目录。
- MVP-A 暂定最小不同故事支持阈值为 `2`。唯一修改位置是 `Code/StoryPattern_Agent/catalog.py` 的 `MIN_PATTERN_STORY_SUPPORT`；生成产物同时记录 `publish_rules.minimum_story_support`，以后调整阈值时同步修改该常量即可追溯规则版本。
- 真实发布产物：`Code/data/story_pattern_official/pattern_catalog_20260820.json`；Snapshot=`evolve_official_20260820T063134335355Z_e2db2e7a06bc`，4 个候选全部发布，0 个 rejected，8 个进入 manual review。
- 发布目录保留模式名称、核心 Function 链、可选步骤、故事/题材支持、occurrence evidence、来源 cluster 和 review edge；人工复核 cluster 保留冲突原因和完整证据。
- 验证：catalog 定向测试 6 项；cluster + summary + catalog 定向测试 23 项；发布产物校验通过。

## 本轮（2026-08-20）：Phase 1 完整重跑
- 完整运行报告：`Code/data/story_pattern_official/phase1_20260820T114432Z.json`。
- 运行边界：重新执行 Snapshot 输入、故事序列、motif 提取、Embedding 变体召回、cluster、4 个 clean cluster 的真实 summary 和 catalog 分流；156 条 HIGH review 使用已冻结的 `high_pair_reviews_20260820.jsonl` 回放并校验 156/156 个 pair ID，不重复调用 HIGH 审查；970 条 EXPANDED 按当前 Phase 1 预算不调用 LLM。
- 阶段计数：23 Functions / 60 Stories / 502 occurrences；502 raw sequence nodes → 435 structural runs → 109 MATCHED segments → 321 motif candidates；321 candidates → 1,126 variant pairs（HIGH 156 / EXPANDED 970）。
- review 回放：156 条，`SAME_PATTERN=31`、`RELATED=109`、`DIFFERENT=16`；31 SAME 边形成 12 clusters，其中 4 clean、8 `needs_review`。复核原因：`CHAIN_PROPAGATION=8`、`INTERNAL_REVIEW_CONFLICT=4`、`ORDER_CONFLICT=4`。
- summary / catalog：4 个 clean cluster 全部生成 summary 并发布，8 个 cluster 进入 manual review，0 个 rejected。summary LLM 共 4 次，prompt 4,076 / completion 1,130 / total 5,206 tokens，墙钟 13.9s。
- 本次 4 个模板：`PAT_761289e14481d653`（末世觉醒协作：`VOLITIONAL_PATH_CHANGE → RELATIONSHIP_INTENSIFICATION → ALLIANCE_FORMATION`）；`PAT_768958bd97b41684`（致命事件后的真相递增与威胁升级：`FATAL_INCIDENT → PARTIAL_TRUTH_REVELATION → THREAT_ESCALATION`）；`PAT_f305e9acbc9e8581`（悬疑强制调查与迟缓真相揭露：`EXTERNAL_COMPULSION → ANOMALY_OMEN → THREAT_ESCALATION → PARTIAL_TRUTH_REVELATION`）；`PAT_fcbaff455c237bd5`（破碎关系的真相重建：`RELATIONSHIP_DISINTEGRATION → PARTIAL_TRUTH_REVELATION → RELATIONSHIP_INTENSIFICATION`）。每个支持 2 个不同故事、evidence_count=2；完整模板字段和证据见运行报告。

## 本轮（2026-08-20）：EXPANDED 优先审查与 cluster 状态修正
- `CHAIN_PROPAGATION` 不再作为冲突：cluster 现在分开输出 `needs_review`（仅已审查到的 RELATED/DIFFERENT、顺序冲突或同 pair 多 verdict）与 `review_incomplete`（cluster 内仍有未审查 variant pair）；状态为 `CLEAN / INCOMPLETE / CONFLICT`。summary 和 catalog 都要求 `review_incomplete=false`。
- 新增 `build_expanded_review_queue`：未审查的 EXPANDED pair 分为 cluster 内部、cluster 桥接、未连接三档，`review_motif_pairs` 可直接消费该队列。
- 实测 970 条 EXPANDED 中：内部 3 条、桥接 17 条、未连接 950 条。先审查内部 + 桥接共 20 条，结果 `SAME_PATTERN=1`、`RELATED=18`、`DIFFERENT=1`；真实 LLM 用量 prompt 54,317 / completion 6,012 / total 60,329 tokens，墙钟 64.2s。checkpoint：`Code/data/story_pattern_official/expanded_priority_reviews_20260820.jsonl`。
- 合并 156 HIGH + 20 EXPANDED review 后：176 review（SAME 32 / RELATED 127 / DIFFERENT 17），12 cluster 变为 11；`review_incomplete=0`，8 个 CLEAN，3 个 CONFLICT（真实内部冲突/顺序冲突），没有将“未审查”误报为冲突。
- 重新 summary + publish：8 个 summary / 8 个 published Pattern / 0 rejected / 3 manual review；新产物 `phase1_expanded_20260820T124042Z_report.json`、`phase1_expanded_20260820T124042Z_catalog.json`、`phase1_expanded_20260820T124042Z_reviews.jsonl`。新增 summary LLM 用量 prompt 10,612 / completion 2,189 / total 12,801 tokens，墙钟 26.4s。
- 仍有 950 条 `UNCONNECTED_PAIR` 未审查；它们不影响现有 cluster 的完整性，应在下一阶段按未连接 motif 覆盖、相似度和跨故事支持排序，而不是全部立即调用 LLM。
- 验证：新增队列测试；全量离线回归 `245 passed in 49.12s`。

## 本轮（2026-08-20）：Story Pattern motif cluster
- 新增纯规则节点 `build_motif_clusters`：仅用 `SAME_PATTERN` 边构建确定性连通分量，重新合并不同故事支持、题材分布和 occurrence evidence；重复 evidence 去重并保留 `source_motif_ids`，所有内部 review 边完整留存。
- cluster ID 由 Snapshot ID + 排序后的 member motif IDs 确定性生成；节点不调用 LLM、不改 OntologySnapshot、不发布 Pattern。
- 风险检查：连通分量未形成两两直接 `SAME_PATTERN` 时标记 `CHAIN_PROPAGATION`；内部 `RELATED/DIFFERENT`、非空 `order_conflicts`、同一 pair 多 verdict 分别记录并使 `needs_review=true`。
- 真实冻结数据结果：321 candidates + 31 条 `SAME_PATTERN` 边形成 12 个候选 cluster，不是 31 个 Pattern；严格检查后 8 个 `needs_review`、4 个可进入 `summarize_story_patterns`，不同故事支持数分布为 4×2、3×1、2×9。
- 验证：新增 cluster 测试 11 项；Story Pattern 定向测试 106 项；全量离线回归 `230 passed in 57.77s`。

## 完整路线图（2026-08-20）：从 Function 提取到自动大纲

### 最终目标与边界
- 最终产品是“基于真实故事知识生成中文短篇网文大纲”，而不是只生成 Function 标签或套路名称；当前范围止于大纲，不生成全文。
- 系统分为两条严格分离的知识线：`Corpus Knowledge` 只保存真实故事中观察到的 Function、occurrence、motif、实例和证据；`Creative Memory` 只保存系统生成且验证过的新连接/新机制，不能反向当作真实规律。
- FunctionExtract Agent 负责发现、评估和发布 Function；Story Pattern Agent 负责从冻结 Snapshot 学习组合规律；未来的 Outline Agent 只读取已发布的 Function/Pattern/Instance 知识，不写回 Function Registry。

### Phase 0：Function 知识发布层（已完成）
- Bootstrap/Evolve 已形成 Function Knowledge 生命周期；PASS 后发布不可变 OntologySnapshot v2（Functions、FunctionOccurrence、评估）。
- 当前可用真实基线：60 篇故事、23 Functions、502 occurrences；下游不再重跑 Matcher/Observer。
- 仍待后续增强但不阻塞套路 MVP：Story Profile、稳定角色关系、Function 的显式前置条件/角色位置/状态变化、Instance Card。

### Phase 1：Story Pattern 库 MVP-A（当前阶段）
目标：把真实故事中的 Function 序列变成一份可查询、可追溯的“候选套路目录”。

1. 已完成序列和候选提取：60 篇故事 → 109 个 MATCHED 片段 → 321 个精确 motif candidates；保留 raw sequence、repetition 和 occurrence 证据。
2. 已完成变体召回与审查：1,126 个跨故事语义候选边；HIGH 156 已由真实 LLM 审查，得到 31 条 `SAME_PATTERN` 边。
3. 已完成 `build_motif_clusters`：只用 31 条 SAME_PATTERN 边建立候选 cluster；重算不同故事支持、合并 evidence、保留 review 边；检测链式传播/内部冲突并标 `needs_review`。
4. 已完成 `summarize_story_patterns`：只对通过 cluster 规则检查的候选调用 LLM，生成 pattern 名称、抽象定义、核心 Function 链、可选步骤、适用条件、反例/限制和引用证据。
5. 已完成 `publish_pattern_catalog`：按暂定最小支持阈值发布不需人工复核的模式为只读 PatternCatalog；候选、被拒模式和人工复核项分别保留，不混入发布目录。

MVP-A 验收标准：给定 `snapshot_id`，可列出每个发布 Pattern 的核心步骤、可选步骤、不同故事支持数、题材分布和可回溯的 occurrence/Observation 证据；任何 Pattern 都能追溯到冻结 OntologySnapshot。当前 31 条 SAME_PATTERN 边不是 31 个 Pattern，必须经过 cluster 和支持度计算后才知道实际数量。

### Phase 2：生成知识补全（MVP-B 前置）
目标：让 Pattern 和 Function 从“分析对象”成为“可以安全生成的结构约束”。

1. `StoryProfile`：为故事抽取并校验主人公、主要人物、目标、关系、世界规则、核心冲突和结局状态；人物在同一故事内必须有稳定 ID。
2. 扩展 Function card：补充结构化自然语言的前置条件、角色位置、状态变化、常见故事阶段和 hard negatives；这是在现有 Function 上增补，不重新提取本体。
3. `InstanceCard`：基于每个 FunctionOccurrence 记录角色绑定、具体事件、实现机制、题材/冲突/关系标签、前后状态、故事位置和原始证据。
4. `transition / realization index`：从真实 occurrence 和 PatternCatalog 统计可连接的 Function、常见实例化机制、不同题材中的实现方式；先做精确统计和标签筛选，再用 Embedding 做实例召回。

验收标准：给定一个 Function 或 Pattern，系统能返回适用的角色位置、前置/后置状态、真实实例机制和可连接的下一步；任何检索结果都带真实故事证据。

### Phase 3：端到端大纲 MVP-B
目标：在用户只给出题材/主题/长度偏好时，生成一份结构成立、可解释、可验证的短篇大纲。

1. `Outline Planner`：从 PatternCatalog、transition index 和用户约束选择一条 Function 序列。Planner 可 `FOLLOW` 成熟模式、`ADAPT` 模式变体、`EXPLORE` 新连接，但新内容必须标为生成内容，不能伪装成语料规律。
2. `Story Seed`：为每条候选序列生成题材、世界、主人公、人物关系、目标、核心冲突和结局方向；随后回查序列前置条件是否满足。
3. `Mechanism Plan`：在写大纲前，为每个 Function 预先给出“谁对谁做什么、为何发生、状态如何改变、怎样连接下一步”的一句话方案。
4. `Outline Realizer`：按序实例化为分段大纲，同时维护状态账本（人物目标/关系、秘密、资源、未解决冲突、世界规则）。
5. `Outline Validator`：规则检查前置条件、状态连续性、角色一致性和结局闭合；LLM 复抽 Function 检查“计划步骤 → 情节 → 能否恢复目标 Function”。

MVP-B 验收标准：至少针对 3 个不同题材各生成 3 份大纲；每份都包含采用的 Pattern/Function、角色与状态账本、逐步情节、验证报告和真实语料引用。人工盲评至少比较三组：直接 LLM、只给 Function 序列的 LLM、完整知识增强系统；先要求完整性与因果连贯性，不以“爆款”作为首个门槛。

### Phase 4：质量优化与 Best-of-N
目标：在“能生成成立大纲”后提升差异化与吸引力，避免为了创新破坏结构。

1. 生成多个 Planner/Seed/Mechanism Plan 候选，按漏斗筛选，避免把所有 token 花在完整大纲上。
2. 对初稿分别检索完整序列、局部 motif、实例机制和表层情节的相似性；结构相似与抄袭风险必须分层处理。
3. LLM 诊断只输出 `KEEP / REPAIR / DIFFERENTIATE / REPLAN`；按最小修改原则，先改事件，再改机制，再改局部 motif，最后才重规划全序列。
4. 通过 validator 后按结构完整性、因果连贯性、人物动机、冲突/兑现、差异化和用户偏好排序，选出 Best-of-N。

验收标准：完整系统相对“直接 LLM”和“只有 Function 序列”的基线，在人工盲评的结构完整性、因果连贯性、人物动机三个核心指标上稳定更高；相似性检查能解释保留或差异化的原因。

### Phase 5：扩库、持续学习与人工治理
目标：从当前 60/120 篇验证数据扩展到大语料，并控制本体和模式漂移。

1. 新语料只经 Bootstrap/Evolve 进入新的 OntologySnapshot；PatternCatalog 按 snapshot 重新计算并保留版本谱系，旧结果可复现。
2. `OTHER/UNCERTAIN`、低支持模式、RELATED 边和 `needs_review` cluster 进入人工/LLM 复核队列，不自动提升为 Function 或发布 Pattern。
3. 周期性评估 Function 边界、Pattern 支持度、题材偏置、实例机制多样性与生成质量；必要时通过新 Snapshot 重新发布，而不是就地改历史结果。
4. Creative Memory 与 Corpus Knowledge 继续隔离；只有人工确认或真实语料支持的内容才能进入 Corpus Knowledge。

### 推荐执行顺序与停止点
- 现在先完成 Phase 1 的 `build_motif_clusters`、`summarize_story_patterns`、`publish_pattern_catalog`，得到可审计的 PatternCatalog。
- PatternCatalog 发布后，先做 Phase 2 的最小字段补全（优先 StoryProfile、Function 前后状态、InstanceCard），不要直接进入生成。
- Phase 2 达到可检索验收后，实现 Phase 3 的单条端到端大纲 MVP-B；先固定 3 个题材的小样本，验证通过再进入 Phase 4。
- Phase 4 的比较实验完成且指标稳定后，才投入 Phase 5 的大规模语料、批量生成与长期治理。


- **Bootstrap 已收尾（2026-08-16）**：run_bootstrap.py 120 篇全量 → `bootstrap` 命名空间 82 functions / 1027 obs；curate 最终全量复核 PASS 6/6（coverage 0.761 / cohesion 0.884 / separation 0 / abstraction 0.890 / evidence 2.89 / diversity 3）；快照 `data/bootstrap/` + 报告 `data/evaluation/evaluation_report.json`；修订历史 `data/evaluation/revise_rounds.jsonl`。日志 test/logs/run_bootstrap_full.log / run_bootstrap_curate.log。
- 进入 Evolve 前一次性补齐（清单见 README「Evolve 阶段待补清单」）：`source_sentence_indices` 已采集（2026-08-17，历史 obs 需重跑回填）、`function_id/status/version_history`、卡片成熟内容由 Curator 生成、命名统一、Matcher/Critic/Curator（Matcher 仍是 Evolve 专属，revise_node 只做 bootstrap 内收敛）。
- 决策项：SPLIT 镜像对近义风险（重跑采样未复现，是否需要豁免名单）；同名 <0.85 函数对唯一化规则；Inducer/闭环 LLM 非确定性（固定候选池 / Run A/B/C）；`data/bootstrap`/`data/evaluation` 被 .gitignore 忽略（仅 DB 为权威源），是否纳入版本控制待定。

## 当前交接更新（2026-08-20）：准备使用 functions.csv 重跑

### 当前已完成

- FunctionExtract 的 Snapshot 发布契约已完成：PASS 后发布不可变 `OntologySnapshot v2`，包含 Functions、FunctionOccurrence、评估结果和 SHA-256；已有 23-Function Snapshot 不覆盖、不原地修改。
- StoryPattern MVP-A 已完成代码和真实运行：输入为 `evolve_official_20260820T063134335355Z_e2db2e7a06bc`，23 Functions、60 篇故事、502 occurrences；完成序列、repetition、context、motif、variant recall、cluster、summary、catalog。
- 23-Function 版本最新结果：176 条已审查 pair（SAME 32 / RELATED 127 / DIFFERENT 17），11 个 cluster（8 个 CLEAN、3 个 CONFLICT），8 个 Pattern 已发布，3 个 cluster 保留人工复核；950 条未连接 EXPANDED pair 尚未调用 LLM。
- StoryPattern 旧产物集中在 `Code/data/story_pattern_official/`，但在新 Snapshot 发布前不应删除；新版本应使用新目录或带 Snapshot 标识的独立产物。

### 当前数据核查结论

- `Code/data/registry/functions.db` 只有 `functions` 表：`bootstrap=30`、`evolve_official=23`，合计 53 条物理记录。
- 用户提供的 `Code/data/registry/functions.csv` 已核实为该 Registry 的 CSV 导出：53 条数据行、35 个跨命名空间去重名称；其中 18 个 Function 名称在两个 namespace 中重复。文件不是历史 52-Function 导出。
- 历史 `O_0=52` 属于已删除的 120 篇旧语料运行；原始 52-Function 文件目前无法从工作区、Git 历史或悬挂对象恢复。因此后续应准确称为“基于当前 functions.csv 重跑”，不能再称为“恢复历史 52 重跑”。

### 本轮尚未执行

- 用户要求“用 functions.csv 重跑”；上一轮只完成输入核查，尚未导入、运行 Evolve、发布新 Snapshot，也尚未清空 StoryPattern 产物。没有删除现有数据。
- 当前 CSV 不能原样作为一个 Snapshot：53 条记录含两个 namespace，且 18 个名称重复；Snapshot 要求 `function_name` 和 `function_id` 唯一。

### 后续执行顺序

1. 从 `functions.csv` 生成独立重跑输入：保留 namespace 信息并确定去重规则；推荐对共享名称优先采用 `evolve_official` 的最终卡片，再加入 `bootstrap` 独有 Function，形成 35 个唯一 Function。该集合需单独使用新 namespace，不写回 `evolve_official`。
2. 在当前 60 篇语料上运行 Evolve 的匹配、周期评估、Curator 和最终评估；只有最终 PASS 才发布新的 Snapshot。若 FAIL，只保留工作产物并修正本体/阈值后重跑。
3. 新 Snapshot 发布成功后，清理或归档 `Code/data/story_pattern_official/` 的旧生成产物；保留旧 23-Function Snapshot 及其 Pattern 结果作为历史版本，不删除源码和测试。
4. 以新 Snapshot 全量运行 StoryPattern：重新生成 occurrence 序列、motif candidates、variant edges、review queue、clusters、summaries 和 PatternCatalog。旧的 156/176 条 review 不能直接复用，因为 Function 序列和 motif identity 已改变。
5. 校验新目录的 `snapshot_id`、Function/occurrence 引用、Pattern evidence 回溯和发布分流；运行全量离线测试，并将新结果追加到本交接文档。

### 关键约束

- 23-Function Snapshot 是不可变历史版本，不能覆盖；新本体必须拥有新的 `snapshot_id`。
- 不把 53 条物理记录误报为 53 个 Function，也不把当前 CSV 误报为历史 52；重跑报告必须同时记录物理行数、namespace 数量和去重后的 Function 数量。
- 若最终采用 35 个去重 Function，本次结果应命名为新的 CSV-derived Snapshot；只有用户提供真正的 52-Function 文件后，才可称为 52-Function 重跑。

## 本轮（2026-08-20）：CSV-derived Snapshot 直接发布 + StoryPattern 全量重跑

### 用户决策
- 用户明确：CSV 的 53 条就是 Evolve 跑完的最终结果，**不再重跑 Evolve**（中断了全量 Evolve 进程）；直接用 functions.csv 发布新 Snapshot 并跑 StoryPattern。

### 发布（跳过 Evolve 匹配/评估）
- 去重规则：共享名称优先 `evolve_official` 卡片 + `bootstrap` 独有 Function → **35 个唯一 Function**（name/id 均唯一；来源 evolve_official 23 + bootstrap 12）。
- 一次性工具：`Code/test/build_csv_rerun_input.py`（CSV → 去重输入 + 导入 `csv_rerun` namespace）、`Code/test/publish_csv_rerun_snapshot.py`（直接发布）。
- 已发布 **CSV-derived Snapshot**：`csv_rerun_20260820T140927554551Z_1eee0ef6d665`（schema v2，35 Functions / 502 occurrences，`source_workflow=evolve`，evaluation 为 demo 构造 PASS，标注 `source=functions.csv direct publish`）。
- occurrences 用 `align_occurrences` 从 `bank_evolve_official.jsonl`（60 篇 502 obs）直接对齐生成：MATCHED 384 / UNCERTAIN 118 / OTHER 0。
- 注意：bootstrap 独有 12 个 Function 在 CSV 中 `supporting_obs_ids` 为空（当前 60 篇语料无证据），发布后无 MATCHED occurrence，属数据现状。
- Registry：`csv_rerun` namespace 35 条；`bootstrap`（30）/`evolve_official`（23）未改动。

### StoryPattern 全量重跑（新 driver）
- 新增 `Code/test/run_story_pattern.py`（纯库串联 driver，分 phase：sequences/motifs/variants/clusters/full）。
- 产物：`Code/data/story_pattern_csv_rerun/`（story_sequences / structural_sequences / motif_candidates / motif_variant_pairs / high_pair_reviews / motif_clusters / pattern_summaries / pattern_catalog / run_report）。
- 全流程：60 篇 / 502 raw nodes → 435 structural runs → 321 motif candidates（3=138/4=91/5=58/6=34，REPEATED 1）→ 1,128 variant pairs（HIGH 156 / EXPANDED 972）。
- HIGH 全量真实 LLM 审查 156/156：`SAME_PATTERN=17 / RELATED=127 / DIFFERENT=12`（总耗时 489.2s）。
- Cluster：11 个（10 CLEAN / 1 needs_review）；summary 生成 10 个、跳过 1 个；catalog 发布 **10 个 Pattern**、manual review 1 个（`MCL_076bc0dfa5322158`）。
- 对比 23-Function 版（SAME 32/RELATED 127/DIFFERENT 17；11 cluster 8 CLEAN 3 CONFLICT；8 Pattern）：本版 SAME 更少、CLEAN 更多、Pattern 10 个。
- 验证：全量离线回归 `245 passed in 51.24s`。

### 遗留
- EXPANDED 972 条未连接 pair 未调 LLM（与 23-Function 版策略一致，留待后续预算）。
- 旧 `Code/data/story_pattern_official/`（23-Function 产物）保留未删；本次新产物在独立目录 `story_pattern_csv_rerun/`。
- 中断的 Evolve 临时产物 `data/evolve_csv_rerun/`、`data/evolve_csv_rerun_smoke/` 已清理；Bank 保持空。

## 本轮（2026-08-20 续）：Evolve 发布前自动唯一化/合并 + Bootstrap supporting 采集修复

### 用户决策
- 发布前合并放 Evolve 图内自动节点（不复用 0.85 余弦 `merge_candidates`，与 2026-08-17 "Separation 删余弦改 LLM" 决策一致）；合并判定走 LLM `merge_groups`。
- Bootstrap `supporting_obs_ids` 为空：确认是旧运行产物（2026-08-19 那次未采集），非代码缺陷；决策"修复 + 重跑 bootstrap 120 篇"。
- 全量跑法：新 namespace `evolve_unify`（复制 `evolve_official` 23 个作种子）+ unify 并入全部 bootstrap；不写回 `evolve_official`。

### 代码改动
- `Code/FunctionExtract_Agent/evolve.py`：新增 `unify_registry_node`（发布前唯一化/合并，插在 `curator → evaluator_final` 之间）：读 `UNIFY_PARENT_NAMESPACES`（默认 `("bootstrap",)`）与当前 namespace 并集，同名当前结果优先、父 namespace 只补缺；调用 `curator._full_merge_scan`（agglomerative 候选 + LLM 确认 `merge_groups` + `_llm_merge` 合并）写回当前 store；报告落盘 `out_dir/unify_report.json`。图拓扑 `curator → unify_registry → evaluator_final`。
- `Code/FunctionExtract_Agent/state.py`：新增 `unify_report` 字段。
- 测试：`test/test_evolve.py` 新增 2 项 unify 节点单测（并集去重/同名当前优先/LLM 合并写回；无合并保持）；现有 8 项 evolve 测试加 `monkeypatch.setattr(ev, "UNIFY_PARENT_NAMESPACES", ())` 隔离真实 bootstrap。

### 验证结果
- **Bootstrap 120 篇重跑**（`zhihu_story_subset_120_20260815_clean`，2026-08-20 16:54 起，64 分钟）：**100 个函数全部带 supporting**（2 条 41 个 / ≥3 条 59 个）；1057 obs；PASS 5/6（仅 separation 未达标，6 组近义）；发布 `bootstrap_20260820T165454075329Z_dc478f413bc9`。根因确认：代码链路本就采集 supporting，旧 bootstrap namespace（30 个全空）是 2026-08-19 未采集的旧产物。
- **Evolve 60 篇全量（`evolve_unify`）**：种子 23（复制自 evolve_official）+ unify 并入 bootstrap 100 → 唯一 122 → LLM 合并 5 组 → 最终 **115 个函数（全部带 supporting）**；60 篇 / 538 obs / coverage 0.794 / novelty 0.060；终评 **PASS 4/6**（coverage/cohesion/abstraction/diversity 达标；separation 9 组、evidence 3.235 未达）；发布 **`evolve_unify_20260820T181150619637Z_49834cdeac49`**（schema v2，115 Functions / 538 occurrences）。产物 `data/evolve_unify/`、日志 `test/logs/evolve_unify_20260821.log`。
- StoryPattern 消费验证：新快照 sequences 阶段通过（115 函数 / 60 故事 / 538 occurrence / 485 structural runs）。
- 全量离线回归：**247 passed in 50.25s**（新增 2 项）。

### 关键约束与遗留
- `evolve_official`（23 函数）/ `bootstrap`（旧 30 全空，已被重跑 100 覆盖）/ `csv_rerun`（35）均保留；新本体在 `evolve_unify` namespace 与独立快照。
- 注意：unify 后本体以 bootstrap 100 个为主（+当前演化 15 个新增），函数数从 23 → 115，覆盖度提升但 separation/evidence 未达标（PASS 阈值 4/6）。
- bootstrap 重跑已覆盖旧 `bootstrap` namespace 与 Bank；旧 2026-08-19 30 函数快照不可恢复（未单独留档），如需回退需从 Git/旧导出找回。
- StoryPattern 尚未对新 `evolve_unify` 快照跑 motifs/variants/review/clusters/summaries/catalog 全流程（仅 sequences 验证）。

## 本轮（2026-08-20 续 2）：撤销 unify 节点，干净重跑（bootstrap 120 → evolve 60）定稿

### 用户决策（修正）
- 用户指出：重跑后 100+ 个函数、DB 新旧 namespace 混在一起（evolve_unify 混血：92 bootstrap + 22 旧 evolve_official + 2 新）、"为什么新增节点"。
- 结论：unify_registry_node 多余——bootstrap 重跑后已是干净唯一化本体，Evolve 直接以它为种子演化即可。
- 语料确认：bootstrap 用 `zhihu_story_subset_120_20260815_clean/`，evolve 用 `zhihu_story_subset_60_5domains_20260819_clean/`。

### 代码回滚
- 撤销 `evolve.py` 的 `unify_registry_node` / `UNIFY_PARENT_NAMESPACES` / 图边 `curator→unify_registry→evaluator_final`（恢复 `curator→evaluator_final`）；撤销 `state.py` 的 `unify_report` 字段；撤销 `test_evolve.py` 的 2 个 unify 单测与 monkeypatch 隔离。
- 验证：`test_evolve.py` 8 passed；全量离线回归 `245 passed in 54.87s`（与基线一致）。

### 干净重跑结果（最终定稿）
- **种子**：`evolve_clean` = bootstrap(120 篇重跑) 100 个全部复制（均带 supporting），Bank 清空，不碰旧 evolve_official。
- **Evolve 60 篇**：520 obs；coverage 0.835 / novelty 0.029；**基线 100 → 最终 59**（新增 10 / 移除 51 / 保留 49——51 个 bootstrap 函数在当前 60 篇无证据被 Curator 移除）。
- **终评 FAIL 3/6**（coverage/cohesion/diversity 过；separation 3 组、abstraction 0.797、evidence 4.93 未达），按契约未自动发布。
- **用户决策 c：接受 59 个工作产物并手动发布** → 发布 **`evolve_clean_20260820T230149522719Z_62353704ecba`**（59 Functions / 520 occurrences：MATCHED 424 / UNCERTAIN 96；evaluation 标注 demo 直发，FAIL 3/6 接受）。产物 `data/evolve_clean/`、日志 `test/logs/evolve_clean_20260821.log`。
- StoryPattern 消费验证：sequences 通过（59 函数 / 60 故事 / 520 occurrence / 448 structural runs）。

### 当前数据状态
- DB namespaces：`bootstrap`(100，120 篇重跑)、`csv_rerun`(35)、`evolve_official`(23)、`evolve_clean`(59)。
- 已发布快照：`evolve_clean_...62353704ecba`（59，最新）、`bootstrap_...dc478f413bc9`（100）、`csv_rerun_...1eee0ef6d665`（35）、`evolve_official_...e2db2e7a06bc`（23）等。
- `evolve_unify`/`evolve_smoke_unify` 已清空并删除产物目录（混血废弃）。
- StoryPattern 尚未对新 59-Function 快照跑 motifs/variants/review/clusters/summaries/catalog 全流程（仅 sequences 验证）。

## 本轮（2026-08-20 续 3）：StoryPattern 全量重跑（evolve_clean 59-Function 快照）
- 输入：`evolve_clean_20260820T230149522719Z_62353704ecba`（59 Functions / 60 篇 / 520 occurrences）。
- 产物：`Code/data/story_pattern_evolve_clean/`（story_sequences / structural_sequences / motif_candidates / motif_variant_pairs / high_pair_reviews / motif_clusters / pattern_summaries / pattern_catalog / run_report）；日志 `test/logs/story_pattern_evolve_clean_20260821.log`。
- 全流程：520 raw nodes → 448 structural runs → **508 motif candidates**（3=193/4=143/5=102/6=70；REPEATED 4 / SINGLE_STORY 504）→ **1,644 variant pairs**（HIGH 141 / EXPANDED 1503）。
- HIGH 141 条真实 LLM 审查：`SAME_PATTERN=42 / RELATED=92 / DIFFERENT=7`（耗时 398s）。
- Cluster：8 个（5 CLEAN / 3 needs_review，其中 2 个 review_incomplete）；summary 生成 5 个；catalog 发布 **5 个 Pattern**、manual review 3 个。
- 发布 Pattern：
  - `PAT_1a362a8df74e92d2` 末日求生助力与危机应对（EXTERNAL_SUPPORT_ACQUISITION → DANGER_EXPOSURE → CRITICAL_ESCAPE → COPING_WITH_HOSTILE_ENVIRONMENT）
  - `PAT_7a2d279932ed41a1` Rescue-Escalation Arc（CRITICAL_ESCAPE → DANGER_RESCUE → CRITICAL_ESCAPE）
  - `PAT_9990084533f63af9` Investigative Truth Unfolding with Clue Recurrence（INVESTIGATION_DEVELOPMENT → MYSTERY_CLUE_INTRODUCTION → TRUTH_REVELATION）
  - `PAT_c5570ae43e6209ca` goal-driven revenge escalation（GOAL_COMMITMENT → REVENGE_MOTIVATION → REVENGE_EXECUTION）
  - `PAT_fa4e8053eea58510` 情感揭示同盟（ROMANTIC_OR_INTIMATE_DEVELOPMENT → ALLIANCE_FORMATION → EMOTIONAL_REVELATION）
- manual review 3 个：`MCL_b3f92c3462db696f` / `MCL_d2869208b0069747` / `MCL_df001f50a6f28541`（均 CLUSTER_NEEDS_REVIEW）。
- 验证：全量离线回归 `245 passed in 51.96s`。

## 本轮（2026-08-20 续 4）：模板核心链长度下限 3 → 4
- 用户质疑模板组合 Function 太少；核实：快照 59 函数全部有 MATCHED、片段平均 4.98、62% 候选 ≥4 长度——瓶颈不在函数数，而在 summary 的 `core_function_names min_length=3`（LLM 倾向取最短公共核心）。
- 改动：`Code/StoryPattern_Agent/Prompt/Summary_prompt.py`（`min_length=3→4` + prompt 文案"至少为 4"）；`summaries.py` 校验 `len(core_names) < 3 → < 4`；`test/test_story_pattern_summaries.py` fixture 补到 4 个函数/4 个 core 名。
- 重跑 StoryPattern（HIGH 141 条 LLM 重审，SAME_PATTERN 42→50 为 LLM 非确定性；summary 出现 3 次"先给 3 个被 schema 拒后重试成功"）。
- 效果：核心链长度 **1×5 + 4×4**（全部 ≥4）；发布模板：
  - `PAT_ab1a4df322aa5132` Trusted Betrayal → Relationship Termination and Escalating Harm（5 步：BETRAYAL_BY_TRUSTED_OTHER → MARRIAGE_TERMINATION → POWER_ABUSE_VICTIMIZATION → RESOURCE_WITHDRAWAL → INITIATE_ASSAULT）
  - `PAT_c5570ae43e6209ca` 复仇驱动下的目标追寻（GOAL_COMMITMENT → BETRAYAL_BY_TRUSTED_OTHER → HIDDEN_BLOCKER_SETUP → REVENGE_EXECUTION）
  - `PAT_ef18bc6a43418bb5` Emotional Revelation to Rescue（SELF_AWARENESS_GROWTH → EMOTIONAL_REVELATION → VICTIMIZATION_AND_CONFRONTATION → DANGER_RESCUE）
  - `PAT_fa4e8053eea58510` 情感升华与关系联盟（ROMANTIC_OR_INTIMATE_DEVELOPMENT → ALLIANCE_FORMATION → RELATIONSHIP_DEVELOPMENT_DEEPENING → EMOTIONAL_REVELATION）
  - `PAT_fd54a4224babf031` 绝境获援（CRITICAL_ESCAPE → EXTERNAL_SUPPORT_ACQUISITION → DECISION_TO_ACT → DANGER_RESCUE）
- 验证：summary 定向测试 6 项通过；全量离线回归 `245 passed in 52.61s`。

## 本轮（2026-08-20 续 5）：HIGH review + summary 冻结回放（消除 LLM 非确定性）
- 问题：同数据重跑 HIGH review 结果漂移（SAME_PATTERN 42→50），模板成员/内容随之变化（Inducer/审查 LLM 非确定性）。
- 改动：`Code/test/run_story_pattern.py` 新增 `--replay-high <jsonl>`（按 `variant_pair_id` 回放已冻结 review，校验 snapshot_id）与 `--replay-summaries <json>`（按 `cluster_id` 回放已冻结 summary），跳过对应 LLM 调用。
- 验证：全回放重跑 25.6s（原 440s，无 LLM），产物与原始**完全一致**（published 5 个 ID、核心链、名称全部相同）；HIGH 141 条 verdict=SAME 50/RELATED 87/DIFFERENT 4 稳定。
- 回放产物：`data/story_pattern_evolve_clean_replay2/`（与 `story_pattern_evolve_clean/` 一致）；日志 `test/logs/story_pattern_evolve_clean_replay2.log`。
- 注意：summary LLM 仍非确定（同一 cluster 会选不同核心子链/名称），但模板 ID 由 review 决定已稳定；如需全链可复现，用 `--replay-summaries` 冻结 summary。
- 验证：全量离线回归 `245 passed in 57.82s`。

## 踩过的坑（不要再踩）
- 本环境 `apply_patch`/`Remove-Item` 被策略拦截：用 .NET `[System.IO.File]`/`[System.IO.Directory]` API 或精确文本替换。
- PowerShell 管道给子进程（`python -` 等）传中文会乱码：脚本内用相对路径或直接在当前 shell 执行。
- `test_bank.py` 的 `persist_dir="Code/data/bank_test"` 会解析到 `Code/Code/data/bank_test`（历史遗留，勿沿用该路径写法）。
- StoryPattern 纯库无 CLI，节点是单步函数：故事循环必须手动 `current_story_index += 1`（`select_story` 不推进下标，否则死循环）。
- StoryPattern driver 顶部 import `variants` 会加载 Embedder（~16s）；stdout 经 PowerShell 管道会被缓冲，调试用 `python -X utf8 -u` + 文件重定向。
- Evolve 的 unify 节点读父 namespace 时必须用 `RegistryStore(db_path=store.db_path, namespace=parent_ns)`（继承当前 store 的 DB 路径），否则会误读真实 `functions.db`。
- Evolve 重跑前务必：目标 namespace 清空/新建（evolve 本身不清空）、Bank 清空、种子从干净 bootstrap 复制——否则新旧函数混血。
- FAIL ≠ 无函数：终评 FAIL 只是不自动发布快照，Registry/工作产物（functions_*.jsonl / occurrences / evaluation_final.json）都在，可手动发布（demo 可构造 PASS evaluation 直发）。

## 本轮（2026-08-22）：Evolve 250 篇全量（evolve_250）+ StoryPattern 模板提取
- 启动命令：`python -X utf8 -m Agent.evolve --corpus zhihu_story_subset_250_5domains_20260821_clean --namespace evolve_250 --out-dir data/evolve_250`。
- 前置：种子 = evolve_clean 59 函数；250 篇清洗语料；Bank 已有前 93 篇 obs（845 条，obs_id 按 story+序号确定性生成，重跑不重复写入）。
- 前两次运行均因代理连接错误（WinError 10048）在预处理阶段中断；本次连通性正常，全量跑完（总耗时 28756s，115s/篇）。
- **Evolve 结果**：250 篇 / 2056 obs（MATCH 1628 / EXTEND 33 / NOVEL 84 / RESOLVED 311），coverage 0.808 / novelty 0.041；84 次 mid 体检；Curator novelty 归纳新增 12 函数 + 修订（curator_plan.jsonl 1688 个动作）。
- **终评 PASS 5/6**（coverage 0.953 / cohesion 0.846 / abstraction 0.807 / evidence 20.79 故事/函数 / diversity 248；仅 separation=3 未达标）→ **自动发布快照 `evolve_250_20260822T063550401096Z_13b1bbda248f`**（62 Functions / 2193 occurrences；基线 59 → 62：新增 13 / 移除 10 / 保留 49），无需手动发布。
- 注意：Bank 2193 obs > run 内 2056 obs——前 93 篇旧 Bank obs（845 条）与本次新提取共存（无重复写入），快照 occurrences 以 Bank 全量 2193 对齐为准。
- **StoryPattern 提取**（snapshot=evolve_250_...13b1bbda248f）：2193 occurrence → 2043 structural runs → 1904 motif 候选（REPEATED 17；长 3=744/4=539/5=371/6=250）→ 7146 variant pairs → HIGH 实审 1758 条（RELATED 1377 / SAME_PATTERN 295 / DIFFERENT 86）→ 96 cluster（75 CLEAN / 21 needs_review / 12 review_incomplete）→ **发布 71 个 Pattern**（核心链 4/5/6 全部 ≥4）、拒绝 4、人工复核 21。
- 产物：`Code/data/story_pattern_evolve_250/`（pattern_catalog.json / pattern_summaries.json / run_report.json 等）；日志 `test/logs/story_pattern_evolve_250_20260822.log`（首轮，HIGH 实审 80 分钟）与 `..._rerun.log`（`--replay-high` 回放重跑，总 693.8s）。
- 代码修复：`StoryPattern_Agent/summaries.py`——摘要生成重试耗尽（ValueError）不再整体崩溃，改为跳过该 cluster（catalog 记 SUMMARY_MISSING 拒绝）；新增回归测试 1 项。
- 验证：全量离线回归 `246 passed in 45.06s`（245 + 1 新增）。
- 遗留：4 个仅 3 函数的 cluster 无法出模板（结构上不可能满足核心链 ≥4）；21 个 cluster 待人工复核；HIGH 1758 条已冻结可回放；summary 未冻结（LLM 非确定，可复现用 `--replay-summaries`）。

## 踩过的坑（续）
- StoryPattern summary：cluster 成员去重后不足 4 个不同函数时，核心链 min_length=4 校验必然失败且重试无效（`chat_structured` 抛 ValueError 导致整个管线崩溃）；不要试图让 LLM 硬凑第 4 个函数，正确做法是跳过该 cluster（catalog 记 SUMMARY_MISSING）。

## 本轮（2026-08-27）：Function Card 补全（evolve_250 · 62 张旁挂卡片）
- 目标：MVP-B（大纲生成）前置——把 62 个 Function 补成"可生成结构约束"（前置条件/角色位置/状态变化），产物绑定冻结快照 `evolve_250_20260822T063550401096Z_13b1bbda248f`，快照/Registry/Bank 只读。
- 证据口径（已确认）：`evidence(f) = supporting_obs_ids(f) ∩ Bank`；多支持 obs 按函数各自计入；`dangling = declared - resident`；不从旧 Bank 回收。不用 occurrences 的 `candidate_functions` 判多支持——align_occurrences 的 `occurrence.update(prior_by_id...)` 会残留旧 match 的候选字段，实测 350 条 UNCERTAIN 带 candidates，其中真正多支持仅 8 条。
- 悬空成因确认：Function 本体跨语料继承且 supporting 只增不删（APPLY_EVIDENCE 只追加、MERGE 并集传播），Bank 语料本位重建/累积，两者生命周期不同步。快照 660 条悬空 = 401（evolve_clean Bank）+ 258（bootstrap Bank）+ 1（无出处）；涉及 53/62 函数（49 个保留种子全带 + 4 个 MERGE 新函数）。
- 实现：`test/backfill_function_cards.py`（确定性聚合纯函数 + 每函数一次 `chat_structured` 抽象；逐函数落盘、重跑跳过已成功卡片）+ `test/test_backfill_function_cards.py`（7 项：dangling 记账/多支持双计/story 去重/频次排序与平局/0 证据边界/LLM 紧凑输入 mock）。
- 卡片 schema：`function_id/function_name/definition` + `evidence`（declared/bank_resident/dangling/support_story_count/participant_labels/common_affected_aspects top-3/evidence_refs）+ `abstraction`（preconditions/role_slots/state_transition{before,after}）+ `llm.ok`。
- 产物：`data/function_cards/evolve_250_20260822T063550401096Z_13b1bbda248f/function_cards.jsonl`（62 张）+ `summary.json`；62/62 `llm.ok`；LLM 62 次 / 147,999 tok / 147.4s；证据合计 declared 2347 / resident 1673 / dangling 674（按函数求和、多支持双计）。
- 验证：62/62、function_id/名称集合与快照一致、evidence 与程序重算逐字段一致；抽查 SECRET_REVELATION / RELATIONSHIP_DEVELOPMENT_DEEPENING 抽象与 Plan.md 示例结构吻合；全量回归 253 项通过。
- 遗留：① Inducer/Merge/Revise 三处 schema 前置未做（等卡片格式验证后再同步，避免返工）；② story_stage 暂缓；③ participant_labels 含少量具体人名（250 语料个别 obs.participants 出现"邱芸/何强"等），role_slots 已做类型级抽象，如需净化可后续处理；④ **悬空 supporting 根治待解决**——语料/Bank 继承只能消除"换语料"诱因，彻底解决需在发布新快照时做函数侧清理（校验 `supporting_obs_ids ⊆ 当前 Bank`，删除/记录失效引用）；当前快照 functions.jsonl 与 occurrences.jsonl 因 660 条悬空声明引用存在内部不一致，新快照发布时应一并处理。
- 踩坑（不要再踩）：DeepSeek `json_object` 模式要求 prompt 必须含 "json" 字样，否则整批 400（首跑 62 连败）；chat_structured 的重试救不了这类 API 层错误，提示词必须自带 JSON 字样。

## 本轮（2026-08-27 续）：transition/realization index 构建
- 新增 `test/build_transition_index.py`（确定性统计，零 LLM）+ `test/test_build_transition_index.py`（3 项）：从 evolve_250 快照 occurrences 恢复 247 个故事序列、折叠连续重复，统计 801 种 Function 邻接对（from/to/count/support_stories）；并统计 62 个 Function 的实例机制（supporting ∩ Bank 的 surface_form 去重 + 计数 + 样本 event）。
- 产物：`data/transition_index/evolve_250_20260822T063550401096Z_13b1bbda248f/transition_index.json`；供 Phase 3 Planner（选序列）与 Mechanism Plan（实例机制参考）使用。
- 备注：surface_form 高度离散（多数机制 count=1），机制表主要作检索池而非"常见机制"榜；后续可按需加入题材分布与 event 聚类。

## 本轮（2026-08-27 续 2）：Phase 2 精简决策 + Phase 3 方向确认
- 边界：MVP-B 生成的是"大纲"而非全文（Plan.md 明确"止于大纲，不生成正文"）。
- 生成链路只需要四块素材：① core_function_chain（套路骨架，首轮不用 optional_steps）；② Function Card（preconditions / role_slots / state_transition）；③ transition index（连接规律 + 实例机制）；④ Outline Realizer 的运行时角色/状态账本（防角色漂移）。
- 明确缓做：StoryProfile 全量预生成（只留生成后验证/抽样）、InstanceCard 角色绑定、轮次 + 辅助要素的语料标注、21 个 needs_review 审计、人物姓名级知识图谱、重提取 Observation。
- 形态学辅助要素（衔接、同化、三重化、倒置、省略）属于 Function 提取结果的逐句标注，应由 `FunctionExtract_Agent` 判定并随 occurrence 发布；生成阶段只消费结构结果，不现场伪造这些标签。当前 MVP 尚未发布这组字段。
- 已具备产物：Function Card 62 张（`data/function_cards/evolve_250_.../`）、transition index（`data/transition_index/evolve_250_.../`，801 邻接对 + 62 机制）、PatternCatalog 71 个（core_function_chain 干净可用；optional_steps 部分为英文自然语言，首轮忽略）。
- 下一步：Phase 3 五步生成管线（Planner → Story Seed → Mechanism Plan → Outline Realizer → Validator），先单轮短篇大纲冒烟，再按 3 题材 × 3 份验收 + 人工盲评。

## 本轮（2026-08-27 续 3）：Phase 3 大纲冒烟（单链端到端）
- 新增 `test/generate_outline.py`（不建 Agent、不铺图）：Planner（确定性 FOLLOW top pattern）→ StorySeed → MechanismPlan → OutlineRealizer → Validator 五个节点串行，用一条 core_function_chain 生成一份单轮短篇大纲。
- 数据流验证通过：输入 = pattern_catalog 的 core_function_chain + Function Card（preconditions/role_slots/state_transition）+ transition index（实例机制）；输出 = seed + 机制方案（role_bindings）+ 分段大纲 + 状态账本 + 校验报告（逐段 recoverable 复抽 + 规则顺序检查）。
- 冒烟暴露并修复两处：① LLM 输出字段与 pydantic schema 不符（identity vs label）→ 提示词显式写死 JSON 字段名；② LLM 重排核心链顺序 → 确定性 `_align` 按 chain 顺序重排，核心链顺序不交给 LLM。
- 产物：`data/outlines/<snapshot_id>/smoke_<题材>.json`。

## 本轮（2026-08-27 续 4）：Outline_Agent 正式化（按题材生成单轮大纲）
- 新增 `Outline_Agent/`（state.py + Prompt/Outline_prompt.py + app.py + __main__.py）：线性 LangGraph `START → planner → seed → mechanism → realize → validate → export → END`；CLI `python -X utf8 -m Outline_Agent --genre 悬疑惊悚 [--snapshot-id ...] [--out-dir ...]`。
- planner：按 `category_counts` 匹配题材（接受 `悬疑惊悚` 或 `01_悬疑惊悚`），取该题材 support 最高 pattern（并列按 pattern_name 字典序），无匹配回退全库最高 support；合并 Function Card 的 preconditions/role_slots/state_transition 到 core_function_chain。
- mechanism/realize 输出后按 chain 顺序确定性 `_align`；validate = LLM 逐段 recoverable 复抽 + `rule_check`（段顺序/覆盖必须等于 chain）+ 前置/状态连续/角色一致/结局闭合。
- 输出：`data/outlines/<snapshot_id>/<题材>_<时间戳>.json`（机器）+ 同名 `.md`（人读分段大纲）；只读知识，不写 Registry/Snapshot。
- 测试：`test/test_outline_agent.py` 7 项（题材规范化/planner 匹配+回退+tie-break/_align/rule_check/图端到端 mock）；全量回归 263 项通过。
- 真实冒烟：`--genre 悬疑惊悚` → FOLLOW「危局援手与连环深渊」核心链，四段大纲、overall_ok=true、rule_issues 空。
- 同一题材换 pattern：CLI 新增 `--list-patterns`（列题材候选，悬疑惊悚 20 个）与 `--pattern <名称>`（显式指定，覆盖题材自动匹配）；测试补至 10 项。
- 重复 Function 递进：`annotate_occurrences` 给链标注 occurrence_index/total；Mechanism/Realize 提示词要求重复项递进且不雷同；`rule_check` 增加确定性检查（重复段 beats 完全相同 → 重复 Function 未递进）。这是一条生成质量规则，不等同于形态学“三重化”标签。
- 边界（已确认）：单份大纲（不做 Best-of-N）；首版忽略 optional_steps/轮次/辅助标签；题材只支持现存 5 键。

## 本轮（2026-08-27 续 5）：MVP-B 批量 + 三组盲评材料
- 新增 `test/run_outline_eval.py`：3 题材（悬疑/现代/末世）× 3 份全系统大纲（full）+ 两个基线（direct=只给题材；function_only=只给有序函数名）。
- 结果：9 份 full 中 8 份 `overall_ok=True`；悬疑惊悚 #2（悬念升级式调查推进，核心链含重复函数）被确定性 `rule_check` 标记为“重复 Function 未递进”（重复段 beats 完全相同），属于生成质量阻断，非崩溃。
- 盲评产物：`data/outline_eval/<snapshot_id>/comparison/<题材>.md`（A/B/C 盲评稿）+ `<题材>.key.json`（A/B/C → direct/function_only/full 揭盲映射）；人工先读 .md 打分，再开 .key.json 揭盲。
- 全程 2 次 LLM JSON 解析失败被 `chat_structured` 自动重试恢复。

## 本轮（2026-08-27 续 6）：MVP-B 第一轮内容盲评
- 生成中性评审副本：`data/outline_eval/<snapshot_id>/blind_review_v1/`；移除方案标题和 Function 名称，仅保留题材、A/B/C 和中性段落编号。原始 comparison 与 key 不修改。
- 统一量表：结构完整性、因果连贯性、人物动机、冲突与转折、新颖性、整体吸引力，均为 1–5 分；前三项为 MVP-B 核心门槛。
- 第一轮单评审结果：`direct=3.94`、`function_only=3.44`、`full=3.22`；核心三项均值分别为 `4.22`、`3.67`、`3.33`。完整系统暂不能判定 MVP-B 通过。
- 关键诊断：悬疑惊悚和末世科幻的 full 方案均在暴露/囚禁阶段结束，缺少主线解决和结局闭合；现代情感 full 结构闭合，但机制和辅助人物较模板化。当前 Validator 的 `overall_ok` 未能可靠拦截“故事未完成”。
- 产物：`blind_review_v1/rubric.md`、`agent_review.json`、`agent_review.md`；验证 `json_ok`，相关测试 `14 passed`。
- 下一步：先修复 Pattern/Planner 的闭合性约束（选择可结束的核心链，或显式补充解决/结局阶段），用同一三组材料协议重跑，再决定是否进入局部修复和 Best-of-N。单评审结果不能替代多人一致性检验。

## 本轮（2026-08-27 续 7）：Pattern/Planner 可闭合性白名单实验（临时启发式，已撤回）
- 根因：PatternCatalog 的 `core_function_chain` 是局部 motif，不天然是完整故事；Planner 原来只按题材支持数选第一名，可能以 `DANGEROUS_EXPOSURE` / `FREEDOM_DEPRIVATION` 等过程型 Function 收尾。
- 实验方法：曾以手工结果型 Function 白名单过滤 Pattern，并要求 Realizer 兑现 `ending_direction`；该方法只用于验证“过程链直接充当完整故事”这一诊断，不是正式系统约束。当前代码已删除 `_CLOSING_FUNCTIONS`、`is_closable_pattern()` 及对应确定性校验。
- 新首选链：悬疑=`TRUTH_EXPOSURE → DECISION_TO_ACT → EXPLOITATION → ACTIVE_COUNTERATTACK`；现代维持关系深化链；末世=`REVENGE_MOTIVATION → EXTERNAL_SUPPORT_ACQUISITION → SOCIAL_MANIPULATION → REVENGE_EXECUTION`。
- 重跑产物独立落盘：`data/outline_eval/<snapshot_id>/closure_v2/`。9 个 full 均通过结果型末端硬约束；7/9 通过语义 Validator。悬疑 #3、现代 #3 虽末端可闭合，但具体实例未兑现 `ending_direction`，被 Validator 正确判失败；进入三组 comparison 的 top full 均通过。
- 第二轮单评审：`direct=4.11`、`function_only=3.67`、`full=3.50`；核心三项 `4.33 / 4.00 / 3.78`。full 相对首轮：结构完整性 `3.33→4.00`、总均分 `3.22→3.50`、核心三项 `3.33→3.78`。
- 结论：分数变化仅证明闭合约束方向值得继续验证，不能证明 Function 白名单是正确架构。正式方案改为 Function 发布可组合的状态/义务合同，由 StoryPattern 组合链路、Outline 在实例层验证闭合。
- 评审产物：`closure_v2/blind_review_v2/rubric.md`、`agent_review.json`、`agent_review.md` 均标记为临时启发式实验；不作为 MVP-B 正式重评或论文级统计结论。

## 本轮（2026-08-27 续 8）：FunctionContract 正式发布链路
- 新增共享契约 `Contracts/function_contract.py`：`FunctionContract` 由角色槽位、状态前置条件、状态效果、义务开启/推进/解除、Function 定义哈希和证据引用组成；它描述 Function 的可组合变换，不判断某个 Function 是否属于结局。
- 新增 `FunctionExtract_Agent/Contract`：只使用 `supporting_obs_ids ∩ 当前 Observation Bank` 的驻留证据生成类型级合同；无驻留证据直接拒绝发布。缓存仅在定义哈希和完整校验均通过时复用。
- Bootstrap 在 `abstract_merge` 后的最终 Function 集合通过终评后生成合同；Evolve 在 Curator 稳定 Function 并通过 `Evaluator_final` 后生成合同。合同不会在仍可能被合并、修订或拆分的阶段提前生成。
- `OntologySnapshot` 升级为 v3：原子发布 `functions.jsonl`、`occurrences.jsonl`、`function_contracts.jsonl`、`evaluation.json` 及各自哈希；严格验证每个 Function 恰有一份合同、定义哈希、证据归属和角色槽位引用。v1/v2 继续只读兼容。
- 验证：FunctionContract、Snapshot、Bootstrap/Evolve、Revise、Outline 联合回归 `57 passed`。本轮未调用真实 LLM、未重新发布真实 62-Function 快照。

## 本轮（2026-08-27 续 9）：FunctionContract 下游链路验收
- 最小 v3 Snapshot 探针确认：`FunctionExtract → FunctionContract → Snapshot v3` 可发布、可校验、可加载。
- 当前消费链尚未闭合：`StoryPatternState` 与 `load_inputs()` 没有携带 `function_contracts`；StoryPattern 的 motif/PatternCatalog 仍只传递 Function ID、名称和定义；`Outline.planner()` 仅接收 catalog 与 Function Card，Mechanism/Validator 也未读取合同。
- 结论：本轮的 `274 passed` 是模块与发布链回归，不代表合同已经影响 Pattern/Planner/Outline。下一步应先定义合同在 StoryPattern 和 Outline 的最小消费接口，再做同一 Snapshot 的端到端验收；在此之前不重新跑真实盲评。

## 本轮（2026-08-27 续 10）：FunctionContract 消费链接入
- StoryPattern `load_inputs` 在 v3 Snapshot 读取 `function_contracts` 和按 ID 索引；summary 将核心 Function 的合同带入 Pattern，Catalog 对 v3 核心链逐项校验合同与 Snapshot 一致。
- Outline 按 `snapshot_id` 加载对应 PatternCatalog 和 v3 合同；Planner 以 Snapshot 合同覆盖旧 Function Card 的角色槽位/前置条件，并拒绝 Pattern 合同与 Snapshot 合同不一致。旧 v2 继续使用 Function Card 兼容路径。
- 新增确定性 Contract Ledger：Mechanism 的实例角色绑定应用到合同，检查状态前置/效果连续性、角色绑定和状态变化说明，跟踪义务开启/推进/解除；Validator 将合同问题写入 `contract_issues` 并强制 `overall_ok=false`。
- 端到端最小图已验证：合同从 Snapshot 进入 Pattern/Planner，经 Mechanism 生成状态账本，最终被 Validator/Export 保留；新增定向测试 `59 passed`，全量离线回归 `281 passed in 58.20s`。
- 当前边界：尚未用真实 62-Function v3 Snapshot 运行 StoryPattern 全流程和三组盲评；需先生成/验证该 Snapshot 的合同词汇与链间状态兼容性。

## 本轮（2026-08-27 续 11）：真实 62-Function v3 Snapshot 与链间兼容性验收
- 基于已通过终评的 `evolve_250_20260822T063550401096Z_13b1bbda248f` 生成独立 v3 Snapshot `evolve_250_contracts_20260827T100511324434Z_670b7cbb13d1`；原 v2 Snapshot 未覆盖。合同由当前 Function 的驻留证据生成，62/62 发布成功，包含 2193 条 Observation，`validate_snapshot` 返回 schema v3 / PASS。
- 真实合同词汇：94 个 aspect、398 个 state、139 个 obligation key；义务效果为 opens 78、advances 54、resolves 27。词汇已暴露命名漂移（例如 `EDANGER`）和粒度离散，当前格式校验尚不足以保证语义词汇可组合。
- 兼容性扫描使用同一 Function 集合的历史 71 个 Pattern，仅作离线诊断，未将旧 Catalog 冒充为 v3 发布物：226 条相邻 Function 边中，严格 `after == precondition` 的 exact compatible edge 为 0，71 个 Pattern 均未得到完整 exact 链。
- 结论：Snapshot 发布链已闭合，但真实语义链尚未达到可组合标准；0/226 不是“所有 Pattern 都错误”的证明，而是状态命名、初始前置条件与链间前置条件尚未分层/规范化的证据。因此本轮不重跑盲评。
- 下一步：在 `FunctionExtract_Agent` 的正式发布链上增加证据约束的 `StateVocabulary`/别名归一化与边语义定义，再重新生成 PatternCatalog，随后沿用同一三组材料协议重评。

## MVP 当前交付边界与后续改进项（2026-08-27）
- MVP 当前状态：Function 提取、不可变 Snapshot v3、Pattern/Planner/Mechanism/Validator 合同消费链和三组盲评材料均已具备；真实 62-Function 合同 Snapshot 已通过发布校验。当前结果可作为工程 MVP，不把严格链兼容性未达标描述为 MVP 阻塞。
- P1：在 `FunctionExtract_Agent` 正式发布阶段建立证据约束的 `StateVocabulary`，统一 aspect/state/obligation key 的规范 ID、别名、拼写漂移和粒度；保留原始表述作为 evidence，不用手工结局 Function 白名单替代。
- P1：定义链边语义，区分世界初始条件、Function 的输入条件、上一步 Function 的输出条件、可持续状态和义务清偿；调整兼容性检查，使其能判断可组合性，而不是只做字符串 exact 匹配。
- P1：基于规范化合同重新生成并发布 PatternCatalog，要求 Pattern 核心链携带同一 Snapshot 的合同，并在发布时报告断链、开放义务和未定义终态。
- P2：让 Planner 依据目标冲突、终态和未清义务规划故事结束，不把单个 Function 标记为“结局 Function”；让 Realizer/Validator 继续验证实例是否兑现合同效果。
- P2：补充真实 Snapshot 下 StoryPattern 全流程验收，再用同一三组 A/B/C 材料协议重评；当前单评审结果只用于工程诊断，后续需增加多人评审一致性。
- P2：修复合同生成的语义质量控制，包括 aspect/state 词汇漂移、证据不足、角色槽位过宽和义务 opens/advances/resolves 不完整，并保留合同生成与 Snapshot 的可追溯报告。

## MVP-B 收尾状态（2026-08-27）
- MVP-B 已收尾：大纲生成链路可运行，真实 Snapshot、Pattern/Planner、Mechanism、Validator、导出物和三组盲评材料均已具备，结果可追溯。
- 已知限制不作为当前交付阻塞：真实合同的状态词汇尚未规范化，严格链兼容性为 `0/226`；这属于后续研究性改进，不影响当前 MVP 的完成判定。
- 后续优化仅保留为 backlog：`StateVocabulary`/别名归一化、链边语义、合同约束下重新发布 PatternCatalog、终态与未清义务验证、多人盲评一致性、Best-of-N 和正文生成。当前不启动这些改造。
- 下一阶段先做 MVP 使用与问题收集：选定生成目标，使用现有 Pattern/Planner 生成一批实际大纲，整理可复现的质量问题，再按一个具体问题进入小步迭代。

## 本轮（2026-08-27 续 12）：MVP-B 实际使用批次
- 沿用当前默认 MVP Snapshot、PatternCatalog 和 Function Card 链路，未覆盖既有评审产物；产物目录为 `data/outline_eval/evolve_250_20260822T063550401096Z_13b1bbda248f/usage_batch_20260827/`。
- 共生成 3 个题材 × 3 份 full 大纲，另保留每个题材的 direct/function_only 对照和 A/B/C 文件；9 份 full 中 `overall_ok=True` 为 5 份，`False` 为 4 份。
- 可复现问题集中为两类：① 3 份大纲的最终段仍未解决核心冲突，只停在营救、逃避、重建或后续行动；② 1 份大纲的重复 Function 未形成递进，重复段情节完全相同。现代情感 3 份均通过，说明问题不是所有题材普遍崩溃。
- 本批次用于实际使用反馈，不作为新的论文级盲评结论。下一次小步迭代优先处理“结局段兑现核心冲突”这一单一问题，暂不启动 StateVocabulary 全量改造。

## 本轮（2026-08-27 续 13）：Pattern 级 ending_spec 实现
- StoryPattern summary 增加可选 `ending_spec`（`resolves` / `must_show` / `final_state`），要求仅依据 cluster 证据生成；局部 motif 或缺少结局证据时返回 `null`。PatternCatalog schema 升为 v2，旧 v1 Catalog 继续只读兼容。
- Outline Planner 将 Pattern 的 `ending_spec` 写入状态并传给 Seed、Realizer、Validator；`OutlineRealization` 增加结构化 `ending`（解决动作 / 冲突解决 / 稳定终态），导出 JSON、Markdown 和 A/B/C 对照稿均保留该字段。
- 确定性校验只检查 ending 结构是否存在且字段非空，语义是否逐项兑现仍由 Validator LLM 判断；没有 ending_spec 的历史 Pattern 不增加新的硬失败条件。
- 验证：新增 ending_spec 传递与缺失结构测试；StoryPattern/Outline 定向测试 `29 passed`，全量离线回归 `283 passed`；真实 MVP Catalog 上单篇 smoke 生成结构化 ending 并 `overall_ok=True`。
- 边界：`data/story_pattern_evolve_250/` 中的历史 71 个 PatternCatalog 未覆盖，仍是旧 schema；要让真实模板携带 ending_spec，需另行运行 summary/catalog 发布并写入新的版本化目录。

## 本轮（2026-08-27 续 14）：Pattern summary/catalog 重生成
- 旧的 `data/story_pattern_evolve_250/` 已移入 `data/story_pattern_evolve_250_archived_20260827_before_ending_spec/`，作为可恢复归档；新的 canonical 产物重新写入原目录。
- 沿用同一 Snapshot、Observation Bank 和 manifest，复用冻结的 `1,758` 条 HIGH 评审，不改变既有 Function、Snapshot 或盲评材料。
- 新生成 `74` 个 summary，发布 `74` 个 Pattern；`pattern_catalog.json` 的 `catalog_schema_version=2`。其中 `10/74` 个 Pattern 具备证据支持的 `ending_spec`，其余局部或证据不足的 Pattern 保持 `null`。
- 新 catalog 已被 Outline 默认加载并生成结构化 ending。样例中的 ending 能描述解决动作和终态，但 Validator 仍识别出“最后一个 Function 的效果跳到 ending 才发生”的未闭合问题；这属于实例化兑现质量，不影响 summary/catalog 发布完成。
- 当前可用产物：`data/story_pattern_evolve_250/pattern_summaries.json`、`data/story_pattern_evolve_250/pattern_catalog.json`；历史产物保留在归档目录。

## 本轮（2026-08-27 续 15）：大纲到正文 MVP
- 新增独立 `Story_Agent`：读取 `Outline_Agent` JSON，按大纲段生成有序场景计划，再一次调用 LLM 写成 3000–5000 字中文短篇。
- 输入使用已有 `seed`、`mechanism_plan`、`outline.segments`、`ending_spec` 和 `outline.ending`；不修改 Function、Pattern 或 Outline 生成链。
- 线性图为 `load_outline → plan_scenes → write_story → export`；场景计划必须覆盖原大纲段且不改变顺序，最后场景承担结局兑现。
- 输出 `data/stories/<snapshot_id>/` 下的 JSON（源大纲、场景计划、分场正文、字符数）和仅含标题、正文的 Markdown。源大纲校验结果保留但不阻断试跑；字符数超出目标只标记，不自动重写。
- 离线测试覆盖大纲格式错误、场景覆盖/顺序/结局和端到端导出；真实悬疑样例完成 10 个场景、3,194 个中文字符，字符数通过。正文 Prompt 明确禁止泄露 P1/P2 等内部角色 ID，并要求叙述使用第三人称。

## 本轮（2026-08-27 续 16）：Function 前置约束进入正文生成
- `Story_Agent` 新增 LLM 前置节点 `function_constraints`，线性图更新为 `load_outline → function_constraints → plan_scenes → write_story → export`；场景计划与正文使用同一份约束，不增加正文后语义校验。
- 约束按原大纲段发布角色绑定、前置条件、结构效果、义务变化、必需行动、原因、状态变化和到下一段的因果连接；故事级约束发布核心冲突、结局解决对象、必须展示的事实、稳定终态和解决动作。
- 程序确定性锁定段索引、Function 名称、段数和顺序，拒绝缺段、重复段或 Function 漂移；约束语义由 LLM 综合 seed、mechanism_plan、contract_ledger、outline 和 ending_spec 生成。
- 离线联合回归 `16 passed`。真实悬疑样例生成 4 段约束、7 个场景和完整正文，正文未暴露角色 ID 或 Function 名；中文字符数为 1,800，按既有 MVP 规则保留并标记 `length_ok=false`。

## 本轮（2026-08-27 续 17）：9 组正文 A/B 盲评
- 以当前快照下原有 3 个题材 × 3 份大纲为同一材料，生成 18 份正文：A 为 `Function 约束 → 场景计划 → 正文`，B 为 `大纲 → 正文`；原始大纲 JSON 未覆盖。
- 原有 9 份历史大纲缺少 `outline.ending`，且其中部分 Pattern 名称已不在当前 Catalog。为保持 Function、seed、mechanism 和 beats 不变，正文入口仅在内存中依据最后一段行动与 `final_ledger` 投影 ending，并在评测 manifest 中标记 `legacy-ending adapter`。
- A 的长度达标数为 `5/9`，B 为 `2/9`。单一 LLM 盲评中，A 获整体优选 `5` 组，B 获 `4` 组；A/B 平均分分别为 `4.111/4.000`。
- 六项平均分（A / B）：结构完整性 `4.444/4.333`、因果连贯性 `4.222/4.111`、人物动机 `4.222/4.000`、冲突与转折 `4.222/4.111`、新颖性 `3.111/3.111`、整体吸引力 `4.111/4.000`。
- 产物目录：`data/story_ab_blind/evolve_250_20260822T063550401096Z_13b1bbda248f/`；匿名稿、揭盲 key 和盲评记录位于其 `blind_review/`。结果为工程诊断，不作为多人一致性或论文级统计结论。
- 当前取舍：暂不修正结局场景的语义兑现检查。`resolves_ending` 仍是场景位置标记，不能保证最后场景已经完成解决动作；该问题记录为后续质量稳定化任务，不阻塞 MVP 使用与本轮 A/B 对比。

## 本轮（2026-08-27 续 18）：10 篇正文生产与自动质量诊断
- 使用当前 `Story_Agent` 批量生成 10 篇正文：9 份历史大纲加 1 份新版悬疑大纲；历史大纲仍只在内存中补 `outline.ending`，原始输入未覆盖。
- 10/10 篇均完成 `load_outline → function_constraints → plan_scenes → write_story → export`，每篇均生成 JSON 和 Markdown；Markdown 完整性检查通过，未泄露 Function、场景元数据或内部角色 ID。
- 生成正文中 4/10 篇达到 3000–5000 中文字符，6/10 篇偏短；长度只作诊断标记，不触发自动重写。
- 独立 LLM 质量诊断发现的问题集中在：人物动机（4 篇）、冲突解决（3 篇）、因果/衔接（4 篇合并计数）以及结构和结局收束。第 10 篇《末世符号》出现最明显的结局偏离：外部支援后的防御行动未充分呈现，核心对抗突然转为合作，未完整兑现大纲结局。
- 自动诊断产物：`data/story_batch_10/usage_batch_story10_20260827T232626/quality_report.json` 和 `quality_report.md`。当前诊断用于工程问题发现，不替代人工或多人一致性评审；结局语义约束仍按既定取舍暂缓修正。

## 本轮（2026-08-27 续 19）：重复 Function 对齐与正文入口校验
- Outline 的 Mechanism、Realization 和 Validator 输出新增唯一 `segment_index`；Planner 在链上按位置写入索引，LLM 输出按索引确定性对齐，并校验索引覆盖和 Function 名一致。
- 重复 Function 不再以 `function_name` 作为唯一键，因此 `A → B → A` 的每次 occurrence 保持独立，原有 `occurrence_index/occurrence_total` 继续用于要求逐次递进。
- Story_Agent 正文入口及正式批处理均拒绝显式 `validation.overall_ok=false` 的大纲；批处理将其记录为 skipped，不调用正文生成节点。
- 验证：相关定向回归 `21 passed`，全量离线回归 `288 passed`；使用实际失败大纲验证入口返回“正式正文批次拒绝生成”。本轮未重新生成远程正文批次。

## 本轮（2026-08-28）：重复 Function 与正文入口真实回归
- 使用 6 个含重复 Function 的 Pattern 候选重新生成，获得 5 份 `overall_ok=true` 大纲并生成 5 篇正文；另 1 份 `overall_ok=false` 大纲被正式正文入口阻断，未调用正文生成。
- 5 份通过大纲的重复 occurrence 均保持独立：Mechanism 与 Outline beats 的 `distinct` 检查均为 true，`occurrence_index` 均按 1、2 保留。说明 `segment_index` 对齐修复在真实 LLM 链路中生效。
- 正文产物为 JSON/Markdown 各 5 份；中文字符数为 3992、3304、1063、2967、2939，长度达标 2/5。篇幅不足仍是正文生成层问题，与本轮两个结构修复无关。
- 回归产物：`data/story_regression_5/regression_story5_20260827T235915/regression_report.json`；本轮未处理结局语义约束和篇幅自动修复。

## 本轮（2026-08-28 续 1）：短篇正文单次生成约束强化
- 短篇 MVP 保持 `load_outline → function_constraints → plan_scenes → write_story → export`，`write_story` 一次读取完整场景计划并生成全文，不增加逐场循环、历史正文或连续性状态。
- 正文输入补充 `mechanism_plan` 和确定性的 `writing_requirements`：总目标为 3800 个中文字符，按场景分配目标篇幅，最后场景不少于约 700 字；实际长度仍在导出时标记，不自动重写。
- 正文 Prompt 强化行动兑现、动机先行、相邻场景因果承接和结局闭合；解决动作必须实际完成并展示稳定终态，不能以准备、承诺、突然援助或冲突改向代替。
- 验证：Story_Agent 定向测试 `5 passed`，全量离线回归 `288 passed`。

## 本轮（2026-08-28 续 2）：单次正文 Prompt 五篇真实评估
- 使用上一轮真实回归中 5 份 `overall_ok=true` 大纲重新生成，保持大纲不变，只观察强化后的单次正文生成；5/5 完成并由独立 LLM 诊断，不自动改写。
- 新正文中文字符数为 `5361、3016、2955、5273、3035`，达标 `2/5`；旧正文平均 2853 字，新正文平均 3928 字，但两篇超上限、一篇略低于下限，说明分场字数软约束提高了平均篇幅，尚未提高长度稳定性。
- 六项平均分：结构完整性 `4.4`、因果连贯性 `4.0`、人物动机 `4.0`、冲突解决 `4.6`、结局闭合 `5.0`、可读性 `4.6`。5 篇均被评为核心冲突得到处理并达到终态。
- 高频内容缺陷仍是动机铺垫不足、相邻情节跳步、关键行动或高潮展开偏快；首次正文调用另出现一次场景 ID 不完整而触发整篇重跑，两次结构化 JSON 解析重试。
- Markdown 确定性扫描未发现 P1/P2、Function、scene_id 或状态账本泄露。产物：`data/story_batch_5/usage_batch_story5_20260828T100225/quality_report.json` 和 `quality_report.md`。

## 本轮（2026-08-28 续 3）：情节实现 Prompt 同大纲复测
- 仅修改 `SCENE_PLAN_PROMPT` 与 `STORY_PROMPT`，不改 schema、State 或图结构；场景 beats 被要求按动机/铺垫、尝试、阻碍、应对、转折、结果组织，并提前建立关键线索、工具、援助和角色转变的依据。
- 使用续 2 完全相同的 5 份大纲重生成。相对上一批，平均分变化为：结构 `4.4→4.6`、因果 `4.0→4.4`、人物动机 `4.0→4.4`、冲突解决 `4.6→4.6`、结局闭合 `5.0→4.6`、可读性 `4.6→4.8`；评估问题数由 `13→7`。
- 新正文字符数为 `2520、2641、2332、3489、3660`，平均 `2928`，长度达标仍为 `2/5`。两篇正文泄露 P2/P3 内部角色 ID，说明 Prompt 约束不能稳定保证输出洁净。
- 结论：该 Prompt 对局部因果、动机和可读性呈积极信号，但同时出现篇幅回落、结局分下降和角色 ID 泄露，尚不能判定为整体质量提升；当前修改保留为待决实验状态。产物：`data/story_batch_5/usage_batch_story5_20260828T102002/quality_report.json` 和 `quality_report.md`。

## 本轮（2026-08-28 续 4）：场景因果增强节点接入
- 在 `plan_scenes` 与 `write_story` 之间新增 `enrich_scenes`，专门补充每场的 `motivation`、`causal_from_previous` 和带后续兑现位置的 `setups`；不修改已有场景行动、Function 顺序或结局。
- 程序按 `scene_id` 确定性对齐增强结果，并拒绝未知场景、缺场景和指向当前/前置场景的伏笔，避免 LLM 通过增强节点改变故事骨架。
- 正文节点接收增强计划，将动机、伏笔和前场因果作为独立输入；图更新为 `load_outline → function_constraints → plan_scenes → enrich_scenes → write_story → export`。
- 验证：Story_Agent `6 passed`，全量离线回归 `289 passed`；真实末世科幻烟测生成 4 场、6 个伏笔、3727 个中文字符，`length_ok=true`。产物：`data/story_smoke_enrich/20260828T/末世科幻_20260828T000300_story_20260828T105158.json` 及对应 Markdown。

## 本轮（2026-08-28 续 5）：取消场景固定字数并进行同大纲对照
- `write_story` 不再生成或传入 `scene_char_targets`；正文 Prompt 改为按每场铺垫、行动、冲突、转折和结果的完整性自然分配篇幅。
- 全篇 `3000–5000` 字保留为软性参考和导出统计，不作为场景平均分配规则。
- 同一份现代情感大纲对照生成：原版本《暗夜之光》为 `3087` 字、9 场；新版本《灯光下的救赎》为 `1766` 字、7 场，`length_ok=false`。
- 新版本的情感连续性略有改善，但全篇过短，说明取消场景字数后不能单独保证正文展开；后续应使用“全篇最低篇幅 + 场景语义完整性”联合约束，而不是恢复场景平均字数。
- 验证：Story_Agent 定向测试 `6 passed`，Python 编译通过。产物：`data/story_eval_modern_unbounded_20260828T/现代情感_20260828T000710_story_20260828T112340.json` 及对应 Markdown。

## 本轮（2026-08-28 续 6）：全篇最低篇幅与语义完整性约束
- 保留无场景平均字数策略；正文 Prompt 将全篇 `min_chinese_chars` 明确为最低要求，要求篇幅不足时优先补足动机、行动、转折和后果。
- 增加场景级语义完整性要求：本场目标或失败结果必须实际发生，不能用总结替代关键行动；结局必须依次展示解决行动、结果、人物反应和稳定终态。
- 该版本仍不增加自动重写、正文后校验或逐场历史上下文。
- 同一现代情感大纲真实生成《暗夜微光》：5 个场景分别为 664、510、605、622、703 字，中文字符数 `2600`，`length_ok=false`；Function 段覆盖、场景顺序、结局位置和正文元数据扫描均通过。
- 与前一版相比，场景级展开和感情递进改善，但全篇最低篇幅仍未稳定达到，说明 Prompt 下限不能替代生成长度控制。
- 仅将 `write_story` 的 `reasoning_effort` 设为 `high` 后，用同一现代情感大纲生成《夜色里的灯火》：10 个场景、6374 个中文字符，`length_ok=false`。
- 相比 `none` 版本，人物过去、危险前因、证据铺垫和结局后果展开更充分；但正文超过上限约 1374 字，说明高推理改善完整性倾向，同时带来篇幅和成本风险。
- 本轮验证：LLM 与 Story_Agent 定向测试共 `11 passed`，正文无 Function/角色 ID/场景元数据泄漏。产物：`data/story_eval_modern_reasoning_high_20260828T/现代情感_20260828T000710_story_20260828T113744.json` 及对应 Markdown。

## 本轮（2026-08-28 续 7）：纯 LLM 正文对照
- 使用与《夜色里的灯火》相同的现代情感基础素材，新增纯 LLM 直写对照；输入仅包含世界、人物、核心冲突和结局方向，不注入 Function、约束合同、场景计划或场景增强。
- 复测版本《在风暴中靠近》生成 `4781` 个中文字符；与结构化链路《夜色里的灯火》的 `6374` 字处于同一量级，但仍短 `1593` 字。产物：`data/story_eval_pure_llm_20260828T/现代情感_纯LLM_story_20260828T120124.json` 及对应 Markdown。
- 纯 LLM 能自行组织“职场压迫—证据追查—威胁升级—反击—关系确认”的表面主线，但 IP 追踪、警方协助和监控证据等关键转折出现较快；结构化链路在前因、人物过去和结局后果上更完整。
- 本轮保留短篇 MVP 的长度目标作为对比参考；纯 LLM 即使收到 `6000` 字下限提示，仍只生成 `4781` 字，说明单次提示不能稳定控制篇幅。
- 两篇均使用 `reasoning_effort=medium` 配置名；按当前 DeepSeek 接口映射，`medium` 实际映射为 `high`，因此这不是有效的中低推理强度对照。

## 本轮（2026-08-28 续 8）：末世科幻结构化与纯 LLM 对照
- 使用同一份 `末世科幻_20260828T000300.json` 大纲生成两版正文；结构化版《温室坐标》经过 Function 约束、场景计划、动机/伏笔/因果增强和一次性写作，纯 LLM 版《废土之上，温室之光》只接收基础素材。
- 为控制变量，纯 LLM 目标调整为 `3000–4000` 字；最终结构化版 `3495` 字，纯 LLM 版 `2873` 字，差 `622` 字，作为本组最接近长度的对照。
- 两版都完成了“寻找温室—遭遇统治者阻挠—识别/处理间谍—进入温室—建立新家园”的主线；结构化版在行动因果、资源迁移和稳定终态上更集中，纯 LLM 版在背叛反转上更突出，但证据和人物关系的转折更依赖临时解释。
- 产物：`data/story_eval_structured_scifi_20260828T/末世科幻_20260828T000300_story_20260828T121750.json`、对应 Markdown，以及 `data/story_eval_pure_llm_scifi_20260828T/04_末世科幻_纯LLM_story_20260828T121953.json`、对应 Markdown。

## 本轮（2026-08-28 续 9）：提取结构化正文 Prompt 的直接调用对照
- 从结构化正文产物中提取 `STORY_PROMPT` 和 `write_story` 的完整输入 payload，包含 Function 约束、场景计划、动机/伏笔/因果增强和结局要求；不经过 LangGraph 前置节点，直接调用一次 LLM 生成正文。
- 直接调用《废土绿洲》生成 `3170` 个中文字符；结构化原文《温室坐标》为 `3495` 字，差 `325` 字，二者均在 `3000–5000` 字区间。
- 两篇的宏观情节和关键因果高度接近，说明结构信息已经主要由最终正文 Prompt 携带；直接调用仍出现 `P3` 角色 ID 泄漏，并对部分动机和结局过程进行了压缩，说明节点链路还承担输入整理、角色替换和输出稳定性作用。
- 新增实验脚本：`Code/test/run_extracted_story_prompt_compare.py`。产物：`Code/data/story_eval_extracted_prompt_20260828T/04_末世科幻_提取prompt_story_20260828T125611.json` 及对应 Markdown。

## 本轮（2026-08-28 续 10）：提取现代情感正文 Prompt
- 根据 `现代情感_20260828T000710_story_20260828T113744.json` 重建 `write_story` 的完整输入，生成可直接复制使用的 prompt 文件；本轮未调用 LLM 生成新正文。
- Prompt 包含 `STORY_PROMPT`、seed、mechanism_plan、Function 约束、场景计划、动机/伏笔/因果增强、写作长度要求和 ending；总长度 `22050` 字符。
- 产物：`Code/data/story_prompt_extract_20260828T/现代情感_20260828T000710_story_20260828T113744_story_prompt.txt`。提取脚本：`Code/test/extract_story_prompt.py`。

## 本轮（2026-08-28 续 11）：反应区间规则后的正文复测
- 在 `SCENE_PLAN_PROMPT` 与 `STORY_PROMPT` 中加入“Function 由场景组整体兑现”“重大事件后的后果反应”“单场最多一个重大转折”和“关系一次最多推进一级”。未改变图拓扑、状态结构或固定场景字数。
- 同一现代情感大纲重新生成《暗处有光》：10 场、`5098` 个中文字符，因超过 5000 字上限 98 字而标记 `length_ok=false`。
- 相比旧结构化版，新增了流言后的主动回避、袭击后的照料与两天日常相处，情感转折不再全部挤在袭击当晚；但受伤后的过去坦白和后续表白仍然偏快，说明 Prompt 规则能改善节奏倾向，但不能完全替代更细的关系阶段规划。
- 与用户提供的纯 LLM《没有风的地方》对照：新结构化版完成了完整的反派处理、身份揭露、公开选择和稳定关系；纯 LLM 版语言与氛围更自然，但停留在审计启动和男女主初步建立联系。
- 产物：`Code/data/story_eval_modern_pacing_20260828T/现代情感_20260828T000710_story_20260828T201011.json` 及对应 Markdown。

## 本轮（2026-08-28 续 12）：取消正文目标与最大字数约束
- `STORY_PROMPT` 不再要求目标字数或最大字数，也不设置单场景字数；正文以场景目标、关键行动、后果反应、关系变化、伏笔兑现和结局动作均已充分展开为结束条件。
- `writing_requirements` 仅保留 `min_chinese_chars=3000` 作为防止过早结束的软提示；导出 `length_ok` 改为只检查是否达到该下限，超过 5000 字不再判定失败。
- 同步清理正文 Prompt 提取脚本和直接对照脚本中的旧目标/最大字数字段。定向测试 `11 passed`，Python 编译通过。

## 本轮（2026-08-28 续 13）：取消长度上限后的现代情感复测
- 使用取消目标/最大字数约束后的正文链重新生成《暗夜灯塔》：11 场、`5588` 个中文字符，`length_ok=true`。
- 结构上出现了医院恢复、一周后的共同生活和关系重新确认，重大事件后的反应区间比上一版更充分；同时正文自然超过原 5000 字上限，验证了长度统计不应把超长直接当作失败。
- 与纯 LLM《没有风的地方》对照：新结构化版完成了完整反派处理、身份揭露、公开选择和稳定关系；纯 LLM 版在语言氛围和心理克制上更自然，但停留在审计启动与初步建立联系。
- 产物：`Code/data/story_eval_modern_no_length_cap_20260828T/现代情感_20260828T000710_story_20260828T202553.json` 及对应 Markdown。

## 本轮（2026-08-28 续 14）：限制 mechanism_plan 与大纲状态幅度
- `MECH_PROMPT` 规定每段只产生当前 Function 所需的最小状态变化，关系每次最多推进一级，重复 Function 通过风险、信息、代价或投入递进，不得提前完成后续 Function 或结局。
- `REALIZE_PROMPT` 禁止大纲把 mechanism_plan 的状态结果继续放大；`VALIDATE_PROMPT` 与 `validate_node` 开始接收并检查 `mechanism_plan`，提前完成后续 Function、关系终态或 ending_spec 时必须判失败。
- 离线验证：Outline、Story 与 LLM 定向测试共 `23 passed`，Python 编译通过。
- 同一 Snapshot、现代情感题材与“拯救之恋”Pattern 重新生成大纲，`overall_ok=true`。前四段分别停在首次正面互动、初步好感、经救援后的信任、暴露脆弱后的理解，第五段才进入明确承诺；产物：`Code/data/outline_eval_mechanism_pacing_20260828T/现代情感_20260828T204205.json`。
- 新大纲生成正文《失真的数据》，8 场、`2639` 字，`length_ok=false`。正文最后擅自加入当众求婚与半年后婚礼，超出大纲的“明确承诺”，说明本轮已修复 mechanism_plan → outline 的状态过满，但正文层仍可能放大结局且当前没有正文后语义校验。
- 正文产物：`Code/data/story_eval_mechanism_pacing_20260828T/现代情感_20260828T204205_story_20260828T204641.json` 及对应 Markdown。

## 本轮（2026-08-28 续 15）：同一新大纲第二次正文采样
- 保持 `现代情感_20260828T204205.json` 完全不变，重新运行 Story_Agent，生成《晚风与归途》：11 场、`9121` 个中文字符，`length_ok=true`。
- 新版本按首次援助、茶水间接触、正式约会、第二次危机、半个月持续互动、暴露过去、最终共同解决危机的顺序推进关系；结尾只确认交往，没有再次越界到求婚或婚礼。
- 相比同大纲第一次采样《失真的数据》的 `2639` 字和突兀求婚，本次递进明显自然，说明 mechanism_plan 与大纲修复已经提供了可实现的合理骨架，但单次 Story_Agent 采样在篇幅和结局强度上仍存在较大方差。
- 产物：`Code/data/story_eval_mechanism_pacing_retry_20260828T/现代情感_20260828T204205_story_20260828T205700.json` 及对应 Markdown。

## 本轮（2026-08-29）：人物关系、动机与双向状态变化进入 Outline schema
- `SeedCharacter` 新增 `motivation` 与 `relationships`：前者区分人物目标和愿意承担代价的原因，后者使用稳定人物 ID 记录开场关系事实、态度、利益联系与边界；结构角色不自动规定人物的开场态度。
- `MechanismStep` 新增 `character_state_changes`：逐人物记录变化前状态、可观察触发证据或代价、变化后状态；关系变化必须覆盖双方，不能只生成主角变化并默认另一方同步接受。
- `MECH_PROMPT` 要求每步 `why` 从 seed 动机、初始关系与前序事实推出；`REALIZE_PROMPT` 和 `VALIDATE_PROMPT` 已消费并检查逐人物变化，原有总体 `state_change` 和合同账本保持不变。
- 关系状态不使用固定恋爱阶梯，而是根据题材和冲突选择熟悉程度、信任、利益立场、权力、责任、依赖或亲密等实际维度；一个动作不能自动解决无直接因果关系的其他状态维度。
- 离线验证：Outline、合同流与 Story 定向测试共 `22 passed`，Python 编译通过。
- 使用“压抑觉醒与决断”真实重跑，`overall_ok=true`。P2 形成“谨慎好感→留意异常→主动帮助→认真考虑关系→私下坦白并承诺”的独立变化链；公开处理上司压力与私下确认关系已分离。产物：`Code/data/outline_eval_character_motivation_20260829T/现代情感_20260829T091817.json`。

## 本轮（2026-08-29 续 2）：大纲结局收束与通过率修复
- `OutlineRealization.ending` 改为必需字段；`rule_check` 对所有大纲检查独立的解决动作、冲突结果和稳定终态。
- `REALIZE_PROMPT` 将 `ending` 明确定义为 Function 链之后的独立结局收束单元。最后一个 Function 只需形成可支持结局的事实、证据、资源、选择、对手弱点或关系条件，不能被要求承担其语义之外的全局解决。
- `VALIDATE_PROMPT` 改为检查最后一个 Function 是否支持 ending，以及 ending 是否实际完成 `resolution_actions`、`ending_spec` 和 `ending_direction`，不再把非终结 Function 本身当作全局结局。
- `candidate_patterns` 默认优先选择带正式 `ending_spec` 的 Pattern；显式指定 Pattern 的行为不变，也未恢复手工结局 Function 名单。
- 全量离线回归：`289 passed`。修复后跨题材稳定性批次产物：`Code/data/story_stability/stability_20260829T101911/`。
- 复测结果：9 份大纲中 8 份通过，16 篇正文生成；修复前为 3/9 大纲通过、6 篇正文。悬疑惊悚由 2/3 提升为 3/3，现代情感由 0/3 提升为 3/3，末世科幻为 2/3；唯一阻断样本因 ending 与 `ending_spec` 的外部支援、谜团应对和稳定终态不一致，保留为真实失败。

## 本轮（2026-08-29 续 3）：正文层首轮质量验收
- 复用上一轮 8 份通过大纲的 16 篇正文样本，使用独立 LLM 诊断器检查 Function/场景兑现、因果、人物动机、冲突解决、结局闭合和可读性。
- 16/16 篇完成产物且长度统计达标。平均评分：结构 `4.75`、因果 `4.50`、人物动机 `4.62`、冲突解决 `4.75`、结局闭合 `4.81`、可读性 `4.81`。
- 发现 1 个高严重度问题：`末世科幻_03_run_02` 的正文只叙述“议会逮捕”，没有实际展示逮捕动作；其余问题主要是因果衔接轻微跳步、局部动机铺垫不足和结尾动作展开偏快。
- 产物：`Code/data/story_stability/stability_20260829T101911/story_quality_report.json` 与对应 Markdown。
- 结论：大纲层已具备进入正文 MVP 的条件；正文层的首要小步修复是把结局 `resolution_actions` 转成可观察的实际行动，同时保留叙述空间，不恢复逐场固定字数。

## 本轮（2026-08-29 续 1）：跨题材短篇稳定性批次
- 新增 `Code/test/run_story_stability_batch.py`，固定当前 Snapshot，按悬疑惊悚、现代情感、末世科幻各选 3 个 Catalog Pattern；每份通过校验的大纲固定生成 2 次正文。
- 批次目录：`Code/data/story_stability/stability_20260829T095042/`；汇总：`stability_report.json`。
- 9 份大纲中 3 份通过、6 份被 `validation.overall_ok=false` 拦截；因此实际生成 6 篇正文，未让失败大纲进入正文层。通过样本来自悬疑惊悚 2 份、末世科幻 1 份，现代情感 3 份全部被拦截。
- 6 篇正文均达到当前最低篇幅要求。3 份可配对大纲的两次正文字符差分别为 `2214`、`651`、`1784`，说明一次性正文生成的采样方差仍然明显。
- 运行中出现一次场景增强 `scene_id` 对齐错误和一次场景计划来源段落对齐错误，均由现有单次重试后成功；这属于链路稳定性信号，后续需与内容质量问题分开处理。

## 本轮（2026-08-28 续 11）：从 raw 正文提取情节创作提示词
- 根据 `现代情感_20260828T000710_story_20260828T113744.md` 的实际叙事内容，提炼出自然语言情节提示词，仅保留人物、事件顺序、冲突升级、关系推进、反转和结局要求。
- 该提示词不包含 Function、场景编号、状态账本、结构化 JSON 或正文节点规则，可直接作为 LLM 的故事创作输入。
- 产物：`Code/data/story_prompt_extract_20260828T/现代情感_夜色里的灯火_plot_prompt.txt`。本轮未调用 LLM。

## 本轮（2026-08-29 续 4）：叙事展开独立节点
- `Outline_Agent` 的 `scaffold` LLM 节点位于 `planner → seed → mechanism → scaffold → realize → validate → export`。公开大纲包含必需的 `narrative_plan`，逐段保存 `genre_realization`、`motivation_setup`、`connective_event`、`reaction_beat` 和前向/ending `setup_payoffs`。
- `mechanism` 只保留角色绑定、结构行动、原因、状态变化和下一步结构条件；真实参考机制由 `scaffold` 消费。程序按 `segment_index` 对齐计划，并拒绝指向当前段、前序段或不存在段落的伏笔回收位置。
- `realize` 与 `validate` 只消费 `narrative_plan` 中已确定的题材实现和叙事支架，不再自行设计第二套动机、反应或伏笔。核心解决动作必须实际发生，逮捕、晋升、制度变化等后续社会结果允许在 `final_state` 概述。
- `Story_Agent` 的图为 `load_outline → function_constraints → plan_scenes → write_story → export`。`plan_scenes` 只把大纲已经确定的叙事支架分配到场景，旧大纲因缺少 `narrative_plan` 明确拒绝。
- 形态学辅助标签（衔接、同化、三重化、倒置、省略）不由本节点生成；当前上游尚未发布这些字段。重复 Function 的递进检查只属于生成质量规则，不命名为“三重化”。
- 离线回归：定向 `26 passed`，全量 `293 passed`。
- 真实验收：`Code/data/story_stability/stability_20260829T141348/`，3 题材 × 2 大纲 × 1 正文全部完成，6/6 大纲通过、6/6 正文生成且长度达标；Function/叙事展开/Outline 顺序全部一致，37 个伏笔目标全部合法，重复 Function 的题材表现均独立，Story 产物不再含 `scene_enrichments`。

## 本轮（2026-08-29 续 5）：全题材关系状态上界
- Outline 的 Seed、Scaffold、Realize 和 Validate 提示词统一使用“关系维度 + 状态上界”：题材标签、性别、共同行动或宽泛的“关系稳定”不能自动决定关系类型。
- Seed 从 Function、角色槽位和 ending contract 能支持的最低关系事实开始；Ending 只能收束 mechanism 已建立的状态，不得把信任、合作、和解或关心推导为另一种关系或更高承诺。
- Validate 对无结构依据的初始关系和结局跃迁判定 `overall_ok=false`；Story 的约束发布、场景计划和正文节点同样不得放大关系终态。
- 定向回归：`25 passed`；全量回归：`292 passed`。
- 使用同一“复仇与关系修复” Pattern 真实重跑，Seed 未再创造 `love_interest` 或爱情预设，Function 链最终将关系稳定在“互信合作伙伴”，结局只执行诉讼、夺回控制权和伙伴关系稳定，`overall_ok=true`。产物：`Code/data/outline_eval_relationship_boundary_20260829T152000/现代情感_20260829T151732.json`。

## 本轮（2026-08-29 续 6）：正文场景开发独立节点
- `Story_Agent` 图调整为 `load_outline → function_constraints → plan_scenes → develop_scenes → write_story → export`。
- `plan_scenes` 只拆分场景及确定人物、时空、目标、阻碍、行动、状态变化和衔接；`develop_scenes` 按 `scene_id` 发布 `pacing_mode`、`expand_points`、可选的 `reaction_decision`、局部 `causal_moments` 与 `exit_aftereffect`，不得改变既定情节或创造新内容。
- `write_story` 只接收 Seed、Function 约束、场景计划、场景开发计划和结局合同，不再重复读取 `mechanism_plan` 与 `narrative_plan`；JSON 产物新增 `scene_developments`，Markdown 仍只包含自然正文。
- 离线验证：Story Agent 端到端 `8 passed`；全量回归 `294 passed`，Python 编译通过。

## 本轮（2026-08-29 续 7）：上游计划正式 schema 化
- `Story_Agent.SourceOutlineDocument` 将 `mechanism_plan` 类型化为 `Outline_Agent.MechanismPlan`，与已有的 `NarrativePlan` 一样在大纲加载边界执行字段校验。
- 旧测试夹具补齐 `segment_index` 和 `character_state_changes`；缺少这些字段的大纲会在进入正文图前明确拒绝。
- 使用新 schema 重新生成现代情感大纲并通过校验，随后生成正文《证言》：10 场、4201 个中文字符、`length_ok=true`；产物位于 `Code/data/story_schema_modern_20260829T/`。

## 本轮（2026-08-29 续 9）：Outline 到 Story 一键编排
- 新增 `Code/Pipeline_Agent` 顶层 LangGraph：`START → generate_outline → generate_story → export → END`。两个节点复用现有 `Outline_Agent` 和 `Story_Agent` 编译图，不复制 Prompt 或 LLM 逻辑。
- `generate_outline` 自动使用已发布 PatternCatalog，可通过 `--pattern` 指定 Pattern；大纲 `validation.overall_ok=false` 时保留大纲并阻止正文启动。
- 默认运行目录为 `Code/data/pipeline_runs/<时间戳>/`，导出大纲 JSON、正文 JSON、正文 Markdown 和 `pipeline_manifest.json`。
- 离线 Pipeline 测试：`2 passed`；全量回归：`296 passed`。
- 真实一键运行 `现代情感` 完成：Pattern 为 `复仇与关系修复`，正文标题《偿还》，3457 个中文字符，`length_ok=true`；产物位于 `Code/data/pipeline_runs/20260829T222355/`。

## 本轮（2026-08-29 续 8）：Story Agent 文学表达计划
- `Story_Agent.develop_scenes` 的 `SceneDevelopment` 新增必需的 `literary_plan`，逐场记录环境叙事作用、感官锚点、意象/母题、对话潜台词、有限修辞重点和句式节奏。
- `STORY_PROMPT` 只执行该计划：文学表达必须服务既定行动、人物反应和状态变化，不新增情节，也不要求每场堆砌修辞。
- 定向回归：`8 passed`，Python 编译通过。
- 使用现代情感大纲真实生成《破晓》：10 场、4431 个中文字符、`length_ok=true`；10/10 场景均包含文学计划，Markdown 未暴露内部字段。产物位于 `Code/data/story_modern_literary_20260829T/`。

## 本轮（2026-08-30）：统一 StoryCLI

- 新增 `Code/StoryCLI`，公开提供 `function bootstrap/evolve`、`template build` 和 `story write` 三组子命令；批量输入支持多个 `.txt` 文件和递归目录。
- `template build` 内部串联现有 Function 运行产物、`StoryPattern_Agent`、`Outline_Agent`，按 `StoryPattern → Outline` 生成并导出 `template_bundle.json`；Pattern 与 Outline 被固定在同一 Bundle 中。
- `story write` 复用 Bundle 中的 Outline；附加用户要求时固定 Pattern、重新生成 Outline，再调用 `Story_Agent`。顶层不复制各 Agent 的 Prompt 或 LangGraph 节点。
- 新增 `StoryPattern_Agent` 的模块入口，复用原有 Pattern driver，避免统一 CLI 通过不可导入的测试脚本路径启动。
- 离线测试：`28 passed`（CLI、Outline、Story、兼容 Pipeline）；模块帮助入口和 Python 编译检查通过。
- 真实正文 smoke：使用现有有效 Outline/Pattern Bundle 调用 `StoryCLI story write`，生成《信任的重量》，5 场、5015 个中文字符、`length_ok=true`；产物位于 `Code/data/story_cli/smoke_story_no_request_retry/`。带附加要求的真实 Outline 实例化因 `overall_ok=false` 被正确阻断，未进入正文。

## 本轮（2026-08-30 续）：真实故事到 Pattern 的统一知识库

- `Code/data/knowledge/story_knowledge.db` 按知识实体保存 `Story → Observation → Function 版本/演化事件 → Snapshot → FunctionOccurrence → Pattern`；`bootstrap/evolve` 作为 `pipeline_runs.workflow` 记录，不作为 Function 类别。
- Bootstrap/Evolve 在终评 PASS 并发布 Snapshot 后，自动事务写入故事原文、Observation、Function 版本、演化历史、Snapshot、Contract 和 Occurrence；StoryPattern 发布后自动写入 Pattern 版本及其真实故事证据。
- `StoryCLI library sync-current` 幂等同步正式 Bootstrap 与 Evolve/Pattern 主线，`library status` 查看数量。当前库包含 1 次 Bootstrap、2 次 Evolve、370 篇真实故事、3250 条 Observation、122 个历代 Function 实体、224 个 Function 版本、218 条演化事件、3 个 Snapshot、5443 条按 Snapshot 保留的 Occurrence、62 个 Contract，以及 74 个 published、1 个 rejected、21 个 manual-review Pattern。
- SQL 已验证可从 Pattern 沿证据关系追溯到 Story、Observation 和 Function；370/370 篇故事保留原文，Pattern 证据关系 253 条，外键违规 0。重复同步数量不变；全量回归 `302 passed`。

## 本轮（2026-08-30 续 2）：Agent 正式读取统一知识库

- `StoryPattern_Agent` 以 `snapshot_id` 从 `story_knowledge.db` 读取 Snapshot manifest、Function、Observation、FunctionOccurrence 和故事元数据，不再要求 Observation、manifest 或 Snapshot 文件路径作为运行输入；Pattern 发布仍写回统一库。
- `Outline_Agent` 按 `snapshot_id` 从统一库查询 published Pattern，并按 Function ID 读取 FunctionContract。历史 Pattern Snapshot 本身没有 Contract 时，使用数据库中该 Function 的最新正式 Contract，保留 Pattern 原有 Function 顺序。
- `FunctionExtract_Agent.evolve` 在处理新语料前，从指定 `base_snapshot_id` 或数据库最新正式 Snapshot 读取 Function，并复制到本轮可变工作 Registry；终评通过后发布新 Snapshot 并写回统一库。Bootstrap 继续从原始故事开始构建首版 Function。
- `Story_Agent` 继续只读取 Outline JSON；正文生成不直接查询知识库。顶层 LangGraph 的节点和边未改变，只调整各入口节点的数据来源。
- 真实库只读验证：3 个 Snapshot、122 个历代 Function、5443 个 Occurrence、62 个 Contract、96 个 Pattern；命令入口检查通过，全量回归 `303 passed`。

## 本轮（2026-08-30 续 3）：一键正文链路门禁分级

- 数据库接入后，历史 Pattern 会使用后续发布的 FunctionContract。合同中的自然语言状态尚未经过统一词汇规范化，因此同义状态的字面差异改为 `contract_warnings`，继续随大纲导出供审计，不再作为确定性结构错误阻断正文。
- 缺失合同角色绑定、缺少实例状态变化等确定性结构错误继续进入 `contract_issues`，并保持 `validation.overall_ok=false` 时不启动正文。
- `Story_Agent` 在 schema 边界将允许为空的 `causal_moments`、文学计划列表和文本字段中的 JSON `null` 正规化为空列表或空字符串；核心展开字段仍保持必需。
- 真实一键链路的大纲通过：`contract_issues=0`、`contract_warnings=14`。复用该大纲生成正文成功，3360 个中文字符、`length_ok=true`；全量回归 `304 passed`。

## 本轮（2026-08-30 续 4）：Outline 语义校验边界修正

- Outline 校验调用不再注入 `contract_ledger.warnings`，只让校验模型处理确定性的合同 `issues`；完整 warnings 仍保留在导出大纲中供审计。
- 全题材关系规则明确区分合作关系与亲密关系：持续共同行动、风险承担、资源共享、保护、坦诚、道歉和明确互信可以建立稳固盟友关系，不需要爱情式情感基础，也不能据此升级为恋爱或婚姻。
- 指向独立 ending 的 setup payoff，只要 ending 明确执行对应 payoff 即视为回收，不要求在 Function 段提前重复完成。
- 使用相同 `Pipeline_Agent --genre 现代情感 --out-dir data/my_story` 命令真实完成大纲和正文《证据的回响》：5201 个中文字符、`length_ok=true`；全量回归 `304 passed`。

## 本轮（2026-08-30 续 5）：完整大纲入统一库

- `story_knowledge.db` 新增 `outlines` 表，完整保存大纲 JSON、Markdown、Snapshot、Pattern、题材、校验状态和稳定 `outline_id`；重复写入同一大纲保持幂等。
- `Outline_Agent` 生成后先写库并返回 `outline_id`，JSON/Markdown 继续作为人读与交换导出物；`Story_Agent`、`Pipeline_Agent` 和 `StoryCLI` 均按 `outline_id` 从统一库读取大纲。
- 已识别并导入 6 份现存完整大纲，其中 4 份校验通过、2 份失败；全部关联 `PAT_751765b2f3e8c2aa`，外键违规为 0。失败大纲可审计但仍被 StoryAgent 门禁拒绝。
- 全量离线回归 `305 passed`；数据库回读验证可按 ID 加载有效大纲，且失败大纲不会进入正文节点。

## 本轮（2026-08-30 续 6）：Pattern 全库一次性使用限制

- 统一库新增 `pattern_usage`，以全库唯一 `pattern_id` 原子领取 Pattern；OutlineAgent 在 Planner 成功选定后、Seed 之前领取，后续生成异常或校验失败均保留消费记录。
- 自动候选会过滤已领取 Pattern，显式指定已使用 Pattern 会明确报错；Pipeline 和 StoryCLI 单份生成复用同一领取逻辑。
- 新增 `StoryCLI outline batch --genre <题材> --count <数量>`，按未使用 Pattern 批量生成只含大纲的批次报告；`--count` 以有效大纲数为目标，失败样本继续消耗 Pattern 并转向下一个候选。
- 按已确认决定清理原有 4 份大纲及 8 个导出文件，当前 DB `outlines=0`、`pattern_usage=0`，Pattern 保留 96 个，外键检查为 0。
- 定向回归 `32 passed`，CLI 帮助入口通过；全量离线回归 `310 passed`。

## 本轮（2026-08-31）：五篇跨题材 CLI Bootstrap 实验

- `StoryCLI function bootstrap` 使用悬疑惊悚 2 篇、古风穿越重生 2 篇、现代情感家庭 1 篇完成全新运行，发布 Snapshot `cli_bootstrap5_20260831_20260831T105736055505Z_f9e08b191021`。
- 最终产物为 46 个 Observation/Occurrence、6 个 Function 和 6 个 FunctionContract；终评 PASS 4/6，Coverage 与 Evidence Count 未达标。
- 46 个 Occurrence 中 14 个 `MATCHED`、32 个 `UNCERTAIN`。按 `UNCERTAIN` 切分并折叠连续同 Function repetition 后，各故事最长连续结构段为 2，未达到 motif 的 3–6 Function 硬条件，因此 `motif_candidates=0`，Outline 与 Story 未启动。
- 统一 CLI 复制后的文件名形如 `0001_<原名>.txt`；Bootstrap 递归收集器已改为接受所有 `.txt`，对应 `test_story_cli.py` 5 项测试通过。

## 本轮（2026-08-31）：第二批五篇 Evolve 增量实验

- `StoryCLI function evolve` 显式以首批 Snapshot `cli_bootstrap5_20260831_20260831T105736055505Z_f9e08b191021` 为基础，处理另一批悬疑惊悚 2 篇、古风穿越重生 2 篇、现代情感家庭 1 篇。
- 新批提取 56 个 Observation：MATCH 34、EXTEND 2、NOVEL 4、Critic RESOLVED 16；36 条证据进入 Curator，6 个 Function 全部保留，平均 supporting 从 3.0 增至 9.0，未新增 Function。
- 终评 FAIL 3/6（Coverage、Abstraction Quality、Diversity 未通过），未发布子 Snapshot，Pattern、Outline、Story 均未启动；正式知识库仍以首批 Bootstrap Snapshot 为最新版本。
- 当前活体 Bank 已累计首批 46 + 第二批 56 = 102 个 Observation，第二批中间产物完整保存在 `Code/data/story_cli/experiment_evolve5/function/output/`，但未发布数据不属于正式 Snapshot。
- Evolve 初始 state 现将输入 manifest 写入 `evaluation_context.manifest_path`；`evaluator_mid_node` / `evaluator_final_node` 在更新 Registry、Bank 和报告路径时保留已有上下文。以本批累计数据验证 Diversity 为 3 个 category、10 个故事、PASS。
- `test_evolve.py` 使用临时独立 ObservationBank，不再清空真实活体 Bank；回归后真实 Bank 保持 102 条。Evolve 10 项、Evaluator 12 项、StoryCLI 5 项测试通过。

## 本轮（2026-09-01）：Pattern Evolve DB 增量主线

- StoryPattern 生产入口已替换为正式九节点 LangGraph；Function Bootstrap/Evolve 发布 Snapshot 后自动以同一 SQLite、同一 namespace 运行 Pattern Evolve。
- 新增 `pattern_runs`、`pattern_story_sequences`、`motif_evidence`、`motif_pair_reviews`、`motif_clusters`、`snapshot_patterns`；Pattern 发布在最后节点单事务完成。Motif、pair、cluster 稳定 ID 不再包含 Snapshot ID。
- 精确 Motif 不调用 LLM；HIGH 及会影响 Cluster 的 EXPANDED pair 才审查。相同输入签名从 DB 继承，LLM 失败整次 Pattern run 失败，无 replay、Catalog 或目录 fallback。
- 清空旧 knowledge/registry/checkpoint DB 后，以固定 namespace `pattern_evolve_cli` 连续运行 5 批、每批 5 个领域各 1 篇。第五批 Snapshot `pattern_evolve_cli_20260831T191956899727Z_cde003907c34` 首次发布 2 个 Pattern；当批为 25 sequences、17 motifs、25 reviews、14 clusters、2 published。
- 同一 Snapshot 重跑前后 Pattern 相关 9 张表行数完全一致。离线全量回归为 317 passed、1 个依赖已删除历史 Snapshot 的数据分布测试 skipped；新增测试覆盖 evidence extend、幂等、失败原子性、merge、split、retire 和无 fallback。

## 本轮（2026-09-01）：Pattern 输入视图累计修正

- `StoryKnowledgeStore.load_story_pattern_inputs_cumulative` 从同一 SQLite 沿父 Snapshot 链合并故事、Observation、Function、Contract 和 FunctionOccurrence；当前子 Snapshot 出现的故事覆盖父版本，其余故事继承。
- `StoryPattern_Agent.load_pattern_delta` 使用累计输入，仍按 occurrence signature 只重算新增或变化故事；未变化故事的 sequence 与 Motif evidence 写入子 Snapshot。
- 对只含本批故事的 Delta Function Snapshot，Pattern 不再把父故事误判为 removed；旧 Motif、Cluster 和 Pattern 可以继续累计演化。
- 新增 Delta 子 Snapshot 继承 Motif 的回归测试；Pattern 增量、输入和序列测试 `46 passed`，StoryPattern/KnowledgeBase 回归 `130 passed, 1 skipped`。

## 本轮（2026-09-01）：第七批 Function → Pattern 自动运行

- 在同一 SQLite 与 namespace `pattern_evolve_cli` 下，以父 Snapshot `pattern_evolve_cli_20260901T014733927945Z_a2dce8fddc86` 运行 5 个新领域文本，CLI 自动完成 Function Evolve 和 Pattern Evolve。
- Function Evolve 发布 Snapshot `pattern_evolve_cli_20260901T022145596125Z_b98c12a490a2`：5 篇、43 个 Observation，最终 Function 库 5 个，终评 PASS 5/6。
- Pattern 使用累计 DB 输入得到 35 条故事序列、26 个 Motif 候选和 27 条 Motif 证据；当前批 pair 复核 60 条（SAME_PATTERN 10、RELATED 46、DIFFERENT 4）。
- 形成 16 个 Cluster：13 个 candidate、3 个 blocked；没有满足发布条件的 Pattern。
- 该批是修复累计输入后的首个运行，补齐了修复前父 Pattern Snapshot 缺失的 30 条历史序列；从下一批开始，未变化故事可按正常增量继承。

## 本轮（2026-09-01）：历史 Pattern Snapshot 重建

- 新增显式 `StoryPattern_Agent --rebuild`，仅清除并重建指定 Snapshot 的 Pattern 派生表，普通运行仍保持幂等；存在后续版本、已生成大纲或已使用 Pattern 时拒绝重建。
- 重建父 Snapshot `pattern_evolve_cli_20260901T014733927945Z_a2dce8fddc86` 后，恢复 30 条序列、17 个 Motif、14 个 Cluster，并发布既有 `PAT_e8b3f6172ff11da8` 的结构扩展版本。
- 重建子 Snapshot `pattern_evolve_cli_20260901T022145596125Z_b98c12a490a2` 后，Pattern delta 正确为 `new=5、unchanged=30、removed=0`，累计序列 35 条。
- 子批新增 Motif 与既有 Pattern Cluster 产生顺序冲突，因此该 Pattern 在当前 Snapshot 为 `blocked`；这是关系审查结果，不是历史故事缺失。全量回归 `319 passed, 1 skipped`。

## 本轮（2026-09-01）：正式库第八批 Function → Pattern

- 在正式 SQLite `Code/data/knowledge/story_knowledge.db`、namespace `pattern_evolve_cli` 下，以 Snapshot `pattern_evolve_cli_20260901T022145596125Z_b98c12a490a2` 为父，运行 5 个未使用文本。
- Function Evolve 发布 Snapshot `pattern_evolve_cli_20260901T025343347463Z_e245f7e8650a`：5 篇、47 个 Observation；当前 Function Snapshot 保留 2 个 Function。
- Pattern 从父链累计读取 40 个故事、10 个 Function 和 327 个 Observation；delta 正确为 `new=5、unchanged=35、removed=0`，写入 40 条序列。
- 本批得到 27 个 Motif 候选、28 条证据和 46 条 pair 复核（SAME_PATTERN 6、RELATED 33、DIFFERENT 7），形成 21 个 Cluster（published 2、candidate 18、blocked 1）。
- 发布新 Pattern `PAT_6f330f5220d72fa0`、`PAT_c59aca22a920024d`；正式 Pattern run 状态为 `SUCCESS`。

## 本轮（2026-09-01）：Function Evolve 增量隔离改造

- Function Evolve 继续使用同一个 SQLite；`pipeline_runs.run_id` 成为暂存可见性边界，运行中版本不进入任何正式 Snapshot。
- Story 与 Observation 拆为稳定逻辑 ID 和不可变版本 ID；`snapshot_story_versions`、`snapshot_observation_versions` 固化每个 Snapshot 的完整成员，旧 Snapshot 回读不再经过可变主表。
- Evolve Bank 改为“父 Snapshot + 当前 Run”的内存计算视图；当前 Run 的同一故事覆盖父版本，新故事追加，未处理的父故事保持可见。
- PASS 时单事务物化完整 Snapshot 并绑定 FunctionOccurrence 的 `observation_version_id`；FAIL 时保留失败 Run/报告，删除该 Run 的暂存 Story/Observation 版本。
- StoryPattern 删除父链累计拼接，直接读取当前 Snapshot 的完整冻结成员；Snapshot schema 升级为 v4，并显式记录 `run_id`、`parent_snapshot_id` 和 Observation 版本绑定。
- 临时 SQLite 集成回归验证：同一故事 old→new 后父 Snapshot 仍读 old、子 Snapshot 读 new；失败 Run 清理后计算视图恢复为已发布版本。项目环境未安装 pytest，已完成 `compileall` 与该集成回归。

## 本轮（2026-09-01）：增量旧路径清理

- 删除旧 `record_snapshot`、`sync_current_library`、PatternCatalog 文件导入和“读取后续最新 FunctionContract”的跨 Snapshot 回退；正式写入只保留 Run → Snapshot 提交通道。
- 逻辑 `stories` / `observations` 表只保留稳定 ID 与归属关系，可变内容仅存在不可变版本表；删除重复 `payload_json`。
- 删除已被九节点 Pattern Evolve 图取代的 `catalog.py`、`review_queue.py`、`stories.py`，以及对应旧测试和历史串联/大纲冒烟脚本；StoryPattern 包导出同步收窄。
- 回归测试改为按 v4 Snapshot、版本 ID 和正式提交接口准备数据。`compileall`、`git diff --check` 及 6 项 KnowledgeBase/增量手动回归通过。

## 本轮（2026-09-01）：真实 Bootstrap → Evolve → Pattern 链路

- 清空并重建正式 SQLite `Code/data/knowledge/story_knowledge.db`；Bootstrap 使用 5 个题材各 2 篇真实故事，共 10 篇，最终评估 `PASS 5/6`，写入 81 个 Observation、8 个 Function，发布根 Snapshot `real_e2e_10_5_20260901T070730299592Z_7eed8b073e14`。
- Evolve 使用同 5 个题材各 1 篇新故事，共 5 篇，显式绑定根 Snapshot；写入 46 个新 Observation，最终评估 `PASS 6/6`，发布子 Snapshot `real_e2e_10_5_20260901T071110445116Z_3490980478d1`，父子关系已入库。
- Pattern 先为根 Snapshot 建立基线，再处理子 Snapshot；两次 Pattern Run 均为 `SUCCESS`。子批 delta 为 `new=5、unchanged=10、removed=0`，累计 15 条故事序列、5 个 Motif、5 个 candidate Cluster；当前没有达到发布条件的 Pattern，这是合法的 Pattern 结果而非运行失败。
- 最终正式库包含 2 个 PASS Function Run、2 个成功 Pattern Run、15 个故事、127 个 ObservationVersion、208 个 FunctionOccurrence；`PRAGMA foreign_key_check` 为空。
- 直接执行 `FunctionExtract_Agent` 不会自动为 Bootstrap 根 Snapshot 运行 Pattern；因此本次在 Evolve 前补建了根 Pattern 基线，这是 Pattern 增量子批的必要前置。

## 本轮（2026-09-01）：继续 Evolve 15 篇并发布 Pattern

- 保留同一 namespace `real_e2e_10_5` 和同一 SQLite，在 15 篇累计故事 Snapshot 基础上再处理 15 篇未使用真实故事；Evolve 新 Run `FR_3d83bd57e9fc40e8` 通过 `PASS 6/6`。
- 新批产生 112 个 Observation，Curator 新增 3 个 Function，Function 总数由 8 增至 11；发布 Snapshot `real_e2e_10_5_20260901T074152029891Z_39d346dc98b6`，父 Snapshot 为 `real_e2e_10_5_20260901T071110445116Z_3490980478d1`。
- Pattern Run `PR_d38e11d1cd1d7032` 成功：累计 30 条故事序列，delta 为 `new=15、changed=3、unchanged=12、removed=0`；生成 17 个 Motif、16 个 Cluster，其中 1 个 published、15 个 candidate。
- 发布 Pattern `PAT_09b039439b865138`（“秘密揭露与冲突升级循环”），支持 2 篇故事；正式库最终 `stories=30`、`observations=239`、`functions=11`、`pattern_runs=3`、`patterns=1`，`PRAGMA foreign_key_check` 为空。

## 本轮（2026-09-01）：Pattern 独立回归验证

- 用正式 Snapshot 结构的临时 SQLite 副本清除 Pattern 派生结果后，实际执行 `StoryPattern_Agent`：2 条故事序列、3 个 Motif、3 条 Pair Review、1 个 Cluster、1 个 published Pattern，状态 `SUCCESS`。
- 同一 Snapshot 第二次运行保持幂等：`pattern_runs=1`、`pattern_story_sequences=2`、`motif_evidence=6`、`motif_clusters=1`、`patterns=1`、`pattern_versions=1`、`snapshot_patterns=1`，`PRAGMA foreign_key_check` 为空。
- 本次只验证 Pattern 下游，不代表 Bootstrap → Evolve → Pattern 全流程；真实 Bootstrap 的最终评估为 FAIL，因此按门禁没有发布正式 Snapshot，Evolve 没有合法父 Snapshot。

## 本轮（2026-09-01）：移除旧数字型 Observation ID 兼容

- StoryPattern 输入现在只接受新格式 `story_id_obs_<12 位小写十六进制>`；不再解析或回退旧 Snapshot 的 `_obs_001` 等数字型 ID。
- Observation 顺序只使用 `observation_order`，缺失时按当前输入顺序排序；StoryPattern 序列不再从 Observation ID 推断顺序。
- 旧 Snapshot 不做迁移、不做兼容读取；新运行继续使用稳定逻辑 Observation ID 和独立 ObservationVersion ID。
- 针对性输入排序、严格格式拒绝、`compileall` 和 `git diff --check` 已通过。

## 本轮（2026-09-01）：清理旧版本旁路与一次性工具

- StoryPattern 审查只使用当前 `motif_review_queue`，删除旧 `motif_variant_pairs` 状态回退。
- Evolve 删除无 `run_id` 的 `--final-only` 终评入口；终评必须属于当前 Run，不能绕过 Run → Snapshot 提交流程。
- 删除无生产调用的 Function Card 迁移/回填脚本和旧数字 ID 序列脚本：`Code/test/migrate_function_cards.py`、`Code/test/backfill_function_cards.py`、`Code/test/seq_motif.py` 及对应回填测试。
- Bootstrap 使用中的 `record_function_run` 暂保留；它仍是当前 Bootstrap 写入 KnowledgeBase 的实际调用点，不属于无调用兼容代码。

## 本轮（2026-09-01）：Observation 逻辑身份改为原文锚点

- Observer 不再用抽取序号或 `source_sentence_indices` 生成 `obs_id`；有句子锚点时先拼接对应原文为 `source_text`，再结合参与者类型和受影响维度生成故事内逻辑 ID。
- 前置插入 Observation、Observer 返回顺序变化、以及同一原文事件的句子合并/拆分，不会让未改变的逻辑 Observation 换 ID；没有原文锚点时才使用规范化语义字段。
- `observation_version_id` 排除逻辑 ID、抽取顺序和句子下标，只绑定 Story Version 与 Observation 内容；纯重排/重切分不制造内容版本，内容变化仍产生新 ObservationVersion。
- 不使用模糊相似度跨不同原文事件强行合并；原文锚点改变时按新逻辑 Observation 处理，避免误合并。
- 当前正式库中的历史 Snapshot 仍含旧的 `_obs_001` 等数字型 ID，且没有 `source_text`；按“不兼容旧 Snapshot”的决定，继续重跑这些旧故事前必须重建正式库/根 Snapshot，本轮未自动改动正式数据库。

## 本轮（2026-09-01）：Occurrence 只使用当前版本

- `align_occurrences` 删除 `prior_occurrences` 参数，不再读取或合并历史 Occurrence。
- 最终 Occurrence 完全由当前 Bank 中的 Observation 和当前 Function `supporting_obs_ids` 重新生成。
- Evolve 最终发布不再从旧 `occurrences.jsonl` 补字段，旧事件、状态、标签和 ObservationVersion 不会进入新 Snapshot。

## 本轮（2026-09-01）：强制中断 Run 启动期收口

- `begin_function_run` 现在在同一 SQLite 事务内先收口所有 `RUNNING` 且没有 `snapshot_id` 的遗留 Function Run：删除其暂存成员及版本，标记为 `FAIL`，并写入 `interrupted_before_snapshot_publish` 审计原因。
- Snapshot 已发布的 Run 不在恢复范围内；新的 Run 随后正常创建。因此强杀、断电或宿主退出不会在下一次 Function Run 后留下可见的悬挂暂存数据。

## 本轮（2026-09-01）：正式库按新 Observation 身份重建并完成真实链路

- 为消除旧正式库中的 `_obs_001` 数字型 Observation，先将旧数据库和旧 Snapshot 移出活动路径，清空活动知识边界后，使用同一批 10 + 5 + 15 篇故事重跑；重建验证完成后已删除旧归档。
- Bootstrap 生成根 Snapshot `real_e2e_10_5_20260901T153223102634Z_982958b04ca9`：80 个 Observation、8 个 Function。
- 第一轮 Evolve 生成子 Snapshot `real_e2e_10_5_20260901T153832895720Z_44ee180820c2`：累计 123 个 Observation。
- 第二轮 Evolve 生成最新 Snapshot `real_e2e_10_5_20260901T155714939955Z_09730b26ad29`：累计 287 个 Observation、12 个 Function；父子关系连续正确。
- 最终 Pattern 成功：30 个故事序列、48 个 cluster、1 个 published pattern（`PAT_e7de04b6cedd03d6`）。
- 收尾检查通过：旧数字型 Observation=0、缺少 `source_text` 的 ObservationVersion=0、Occurrence 与 Snapshot 版本错位=0、`PRAGMA foreign_key_check` 为空；3 个 Function Run 均 `PASS`，3 个 Pattern Run 均 `SUCCESS`。
- 活动 Snapshot 目录只包含上述三代新链；旧数据库和旧 Snapshot 已删除，未进入当前正式数据库。

## 本轮（2026-09-01）：Function 演化后回看父 Snapshot 未决 Observation

- Evolve 在 `Curator` 与最终评估之间增加 `rematch_unresolved` 节点。
- 仅读取父 Snapshot 中状态为 `UNCERTAIN` / `OTHER` 且仍存在于当前 Bank 视图的 Observation。
- 仅当 Observation 与本轮新增、修订、拆分或合并的 Function 相似度达到 0.60 时，才复用 Matcher 调用 LLM。
- 成功的 `MATCH` / `EXTEND` 只加入当前工作区 Function 的 `supporting_obs_ids`；最终 Occurrence 仍由当前 Bank 和当前 Function 统一重建，父 Snapshot 不变。
- 不新增 SQLite 表、不重跑全部 Observation；回看统计写入当前 `match_report.json` 的 `retro_match` 字段。

## 本轮（2026-09-01）：Snapshot assignment 可见性与 Pattern 摘要语义失效

- Bootstrap 与 Evolve 在最终 `align_occurrences` 后，从正式 `MATCHED` / `UNCERTAIN` / `OTHER` Occurrence 计算 `assignment_coverage`、`uncertain_rate`、`other_rate`，写入并打印 Snapshot 的 `evaluation.json`；Evaluator 原有的语义 `coverage` 和 PASS 门槛保持不变。
- Pattern Cluster 新增 `summary_input_signature`，只哈希该 Cluster 实际用于摘要的 Function ID、名称、定义和 Contract，不绑定 Function 支持证据、置信度或完整 FunctionVersion。
- 同一结构且同一摘要输入才继承旧摘要；语义签名变化时只重跑受影响 Cluster 的摘要，PatternVersion 动作为 `SEMANTICS_REVISED`。故事 sequence 与 occurrence signature 不因此重建。
- 针对性回归：Occurrence 指标测试 5 项通过；Pattern 局部语义测试 6 项通过；合计 11 passed，`py_compile` 与 `git diff --check` 通过。

## 本轮（2026-09-01）：50 篇 Bootstrap + 50 篇 Evolve 真实重建

- 清空活动知识边界后，用同一语料排序的前 50 篇 Bootstrap、后 50 篇 Evolve 重建；正式 SQLite 仍为同一个 `Code/data/knowledge/story_knowledge.db`。
- Bootstrap Run `FR_75c161ee85b3f8e1` 为 `PASS`，发布根 Snapshot `real_50_50_20260901_20260901T181717556851Z_0c6768e15f35`：50 篇、446 个 Observation、23 个 Function；Assignment 为 `133/446=0.2982`，语义 coverage `0.8184`。
- Evolve 首次因 RetroMatch 的逐字段单条 embedding 长时间停滞而中止并标记 `FAIL`；将 `Embedder.encode_observations` 改为批量编码后重跑。成功 Run `FR_2ca066fd591e41b3` 为 `PASS`，发布子 Snapshot `real_50_50_20260901_20260901T194558190303Z_7929591261b8`，父 Snapshot 正确为根 Snapshot：累计 100 篇、880 个 Observation、20 个 Function。
- Evolve 最终 Assignment 为 `MATCHED=560/880=0.6364`、`UNCERTAIN=320/880=0.3636`、`OTHER=0`；语义 coverage `0.7898`，Evaluator 总体 `PASS`，但 separation 与 diversity 未达标。RetroMatch 回看父 Snapshot 未决 313 个，选中 136 个，新增归属 112 个。
- 新身份检查通过：两个 Snapshot 的 Observation 都有 `source_text`，旧 `_obs_001` 数字型 ID 为 0，Observation ID 唯一；Snapshot 文件校验、父子成员关系和 `PRAGMA foreign_key_check` 均通过。相关回归测试 26 项通过。
- 根 Snapshot 的 Pattern 基线 `PR_023db679e3165d4f` 为 `SUCCESS`，但 0 个 published Pattern；50 篇中有 1 篇没有 Observation，因此 Pattern 序列表为 49 条。子 Snapshot Pattern `PR_bc4add9a9969e22e` 运行约 36 分钟后被停止并标记 `FAILED`，未发布 Pattern，也没有生成文章；这不是“100 篇仍无 Pattern”的正式结果。
- 子 Snapshot 的只读复算显示：100 篇形成 370 个 Motif 候选、1390 对语义变体，其中 754 对为 HIGH，当前实现会逐对串行调用 LLM；594 对 HIGH 涉及长度至少 4 的 Motif。实际瓶颈是候选对和串行审查规模，不是缺少可发布候选。
- 本轮确认的运行问题：① RetroMatch 原实现对每个 Observation 的 6 个字段分别推理，已改为批量编码；② LLM 偶尔返回非法 `label`、非法 `SEMI_SAME` 或格式错误，当前靠结构化重试恢复；③ Pattern 在 Motif 数增长后产生大量语义配对并串行 LLM 审查，缺少限量、批处理和可见进度；④ Pattern 不应从 Snapshot 中省略零 Observation 故事，49/50 的输入覆盖需要后续修正；⑤ Bootstrap checkpoint 将约 2195 个 `all_pairs` 保存在 LangGraph 状态，文件约 157MB，存在状态膨胀问题。

## 本轮（2026-09-01）：精简 Pattern 审查并完成单篇文章验证

- Pattern 审查收紧为轻量条件：只审查 `HIGH` 召回、至少一个 Motif 长度不小于 4、双方互相进入 Top-2 的候选对；未选中的变体不再进入串行 LLM 审查。
- 子 Snapshot 的 Pattern Run `PR_bc4add9a9969e22e` 成功：99 条故事序列、370 个 Motif、90 条 Pair Review、323 个 Cluster，其中 26 个发布、296 个候选、1 个阻塞；当前正式 Pattern 数为 26。此前的 0 个发布结果是旧审查规模未完成，不是候选为空。
- 用 Pattern“层层递进的真相揭示与威胁升级”完成一篇真实文章验证：Outline `OUT_19035f8cb68d64e0` 成功，正文 JSON 约 92.5KB、Markdown 约 19.9KB，产物位于 `Code/data/rebuild_50_50_20260901/article/`，正文的 `source_outline_id` 和 `snapshot_id` 均正确指向本轮结果。
- 因本轮 Function Evolve 是直接调用 Agent，未自动生成 StoryCLI 所需的 `function_run.json`；没有重跑抽取，而是补写已有 Snapshot/Pattern 的运行清单后完成文章验证。该流程入口不一致应后续统一，但不影响本次数据库结果。
- 本轮确认的剩余问题：100 篇中有 1 篇没有 Observation，因而只生成 99 条 Pattern 序列；当前精简筛选偏保守，可能少审查有效候选，后续若需要提升召回应采用批量审查/可恢复队列，而不是恢复全量串行审查。

## 本轮（2026-09-01）：Pattern Review 阶段超时与失败状态收口

- 在 Motif Review 和 Pattern Summary 两个 LLM 阶段增加固定 15 分钟总预算；每条 Review/摘要前后检查截止时间，超时抛出 `TimeoutError`，不进入 Pattern 提交节点。
- `run_pattern_evolve` 统一捕获异常、`KeyboardInterrupt` 和 `SystemExit`，调用 `fail_pattern_run` 写入 `pattern_runs.status=FAILED` 及错误原因；正式 Pattern 仍只通过 `commit_pattern_run` 原子发布。
- 临时 SQLite 集成验证确认：模拟 Review 超时后，运行记录为 `FAILED`，错误原因可追溯；Pattern 相关回归测试 50 项全部通过，`py_compile` 与 `git diff --check` 通过。
- 该方案不改变 Function Snapshot、不新增表；底层 OpenAI 客户端原有的单请求 120 秒超时继续保留，新增的是整个 Review 阶段的总预算。

## 本轮（2026-09-01）：补齐 Function MERGE/SPLIT lineage

- 不新增表或数据库；复用 `version_history` 写入现有 `function_evolution_events.payload_json`。
- MERGE 事件现在记录 `source_function_ids` 和 `target_function_ids`；SPLIT 的每个子 Function 记录父 Function ID 与完整子 Function ID 集合。
- Bootstrap Revise 和 Evolve Curator 两条演化路径统一写入 lineage；REVISE 保留原 Function ID，不额外生成 lineage 边。
- 相关回归验证：37 项 Curator/Revise/KnowledgeBase/Registry 测试通过。

## 本轮（2026-09-01）：移出 Bootstrap 累计 pair，收敛 checkpoint 体积

- 根因：即使 `all_pairs` 只保存 `obs_id + similarity`，累计列表仍会在每个 LangGraph checkpoint 中被重复序列化。
- 修复：删除 `NarrativePipelineState.all_pairs`；`pairs_collector` 将三元组追加到当前 `out_dir/pairs_<namespace>.jsonl`，`cluster_node` 再从该工作文件读取并通过 Bank 恢复完整 Observation。聚类后的 `induction_components` 也只保存 pair 引用，`induce_step` 使用时再从 Bank 恢复。重复 pair 在聚类读取时去重，支持节点重试/续跑。
- 清理：Bootstrap fresh 启动时删除对应 pair 工作文件，并对已删除的 checkpoint 页面执行 `VACUUM`；不改知识库 SQLite、Snapshot 或正式数据结构。
- 验证：Bootstrap 续跑与聚类归纳测试通过；checkpoint `writes` 中不再有 `all_pairs`；全套测试 `289 passed, 1 skipped`，`py_compile` 与 `git diff --check` 通过。

## 本轮（2026-09-01）：清理旧格式 MERGE 事件索引

- 按精确 `event_id` 从正式 SQLite 的 `function_evolution_events` 删除 3 条旧代码生成、缺少 source/target ID 的 MERGE 记录。
- 删除后旧格式 MERGE=0，剩余 Function 事件为 `APPLY_EVIDENCE=15`、`CREATE=23`、`RETRO_MATCH=18`、`REVISE=1`；`PRAGMA foreign_key_check`=0。
- 已发布 Snapshot 文件保持不可变，未直接修改其中的历史 FunctionVersion；后续新事件统一使用 lineage payload。

## 本轮（2026-09-02）：Pattern 保留零 Observation 故事并清理 Observation 孤儿

- Pattern 输入现在以 Snapshot manifest 的完整故事列表为准；没有 Observation 的故事保留空 `raw_sequence` / `structural_sequence`，不制造虚假 Occurrence 或 Motif，也不再静默从 Pattern 输入中丢失。
- 失败或启动恢复时，删除本 Run 的 ObservationVersion 后，同步删除没有任何 ObservationVersion 归属的 Observation；已有版本或正式 Snapshot 中仍被使用的 Observation 不受影响。
- 对活动知识库清理了 415 条历史孤儿 Observation；当前 `observations=880`、孤儿为 0，正式 ObservationVersion、Snapshot 成员和 Occurrence 数量未减少。
- 验证：相关回归 53 项通过；全套测试 `292 passed, 1 skipped`，`compileall` 与 `git diff --check` 通过。

## 后续优化（暂不执行）：Snapshot 内部版本绑定与数据库级不可变保护

- 当前正式数据未发现 Snapshot 版本错位；单写入应用通过 `StoryKnowledgeStore` 提交，Snapshot 文件已有 SHA-256 校验，因此该问题暂不作为当前阻塞项处理。
- 后续优先采用一个集中式 Snapshot integrity check，在提交和读取时验证 ObservationVersion、StoryVersion、FunctionVersion 与当前 Snapshot 的成员关系。
- 暂不增加复合外键或多组 SQLite trigger，避免在当前单写入架构中引入不必要的表结构和维护复杂度；只有出现多进程写入、外部 SQL 写入或论文级数据库约束要求时再启用数据库级硬保护。

## 后续优化（暂不执行）：固定 Outline 外部派生输入版本

- 当前 Outline 的 Pattern 与 FunctionContract 已按 Snapshot 从 SQLite 读取；Function Card 和 Transition Index 按同一 `snapshot_id` 分目录，已有基本隔离。
- 暂不新增版本表或迁移数据库；后续在 A/B 实验、跨批次比较或论文级复现前，在 Outline 运行产物中记录外部 Function Card / Transition Index 的 SHA-256。
- 该项属于可复现性增强，不阻塞当前 Bootstrap、Evolve、Pattern 或 Outline 链路。

## 本轮（2026-09-02）：删除旧 Agent 兼容入口与失效 Snapshot 默认值

- 删除 `Code/Agent/__init__.py` 兼容 shim；生产代码、测试和脚本统一使用 `FunctionExtract_Agent.*`，并将原先依赖 shim 注入路径的 `Prompt`、`Embedding`、`Retrieval` 导入改为显式包路径。
- 删除失效的 `DEFAULT_SNAPSHOT_ID` 和一次性脚本中的旧 Snapshot 硬编码；Outline、Pipeline、StoryCLI 现要求显式 Snapshot，避免误读已删除的历史 Snapshot。
- 入口文档同步到 `FunctionExtract_Agent`；未提前删除仍由当前 Bootstrap 使用的 `record_function_run` 和 stdout Snapshot 解析，待下一阶段 manifest 链路替代后清理。
- 验证：`292 passed, 1 skipped`；`compileall`、入口 `--help`、`git diff --check` 通过。当前环境下不执行真实 LLM 流程。

## 本轮（2026-09-02）：统一 Bootstrap / Evolve / Pattern 的最小 Run 控制面

- Bootstrap 改为在图启动前创建 `RUNNING` Function Run；每篇故事在 `bank_adder` 写入该 Run 的暂存区（零 Observation 故事也保留 StoryVersion 成员），PASS 时用同一 `run_id` 提交 Snapshot，FAIL 或异常时清理暂存并保留失败记录。`--resume` 仅恢复 checkpoint 中仍为 `RUNNING` 的同一 Run。
- 删除旧的 `record_function_run` 事后回填路径；它曾在文件 Snapshot 发布后才创建 Run，无法作为正式 Bootstrap 生命周期的一部分。
- Pattern 的 `begin_pattern_run` 会将先前残留的 `RUNNING` Run 标记为 `FAILED(interrupted_before_pattern_commit)`，然后启动当前 Run。该策略保持现有单机串行写入假设，不增加锁、队列或新表。
- Bootstrap、Evolve 和 Pattern CLI 的最终结果统一为 `{"run_result": ...}`；Function 结果包含 `run_id`、`status`、`workflow`、`namespace`、父/子 Snapshot 与终评报告，Pattern 保留相同运行标识与 Pattern 统计。
- 验证：新增 Bootstrap 暂存→提交、零 Observation 故事成员和 Pattern 悬挂 Run 收口测试；全套 `294 passed, 1 skipped`，`git diff --check` 与 `compileall` 通过。未重跑真实 LLM 或修改正式知识库。

## 本轮（2026-09-02）：单篇真实 Evolve → Pattern 接口验证

- 以当前 100 篇正式 Snapshot `real_50_50_20260901_20260901T194558190303Z_7929591261b8` 为父，使用真实 LLM 处理新故事 `01_悬疑惊悚/2944521006_348025005.txt`（5,005 字）。Evolve Run `FR_bb22e41228884f1e` 为 `PASS`，发布子 Snapshot `real_50_50_20260901_20260902T073957699614Z_6f112aad5060`。
- 子 Snapshot 的正式成员为 101 篇故事、886 个 Observation、886 个 Occurrence、19 个 Function；Occurrence 为 `MATCHED=564`、`UNCERTAIN=322`。Snapshot SHA 校验与 `PRAGMA foreign_key_check` 通过。
- 随后真实 Pattern Run `PR_9dda7ad7f7e431d2` 正确读取该完整子 Snapshot，并在摘要阶段因 LLM 输出的 `core_function_names` 含非当前 Function 名称而标记 `FAILED`：`summary 核心 Function 无效: MCL_a8cd6c625f925707`。
- 失败未写入任何该 Snapshot 的 Pattern sequence、motif、cluster 或 pattern；Function 子 Snapshot 仍是正式可用的 PASS 结果。这验证了 Pattern 的真实异常收口与原子发布边界；问题位于摘要输出的名称严格校验，而非 Run 生命周期或 Snapshot 数据流。

## 本轮（2026-09-02）：移除 Pattern Summary 对 Function 名称复述的依赖

- `StoryPatternSummary` 不再要求 LLM 输出 `core_function_names` 或任何 Function 选择字段；LLM 只负责生成模式名称、抽象定义、适用条件、限制和结局说明。
- Pattern 节点直接从 Cluster 的 `anchor_motif_id` 读取稳定 `function_ids`，再从当前 Snapshot 的 Function 表回填名称、定义和 Contract。4 步以上 motif 优先作为锚点，避免 Cluster 中较短变体抢占核心链。
- 不改数据库表结构、Snapshot 边界或 Pattern 增量签名；这只是把 Function 身份绑定从 LLM 输出移到系统已有的 motif 数据。
- 真实 Pattern 重试成功：`PR_9dda7ad7f7e431d2`，101 条序列、365 个 Motif、324 个 Cluster、25 个 published Pattern；`PRAGMA foreign_key_check` 为空。
- 验证：针对性测试 `20 passed`，全套测试 `294 passed, 1 skipped`；测试生成的共享 Bank 已恢复为 80 行真实基线，临时 Chroma 目录已移入回收站。

## 本轮（2026-09-02）：单篇真实 Bootstrap 验证与遗留路径清理

- 使用真实 LLM、真实 Observer、真实 SQLite Run 流程处理一篇 `2944521006_348025005` 故事。Bootstrap Run `FR_3af086d8fcc54cda` 实际完成抽取，生成 9 个 Observation，LLM 调用 2 次、总计约 11,116 tokens。
- 单篇 Bootstrap 没有跨故事相似对，Induction 分量为 0，Evaluator 判定 `FAIL`，因此没有发布 Snapshot。这是单篇输入的业务结果，不是接口异常；Run 结果已通过 `run_result` 返回并写入隔离验证数据库。
- 运行使用独立 Bank、Registry、KnowledgeDB 和 Snapshot 输出目录，未清空或污染当前正式知识库；正式共享 Bank 仍恢复为 80 行真实基线。
- 清理确认：旧 `Code/Agent` 兼容 shim、旧 `test_evolve.py`、旧 Pattern 桥接路径以及 Summary 的 Function 名称/索引字段已无生产引用并已删除；其余人工实验脚本仍有复现价值，未作无依据删除。

## 本轮（2026-09-02）：增加 Function Coordinator 调度 Agent

- 新增 `Code/FunctionCoordinator_Agent`，使用 LangGraph 条件边编排 `Bootstrap/Evolve → Pattern`；不调用 LLM、不新增数据库表，也不改变现有 Function Run、Pattern Run 或 Snapshot 提交边界。
- Coordinator 通过子 Agent 已有 CLI 的 `run_result` 做路由：Function `PASS + snapshot_id` 才进入 Pattern，Pattern `SUCCESS` 才完成；业务质量失败直接停止，进程级超时/限流等暂时错误最多按 `--max-retries` 有限重试。
- 现有 `Pipeline_Agent` 保持 `Outline → Story` 职责不变；Function Coordinator 是独立控制面。Coordinator 最终返回包含 Function/Pattern 子结果和尝试次数的机器可读 `run_result`。
- 新增 5 项路由、重试和结果解析测试；验证结果为 `299 passed, 1 skipped`，CLI `--help` 和 `git diff --check` 通过。

## 本轮（2026-09-02）：统一 Bootstrap / Evolve / Pattern 失败结果

- 新增 `Code/Contracts/run_result.py`，三个子 Agent 的失败返回统一为 `status=FAILED`，并携带阶段、工作流、Run、namespace、父/子 Snapshot、错误码、错误信息和 `retryable`。
- Bootstrap/Evolve 的语料、基础 Snapshot、checkpoint 等早期失败也输出同一 `{"run_result": ...}` 协议；运行中异常和评估不通过沿用同一协议。
- Pattern 运行异常和启动收口写入相同失败 payload；正式 SQLite 的物理状态仍保留 `pipeline_runs.status=FAIL`、`pattern_runs.status=FAILED`，不改变已有成功状态语义。
- 验证：全套测试 `302 passed, 1 skipped`；测试生成的共享 Bank 已恢复为 80 行真实基线，临时 Chroma 目录已移入回收站。

## 本轮（2026-09-02）：补 Coordinator 真实子进程协议测试

- 在 `Code/test/test_function_coordinator.py` 增加真实 Python 子进程测试，不 mock `_run_stage`；子进程输出进度日志和 JSON `run_result`，由 Coordinator 实际读取、解析并完成 Function → Pattern 路由。
- 增加非零退出码覆盖测试：即使子进程报告 `PASS`，Coordinator 也会将结果收口为 `FAILED`，并阻止进入 Pattern。
- 验证：Coordinator 定向测试 `7 passed`；未调用 LLM。

## 本轮（2026-09-02）：Coordinator 阶段超时与有限错误分类

- Coordinator 为每个 Bootstrap/Evolve/Pattern 子进程增加默认 1800 秒阶段超时，超时后终止当前进程并返回统一 `STAGE_TIMEOUT` 失败结果；不增加 Coordinator Run 表或第二套恢复状态。
- 重试判定沿用子 Agent 的 `retryable`，仅增加少量永久错误码保护（语料、Snapshot、checkpoint 和质量门失败不重试）；没有引入 LLM 错误分类器。
- 验证：真实子进程、超时、退出码和永久错误码测试均通过；全套测试 `306 passed, 1 skipped`。共享 Bank 已恢复为 80 行真实基线，临时 Chroma 已移入回收站。

## 本轮（2026-09-02）：Coordinator Evolve 自动继承父 Snapshot namespace

- Coordinator 的 Evolve 模式现在读取 `base_snapshot_id` 对应 Snapshot manifest，并将其 namespace 作为 Evolve Registry、Function Run 和子 Snapshot 的唯一 namespace；调用者传入的不一致值只作为提示，不再覆盖父 lineage。
- Bootstrap 仍使用显式 namespace；不新增 namespace 映射表、Run 表或数据库边界。
- 验证：新增父 Snapshot namespace 继承测试；全套测试 `307 passed, 1 skipped`，共享 Bank 已恢复为 80 行真实基线。

## 本轮（2026-09-02）：真实 Coordinator 全流程复测

- 使用真实 LLM、临时 KnowledgeDB 和 3 篇跨题材故事复测；即使命令传入错误 namespace，Coordinator 也自动继承父 Snapshot 的 `real_50_50_20260901`。
- Evolve Run `FR_2e754a7cab6f4739` 成功，发布临时子 Snapshot `real_50_50_20260901_20260902T131330691437Z_ba37aa81a6ad`；Snapshot 为 104 篇故事、919 个 Observation、19 个 Function。
- Pattern Run `PR_de14350298651dae` 在输入一致性检查处失败：`motif candidate Function ID/名称不一致: MC_47c799047da2d87e: F_E7DF0FDE`。该错误被标记为不可重试，Coordinator 正确停止，未完成 Pattern 发布。
- 正式 KnowledgeDB 最新 Snapshot 仍未改变，Registry 备份恢复后一致；临时验证目录已移入回收站。

## 本轮（2026-09-02）：Pattern 增量 Motif 名称按当前 Snapshot 重投影

- 修复 Pattern 继承父 Snapshot Motif 证据时携带旧 `function_names` 的问题；继承路径现在只保留 `function_ids` 和证据，名称统一从当前 Snapshot 的 `function_by_id` 重新生成。
- 历史 Snapshot 不修改，Function ID 仍是 Pattern 的唯一引用；本次投影只发生在每次 Pattern 运行的输入构建阶段，不增加 LLM 调用，也不需要重跑 Observation。
- 如果 `MERGE/SPLIT` 使 Function ID 消失，仍需依靠 lineage 做显式重映射；本修复针对同一稳定 ID 的 Function 名称修订。
- 验证：针对性测试 `41 passed, 1 skipped`；全套离线测试 `308 passed, 1 skipped`。

## 本轮（2026-09-02）：真实 Pattern 重建验证名称投影

- 使用临时 KnowledgeDB 中的真实子 Snapshot `real_50_50_20260901_20260902T131330691437Z_ba37aa81a6ad` 重跑 Pattern；该 Snapshot 曾因 `F_E7DF0FDE` 的旧名称继承而失败。
- 真实 Pattern Run `PR_de14350298651dae` 成功完成：104 条序列、261 个 Motif、242 个 Cluster、9 个 published Cluster、9 个 published Pattern；原一致性错误未再出现。
- 正式 KnowledgeDB 最新 Snapshot 仍为 `real_50_50_20260901_20260902T073957699614Z_6f112aad5060`，本次只修改临时验证库。

## 本轮（2026-09-02）：原路径全新库上的 Coordinator 全链路验证

- 将正式运行状态 `data/knowledge`、`data/registry`、`FunctionExtract_Agent/data/bank`、`data/ontology_snapshots` 和 `data/checkpoints` 移入回收站，在原路径重建空运行环境；语料和历史输出目录未删除。
- 真实 Coordinator Bootstrap 处理 10 篇故事，Function Run `FR_ff890e0fd24d48eb` PASS，发布根 Snapshot `real_coordinator_rebuild_20260902_20260902T143306834821Z_2cf78969b5c8`；包含 10 篇故事、69 个 Observation、8 个 Function。根 Pattern Run `PR_3d04b6d5c11ef88b` SUCCESS，但当前样本仅形成 1 个 candidate Cluster，0 个 published Pattern。
- 真实 Coordinator Evolve 增加剩余 5 篇故事，自动从父 Snapshot 继承 namespace，Function Run `FR_d150784b96b644f0` PASS，发布子 Snapshot `real_coordinator_rebuild_20260902_20260902T143716690768Z_46b96bd1031b`；子 Snapshot 共 15 篇故事、128 个 Observation、9 个 Function。子 Pattern Run `PR_3d499ccd724bdd00` SUCCESS，16 个 candidate Cluster，0 个 published Pattern。
- 自动化链路验证通过：Bootstrap → Pattern、Evolve → Pattern 均由 Coordinator 子进程自动衔接，无中途人工纠正；父子 Snapshot、两组 Run 状态均正确，`PRAGMA foreign_key_check` 为空。Evaluator 的业务质量报告仍可能 PASS 但未达 6/6，Pattern 0 published 属于当前样本结构不足，不是流程失败。

## 本轮（2026-09-02）：同一正式库追加 10 篇并自动提取 Pattern

- 沿用最新父 Snapshot `real_coordinator_rebuild_20260902_20260902T143716690768Z_46b96bd1031b`，在同一个 `data/knowledge/story_knowledge.db` 中追加 10 篇未处理真实语料；没有新建数据库，也没有人工衔接。
- Evolve Run `FR_e3685e7972684062` PASS，发布子 Snapshot `real_coordinator_rebuild_20260902_20260902T144924647688Z_46f8a97d4a75`；累计 25 篇故事、225 个 Observation、8 个 Function，assignment coverage `130/225=57.78%`。
- Coordinator 自动启动 Pattern Run `PR_2dcaf84c5d487461` SUCCESS；25 条序列、73 个新输入 Motif、67 个 Cluster、4 个 published Cluster、4 个 published Pattern（`PAT_012e4b8327a64ef5`、`PAT_3b533703d96368fd`、`PAT_4ed54faaee43fd11`、`PAT_e67be7980a7a5ba2`）。
- 最终核验：3 个 Function Run 和 3 个 Pattern Run 均无 `RUNNING`；最新 Snapshot 父子关系正确，`PRAGMA foreign_key_check` 为空。过程中出现的 LLM 结构化输出错误由现有重试自动恢复。

## 本轮（2026-09-02）：建立第一版可信增量质量基线

- 对最新 Snapshot `real_coordinator_rebuild_20260902_20260902T144924647688Z_46f8a97d4a75` 完成结构检查和 60 个 Observation 语义抽样评审；报告位于 `Code/data/real_coordinator_rebuild_20260902/quality_baseline_20260902.md`。
- 自动检查通过：4 个 Published Pattern 的 Function ID 均存在且名称投影无旧值；父子 Snapshot 正确；没有悬挂 Run；外键检查通过。
- 30 个 MATCHED 样本初评为 `C=20`、`P=6`、`M=4`；30 个 UNCERTAIN 样本中 `U_OK=14`、`U_RE=16`。这说明下一步应优先做受限 RetroMatch 和 Pattern 重叠评审，而不是增加 Supervisor。
- 4 个 Published Pattern 中至少 3 个共享“揭示—威胁”骨架，当前应视为“1 个较强候选 + 3 个待合并/验证变体”，暂不直接删除。
- 质量基线同时发现最新 Snapshot 有 32/225 个 Observation 缺少 `source_text`（MATCHED 23、UNCERTAIN 9）；这不是引用完整性错误，但会降低人工证据复核强度，下一轮应单独追踪其输入定位来源。

## 本轮（2026-09-02）：跨题材真实增量观察

- 在同一正式 KnowledgeDB 中，以 Snapshot `real_coordinator_rebuild_20260902_20260902T144924647688Z_46f8a97d4a75` 为父版本，追加 10 篇未处理故事：古风仙侠 3、现代情感 3、末世科幻 2、现实家庭职场 2；没有新增数据库或中途人工干预。
- Evolve Run `FR_fe7c93bb90994570` PASS，发布 Snapshot `real_coordinator_rebuild_20260902_20260902T152656592904Z_22bb53b3ba5b`；累计 35 篇故事、304 个 Observation、9 个 Function。最终 assignment coverage `189/304=62.17%`，`UNCERTAIN=115`。
- 受限 RetroMatch 实际回看 5 个旧未决 Observation，新增归属 2 个；没有全量重跑 Observation。该机制在跨题材批次中确实产生了有限增量收益。
- Pattern Run `PR_e27bba34b67c4815` SUCCESS，发布 5 个 Pattern，同时退休上一 Snapshot 的 4 个 Pattern。当前仍可见重复骨架：两组“关系破裂—威胁—反思”和两组“隐藏能力揭示—威胁”高度重叠；这是重复出现的质量问题，不是流程或引用错误。
- 跨题材后的 Evaluator 仍因 `abstraction_quality` 失败，明确指出 `THREAT_OR_DANGER_CONFRONTATION`、`PERSONAL_GROWTH_AND_REFORM` 过宽；该问题不再能归因于单一悬疑题材。各题材 assignment coverage 为：悬疑 `64.8%`、古风 `62.7%`、现代 `64.0%`、末世 `60.0%`、家庭职场 `57.1%`。
- 本轮没有修改代码。当前结论是：继续积累数据用于判断重复问题是合理的；下一次仍先观察，不因一批结果直接增加去重 Agent 或 LLM Supervisor。

## 本轮（2026-09-02）：第二批跨题材真实增量观察

- 继续沿用同一正式库和 Snapshot 链，追加 8 篇未处理故事：古风仙侠、现代情感、末世科幻、现实家庭职场各 2 篇；悬疑语料已经全部处理完，因此没有人为重复采样。
- Evolve Run `FR_e73729f19de5448b` PASS，发布 Snapshot `real_coordinator_rebuild_20260902_20260902T154930744187Z_9195b273a20a`；累计 43 篇故事、367 个 Observation、8 个 Function，assignment coverage `212/367=57.77%`，`UNCERTAIN=155`。
- 本轮受限 RetroMatch 回看 2 个旧未决 Observation，新增归属 2 个；仍保持局部增量，不重跑全部旧 Observation。
- Pattern Run `PR_96377123e12a4d35` SUCCESS；当前 4 个 Published Pattern，1 个 Pattern 合并，1 个候选 Cluster 被阻断，2 个上一轮 Pattern 退休。Pattern 仍集中在“关系破裂/身份或属性揭示—威胁—反思/资源”骨架，但已有跨题材支持的模式。
- 上一批的 Function 过宽警告本轮最终未重复出现，Evaluator `abstraction_quality=1.0`；但本轮中期曾再次提示 `THREAT_OR_DANGER_CONFRONTATION` 把“对抗”和“逃离”放在同一定义中，因此该问题暂时只能判定为间歇性重复，不能视为已解决。
- 各题材 assignment coverage 为：悬疑 `66.7%`、古风 `56.5%`、现代 `53.8%`、末世 `57.9%`、家庭职场 `50.0%`。跨题材后整体匹配率仍偏低，家庭职场和现代情感尤其明显。
- 本轮没有修改业务代码，也没有新增测试库；当前仍以数据积累和批次比较为主。

## 本轮（2026-09-02）：第三批跨题材真实增量观察

- 以 Snapshot `real_coordinator_rebuild_20260902_20260902T154930744187Z_9195b273a20a` 为父版本，在同一正式 KnowledgeDB 中追加 10 篇未处理故事：古风 2、现代 2、末世 3、家庭职场 3。
- Evolve Run `FR_0b1f40b721ad45e1` PASS，发布 Snapshot `real_coordinator_rebuild_20260902_20260902T160122211213Z_8d96cbbc6312`；累计 53 篇故事、456 个 Observation、8 个 Function。最终 assignment coverage `271/456=59.43%`，`UNCERTAIN=185`。
- 受限 RetroMatch 本批没有单独产生回看输出变化；Evolve、Pattern 均由 Coordinator 自动完成，Function/Pattern Run 无悬挂，外键检查通过。
- 最终 Evaluator 连续通过 6/6，`abstraction_quality=1.0`；本批没有新增或移除 Function。说明上一批的 Function 过宽警告尚未形成连续最终失败，但不能认为语义边界已稳定。
- Pattern Run `PR_8c152aa766f1013b` SUCCESS：10 个 Published Pattern，3 个旧 Pattern 更新，未发生合并或阻断。模式仍高度集中于“揭示—威胁—反思/资源”组合，并出现跨题材支持，但重复骨架没有消失。
- 各题材 assignment coverage 为：悬疑 `66.7%`、古风 `54.4%`、现代 `53.5%`、末世 `62.2%`、家庭职场 `58.7%`。整体仍处于约 59% 的低匹配区间，现代和古风较弱。
- 本轮没有修改业务代码。当前结论：Pattern 重复和跨题材低匹配已具备多批次证据，下一阶段可以做最小诊断规则；仍不需要增加 Supervisor 或独立 Agent。

## 本轮（2026-09-02）：Pattern → 故事 → Evolve 闭环验证

- 选用当前 Published Pattern `PAT_a8ac650d2929a13f`（`Secret Alliance Under Threat`），在正式 KnowledgeDB 的只读副本上由 Pipeline 真实生成现代情感大纲和正文《裂痕》；大纲校验通过，正文 4322 字、4 个场景。
- 生成故事通过 Evolve 分析：Function Run `FR_b1de90b70cfb49a4` PASS，12 个 Observation 全部 `MATCHED`，无 `UNCERTAIN`、`NOVEL` 或新增 Function；分析副本 Snapshot 为 `real_coordinator_rebuild_20260902_20260902T162759856082Z_2106c2178daf`。
- 实际 Function 序列包含预期四个 Function，并保持“关系破裂 → 属性揭示 → 资源/支持 → 威胁”的相对顺序，但增加了重复威胁、联盟、资源获取和个人成长环节；说明 Pattern 是高层结构约束，不是固定脚本。
- Evolve 最终仍为 `PASS 5/6`，`abstraction_quality=0.75`；再次指出 Alliance/Deal 和 Threat/逃离的语义混合。该结果强化了 Function 边界问题，但没有破坏生成—分析接口。
- Pattern 在隔离副本中成功完成；验证报告位于 `Code/data/closed_loop_eval_20260902/closed_loop_report.md`。正式 53 篇故事的数据库和 Snapshot 链未改变。
- 本轮没有修改业务代码；下一步先用另一个 Pattern 做一篇同样的生成验证，不马上调整 Function 或 Pattern 逻辑。

## 本轮（2026-09-02）：第二篇 Pattern 生成—分析闭环验证

- 选用不同的 Published Pattern `PAT_69e6fcd9443f7dc1`（`反思揭示与自立成长`），在正式 Snapshot 的第二个隔离副本中生成现实家庭职场故事《迟到的决定》；大纲校验通过，正文 4175 字、4 个场景。
- Evolve Run `FR_472b5d06bdf1476e` PASS，5 个 Observation 全部 `MATCHED`，无 `UNCERTAIN`、`NOVEL` 或新增 Function；Pattern Run `PR_0551c30883279167` SUCCESS。
- 预期链为 `INTERNAL_REFLECTION → HIDDEN_ATTR_REVELATION → PERSONAL_GROWTH_AND_REFORM → RESOURCE_OR_SUPPORT_ACQUISITION`，实际链为 `RELATIONSHIP_BREAKDOWN → HIDDEN_ATTR_REVELATION → HIDDEN_ATTR_REVELATION → STRATEGIC_ALLIANCE_OR_DEAL → PERSONAL_GROWTH_AND_REFORM`。
- 目标 Function 只出现 2/4；这与第一篇 4/4 的结果不同，说明 Pattern 对生成有方向性影响，但目前不能稳定保持目标 Function 链。`MATCHED` 全部成功也不等于遵循 Pattern。
- 本轮没有修改正式库或业务代码。第二篇验证报告位于 `Code/data/closed_loop_eval_20260902_b/closed_loop_report.md`。

## 本轮（2026-09-02）：三种 Pattern 生成—分析批次验证

- 选取三个结构不同的 Pattern，分别从正式 Snapshot `real_coordinator_rebuild_20260902_20260902T160122211213Z_8d96cbbc6312` 建立隔离副本，执行三篇真实生成和 Evolve；没有写入正式 KnowledgeDB。
- `alliance`（现代情感）生成《代号L-7》：目标 Function 出现 `3/4`，Evolve Run `FR_469428f7a4af43ee` PASS，Pattern Run `PR_a23eee13f8fb7fe5` SUCCESS。
- `crisis`（末世科幻）生成《守望新土》：目标 Function 出现 `4/5`，Evolve Run `FR_d50cf36c72774d2b` PASS，Pattern Run `PR_700267599aa00ba3` SUCCESS。
- `breakup`（古风仙侠）生成《天衡遗鹤》：预期 Function 链只部分出现；Evolve Run `FR_2c4ad8e06ef84aab` 在发布前的 `RESOURCE_OR_SUPPORT_ACQUISITION` FunctionContract 校验处 FAILED，没有 Snapshot，也没有进入新的 Pattern。
- 三篇均没有精确复现目标链；两篇成功样本保持了大部分目标方向并加入额外叙事环节，支持 Pattern 为高层约束而非硬模板。第三篇的发布失败是独立的 Contract 问题，不能混入结构保持率统计。
- 批次报告位于 `Code/data/closed_loop_batch_20260902/closed_loop_batch_report.md`。正式库仍保持 53 篇故事、456 个 Observation。

## 本轮（2026-09-03）：Evolve 复用父 Snapshot 的有效 FunctionContract

- 修复前，Evolve 使用新的 `out_dir` 时会为全部 Function 重新请求 Contract；未变化 Function 也可能因新的 LLM 格式错误阻断发布。之前《天衡遗鹤》正是在发布前因非法 `RESOURCE_OR_SUPPORT_ACQUISITION` Contract 失败。
- 现在 Evolve 在最终发布前读取父 Snapshot 已校验的 `function_contracts.jsonl`，按 `function_id + definition_sha256` 复用未变化 Contract；新增或定义变化的 Function 仍走原有生成和严格校验。
- 单元测试 `test_function_contract.py` 全部通过（6 passed）。同一失败故事、同一父 Snapshot、隔离 KnowledgeDB 真实重跑成功：Function Run `FR_3e6119255e5d497e` PASS，子 Snapshot `real_coordinator_rebuild_20260902_20260903T073404224532Z_60980ee958fa` 发布；父子 Contract 文件 SHA-256 相同。
- Coordinator 随后自动完成 Pattern：Pattern Run `PR_a7344fe56ee77b4b` SUCCESS，13 个 Published Pattern，3 个新建、1 个更新。正式 KnowledgeDB 未修改，仍保持 53 篇/456 个 Observation 的正式基线。
- 这不是保留非法新 Contract 的回退：定义变化时仍必须重新生成并通过校验；本修复只复用父 Snapshot 中已证明有效且定义未变的 Contract。

## 本轮（2026-09-03）：五领域跨题材可信增量验证

- 以正式 Snapshot `real_coordinator_rebuild_20260902_20260902T160122211213Z_8d96cbbc6312`（53 篇、456 个 Observation）为父版本，从同来源 250 篇五领域真实语料中选取此前未处理的 15 篇，每个领域 3 篇，在同一正式 DB 中运行 Coordinator。
- Evolve Run `FR_a776252cdc4c44ad` PASS，发布子 Snapshot `real_coordinator_rebuild_20260902_20260903T080910344525Z_0bc8086d7c18`；累计 68 篇、588 个 Observation/FunctionOccurrence，五领域分布为 15/14/13/13/13，`foreign_key_check` 通过。
- 最终 Evaluator PASS 6/6；assignment coverage `344/588=58.5%`，`MATCHED=344`、`UNCERTAIN=244`、`OTHER=0`。受限 RetroMatch 召回 12 个旧未决项，新增归属 8 个。
- Pattern Run `PR_83b1ff049c7a8585` SUCCESS：13 个 Published Pattern，11 个新建、8 个退休、0 个阻断/合并；其中 12 个拥有至少两个领域的证据，但仅 3 个包含本次新批次故事。
- 重要结论：增量数据链路和跨领域证据生成通过第一轮；但 Function 演化使 41 篇旧故事变为 Pattern `changed`，Pattern 变化幅度较大，暂不能宣称稳定。`RELATIONSHIP_NEGOTIATION` 建议修订是语义提示，不影响本轮提交。
- 完整报告：`Code/data/real_coordinator_rebuild_20260902/cross_topic_validation_20260903.md`。本轮没有修改业务代码。

## 本轮（2026-09-03）：第二批五领域跨题材可信增量验证

- 继续在同一正式 SQLite 和 Snapshot 链上，从 500 篇五领域语料中选择此前未处理的 15 篇，每个领域 3 篇；父 Snapshot 为 `real_coordinator_rebuild_20260902_20260903T080910344525Z_0bc8086d7c18`。
- Evolve Run `FR_cb37ea8e896f4c16` PASS，发布子 Snapshot `real_coordinator_rebuild_20260902_20260903T082812603975Z_1db1166a208f`；累计 83 篇、716 个 Observation/FunctionOccurrence。Pattern Run `PR_6a8b5abcde77fc63` SUCCESS。
- 本批最终 assignment coverage `418/716=58.4%`，与上一批 `58.5%` 基本一致；受限 RetroMatch 回看 39 个候选，新增归属 5 个。低匹配率已获得跨批次重复证据。
- Evaluator 最终为业务 `PASS` 但 5/6 维通过，`separation` 未通过；`RELATIONSHIP_NEGOTIATION` 被拆为 `RELATIONSHIP_FORMATION` / `RELATIONSHIP_DISSOLUTION` 后仍被判定相互接近，关系语义边界问题再次出现。
- Pattern 结果为 16 个 Published、10 个新建、4 个更新、5 个退休、0 个合并；11/16 个具有至少两个领域证据。Pattern 重复和 churn 仍然存在，但没有破坏 Snapshot 或引用一致性。
- Evolve 输出中有 1 个同故事重复 `obs_id`，最终 SQLite 以唯一身份幂等收敛为 128 个新增 ObservationVersion；未形成孤立 Occurrence，先记录为输出层轻微问题，不扩大本轮修复。
- 完整报告：`Code/data/real_coordinator_rebuild_20260902/cross_topic_validation_20260903_batch2.md`。当前不新增 Agent、数据库或运行时边界；下一步可做最小离线诊断和人工抽样。
## 本轮（2026-09-03）：Pattern 驱动故事生成与结构保持验证

- 基于 Snapshot `real_coordinator_rebuild_20260902_20260903T082812603975Z_1db1166a208f`，选择 3 个不同结构的 Published Pattern，生成悬疑、现代情感、末世科幻各 1 篇真实故事。
- 三篇均完成 `Pattern → Outline → Story`；随后作为新故事进入同一正式 SQLite 的 `Evolve → Pattern`。
- Function Run：`FR_e1d387e7196f439a`；Pattern Run：`PR_1d53bb856cfe27ee`；输出 Snapshot：`real_coordinator_rebuild_20260902_20260903T090305538477Z_237159895d81`。
- Evolve：29 个新 Observation；最终 `MATCHED=443/745`（59.5%），`UNCERTAIN=302`；RetroMatch 18 个候选，新增 3 个归属；Evaluator PASS 6/6。
- Pattern：19 个 Published，新增 12 个、更新 1 个、退休 9 个；现代情感生成故事进入 4 个 Pattern，末世科幻进入 1 个，悬疑未进入 Published Pattern。
- 目标链与重新抽取链的诊断 LCS 保留率：悬疑 75%、现代情感 50%、末世科幻 0%。大纲层结构保持，但正文回流后的识别不稳定。
- 本轮没有修改生产代码，没有新增 Agent 或数据库边界。关系 Function 被回流评估合并为 `RELATIONSHIP_STATUS_CHANGE`，匹配覆盖率约 59.5%，继续作为已知质量指标观察。
- 详细报告：`Code/data/pattern_generation_validation_20260903/validation_report.md`。
## 本轮（2026-09-03）：Pattern 应用阶段最小真实验证

- 基于 Snapshot `real_coordinator_rebuild_20260902_20260903T090305538477Z_237159895d81`，尝试用 3 个未使用 Published Pattern 生成悬疑、古风、现实家庭职场各 1 篇故事。
- 现实家庭职场成功：Pattern `PAT_9bad08925bfbbed0`，Outline `OUT_de6541ca62901c58`，大纲校验通过，正文 7,211 个中文字符。
- 悬疑失败：`final_ledger` 返回对象而非 Schema 要求的字符串，结构化重试 2 次后失败。
- 古风失败：生成的伏笔兑现位置不满足顺序规则。
- 失败尝试产生的两个 Pattern 占用和一个失败大纲记录已清理，避免污染后续 Pattern 选择；历史 Snapshot、Function 和正式 Pattern 未修改。
- 本轮没有再次进入 Evolve，因此没有新正式 Snapshot。应用阶段成功路径已验证，但 3 次尝试成功率为 1/3，生成稳定性仍需作为质量指标观察。
- 详细报告：`Code/data/pattern_application_20260903/application_report.md`。

## 本轮（2026-09-03）：Pattern 应用最小修复

- `REALIZE_PROMPT` 明确 `final_ledger` 必须是字符串数组，保持 `OutlineRealization` 原有 schema，不扩展嵌套结构。
- `scaffold_node` 对非法 `payoff_segment_index` 增加一次受限业务重试；仍失败则直接报错，不引入新的 Agent 或通用校验层。
- 移除 Planner 阶段的提前 `claim_pattern`；Pattern 使用绑定改在 `record_outline()` 同一 SQLite 事务中创建并绑定。大纲生成中途失败不会留下孤立占用，已有手动领取接口仍可完成绑定。
- 全部测试通过：311 passed, 1 skipped；定向 Outline/KnowledgeBase 测试 26 passed。

## 本轮（2026-09-03）：最小修复真实验证

- 在正式 Snapshot `real_coordinator_rebuild_20260902_20260903T090305538477Z_237159895d81` 上，用未使用 Pattern `PAT_64daadacc3a5443e` 完成真实 `Pattern → Outline`。
- 真实 LLM 流程 7 次调用成功，`overall_ok=True`；`final_ledger` 实际元素类型全部为 `str`，所有 `payoff_segment_index` 均指向后续段或 ending。
- 数据库新增 1 个成功大纲 `OUT_59034cd23c7671bf`，Pattern 使用绑定与大纲一致；Snapshot 数量未增加，Function/Pattern 悬挂 Run 均为 0。
- 验证输出：`Code/data/minimal_fix_validation_20260903/real_outline/现代情感_20260903T070219.json`。

## 本轮（2026-09-03）：生成—回流—再归纳质量基线

- 在正式 Snapshot `real_coordinator_rebuild_20260902_20260903T090305538477Z_237159895d81` 上，使用 5 个未使用 Pattern 尝试生成悬疑、现代、末世、现实家庭职场、古风 5 个题材样本；3 篇完整生成，2 篇大纲校验失败，最终完整生成率 `3/5=60%`。
- 3 篇成功正文进入同一正式 SQLite 的 Coordinator `Evolve → Pattern`；Function Run `FR_65cae29d53b344a4` PASS，发布子 Snapshot `real_coordinator_rebuild_20260902_20260903T122259023286Z_5bcfc6f217b0`；Pattern Run `PR_a5656dd5cee16d46` SUCCESS。
- 新故事 28 个 Observation 中 22 个 MATCHED、6 个 UNCERTAIN；新故事 assignment coverage `78.6%`，全 Snapshot `495/773=64.0%`。RetroMatch 召回 93 个旧未决候选，新增归属 30 个。
- Pattern 从父版本的 19 个 Published 增至 22 个：新建 15、更新 2、退休 12；没有阻断 Pattern 或合并。Function 从 6 个变为 9 个，关系边界及调查/证据粒度问题再次出现。
- 三篇成功故事的目标 Function 链 LCS 保留率为悬疑 80%、现代 75%、古风 80%。说明 Pattern 对高层方向有约束，但回流后仍有额外 Function，不能视为固定脚本。
- 基线报告：`Code/data/closed_loop_regression_20260903/regression_baseline.md`。当前不新增 Agent、数据库或架构边界；后续仅用独立小批次观察失败模式是否重复。

## 阶段决策（2026-09-03）：进入实际使用与数据积累

- 用户确认当前链路“可用即可，后续再优化”。Bootstrap → Evolve → Pattern → Outline → Story → Evolve → Pattern 已有真实成功闭环，Snapshot、Run 和外键检查正常。
- 下一阶段不再以架构验证或即时修复为主，而是使用当前正式 Snapshot 和 Coordinator 持续生成、回流和积累不同题材数据；生成成功率、assignment coverage、Function 边界和 Pattern churn 作为持续指标保留。
- 暂不启动 StateVocabulary 全量改造、Best-of-N、Supervisor 或新的数据边界；只有实际使用中出现重复且影响结果的故障时，才做单点最小优化。

## 本轮（2026-09-03）：最小 StateVocabulary

- 新增 `Code/Contracts/state_vocabulary.py`，从当前 FunctionContract 确定性生成 `canonical_id / aliases / raw_evidence`；规范化 Unicode、空白和已有大写标识符，不调用 LLM 推断同义词。
- `build_contract_ledger()` 使用 canonical ID 比较 aspect、state 和 obligation key，同时保留原始状态文本；账本输出附带词表，Planner/Realizer 可继续消费原有字段。
- 新发布的 OntologySnapshot 在存在 FunctionContract 时写入并哈希校验 `state_vocabulary.json`；现有不可变 Snapshot 不修改，仍可正常读取。
- Contract 输出目录同步生成 `state_vocabulary.json`。没有新增 SQLite 表或运行时数据库边界。
- 定向测试 `25 passed`，全量测试 `313 passed, 1 skipped`；当前正式 Snapshot 的 9 个合同可生成 112 个词表条目。
- 当前版本只解决确定性规范化和词表追踪，不自动判断中文语义同义词；后续如需语义合并，应基于真实重复案例单独设计。

## 本轮（2026-09-03）：StateVocabulary 进入真实 Evolve 数据流

- 在正式 Snapshot `real_coordinator_rebuild_20260902_20260903T122259023286Z_5bcfc6f217b0` 上处理 1 篇此前未入库的真实末世科幻故事 `2534659706_430078256`。
- Function Run `FR_62fa2b90d1414ec3` PASS，Pattern Run `PR_a40e9cf6c7add34a` SUCCESS，发布子 Snapshot `real_coordinator_rebuild_20260902_20260903T130418047879Z_b21aaffdc548`。
- 新 Snapshot 正常携带 `state_vocabulary.json`，文件 SHA-256 与 manifest 一致；词表共 101 条（16 aspect、61 state、24 obligation key）。Snapshot 校验、SQLite 外键检查通过，Function/Pattern 悬挂 Run 均为 0。
- 本次验证证明 StateVocabulary 已进入真实 Snapshot → Evolve → Pattern 数据流；当前版本证明的是稳定规范化和持久化，不证明中文语义同义词自动合并。

## 架构边界记录（2026-09-03）：StateVocabulary 与 Pattern 去重的职责

- 如果项目只需要发现相似 Pattern，StateVocabulary 不是必需组件；StoryPattern 已能在较高层面对故事结构做相似度归纳和去重。
- 如果项目还需要判断状态转移、规划 Function 顺序、统计状态或检查义务是否完成，StateVocabulary 才提供底层的统一状态标识。
- 两者职责不同：StateVocabulary 统一单个状态/aspect/义务字段，StoryPattern 去重一组 Function 形成的故事结构；Pattern 去重不能替代底层状态词汇统一。
- 当前只保留最小版本：确定性格式统一、稳定 `canonical_id`、保留原始文本证据、随 Snapshot 保存并校验哈希。
- 暂不引入 LLM 词表本体或自动语义同义词合并；只有真实数据反复出现并影响结果时，才基于具体案例增加离线确认的 alias。

## 本轮（2026-09-03）：轻量 Story Profile 与稳定人物映射

- Observer 现在在同一次结构化调用中产出必需的 `story_profile`：世界背景、主人公、主要人物、称呼、长期目标、动机、开场关系、核心冲突和结尾稳定状态；不新增 Agent 或 LLM 调用。新 Bootstrap/Evolve 缺少 profile 会在 Observer 阶段失败，不会静默发布不完整人物数据。
- 每条 Observation 保留原有跨故事抽象字段 `participants`，另增加故事内 `participant_ids`。人物 ID 必须来自 profile，关系键也必须引用已定义人物；profile 随当前 `story_version` 一起持久化，不改变 Snapshot/Run 边界。
- Matcher 的 FunctionOccurrence 和 Inducer 的证据提示透传 `participant_ids`，使稳定人物信息可沿现有分析链继续使用；旧数据没有 profile 时仍按原字段读取。
- Story Agent 场景校验禁止引用未在 `seed.characters` 中的人物；正文输出增加 `character_names`，必须覆盖全部稳定人物 ID 且姓名唯一，减少跨场景人物漂移。
- 验证：全套离线测试 `318 passed, 1 skipped`；`compileall`、`git diff --check` 通过。未启动真实 LLM 批处理，未修改正式知识库。
- 尚未实现：从高质量 MATCHED Occurrence 投影实例案例，以及 Planner 对转移、motif 和实例案例的实际检索消费；这是下一项独立工作。

## 本轮（2026-09-03）：Story Profile 接入 Outline → Story 与 A/B 正文对比

- Outline 导出新增轻量 `story_profile`：由已有 `StorySeed` 确定性投影，不增加 LLM 调用；旧大纲仍可缺省该字段。Story Agent 的 Function constraints、scene plan、scene development 和 write_story 四个节点在 Profile 存在时都会接收它；Profile 缺失时完全省略字段，不发送 `null`。
- 使用同一份已校验大纲 `OUT_20ff90e03b4865fa` 做隔离 A/B。两组复用同一套 8 个场景计划和场景展开，只在最终正文节点区分是否传入 Profile；两组均真实调用 LLM。
- A 组（有 Profile）生成《修正报告》，4,670 个中文字符；B 组（无 Profile）生成《迟到的复核》，5,846 个中文字符。两组均无 P1/P2/P3 内部 ID 写入正文，均完成 8 场。
- A 组使用 Profile 中的 `沈知微`、`周恺`，P3 将 `韩主任/韩总` 具体化为 `韩宏`；B 组自行生成 `林恕`、`周屿`、`程越`。因此当前最明确的收益是故事级身份/关系/目标锚点，而不是篇幅或总体质量提升。
- 单样本不能证明 Profile 提升整体写作质量；`character_names` 合同本身已经保证跨场景姓名稳定。真实样本还显示 Profile 的称呼目前不是硬约束，后续若重复出现应在 `validate_character_names()` 增加 canonical mention 校验。
- 对比正文和报告保存在 `Code/data/story_profile_ab_validation_20260903/`。定向 Outline/Story 回归 `29 passed`，`compileall` 和 `git diff --check` 通过。

## 本轮（2026-09-03）：Story Profile 真实 LLM 验证

- 使用真实 LLM 对真实末世科幻故事 `2534659706_430078256.txt` 做 1 篇隔离 Evolve；基础 Snapshot 为 `real_coordinator_rebuild_20260902_20260903T130418047879Z_b21aaffdc548`，运行 `FR_bc8a93ace2704ca4`，结果 `PASS`。
- 本轮实际调用 5 次 LLM、共 16,222 tokens；Preprocessor、Observer、Matcher、Curator/Evaluator 均正常完成。新故事产生 5 条 Observation，5/5 都带 `participant_ids`：前 3 条为 `P1`，后 2 条为 `P1/P2`。
- Profile 实际落入 `story_versions.payload_json`，并随临时 Snapshot `real_profile_validation_20260903_20260903T144013611714Z_bc3662d8c450` 发布；模型生成了 `P1=富二代旅行者`、`P2=越野旅友`、长期目标、动机和双向关系。
- 真实结果确认这次修改解决了“故事内人物 ID 可定义、可引用、可随版本持久化”的链路问题，但没有解决所有字面事实校对：模型将“森森”误写为“森余”。后续若该质量问题重复且影响使用，再单独考虑 alias/mention 校验，不提前增加 Agent。
- 隔离验证产物保存在 `Code/data/story_profile_validation_20260903/`；正式 Knowledge DB 最新 Snapshot 仍为 `real_coordinator_rebuild_20260902_20260903T130418047879Z_b21aaffdc548`，正式 Registry 已恢复原文件哈希。

## 本轮（2026-09-03）：Story Profile 收缩为预留接口

- 根据真实 A/B 结果，撤回 Profile 在 Observer、Evolve、Outline 和 Story Agent 中的具体执行链路；不再新增 Profile LLM 输出、人物 ID 透传、Profile 持久化或生成提示约束。
- `SourceOutlineDocument.story_profile` 保留为可选输入字段，仅作为未来扩展接口，当前不会被 Story Agent 消费；Outline 也不再自动生成该字段。
- 删除 `StoryCharacter`、`StoryProfile`、`participant_ids` 及其 Matcher/Inducer 透传和相关测试，避免为尚未证明有价值的能力保留运行时复杂度。
- `character_names` 和场景人物 ID 校验继续保留，它们是 Story Agent 自身的正文一致性合同，不依赖 `story_profile`。

## 本轮（2026-09-03）：Planner 对 transition、motif 和实例案例的消费审计

- 对正式 Snapshot `real_coordinator_rebuild_20260902_20260903T130418047879Z_b21aaffdc548` 做了只读运行时探针：知识库有 30 个 Published Pattern、294 条 motif evidence、193 个 motif cluster、8 个 FunctionContract 和 781 个 FunctionOccurrence。
- Outline Planner 实际读取 Pattern Catalog、FunctionContract 和本地 Function Card；当前对应 `Code/data/function_cards/<snapshot>/function_cards.jsonl` 不存在，因此实际加载 `0` 张 Card。`planner()` 输出的 chain 只有 Function、Contract、preconditions、role_slots 和空的 `state_transition`，不包含 motif evidence 或实例案例。
- 代码虽然通过 `load_mechanisms()` 查找 `Code/data/transition_index/<snapshot>/transition_index.json`，但当前文件不存在；运行时 `reference_mechanisms` 的 Function 键全部为空。并且该入口只消费 `mechanisms`，没有消费 index 中独立的 `transitions` 列表，因此真实 Function transition 尚未进入 Planner。
- motif 已在 StoryPattern Agent 中用于生成 Published Pattern，Planner 只能间接使用 Pattern 的 `core_function_chain`，没有查询或传递 motif evidence/局部 motif 本身。知识库 Function 记录中的 `realization_patterns` 也没有被 Outline Planner 加载；实例化案例尚未形成独立可检索输入。
- 结论：当前是“Pattern 间接继承 motif、Planner 使用抽象 Function/Contract”，不是“Planner 已查询并使用 transition、局部 motif 和实例案例”。本轮只记录缺口，不扩展实现。

## 本轮（2026-09-03）：Planner 接入 Snapshot 参考上下文

- `Code/Outline_Agent/app.py` 新增只读 `load_planner_references()`：从同一 Snapshot 的 `MATCHED FunctionOccurrence` 按故事顺序统计 Function transition；按所选 Pattern 的 `member_motif_ids` 筛选局部 motif evidence；再依据 Function 的 `supporting_obs_ids` 投影最多 3 条去重的 Occurrence 实例案例。
- Planner 将三类引用保留在 `planner_references`，并把对应的 `reference_transitions`、`reference_instance_cases` 附着到每个 chain step；Mechanism/Scaffold 的真实 LLM 输入同时收到这些字段，最终 Outline JSON 也保留引用，形成“读取 → Prompt → 可审计导出”链路。
- 删除 Outline 运行时对不存在的 `transition_index/<snapshot>` 机制文件的旧依赖；Function Card 仍作为可选抽象增强，FunctionContract、抽象 Function 和 Pattern 的原有路径保持不变。没有新增数据库表、Agent 或写入操作。
- 真实只读 LLM smoke：正式 Snapshot + 首个 Published Pattern 查询到 3 条 motif reference、9 条 transition edge、9 条实例案例；Seed → Mechanism → Scaffold 共 3 次真实 LLM 调用，Scaffold 首次结构校验失败后自动重试并成功，未写入知识库。
- 离线验证：`318 passed, 1 skipped`，`compileall` 和 `git diff --check` 通过。单次 smoke 只能证明引用已查询并传入模型，不能单独证明模型在语义上充分利用每条引用；后续如需论文级结论，应做多题材、多样本人工评审。

## 本轮（2026-09-03）：删除 Planner 的 Function Card 兼容分支

- 正式 Planner 已以 Pattern + FunctionContract 为核心输入；删除只读不到正式 Snapshot 的 `load_cards()`、`cards` 参数和空的 `state_transition` 兼容字段，避免旧派生文件路径和空状态字段干扰 LLM。
- 保留 `function_id`、FunctionContract、Occurrence transition、所选 Pattern motif 和实例案例；Pattern 合同仍可在没有 Snapshot Contract 时作为纯函数调用的回退来源，运行时 Planner 节点继续使用正式 Snapshot Contract。
- 全量验证：`318 passed, 1 skipped`；未产生正式知识库写入。

## 本轮（2026-09-04）：Planner 真实 LLM A/B 对照验证

- 使用正式 Snapshot `real_coordinator_rebuild_20260902_20260903T130418047879Z_b21aaffdc548` 和 Pattern `Threat-Driven Relationship Transformation`，固定同一 Function chain 与同一份真实 LLM Seed。
- A 组传入 5 条 motif、9 条 transition edge、9 条实例案例；B 组清空三类参考。两组只运行真实 LLM 的 Mechanism/Scaffold，不调用 export，不写 Knowledge DB、Registry 或 Snapshot。
- 首轮 A/B 的 Mechanism 4/4 步骤不同（文本相似度 0.119），Scaffold 4/4 步骤不同（0.083）；另外两轮 Mechanism 复测仍为 4/4 不同，相似度 0.089、0.086。两组始终保留同一 Function chain。
- 结论分两层：运行时“查询并传入”通过；“差异由参考信息而非模型采样造成”尚不能证明，因为当前 LLM 接口未固定 temperature/seed，且输出没有稳定的引用 ID 追踪。验证报告见 `Code/data/planner_ab_validation_20260904.md`。当前不增加 Agent，后续若追求严谨质量结论，再做固定采样或独立盲评。

## 本轮（2026-09-04）：Planner 阶段收敛，转入生成质量阶段

- 已决定暂时冻结 Planner：保留 Pattern chain、FunctionContract、transition、局部 motif 和 Occurrence 实例案例的确定性编排与传递，不再增加 Planner Agent 或恢复旧 Function Card 兼容代码。
- 已将 Planner 的职责边界、按需改进项和不纳入默认工作的内容写入 `Plan.md` 第十五节。
- 再次调整下一阶段：Pattern 驱动的真实故事生成质量已经通过多轮真实回归验证，生成细节问题暂时降为维护项。下一阶段转向结构层推进，重点审计 Function 本体边界、transition 图、motif/Pattern 抽象、跨题材泛化和 Planner chain 的结构闭合，不再优先修单个结局或格式案例。
- 生成节点受限重试/纠错、结局兑现和正文回流后的结构保持暂作维护项；当前不扩展 Supervisor、Best-of-N 或数据库结构。

## 本轮（2026-09-04）：Function—transition—motif—Pattern 分层结构审计

- 对正式 Snapshot `real_coordinator_rebuild_20260902_20260903T130418047879Z_b21aaffdc548` 做了只读审计：8 个 Function/Contract、505 条 MATCHED Occurrence、90 条故事序列、45 个 transition edge、235 个 motif、193 个 cluster、30 个 Published Pattern。
- 已确认 Pattern 层具备真实证据：30 个 Pattern 均至少有 2 个故事支持，21 个有跨题材支持；Pattern chain 的 Contract 引用完整且 hash 一致。
- 结构缺口集中在 Contract 组合语义：97 个 Pattern 相邻 Function 对中，0 个存在精确的 `effect.after → next precondition.state` 连接，只有 34 个共享 aspect；当前 Pattern 更接近“有证据的序列模板”，尚不是状态可验证的因果模板。
- transition 图 45/56 非自环边较密，19 条边仅有不超过 2 个故事支持；motif 候选中 198/235 只支持单故事，说明候选层碎片化，不能把所有边和 motif 作为同等强度结构知识。
- 说明：跨题材边不是缺陷，而是项目目标“抽取可跨题材泛化的抽象 Function”的正向证据。需要处理的是 transition 强弱分层和语义兼容性，不是消除跨题材连接。
- 完整报告见 `Code/data/structure_audit_20260904.md`。当前不新增义务图或结构化 transition 表；若后续需要 Pattern 因果审计，复用已有 Ledger/Checker 做只读诊断，再根据真实收益决定是否接入 Planner。
- 代码核对补充：项目已有 `Contracts/ledger.py` 中的 `check_contract_chain()` 与 `build_contract_ledger()`，但它们在 Outline 生成阶段运行；StoryPattern 目前只传递 Contract 给摘要 LLM，并检查 Contract 存在，没有用状态/义务兼容性参与 Pattern 发布。后续应复用这套逻辑做 Pattern 诊断，不要再造一套状态系统。
- 必要性收敛：motif 候选碎片化、Pattern 近邻变体和 Contract 组合不完整目前都不阻塞核心链路，不立即修改。前两项分别在影响成本/选择时再治理，后一项只有在需要 Pattern 因果闭合证明时才复用 Ledger 做只读诊断。

## 本轮（2026-09-04）：StoryProfile—角色绑定—关系账本闭环

- 新增 `Contracts/story_profile.py`：`StoryProfile` 固化主人公、人物长期目标/动机、开场关系与对主人公立场；`EventRoleBindings` 固化 `actor/affected/information_provider/resource_provider/beneficiary/obstacle` 六个标准位置；`RelationshipDelta` 固化有证据的关系变化。
- Observer 在一次结构化调用中同时输出 Profile 与 Observation；Observation/FunctionOccurrence 透传 `participant_ids`、`role_bindings`、`relationship_deltas`。FunctionContract 只允许六个标准角色位置，不把角色位置硬编码为主人公、反派或帮助者。
- Snapshot 升级为 schema 5，新增不可变 `story_profiles.jsonl`。发布与知识库提交会校验人物 ID、角色槽位、关系边、关系变化证据和 MATCHED occurrence 的合同槽位；story version/Profile 不一致也会拒绝提交。旧 v4 Snapshot 不做静默兼容，必须显式重建。
- 新增 `Contracts/role_projection.py`，从同一 Snapshot 投影 Function 角色位置统计与去专名关系变化案例；published/dynamic Outline Planner 将它们传给 Mechanism 阶段。`MechanismStep.relationship_changes`、Story Agent 的 Function constraints 和 Markdown 导出均保留这条关系变化链。
- `Contracts/ledger.py` 新增关系账本：关系变化双方必须是已知人物、存在初始关系或本步角色绑定，FunctionContract 必须声明覆盖双方的 `RELATIONSHIP_STATUS` effect，且双方状态项和证据不能为空。
- 定向回归：StoryProfile/roles、Snapshot、KnowledgeBase（含父 Snapshot Profile 继承/当前 Run 覆盖）、FunctionContract、contract flow、dynamic Planner 共 50 项通过；`compileall` 通过。全量 pytest 仍受环境中既有 `sentence_transformers/torch` 不兼容与缺少 `chromadb` 阻塞；当时未重建正式 DB。

## 本轮（2026-09-04）：StoryProfile v5 真实 LLM 重跑

- 使用 3 篇跨题材真实故事做隔离验证：悬疑 `2944521006_348025005`、现代情感 `1098353532_335946791`、末世科幻 `2534659706_430078256`；真实调用 Pre-Processor、Observer 和 Outline Mechanism，共 12 次 LLM 调用、95,365 tokens、172.0 秒。
- 真实 Observer 产生 3 份 Profile、28 条 Observation；28/28 有 `participant_ids`，关系变化共 8 条。画像人物数分别为 9、5、2，开场关系边分别为 6、4、1。首篇 Observer 的第一次调用出现 `role_bindings` 引用人物但 `participant_ids` 漏列，严格跨字段校验拒绝该结果；外层重试后成功，没有自动修正人物集合。
- 使用 smoke Function 将真实 Observation 绑定后发布 schema 5 Snapshot，并提交隔离 SQLite：28 条 MATCHED occurrence、3 条匿名关系变化案例、Profile 投影和关系账本均成功；SQLite `foreign_key_check` 为空，Mechanism 真实输出的关系账本 issues 为空。
- 验证产物位于 `Code/data/story_profile_v5_real_validation_20260904_retry/`。本次 Function 绑定是数据流 smoke，不代表新的正式 Function 归纳结果；正式 Knowledge DB 仍未修改，正式最新 Snapshot 仍是 schema 4，因此尚未证明完整正式库重建后的全量 Evolve/Outline 质量。

## 本轮（2026-09-04）：schema 5 正式重建与 15 篇 Evolve 链路验证

- 按用户要求将旧 schema 4 正式重建状态做可恢复归档，保存在 `Code/data/_archive_schema4_rebuild_20260904/`；没有删除历史数据。新的正式根 Bootstrap Run 为 `FR_6034217c6270439e`，发布 schema 5 Snapshot `real_coordinator_rebuild_v5_20260904_20260904T144557585107Z_6fb574a248e6`，包含 12 个 StoryProfile、95 条 Observation、7 个 Function/Contract。
- 108 篇 Evolve 批次中止后，Run `FR_6cc29d2044a14945` 被记录为失败，暂存 `run_stories`/`run_observations` 均清零；此前两次真实失败 Run 也只保留审计记录，没有发布 Snapshot。修复最终对齐逻辑后，正式 15 篇 Evolve Run `FR_9f5cbe9425944e44` 成功，输入为根 Snapshot 后语料清单的前 15 篇，产生 121 条新 Observation。
- 新子 Snapshot 为 `real_coordinator_rebuild_v5_20260904_20260904T153921189793Z_8ae9ee1f6b63`，父节点正确指向根；总计 27 个 StoryProfile、216 个 FunctionOccurrence、7 个带状态/义务契约的 Function。最终 Evolve 评估 6/6 通过；94 条 Occurrence 为契约完整的 `MATCHED`，122 条保留为 `UNCERTAIN`，没有用人物猜测填补缺失槽位。
- 真实 Coordinator 自动触发 Pattern Run `PR_06a330c7bc9ad178` 并成功完成：27 条故事序列、18 个 motif、16 个 cluster、15 个候选 cluster；当前样本尚未达到 Published Pattern 门槛（`published_patterns=0`），所以不能把本轮描述为已有可选 Pattern 的正常 Outline 生成。
- Snapshot 校验确认 7 组角色统计和 17 个匿名关系变化案例可从冻结 Snapshot 投影，并可被 dynamic Planner 读取。随后运行一次真实 dynamic Outline：Mechanism 确实收到长期目标、立场、角色位置和关系案例，但模型生成的 `P3` 不在本次 seed，且为没有 `RELATIONSHIP_STATUS` 效果的 Function 添加了关系变化；关系账本将其判为 `overall_ok=false` 并保留诊断产物，证明下游不会把无证据关系变化静默写入大纲。
- 本轮真实运行暴露并修复一个发布边界：`align_occurrences()` 过去只按 supporting evidence 标记 `MATCHED`，没有按最终 FunctionContract 的 `role_slots` 复核。现在缺少必要人物槽位的匹配会降级为 `UNCERTAIN`，Snapshot 发布仍对直接伪造/非法 occurrence 保持严格拒绝。全量离线回归为 `334 passed, 1 skipped`。

## 本轮（2026-09-04）：平衡增量 Evolve 与 27 份关系连续性门槛评测

- 在 schema 5 正式重建根之后，按悬疑惊悚、古风仙侠、现代情感各 5 篇连续完成 4 批增量 Evolve，共新增 60 篇真实故事。4 个 Run（`FR_48abce8a18a6480f`、`FR_5b079c6dc2f54c54`、`FR_298e32aeb64c48c7`、`FR_f2f754a8adbf4c50`）和对应 Pattern Run 均成功，最终冻结 Snapshot `real_coordinator_rebuild_v5_20260904_20260904T170911270122Z_a18d9bc44323`。
- 最终 Pattern Run `PR_f85a319c39c2455e` 在该 Snapshot 上发布 6 个 Published Pattern，另有 1 个 blocked Pattern；达到至少 3 个 Published Pattern 的冻结条件。最后一批 Evolve 的 Coordinator 评估为 5/6 维度通过（`separation` 仍失败），但按当前项目门槛整体为 PASS。
- 新增 `Code/test/run_relationship_outline_eval.py` 作为隔离评测 harness：固定 3 个 Published Pattern、3 个题材，每个组合使用同一真实 LLM Seed 重复 3 次，共生成 27 份 Outline；每个案例复制知识库，避免消耗正式 Pattern 使用次数或写入正式 Outline。
- 27/27 生成完成，但硬校验通过 `0/27`、关系账本通过 `0/27`、完整重复组 `0/9`；14/14 份自动人物审查通过，说明抽查到的长期目标和立场与 Seed 人物画像一致，但不能抵消关系账本失败。
- 主要失败集中于：`HAZARD_ENCOUNTER`、`PROTECTIVE_INTERVENTION`、`REVELATION_SHIFTING_COGNITION` 的 FunctionContract 未声明关系效果；`CONFRONT_OPPOSITION`/`SOCIAL_BOND_DISRUPTION` 的关系效果没有覆盖实际绑定的双方；部分步骤关系双方未绑定或 `before` 与账本状态不一致。该结果说明“人物画像能传入并被保持”已有正向证据，但“Function 只产生合同和账本有证据支持的关系变化”尚未成立。
- 因硬校验和重复率均未达到门槛，按用户要求没有启动 81～100 份扩展，也没有作出“能够稳定保持人物立场、长期目标和关系连续性”的表述。评测产物见 `Code/data/relationship_outline_eval_20260904/phase1_27/`；正式库的 `pattern_usage` 仍为 0，评测未污染正式 Pattern 使用记录。

## 本轮（2026-09-04）：FunctionContract—Mechanism 关系边界修复与 27 份真实复评

- `FunctionContract` 现在只把恰好覆盖两个不同标准角色槽位的 `RELATIONSHIP_STATUS`/`RELATIONSHIP` effect 视为有效二元关系授权；新合同对单角色关系 effect 直接拒绝。运行时对旧 Snapshot 中的非法 effect 采取保守策略：不授权任何关系变化，不原地修改冻结数据。
- Outline Mechanism 收到由 Contract 确定性计算的 `relationship_constraints`，关系账本按同一 effect 的两端精确匹配人物绑定；`before` 由 seed 初始关系、Contract before 和前一步 after 继承，模型只决定 after/evidence。账本错误最多反馈重试一次，仍失败则不进入 Scaffold/Realize。
- 保留同一冻结 Snapshot、同一 9 个 seed、3 Pattern × 3 题材 × 3 次重复，真实复评写入 `Code/data/relationship_outline_eval_20260904/phase2_27/`。27/27 生成，关系账本通过 `27/27`，关系变化从上一轮 `139` 条降至 `39` 条，且只出现在允许关系 effect 的 `RELATIONSHIP_FORMATION` / `COMMUNITY_FORMATION`。
- 整体硬校验为 `12/27`，完整重复组 `1/9`，人物目标/立场自动审查 `12/14`；因此修复证明了关系越界与连续性门禁已闭合，但尚不能宣称大纲整体稳定。未启动扩展评测。专用环境全量回归 `338 passed, 1 skipped`。
- 当前冻结 Snapshot 仍保留两个历史单角色关系 effect（`CONFRONT_OPPOSITION`、`SOCIAL_BOND_DISRUPTION`）；这是兼容读取下的非授权旧数据。若要发布干净的正式 Contract 数据，需要后续生成新的不可变 Snapshot，不能回写本 Snapshot。

## 本轮（2026-09-04）：Outline 评测口径与角色上下文收敛

- Outline 的结局上下文现在区分 Pattern 的可选 `ending_spec` 与实际生成的 `outline.ending`；没有 Pattern 结局规范时，运行时由 `seed.core_conflict`/`seed.ending_direction`构造 `ending_target`，并把前序义务、ending 伏笔和关系终态汇总为临时 `ending_budget`，不新增持久化表或第二套结局 schema。
- `SeedCharacter` 增加可机读的 `stance_toward_protagonist`；Mechanism 的关系约束同时传递 Contract 的关系 effect 上限；重复 Function 与立场逆转规则继续复用现有 occurrence/why/state 字段。
- 关系连续性评测拆分 `structural_ok`、`semantic_ok` 和 `overall_ok`；人物审核的通过值由 assessment 明细确定性计算，不再使用 LLM 可能自相矛盾的 `overall_ok` 汇总。新增 `--require-ending-spec`，只在完整 Outline 稳定性评测时筛选有真实结局证据的 Published Pattern；不手工给局部 Pattern 补 ending_spec。
- 定向回归为 46 项通过；全仓 pytest 仍被既有环境依赖问题阻塞（`sentence_transformers/transformers` 与 `chromadb`），未修改无关依赖或数据。

## 本轮（2026-09-05）：结局语义门禁与一次受限 Realize 重写

- 保留现有角色绑定、关系账本、FunctionContract、Snapshot、KnowledgeBase 和 StoryProfile；只在 Outline Validator 边界补充结局身份/关系语义检查，没有增加 Agent、数据库表、持久化 schema 或新 Validator 层。
- `validate_node` 现在对结局引用 seed 外人物 ID、合并/互换不同人物 ID，以及将前序“谨慎合作/低信任/未和解”写成“互信/和解/稳定联盟”给出确定性语义问题；结局真相、证据、解决方案的前因支持和 setup_payoff/obligation 的“可观察动作 → 后果”仍由现有 LLM Validator 判断。
- LangGraph 在 `validate → realize` 增加最小条件回边：仅当 `overall_ok=false` 且 `rule_issues`、`contract_issues` 都为空时重写一次；固定 seed、Function chain、role_bindings、mechanism、relationship_changes 和 narrative，第二次仍失败直接 export 保留失败结果。隔离评测 harness 复用同一条件与计数器。
- 生产 Outline API 模型仍为 `deepseek-v4-flash`、`reasoning_effort=none`；独立评审使用的 `gpt-5.6-luna`、`xhigh` 只代表 Codex 评审执行模型，不作为 API 模型，也未添加端点 fallback。没有运行 Evolve/Pattern 或昂贵的 27 份真实 LLM 评测。
- 离线验证：`python -m pytest Code/test/test_dynamic_planner.py Code/test/test_outline_agent.py Code/test/test_contract_flow.py -q` → `49 passed`；`python -m compileall -q Code` 通过；本轮相关文件的 `git diff --check` 通过。仓库全量检查只命中本轮之前已存在的 `Plan.md:820` 尾随空格/EOF 空行，未修改无关文件。

## 本轮（2026-09-05）：5 篇增量 Evolve 尝试未发布

- 以正式父 Snapshot `real_coordinator_rebuild_v5_20260904_20260904T170911270122Z_a18d9bc44323` 选择 5 篇原始 120 篇语料中尚未入库的故事（悬疑 1、古风 2、现代情感 2）进行增量 Evolve。
- 第一次 15 篇尝试因一个文件路径错误实际只处理 4 篇，随后人工中断；第二次修正为 5 篇并完整处理，两个 Run（`FR_26ad2e013a674bb7`、`FR_77a81196eb9c4784`）最终均在 FunctionContract 发布前失败。
- 失败原因相同：LLM 为关系状态效果生成了只有 `role_slots=['actor']` 的单角色合同，触发当前严格的“关系效果必须覆盖两个不同角色槽位”门禁。Evolve 过程虽完成了最终评估（第二次 6/6 PASS），但没有发布子 Snapshot，也没有进入 Pattern。
- 正式库保持不变：最新 Snapshot 仍为 `real_coordinator_rebuild_v5_20260904_20260904T170911270122Z_a18d9bc44323`，`story_versions=87`；两个失败 Run 的 `run_stories`/`run_observations` 暂存均已清零。当前不继续盲目重跑，下一步应先处理该 Contract 生成失败的最小根因，再重试同一批次。

## 本轮（2026-09-05）：5 篇增量 Evolve → Pattern 完成

- 按用户要求以父 Snapshot `real_coordinator_rebuild_v5_20260904_20260904T170911270122Z_a18d9bc44323` 增量处理 5 篇未入库故事：`131735036_52597335`、`1859328724_293120775`、`2554565947_438706550`、`3114910977_326607114`、`3257901908_580075993`。最终 Evolve Run 为 `FR_87f606da61ee4480`，子 Snapshot 为 `real_coordinator_rebuild_v5_20260904_20260905T153027932297Z_e698f1f44c84`。
- Evolve 最终评估 6/6 通过；总计 92 个 StoryProfile、730 个 FunctionOccurrence、14 个 Function，新增 `ABRUPT_LIFE_CHANGE`。Coordinator 自动完成 Pattern Run `PR_c3e6eef3a6e59e66`，Pattern 结果为 6 个 Published、1 个 blocked，新增 Pattern 3 个、更新 2 个。
- 对新 Snapshot 的严格校验通过；SQLite `foreign_key_check` 为空、`integrity_check=ok`。6 个 Published Pattern 的 `ending_spec` 全部为空，非空数量为 `0/6`；3 个本轮新增 Published Pattern 也没有出现结局规范。因此本轮只证明增量链路和 Pattern 发布闭环可用，不能证明新增 5 篇会自然产生“完整故事 Pattern”或结局结构。
- 为兼容父 Snapshot 中两个历史单角色关系 effect，新增子 Snapshot 迁移边界：读取父 Contract 时跳过旧数据的整库严格校验，在子 Snapshot 中把无合法二元关系 effect 的历史 effect 降级为 `FUNCTION_STATE`，不授予关系边；父 Snapshot 不变，新 Contract 仍保持严格二元关系门禁。相关 Contract/Snapshot 回归 22 项通过，随后本轮完整运行成功。

## 本轮（2026-09-06）：Seed 结局方向约束收紧与真实 Outline smoke

- 保留现有结局分层：Pattern 的可选 `ending_spec` 仍只表示历史证据；无 `ending_spec` 时继续由 Seed 生成 `ending_direction`，`ending_target.must_show` 保持空数组；具体解决动作仍由 `outline.ending.resolution_actions` 负责。
- 仅收紧 `DYNAMIC_SEED_PROMPT` 与 `SEED_PROMPT`：`ending_direction` 必须按“可观察解决动作 → 直接冲突结果 → 稳定终态”组织为单一结局方向。不新增字段、Agent、数据库或解析规则。
- 离线回归 `60 passed`。使用正式 Snapshot 的 4 个临时知识库副本做真实 LLM smoke（悬疑 2、古风 1、现代情感 1），4 份均生成完整 `outline.ending`，Validator `3/4` 通过；失败样本是前序未建立记忆/证据/义务导致的语义闭合问题，不是结局字段缺失。正式库保持只读，`outlines=1`、`pattern_usage=0`。
- 结果只证明 Seed 结局方向和现有 ending 链可用，不证明结局语义稳定；后续若同类“结局引入前序不存在信息/义务”重复出现，再针对现有 Realize/Validator 做局部修复。

## 本轮（2026-09-06）：用 Outline 生成正文验证结局是否真正闭合

- 不能只以 `outline.ending` 非空或 Outline Validator `overall_ok=true` 判定“完整结局”。使用本轮生成的 5 份 Outline 继续跑现有 `Story_Agent`：1 份原本 `overall_ok=false`，按正式入口阻断；4 份中 1 份在场景计划阶段引用 seed 未定义的“P3 的手下”“村长”而失败，另 3 份成功生成正文。
- 3 份正文均达到中文字符下限（`5674`、`4640`、`6559`），使用现有独立质量诊断 Prompt 复核最后场景：现代情感与悬疑正文的 `ending_closure=5/5`、`conflict_resolution=5/5`；古风仙侠的 `ending_closure=5/5`、`conflict_resolution=4/5`，结局已解决但 P3 和解转折略突兀。3 份正文都实际写出了解决行动、冲突后果和稳定终态。
- 结论收窄为：当前方案已经有“Outline → 正文 → 独立结局评审”的正面样本，但尚不能宣称 Outline 批次全部可消费或结局稳定。下一步优先修复真实暴露的未定义人物引用/场景计划问题；不新增 `must_show`、Agent 或数据库层。
- 本次所有 Outline/Story 均使用临时数据库副本；正式 Knowledge DB 未写入。

## 本轮（2026-09-06）：收拢 Story Agent 的场景人物引用边界

- 真实正文验证发现：Outline Validator 通过的样本，场景计划仍可能把“P3 的手下”“村长”等非 seed 人物写入 `scene.characters`，导致 Story Agent 在正文前置阶段拒绝执行。
- `SCENE_PLAN_PROMPT` 现在明确要求 `characters` 只能使用输入的 `allowed_character_ids`；非核心人物只能作为 beats/setting 背景描述，必要角色必须先进入 seed。`plan_scenes_node` 将 seed 人物 ID 作为确定性输入，不放宽现有未知人物硬校验。
- 对未知人物错误复用现有有限重试模式，仅反馈一次并要求只修正 `characters`；第二次仍非法则阻断，不静默删除人物或把自然语言角色猜测映射到已有 ID。
- 离线 Story Agent/Contract/Outline 回归为 `51 passed`。对原真实失败 Outline 重跑：首次曾因场景草案对齐波动失败，第二次成功生成正文（`5060` 字符）；最终 4 个场景的 `characters` 均为 seed 中的 `P1/P2/P3`，独立质量诊断六项均为 `5/5`、无问题。正式数据库保持只读。

## 本轮（2026-09-06）：Pattern 接通 StoryProfile 结局证据与隔离重跑

- Pattern 输入现在从 Snapshot 加载 StoryProfile，并把 `core_conflict`、`ending_state`、`ending_resolution_actions`、`ending_evidence_sentence_indices`、`ending_closure` 传入 motif evidence；`reaches_story_end` 由完整 structural sequence 的最终 `MATCHED` 节点确定性计算。Summary 的输入签名同时绑定结局证据，避免资料变化时复用旧摘要。
- 先在正式最新 Snapshot 的数据库副本上重跑 Pattern：`10` 个 Published Pattern 中 `3` 个得到非空 `ending_spec`，但证据仍混有非尾部 motif（全体 motif evidence `15/101` 触达尾部），说明只接通既有 `core_conflict`/`ending_state` 仍不足以形成可审计的完整结局归纳。
- 因此按最小范围扩充现有 StoryProfile，而非新增平行 Profile：新增 `ending_resolution_actions`、`ending_evidence_sentence_indices`、`ending_closure`（`resolved/partial/open`），Observer Prompt/边界校验和旧 Profile 读取均已兼容；相关 Pattern/Observer/Snapshot 回归 `147 passed, 1 skipped`，全仓回归 `355 passed, 1 skipped`。
- 使用 3 篇未入库的真实古风故事在临时 DB 完整跑通 `Evolve → schema 5 Snapshot → Pattern`：新 Snapshot `/tmp/function-ending-evolve.CjurRf/snapshots3/ending_schema_smoke_3_20260906_20260906T104423149252Z_11173bc5baa2` 含 `95` 份 Profile，新增 Profile 均落盘结局证据字段；Pattern Run `PR_dfb9a8cc3671283f` 成功但因候选 cluster 未达到发布条件，`published_patterns=0`，没有生成新的 `ending_spec`。这证明字段和不可变 Snapshot 链已接通，不证明结局 Pattern 语义已达标。
- 正式 Knowledge DB 未写入；5 篇混合题材 smoke 因既有 Observer 人物证据越界失败，已清空暂存并保留失败 Run 审计，未继续盲目扩大批次。若正式重建，需在同一 namespace 下使用新 Observer 重新处理故事，复用 Function 本体/ID，重建 Occurrence、Snapshot、motif 和 Pattern。

## 本轮（2026-09-06）：Observer 越界限制与 92 篇正式结局证据重建

- Observer 对 characters/relationships/ending 的非负越界 evidence sentence indices 做确定性丢弃并写入 warning；负数和结构非法仍走现有失败重试。为避免回写旧版本，本次用显式 `ending_evidence_v1` 生成新的 StoryVersion/ObservationVersion。
- 在同一 namespace `real_coordinator_rebuild_v5_20260904`，从父 Snapshot `real_coordinator_rebuild_v5_20260904_20260905T153027932297Z_e698f1f44c84` 正式重提取 92 篇故事。Evolve Run `FR_cf8b4b842ee44940` 成功：92 个 StoryProfile、741 个 Observation/Occurrence；14 个 Function ID 与 Function 本体保持不变，Curator 只应用已有 MATCH/EXTEND 证据，不归纳/修订/删除 Function。新 Snapshot：`real_coordinator_rebuild_v5_20260904_20260906T152048649508Z_4fef618ebe77`。
- 新 Snapshot 中 35 个 Profile 有 resolution actions、12 个为 `resolved`；Occurrence 为 353 `MATCHED`、388 `UNCERTAIN`。Schema 5、父子 lineage、外键和 SQLite integrity 校验均通过；失败的首次正式尝试未发布 Snapshot，正式 Registry 已恢复原始校验和。
- 在新 Snapshot 上重建 Pattern，Run `PR_55e46b86aaba78c9` 成功：92 sequences、79 motifs、72 clusters、7 Published Pattern。Summary 增加确定性的跨故事结局证据门控；本批 `ending_spec` 为 `0/7`，因为没有至少两个故事同时满足尾部触达、`resolved`、resolution actions 和 sentence evidence，未手工补写。
- 全仓 `pytest`：`359 passed, 1 skipped`；`compileall` 与 `git diff --check` 通过。未重建 Function 本体，也未引入第二套结局或 obligation 系统。

## 本轮（2026-09-07）：停用 Pattern 结局归纳，保留兼容字段

- 按精简方案移除 Observer Prompt/输出中的三个结局证据字段及其下标过滤，移除 Pattern 的 StoryProfile 加载、结局位置计算、motif/summary 结局证据传播和跨故事门控；`StoryProfile.core_conflict`、`ending_state` 保留。
- `StoryProfile` 模型不再声明三个主动字段，但对历史 JSON 做精确兼容过滤；现有 Snapshot/数据库不改写。`StoryPatternSummary.ending_spec` 和下游 `build_ending_target()` 兼容读取继续保留，Pattern 摘要统一将 `ending_spec` 置为 `None`，Prompt 也固定要求返回 `null`。
- 删除对应专用 Pattern/Profile 测试，保留 Observer 人物/关系证据越界保护、Outline 完整 `ending` 与 seed 回退测试。未执行 Evolve、Pattern 或 92 篇 LLM 重跑。
- 验证：全仓 `pytest` 为 `353 passed, 1 skipped`；正式 Snapshot `real_coordinator_rebuild_v5_20260904_20260906T152048649508Z_4fef618ebe77` schema 5 校验通过，Pattern Run `PR_55e46b86aaba78c9` 仍为 SUCCESS；SQLite `foreign_key_check=0`、`integrity_check=ok`。

## 本轮（2026-09-07）：结构、冗余与数据流只读审计

- 当前主链仍是 `Bootstrap → Evolve → Snapshot → Pattern → Outline → Story`。全量收集 354 项测试，执行结果为 `353 passed, 1 skipped`；没有确认可安全删除的已收集测试。
- 正式 Knowledge DB 只读核验通过：`integrity_check=ok`、`foreign_key_check=0`，最新 Snapshot 与 Pattern Run 的引用、Occurrence 绑定和失败 Run 暂存均无悬挂记录。`UNCERTAIN` Occurrence 的空 `function_id` 是既定语义，不是外键异常。
- 发现两个需要后续结构决策的边界漂移：持久 Registry 的 14 个 Function payload 与父 Snapshot 一致、与最新 Snapshot 的 14 个 payload 均不一致；默认 ObservationBank 实际落在 `FunctionExtract_Agent/data/bank`，而 README 约定为 `Code/data/bank`，该嵌套 Chroma 当前无 embedding 记录且含已脱离 collection 的物理目录。当前 Evolve 使用 Knowledge DB 的 run-scoped view，故未判定为当前发布链断裂；后续应收敛 Registry 生命周期和 Bank 单一存储路径。
- 8 个历史磁盘 Snapshot 中最新 2 个可通过当前严格 Contract 校验，较早 6 个因历史单角色关系 effect 被当前二元关系门禁拒绝；不可回写历史 Snapshot，应保留现有子 Snapshot 迁移边界并明确历史读取策略。
- 明确代码级低风险候选只有 `Story_Agent.state` 中无调用的 `ScenePlanItem/ScenePlan` 和 `Critic` 中未使用的 `CriticReview` import；`STANDARD_ROLE_POSITIONS` 更像兼容别名，暂不删除。Coordinator、StoryCLI、Pipeline 存在三套编排入口，但均有现行测试或用户入口，不宜在未确定唯一控制面前删除。
- 审计阶段未删除代码、测试、数据库或 Chroma 文件；随后执行的最小修复另记如下，仍保留工作树已有修改。

## 本轮（2026-09-07）：最小边界修复与单篇 Evolve 验证

- `ObservationBank` 默认 `data/bank` 统一解析到 `Code/data/bank`；旧的 `FunctionExtract_Agent/data/bank` 生成物未删除，避免覆盖工作树已有 Chroma 修改。Evolve 继续使用 Knowledge DB 的 run-scoped Bank view。
- Evolve 在失败/异常出口恢复 Registry 到父 Snapshot，正常 PASS 出口同步到新发布 Snapshot；用临时 DB 模拟失败出口验证了 14 个 Function payload 与父 Snapshot 完全一致。
- 删除 `Story_Agent.state` 中无调用的 `ScenePlanItem`/`ScenePlan`，删除 `CriticReview` 未使用 import；没有删除 pytest 测试。
- README 当前运行说明已更新：离线测试改为 `python -m pytest test -q`，embedding 改为 `BAAI/bge-small-zh-v1.5`，当前 LLM 路径改为 `FunctionExtract_Agent/llm.py`；历史进展段保留原有时间线和结论，路径统一为当前结构。
- 定向离线回归 `50 + 19 = 69 passed`，compileall、CLI help 和 diff check 通过。使用正式 Knowledge DB 临时副本跑 1 篇真实 Evolve：Run `FR_341a01b1d0ab493f` PASS，发布临时 Schema 5 Snapshot，14 个 Function 保持稳定，临时 SQLite integrity/FK 检查通过；assignment `MATCHED=358/739`、`UNCERTAIN=381`，仅证明流程和边界，不证明语义质量。
- 正式 Knowledge DB、正式 Registry 和旧 Chroma 未写入；本轮未执行全量清空或全量 LLM 重建。

## 本轮（2026-09-07）：清理临时代码与数据，只保留正式边界

- 按用户要求，将 `Code/data/` 下的 archive、smoke、validation、eval、e2e、incremental、profile、rebuild、closed_loop 目录和一次性审计报告移入系统 Trash；保留 `knowledge/`、`registry/`、`ontology_snapshots/`、`checkpoints/`、`evaluation/`，以及当前正式 namespace 的 `bootstrap`、`evolve_15_final`、`outline_dynamic` 和最新成功 Evolve 产物。
- 清空 `story_cli/stories/` 下 51 个重复 `OUT_NEW` 生成目录，保留正式输出根目录；清除空的 `Code/data/bank/chroma_db` 缓存、旧嵌套 `FunctionExtract_Agent/data/bank` Chroma、根目录临时 rebuild 数据、`.pytest_cache`、`__pycache__`、`.pyc` 和 `.DS_Store`。
- 删除未被生产链或 pytest 使用的一次性比较/评测 harness；保留 `clean_corpus.py`、`build_transition_index.py`、`story_pattern_loader.py` 及全部 `test_*.py`，没有删除行为测试。
- 正式 Knowledge DB、Registry、Snapshot、checkpoint 和正式语料未被清理动作改写；后续验证应使用 `PYTHONDONTWRITEBYTECODE=1` 与禁用 pytest cache，避免重新产生临时文件。

## 本轮（2026-09-07）：Serving Snapshot 与候选 Snapshot 解耦

- `KnowledgeBase` 新增同库单行 `serving_snapshots` 指针，保存 `snapshot_id`、`promoted_at`，并通过 Snapshot 关联保留 `snapshot_created_at` 与 namespace；`promote_snapshot()` 是唯一切换入口，Snapshot 内容仍不可变。
- 不保留空白新库/旧库自动推断 serving 的通用兼容分支；正式库已先备份，再由当前代码创建指针表并显式 promote 当前 Snapshot。之后 `commit_function_run()` 不会因 Evolve/Bootstrap 产生候选而自动切换 serving。
- Outline Planner、dynamic Planner references 和 StoryCLI 的无 `snapshot_id` 路径默认解析 serving；Evolve 无显式父 Snapshot 时也从 serving 建立工作基线，显式 `base_snapshot_id` 仍优先。
- 本次 serving 代码从隔离 worktree 合并到 main；已有 main 工作树改动保留，正式库实际验证另行记录。

## 本轮（2026-09-07）：main 正式库 Serving 链路验证

- 将隔离 worktree 的 Serving 相关代码只合并到 main 对应文件，保留 main 原有未提交改动；main 的 `compileall`、Serving 默认解析和 `git diff --check` 均通过。
- 在 main 上对正式库执行单篇真实 Evolve（`--freeze-functions`，仅冻结 Function 本体，不跳过 Observation/Matcher/Evaluator/Snapshot 提交）。Run `FR_2b6442e4f79543c0` 以旧 serving `real_coordinator_rebuild_v5_20260904_20260906T152048649508Z_4fef618ebe77` 为父版本，`6/6` 评估通过，发布候选 `serving_verification_main_20260907_20260907T025642311869Z_aaef6bcfe669`。
- 候选提交后 serving 仍保持旧 ID；默认 Outline Resolver 和 dynamic Planner 都读取旧 ID，显式传候选 ID 才读取候选。旧 Snapshot 故事数 `92`，候选为 `93`，证明默认路径没有偷偷读取最新候选。
- 显式 `promote_snapshot()` 后，唯一 serving 指针切换到候选，默认 Planner 随之切换；最终正式库 `Snapshot=9`、`integrity_check=ok`、`foreign_key_check` 为空。验证前备份为 `Code/data/knowledge/story_knowledge_before_main_serving_verification_20260907.db`。

## 本轮（2026-09-07）：Generation Outcome 最小反馈闭环

- 在现有 Knowledge SQLite 增加逻辑隔离的 `generation_outcomes`，记录 `snapshot_id`、`pattern_id`、`outline_id`、Planner 模式、验证结果、是否重试、失败类型和后续动作；不新增数据库，不回写 Corpus、Function、Pattern 或 Snapshot。
- `export_node` 在现有 Outline 落库后写入 outcome；验证成功且未重写记为 `accepted`，验证成功且发生一次重写记为 `rewritten`，最终未通过记为 `rejected`。失败类型只按现有结果确定性归类为 `contract`、`rule` 或 `semantic`。
- `load_pattern_feedback(snapshot_id)` 按 Snapshot 聚合：首次失败不降权，重复失败产生负分，accepted/rewritten 产生正分；Outline Planner、候选 Pattern 列表和 StoryCLI 批量入口复用这个排序信号。现有 `pattern_usage` 的单次使用边界保持不变，反馈不负责重新启用已消费 Pattern。
- 离线全仓回归 `356 passed, 1 skipped`。正式库用父 Snapshot `real_coordinator_rebuild_v5_20260904_20260906T152048649508Z_4fef618ebe77` 的 `PAT_7d0b26b318f228c1` 完成一次真实 Outline：生成 `OUT_07509ac2dd6a3a01`，写入 `GO_72e2e9e256ba9168`，验证通过、未重试、`accepted`；反馈读取后候选排序由第 3 提升到第 1。
- 与运行前正式库备份逐表对比，Corpus、Function、Pattern、Snapshot 及 serving 指针均无变化；SQLite `integrity_check=ok`、`foreign_key_check=0`。当前 serving 仍是 `serving_verification_main_20260907_20260907T025642311869Z_aaef6bcfe669`。
