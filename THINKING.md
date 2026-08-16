# THINKING.md — 技术难点总结

> 作用：总结并持续更新项目遇到的技术难点——难点、根因、方案、验证、状态。只收录突破性或有意义的难点，不做流水账式记录。
> 约定：每个难点按「难点 → 根因 → 方案 → 验证 → 状态」维护；有新进展时直接更新原条目的方案与状态，不重复追加；新难点追加为新编号条目；未决事项记录在各条目的「状态」中。
> 与 HANDOFF.md（任务进度交接）互补：HANDOFF 记任务进度，THINKING 记技术难点的沉淀与演进。

## 项目现状（背景）

- Bootstrap 链路（Pre-Processor→Observer→Bank→Retrieval→Inducer）完整可跑；Evolve、评价体系、版本管理全部缺失，另行规划。
- 动手前先做只读调查（排除书稿目录）；清理了未使用的 import/函数/常量、`test/ories/` 误建目录、`__pycache__` 与生成物；三个过期测试（`test_app.py` 等）暂保留、去留待定。

## 1. Function 去重与置信度质量

- **难点**：基线 30 篇跑出 54 个 Function：5 个同名重复、SACRIFICE 家族近义冗余；置信度全部挤在 [0.50, 0.60)，区分度不足；story_id 是随机 uuid，结果不可复现。不解决会污染后续 MATCH/NOVEL 判定。
- **根因**：名称不同但结构相同的近义 Function 无法被现有逻辑识别；bootstrap 阶段的软惩罚与已有 Registry 耦合，会误伤新候选。
- **方案**：
  - 范围：质量 + 速度一起做。
  - 去重：确定性规则，"保留置信度最高即可"，不用 LLM 聚合。
  - 新增 `load_registry_functions`（统一读 Registry，消除两处重复读取）、`max_definition_similarity` + `NEAR_DUP_THRESHOLD=0.85`（抓近义，阈值预留调参）、`APPLY_CONFUSABLE`（bootstrap 豁免软惩罚，硬去重承担过滤职责）——均为去重目标的最小必要实现。
  - 可复现：本轮只保证可复现，Run A/B/C 对齐推迟到评价阶段。
- **验证**：基线实测（30 篇 ≈ 51 分钟、约 100 秒/篇）来自 2026-08-15 试跑；去重方案本身尚未全量验收。
- **状态**：待 30 篇全量重跑验收（本轮只跑了 10 篇）；0.85 近义阈值对中文定义可能偏保守（`PROPHECY_FULFILLMENT_BY_AVOIDANCE` 与 `PROPHECY_DRIVEN_ACTION` 语义接近但未被合并），需调参实验。

## 2. 规则切句 vs LLM 分句（最终：恢复 LLM）

- **难点**：LLM 分句成本高（可省约 1/3 LLM 调用）且有丢 `sentences` 的 bug（兜底逻辑因此存在）；规则切句能省成本，但叙事分段质量与灵活度不如 LLM。
- **验证**（规则切句阶段）：下游只消费 `sentences` 与 `story_id`（observer.py:67），`segments/paragraph_count` 无人使用；规则切句不丢文本（LLM 版反而会丢 `sentences`）；story1-5 规则切句句子数与 LLM 版完全一致（11/37/18/13/37）。
- **决策**：2026-08-15 用户评估后恢复 LLM 分句——`Pre_prompt.py` 恢复、`preprocessor_node` 走 `chat_structured` 结构化输出，保证叙事分段质量；规则切句（`_split_sentences`，含闭合引号边界修复）保留为 LLM 长输出丢 `sentences` 时的兜底，并同时被 `clean_corpus.py` 复用。
- **状态**：LLM 主路径 + 规则兜底；`test_preprocessor.py` 改为离线 mock LLM。真正的质量瓶颈仍在 Observer/Inducer 的 LLM 输出变异性（同故事两次运行 obs 数不同，如 story1: 4→2）；为控制验证成本，验收规模从 30 篇压缩到 10 篇。
- **实测对比（2026-08-15，`03_现代情感家庭/1722040836_441456266.txt`，5.9k 字符）**：LLM 分句 207.7s/篇（约 36s/千字），规则切句 1ms；LLM 253 句 vs 规则 344 句，190/344 句完全一致，46 个差异块全部为"规则多句→LLM 合并"（其中 10 处修复 `？！`/`！”` 悬空标点碎片）；两者字符守恒均 100%、孤立引号均 0。结论：LLM 质量更优但成本高，120 篇仅分句环节预计 ~8-10 小时，全量前需评估。


## 3. 语料清洗：头部误删与幂等性

- **难点**：规则清洗一旦"按关键词删整行"或作用域过宽，会误删标题/开篇句，且对输出重跑不幂等。
- **根因**（code-reviewer 2026-08-15 审查）：
  - M1：`已完结` 全行匹配删掉了 `【已完结】一夜之间…`（开篇句）与 `《冰洞》（已完结）`（标题）；
  - M3：`《枕眠》（已完结～）` 是正文中间的碎片，一次清洗不删、二次清洗落入头区才删 → 幂等破坏；
  - M4：尾部促销块（读者催更提问 + URL 簇）比 25 行窗口长，截断漏掉块首；
  - M2：规则切句不消费闭合引号，`“我们需要一根桅杆。”` 被切成孤立 `”` 句（全语料曾占 14.8%）。
- **方案**：
  - 完结标记改为"剥离→判空/判内容"：纯标记行删除、带正文保留正文；作者行用 manifest.author_name 精确匹配；
  - 幂等由构造保证：标记剥离全局生效（含正文中间碎片），二次清洗无残留标记；
  - 促销块截断向上吸收 `【打赏】`/读者催更提问；`答案在评论区` 备注行全局剔除（避免与正文拼接成 `16、…17、…` 后二次清洗才被截断）；
  - 切句合并纯引号碎片 + 句首闭合引号移回前句。
- **验证**：120 篇重生成——幂等 0 违规、促销/URL/孤立引号残留 0、manifest 120/120 命中、剔除噪音 1035 行、内容守恒 -5443 字符；`test_clean_corpus.py` 新增回归用例全部通过。
- **状态**：已修复并验收。

## 4. 3 篇跨题材全流程验证：LLM 分句偶发失控

- **难点**：3 篇跨题材（现代/悬疑/古风）全流程首跑，现代篇 Pre-Processor 直接失败（`JSON 解析失败: Expecting value: line 16 column 101692`），悬疑篇句子数塌缩为 1。
- **根因**：pre_processor 让 LLM 同时输出 `segments[].content` 与 `sentences[]` 两份全文，正常输出 ~15KB；模型偶发失控膨胀到 104KB+ 被 API 截断 → JSON 解析失败（同一故事复跑即恢复 277 句，属随机故障）。悬疑篇塌缩为 `sentences=[全文]` 同样是 LLM 输出不稳。
- **方案**：`preprocessor_node` 对 `chat_structured` 加「重试 1 次 + 规则切句兜底」——两次 JSON 解析失败时用 `_join_paragraphs(_clean_lines())` + `_split_sentences()` 构造同结构 `NormalizedResult`，下游链路无感（符合"LLM 主路径 + 规则兜底"既有设计，最小改动）。
- **验证**：修复后 3 篇全过——608.0s（202.7s/篇，比首跑 311.6s/篇快约 35%，LLM 输出偶然更短）；现代 252 句/8 obs、悬疑 270 句/5 obs、古风 157 句/5 obs；跨故事相似对 25；Registry 2 functions。
- **遗留**：跨轮 Function 不稳定（首跑 3 个 vs 复跑 2 个，名称全不同）——Inducer 候选生成非确定，影响"可复现"口径，评价阶段需固定候选池或 Run A/B/C 对齐；`SPECIAL_KNOWLEDGE_REVELATION` 的 supporting 含牵强 obs（现代篇 obs_006），0.5 阈值边缘候选偏噪。
- **状态**：3 篇验证完成；全量 120 篇前需定"Inducer 非确定性"应对策略。

## 5. 批后统一归纳：obs 相似度阈值校准与聚类设计

- **难点**：文档设计的"批后统一归纳"要求阶段 1 不跑 inducer、阶段 2 用整批证据统一归纳；实现需要 ①无 inducer 的提取图，②把全部跨故事相似对聚成"一组相似 obs"再交给 Inducer。
- **根因/发现**：all-MiniLM-L6-v2 对中文结构化 obs 的余弦相似度整体偏低——悬疑 3 篇实测 max=0.690、median=0.581、top-5 检索对最低 0.479；初始 0.80 阈值把所有边过滤掉（50 对 → 0 分量）。0.60 为合理噪声底线（滤掉明显无关弱边，保留强边）。
- **方案**：`Agent/Inducer/cluster.py` 纯函数——按相似度≥0.60 建边 → 连通分量 → 每分量（≥2 故事）调用一次 `inducer_node` → 分量 >40 obs 按度贪心拆分；`app.py` 新增 `extract_app`（preprocessor→observer→bank_adder→retrieval，无 inducer）。
- **验证**：3 篇冒烟（阶段 1 全 Function=0，阶段 2 写 ANOMALY_DISCOVERY）；悬疑 40 篇正式跑 254 obs → 23 functions，evaluator HEALTHY，置信度 [0.591, 0.757]（mean 0.670）。
- **遗留**：0.60 阈值与 40 obs 上限为经验值；40 篇时出现 40 obs/25 故事的大分量，贪心拆分可能切断语义组，120 篇全量后需复查；LLM 分句「1 句塌缩」已于 2026-08-16 补兜底（句子数 < 句末标点数/3 → 规则切句）。
- **状态**：三批（悬疑/古风/现代）全部完成并验收；批后 obs 聚类阈值 0.60、拆分上限 40 obs 为经验值，120 篇全量后再复查。

## 6. Bootstrap 阶段不补 Function Card / Observation 扩展字段（决策）

- **问题**：`functions.jsonl` 缺文档 Function Card 的 `Function ID/Status/Version History/Structural Significance/Typical Context/Consequences/Participant Roles/Before-After State` 等 8 项；`observations.jsonl` 缺 prompt 已要求输出的 `source_sentence_indices`（schema drift，README 已知问题 #3）。
- **判断**：bootstrap 阶段**不补**。理由：①LLM 不消费这两个文件，不影响 O0 产出；②O0 是 provisional，Status/Version History 从 O0 之后才真正记账；③消费者（Matcher/Critic/Curator、Run A/B/C 评价）未实现 → YAGNI；④改 schema 需连带 Observer/Bank/测试/快照回填，风险大于收益。
- **遗留**：进入 Evolve/评价阶段时一次性补 `function_id/status/version_history/source_sentence_indices`（连同演化需求一起设计）；`source_sentence_indices` 若在意浪费，可先删 prompt 中该要求（非阻塞）。
- **状态**：已定案；悬疑批不受影响。

## 7. 分句 prompt 去重复输出实验（V1 vs V2）

- **难点**：Pre-Processor 让 LLM 输出全文两次（`segments[].content` + `sentences[]`），是单篇耗时大头（~60-75%）。
- **方案**：V2 prompt 让 `segments` 只输出 `sentence_indices`、不输出 `content`，`sentences` 保留全文 → 输出量降约 40%。
- **实测**（3 篇跨题材 + 古风复核 3 次，2026-08-16）：
  - 输出量：V1 ~12.4-15.1K 字符 vs V2 ~7.1-9.2K（稳定 -40%）；
  - 墙钟：首轮 V1 平均 174s vs V2 90s（-48%）；补测后 V1 ~169s vs V2 ~149s（-12%）——DeepSeek 延迟波动大，时间节省不如输出量确定；
  - 句子粒度：2/3 篇一致，古风首次 V2 81 句为异常值，复核 130/137 句正常；文本守恒均 ~100%。
- **结论倾向**：采用 V2（成本 -40%、质量无损）；需同步改兜底（空 `sentences` → `_rule_normalized_result`）与 `Pre_prompt.py`。
- **状态**：已采用（2026-08-16）。3 篇同批冒烟 117.1s/篇 vs V1 208.0s/篇（-44%），句子粒度相当；`Pre_prompt.py` 已换 V2，空 `sentences` 兜底改走 `_rule_normalized_result`，`test_preprocessor.py` 全过。 三批全量实测（2026-08-16）：V1 悬疑 275.6s/篇 vs V2 古风 240.1 / 现代 195.2s/篇（-13%~-29%），节省主要来自输出量、墙钟受 DeepSeek 延迟波动；三批 evaluator 均 HEALTHY，句子粒度未见回退。

## 8. Evaluator_v0：批后六维本体评估与阈值校准（2026-08-16）

- **难点**：旧 `test/evaluator_v0.py` 只做三件布尔检查（同名重复 / 近义组 / <2 故事支持），回答不了"O_0 是否达标可进入 Evolve"，也定位不了四类质量问题：近义碎片化、定义双向混叠、obs 贴合度弱、题材表层绑定。
- **方案**：批后六维评估（Bootstrap → Evolve 入口）——Coverage / Cohesion / Separation / Abstraction Quality / Evidence Count / Diversity，达标 ≥4/6 判 PASS，FAIL 只输出建议清单（不自动退回 Inducer）。Abstraction 用 LLM 混合复核（方向词对规则预筛作 prompt 种子），其余 5 维确定性可复现；不新增图链路，batch_run 阶段 2 归纳后直接调用 `evaluator_node`（沿用直接调 inducer_node 的模式）；`evaluation_context` 支持指向快照并集评估。
- **阈值校准依据**（MiniLM 中文实测）：
  - Coverage 相似阈值 0.65（中文基线 0.5-0.6），达标 ≥0.60；
  - Cohesion 达标 ≥0.60；weak-fit 用 0.80 在 76 函数真实集标 49 条过噪，降到 0.70 后仅 5 条真离群；
  - Separation 用 0.85 分组（对齐 `NEAR_DUP_THRESHOLD`）抓到 13 组近义；0.78 分组会串出巨型连通分量不可用，降级为复核建议列表（`SEP_REVIEW_THRESHOLD`）；
  - Evidence 2/3/4、Diversity 2 题材（回退 20 故事）、Abstraction OK ≥0.80、通过线 ≥4/6。
- **验证**：集成验收三题材快照并集（76 funcs / 831 obs + manifest）PASS 5/6（仅 Separation FAIL）：coverage 0.83 / cohesion 0.88 / separation 13 / abstraction 0.83 / evidence 3.78 / diversity 3。四类问题的证据：13 组近义（`CONFLICT_RESOLUTION`≈`RELATIONSHIP_STRENGTHENING` 0.995、`INFORMATION_REVELATION`≈`RELATIONSHIP_BREAKDOWN` 0.908 等）；4 个题材绑定函数（`SUPERNATURAL_ENCOUNTER`/`FATE_REWRITING`/`SECOND_CHANCE`/`FATE_CHANGE_DECISION`）；7 个双向混叠 REVISE；weak-fit 5 条离群 obs。报告落盘 `Code/data/evaluation/evaluation_report.json`。
- **遗留**：v1 FAIL 只输出建议、不自动退回 Inducer（自动重试/扩语料留待 Evolve）；同题材 13 组 + 跨题材 20 组近义如何合并（人工规则 vs 阈值下调 vs Curator MERGE）未决；Abstraction LLM 非确定性接受（与 Inducer 一致）。
- **状态**：已实现并接入 batch_run 阶段 3；旧 `test/evaluator_v0.py` 已删除，其职责由 Separation + Evidence Count 承接。