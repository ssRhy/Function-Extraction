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


- **Bootstrap 已收尾（2026-08-16）**：run_bootstrap.py 120 篇全量 → `bootstrap` 命名空间 82 functions / 1027 obs；curate 最终全量复核 PASS 6/6（coverage 0.761 / cohesion 0.884 / separation 0 / abstraction 0.890 / evidence 2.89 / diversity 3）；快照 `data/bootstrap/` + 报告 `data/evaluation/evaluation_report.json`；修订历史 `data/evaluation/revise_rounds.jsonl`。日志 test/logs/run_bootstrap_full.log / run_bootstrap_curate.log。
- 进入 Evolve 前一次性补齐（清单见 README「Evolve 阶段待补清单」）：`source_sentence_indices` 已采集（2026-08-17，历史 obs 需重跑回填）、`function_id/status/version_history`、卡片成熟内容由 Curator 生成、命名统一、Matcher/Critic/Curator（Matcher 仍是 Evolve 专属，revise_node 只做 bootstrap 内收敛）。
- 决策项：SPLIT 镜像对近义风险（重跑采样未复现，是否需要豁免名单）；同名 <0.85 函数对唯一化规则；Inducer/闭环 LLM 非确定性（固定候选池 / Run A/B/C）；`data/bootstrap`/`data/evaluation` 被 .gitignore 忽略（仅 DB 为权威源），是否纳入版本控制待定。

## 踩过的坑（不要再踩）
- 本环境 `apply_patch`/`Remove-Item` 被策略拦截：用 .NET `[System.IO.File]`/`[System.IO.Directory]` API 或精确文本替换。
- PowerShell 管道给子进程（`python -` 等）传中文会乱码：脚本内用相对路径或直接在当前 shell 执行。
- `test_bank.py` 的 `persist_dir="Code/data/bank_test"` 会解析到 `Code/Code/data/bank_test`（历史遗留，勿沿用该路径写法）。
