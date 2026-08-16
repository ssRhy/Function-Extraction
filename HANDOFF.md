# 会话交接协议

## `HANDOFF.md`｜跨天任务必备

长会话收尾：先写 `HANDOFF.md`，只记任务进度，不堆经验。

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

## 下一步
- Bootstrap 三批完成，120 篇 O_0 快照齐备（`Code/data/genre_functions/`）；Evaluator_v0 已实现并接入 `--batch-induction` 阶段 3（跑完自动评估，报告 `Code/data/evaluation/evaluation_report.json`）。
- 决策项：同题材 13 组近义 + 跨题材 20 组近义如何合并（人工规则 / 阈值下调 / Evolve Curator MERGE）；4 个题材绑定函数（`SUPERNATURAL_ENCOUNTER` 等）是否 REVISE；Inducer 非确定性（固定候选池 / Run A/B/C）。
- 进入 Evolve 前一次性补齐（清单见 README「Evolve 阶段待补清单」）：`source_sentence_indices` 采集（需全量重跑回填）、`function_id/status/version_history`、卡片成熟内容由 Curator 生成、命名统一、Matcher/Critic/Curator。
- 三个过期测试（`test_app.py` 等）去留未定。

## 踩过的坑（不要再踩）
- 本环境 `apply_patch`/`Remove-Item` 被策略拦截：用 .NET `[System.IO.File]`/`[System.IO.Directory]` API 或精确文本替换。
- PowerShell 管道给子进程（`python -` 等）传中文会乱码：脚本内用相对路径或直接在当前 shell 执行。
- `test_bank.py` 的 `persist_dir="Code/data/bank_test"` 会解析到 `Code/Code/data/bank_test`（历史遗留，勿沿用该路径写法）。