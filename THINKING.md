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
- **Evidence 阈值校准（2026-08-16）**：`EVIDENCE_MEAN_STORIES 3.0→2.5`、`EVIDENCE_MEAN_OBS 4→3`——3/4 是计划默认（当时注明"验收步骤负责校准"但从未对真实分布校准），历次真实运行（union 3.79、bootstrap 2.892/3.048）从未达到 mean_obs≥4；实测中位数 3/3，校准后 evidence 达标（2.892≥2.5、3.048≥3）。≥2 故事硬下限（理论依据 §6.2）不动。
- **新发现（同一轮）**：`--evaluate-only` 全新全量 Abstraction 复核（83 个全评、0 复用）得 0.7952（<0.80），暴露原 1.0 依赖增量复用；LLM 非确定性使 abstraction 在 0.80 贴边，17 个函数有可执行问题（REVISE/too_broad/题材绑定），需一轮 curate 修订后复评才能真 6/6。

## 9. Bootstrap 自动修订闭环（curate_app）与 SPLIT 镜像近义（2026-08-16）

- **难点**：Evaluator 出建议后需要 LLM 全自动修订并"保持 O_0 可用"，但不能每次靠人工/换批重跑；且并集评估是 PASS 5/6（Separation 是唯一 FAIL 维度），"PASS 即停"会让修订永不触发。
- **方案**：`revise_node`（bootstrap 内嵌 Curator-lite）+ `curate_app` 编译图闭环——`START → evaluator → conditional → revise → evaluator… → END`。`should_continue` 的终止条件不是"verdict==PASS"，而是"报告已无可执行问题（merge_groups/revise_definitions/genre_bound/granularity/weak_fit/low_evidence）或达 `MAX_EVAL_ROUNDS`（3）"，否则即使 PASS 5/6 也会继续修订直到 6/6 或上限。修订动作：MERGE（supporting obs 程序并集）、REVISE、SPLIT（obs 按向量余弦确定性分配，不信任 LLM 输出 obs）、weak-fit 剔除、低证据移除；confidence 用 bootstrap 豁免口径重算（SimpleNamespace 轻量桩，不改 confidence.py）。
- **验证**（三题材并集，3 轮，增量复核 + 同名去重后 515s）：76 → 57 funcs（同名 0）；Separation 13 → 0；题材绑定/粒度/weak-fit/低证据清零；Abstraction 0.965、evidence mean_obs 4.65；最终 PASS 6/6（coverage 0.81 / cohesion 0.87 / separation 0 / abstraction 0.96 / evidence 4.65 / diversity 3）。
- **关键发现**：SPLIT 拆出的正/负镜像对（首采样 `POSITIVE_TURNING_POINT` / `NEGATIVE_TURNING_POINT` sim 0.982）会被 Separation 标为近义——定义高度对称但结构作用相反，embedding 余弦无法区分；这是"阈值判定 vs 语义方向"的固有盲区，需在 Evolve/阈值策略层面解决（如把同源 SPLIT 对加入豁免名单）。重跑采样中该问题未复现（Separation 归零），但风险仍在。
- **状态**：已实现并验收（LLM 非确定性，两次采样分别 PASS 5/6 与 6/6；交付物以重跑 6/6 为准，`revise_report.json` 随闭环落盘）；最终报告残留非阻塞建议（1 REVISE、1 题材绑定、2 weak-fit、33 组 <0.85 复核对），Evolve 阶段处理。
## 10. curate_app 增量 Abstraction 复核（2026-08-16）

- **问题**：闭环 680s 里，Abstraction 的 LLM 复核每轮把所有函数全量重评一遍（4 轮 ≈ 13–16 次调用，占大头）。用户追问"能不能只把有问题的组丢给 LLM 处理"。
- **澄清**：13 组近义是向量检测（免费）；但双向混叠/题材绑定/粒度没有可靠规则，只能靠 LLM 圈出问题组（规则只是预筛 prompt 种子）；且修订产物会带新问题（merge 出的 `RELATIONSHIP_TRANSFORMATION` 第 2 轮又被 REVISE、SPLIT 拆出镜像近义），所以必须"评→改→再评"循环，单次跑不完。
- **方案**：首轮全量 + 后续轮只重评变更集（merge 产物 / revised / split 子函数），未变更函数按 function_name 沿用旧评审；确定性五维仍全量（向量秒级）。实现：`evaluator._review_abstraction(review_targets, prev_reviews)` + `revise` 记录 `changed` 回传 `review_targets` + `curate_run` 回溯 checkpointer 落盘每轮动作。
- **实测**（并集重跑，2026-08-16）：Abstraction LLM 调用 13–16 → 8 次（全量 76 分 4 批 + 增量 30/11/1）；耗时 680s → 515s（-24%）；76 → 57 funcs、同名 0（`_dedup_names` 把撞名的 `RELATIONSHIP_BONDING`/`RELATIONSHIP_BREAKDOWN`/`RELATIONSHIP_DEEPENING` 加 `_2` 后缀），最终 PASS 6/6、Separation 归零；`revise_rounds.jsonl` 记录每轮 changed 与 renamed_duplicates。
- **取舍**：首轮若 LLM 漏检某函数，增量轮不会自动重抓（可加最后一轮全量终检兜底，未启用）；增量让"未变更函数"的评审结果跨轮稳定，也少了一个非确定性波动源。

## 11. Registry 升级：SQLite + 批次隔离（2026-08-16）

- **用户问题链**："registry 是不是要设计一个数据库" → "如果升级了 Registry，bootstrap 也要升级吗"。澄清结论：升级分两维——**存储层**（JSONL→DB）不改节点逻辑，只收敛读写访问点；**schema 层**（function_id/status/version_history）才需要 bootstrap 写入方兼容 + 一次性 backfill，且 source_sentence_indices 例外（需重跑全量 obs）。当前无任何 LLM prompt 直接消费 Registry，升级是纯数据层问题。
- **用户决策**：直接上 SQLite + 批次隔离（每批独立命名空间，启动不再删除其他批次）；JSONL 保留为快照/交换格式（curate_run/genre_extract/gen_evaluation_report 都吃 JSONL）。
- **实现要点**：RegistryStore(db_path, namespace) 单表 unctions(namespace, function_name, definition, payload, updated_at)，payload 整存完整 JSON——字段无损、未来 Evolve 加字段零迁移；活跃 store 走模块级 get_active_store/set_active_store，batch_run 启动按 --genre or "all" 建 store 并 clear() 只清当前批；Inducer/Confidence/Evaluator/Revise 全部收敛到 store，JSONL 只在显式 
egistry_file（快照/并集）模式；revise 写回 store 前自动导出 .pre_revise.<ns>.jsonl 备份；	est/import_registry.py 用于把并集修订结果导入 union 命名空间。
- **5 篇试跑验收**（悬疑 2 + 古风 2 + 现代 1，--batch-induction）：40 obs / 5 functions（均 ≥2 故事支持）；闭环第 1 轮 PASS 4/6（Abstraction 0.4 失败，3 个函数被标题材绑定/粒度过细）→ 修订 3 个 → 第 2 轮 PASS 5/6（evidence 2.2 因 5 篇小样本不达标，属预期）；耗时 1282s（256.4s/篇，与近期全量批 195–275s/篇 同量级；旧 61.5s/篇 是逐篇模式口径，不可直接比）。DB 命名空间 ll 与 data/trial5/functions_all.jsonl 逐字段一致。
- **遗留**：试跑命名空间 ll 与 Bank 待全量重跑前清空；evidence_count 阈值（mean_stories≥3）在小样本下必然 FAIL，全量 40 篇/批后应自然达标；unctions.db 已 gitignore，被取代的 unctions.jsonl 已 git rm --cached。
## 12. Bootstrap 提速根因：隐藏推理 token + V3 混合切句（2026-08-16）

- **难点**：全量 120 篇三批合计约 8 小时（195–275s/篇），用户要求大幅提速；此前误以为是 Pre-Processor"全文回显"导致输出 token 大。
- **根因**：deepseek-v4-flash 隐藏推理 token 才是耗时/成本大头——单次切句 completion 8220 tok 中 reasoning 占 8207（99.8%），可见输出仅 28 字符 JSON；`LLM_USAGE=1` 按调用方归因后确认 Pre-Processor 与 Observer 的 completion 大头是推理 token。
- **方案**（两处最小改动，已落地）：
  - `Agent/llm.py`：`chat/chat_structured` 默认 `reasoning_effort="none"`（同调用实测 low=31.4s/3925 tok → none=1.6s/248 tok，约 20 倍；可见输出仍有效）。
  - `pre_processor.py`：默认改走 V3 混合切句 `_hybrid_normalized_result`——规则切句生成候选句子与编号，LLM 只输出 merges/splits 修正（`PRE_HYBRID_SYSTEM_PROMPT` / `PreCorrection`），不回显全文；输出从 ~21k token 降到几百 token，质量仍由 LLM 把关（等价于 LLM 对规则候选做监督式合并/拆分）。
- **验证**（trial5_none，2026-08-16，5 篇跨题材）：93.9s（18.8s/篇）vs 基线 trial5 1282s（256.4s/篇）→ 约 13.6 倍；47 obs / 5 functions（数量与基线一致）；闭环 PASS 5/6（第 1 轮 4/6 → 修订 1/拆分 1 → 5/6；evidence 小样本不达标为预期）；LLM 15 次 / 89,791 tok / 88.8s。3 篇试跑（trial_none）仅 1 function → 判为样本量不足（跨故事分量过少），5 篇恢复 → 支撑质量持平结论。
- **遗留风险**：`none` 对 Inducer/Evaluator（需综合推理）的质量代价未单独对照，当前 5 篇显示影响可控；Observer 仍是单篇主要耗时（5 篇合计 52.8s，约 10.6s/篇）。全量 120 篇预计 ~1h，需重跑后与旧三批结果对照近义组与函数分布。
- **V2+none 对照（用户提议回退验证，2026-08-16）**：按"Pre-Processor 恢复 V2 全量 LLM 分句 + reasoning_effort=none"实测同 3 篇跨题材（trial5_v2none）——preprocessor 60.3s/篇（completion ~11.6k/篇）vs 混合 3.6s/篇（~600/篇），总耗时 79.9s/篇 vs 18.8s/篇（约 4.2 倍）；2/3 篇首轮 JSON 解析失败触发重试（V2 历史不稳定在 none 下复现）；句子数 289/331/180（与 V2+推理一致，none 不损 V2 分句质量；混合版 317/389/179，规则基底略多句）。结论：**保留 V3 混合**——LLM 仍把关合并/拆分质量，成本 1/4 且无截断风险。
- **V2 vs V3 同篇定案对照（2026-08-16，trial3_v2 vs trial3_v3，同 3 篇跨题材单次采样）**：总耗时 85.1s/篇 vs 18.4s/篇（4.6 倍）；V2 3/3 篇首轮 JSON 失败（1 篇连败 2 次掉规则兜底，等于 1/3 内容未走 LLM），V3 0 失败；最终 Function 均 4 个且全部 ≥2 故事支持（V2: SECRET_DISCOVERY/ALLY_INTRODUCTION/SELF_IMPROVEMENT_AFTER_CRISIS/DISTURBING_ENCOUNTER；V3: TRUST_ESTABLISHMENT/RELATIONSHIP_DETERIORATION/ESCAPE_IMPULSE/SELF_REFORMATION，概念重叠仅 SELF_IMPROVEMENT_AFTER_CRISIS≈SELF_REFORMATION，其余差异属 Inducer 非确定性）；Evaluator V3 PASS 5/6（coverage 0.70、0 轮修订）vs V2 PASS 4/6（coverage 0.45、移除 2 个低证据/题材绑定函数）；总 token 50,631 vs 105,317。**用户决策：保留 V3 混合切句。**
- **状态**：已定案（保留 V3）；下一步由用户决定是否清空 `all` 命名空间 + Bank 后全量重跑三批。
## 13. 120 篇全量重跑验收：V3 提速 ~13 倍，并集闭环 PASS 5/6（2026-08-16）

- **背景**：V3 定版后清空重跑三批（悬疑/古风/现代各 40 篇），验证提速与并集质量。
- **结果**：三批 2142.7s ≈ 36min（17.8s/篇，旧约 8h，~13 倍）；obs 335/304/372，funcs 31/32/39；并集 102 funcs → curate 3 轮 → 75 funcs；最终 PASS 5/6（separation 16→0、abstraction 0.987、coverage 0.797、cohesion 0.874、diversity 3；evidence mean_obs 3.79<4 未达标，接近阈值）。
- **遗留**：evidence 维度差 0.2（mean_obs 需 ≥4），可接受或在下批语料补齐；跨题材近义经合并后仍残留 <0.85 的 review_pairs（如 RELATIONSHIP_FORMATION≈RELATIONSHIP_ESTABLISHMENT_THROUGH_EVENT 0.844），Evolve 阶段做阈值/合并决策；`functions.db` 四命名空间已就位，`union` 为修订后 O_0。
- **状态**：Bootstrap 全量验收完成；进入 Evolve 前的待补清单见 README「Evolve 阶段待补清单」。

## 14. 统一全流程入口 run_bootstrap.py：删除分批/并集（2026-08-16）

- **难点**：Bootstrap 流程被拆成"3 题材分批 + 手动并集 + 多入口脚本"（batch_run --genre / genre_extract / gen_evaluation_report / curate_run / import_registry），入口分散、合并依赖人工步骤；用户要求"一次过大量文本、不需要分批、不需要合并"。
- **方案**：新增 `Code/run_bootstrap.py` 一键入口——清空 Bank + 本命名空间 → 全量提取 obs（extract_app）→ 跨题材统一聚类归纳（阈值 0.60、≥2 故事分量）→ curate_app 评估 + 修订闭环 → 快照；跨题材 obs 直接一起归纳，函数天然题材无关。删除 5 个旧脚本；`llm.py` 删除 `reasoning_effort` 参数、硬编码 `"none"`（已核实无外部调用方覆盖）。
- **验证**：3 篇跨题材冒烟 52.7s（17.6s/篇），30 obs → 1 跨题材分量 → 6 函数 → 修订移除 3 低证据 → 3 函数，Evaluator PASS 4/6；离线回归 54 项全过。
- **全量验收（2026-08-16）**：120 篇 2265.6s ≈ 37.8 分钟（18.9s/篇）；1027 obs → 116 → curate（修订 4/拆分 13/移除 11）→ 83 functions（conf [0.546, 0.749]，全部 ≥2 故事）；Evaluator PASS 5/6（evidence mean_stories 2.892<3 临界未达标，与旧 union 同形态）；LLM 306 次 / 1.93M tok。快照 `data/bootstrap/functions_bootstrap.jsonl`。
- **状态**：已落地并通过全量验收；bootstrap 命名空间 83 = 当前 O_0；旧命名空间 01/02/03/union 保留作历史对照。

## 15. 评估闭环度量缺陷：最终判定必须用全新全量复核（2026-08-16）

- **难点**：同一 O0 在"增量复用路径"（abstraction 1.0）与"全新全量复核路径"（0.7952）下分数不同——最终判定混着旧评审，不可复现；且逐项校准阈值是打地鼠（evidence 过了 abstraction 又露出来），真实状态是"还差一轮质量收敛"。
- **根因**：`curate_app` 最终轮用了增量复核（`review_targets=changed` + `prev_reviews` 复用），verdict 依赖缓存的旧评审；校准阈值掩盖而非解决贴线问题。
- **方案**：① `curate_app` 新增 `final_review` 节点（`force_full_review=True` → 全量复核、不复用），PASS/达上限后强制一次全新测量，仍有可执行问题则继续修订（≤3 轮）；② 新增 `run_bootstrap.py --curate-only`（命名空间上直接跑闭环，写回 DB + 同步快照）。
- **验证**：bootstrap 命名空间 `--curate-only`：83 → 82（拆分 5 / 移除 2），3 轮，最终 **PASS 6/6**（abstraction 全量(最终)复核 0.8902）；回归 54 项全过。
- **状态**：已落地。残留建议（REVISE/题材绑定/粒度）写入报告，Evolve 阶段处理；证据增长仍交给 Evolve。


## 16. LangGraph 范式审查与仓库清理（2026-08-16）

- **审查结论**：用 $langgraph-coding skill 核对 `app.py`/`state.py`——State = `TypedDict + Annotated[list, add_messages]`；node 返回字段更新；图先建节点后连边再 compile；条件边字符串路由与映射一致；`MemorySaver` checkpointer + 稳定 `thread_id`；curate 闭环有界（`evaluation_round` 上限 + `final_review` 出口），无死循环。重试未引入 tenacity（沿用库内循环模式：`revise.py` LLM_RETRY / `pre_processor.py` 2 次尝试），符合 skill"仅对确实不稳定且可安全重试的外部调用加重试"。
- **清理**：删除过期文件 `test_app.py`（依赖已删 story.txt）、`test_bank.py`（其 persist_dir 路径 bug 产物 `Code/Code/data/bank_test` 也被 git 跟踪，一并删除）、`test/stories/`（30 篇）、`draw_graph.py` + `langgraph_overall.*`、`nf_llm_result.json`/`nf_rule_result.json`/`_enc_probe.txt`、旧日志与 `data/` 旧分批/试跑产物（genre_functions、trial3_*、trial5*、trial_none、union 快照），保留 `data/bootstrap/` 与 `evaluation_report.json`。
- **旧命名空间清空**：`01_悬疑惊悚`/`02_古风穿越重生`/`03_现代情感家庭`/`union` 从 functions.db 清除，仅剩 `bootstrap`(82)。
- **修订历史落盘**：`revise_node` 每轮修订后追加 `data/evaluation/revise_rounds.jsonl`（round/ts/actions），替代旧 curate_run 的 checkpointer 回溯方案。
- **`.env` 去跟踪**：`git rm --cached Code/Agent/.env`（工作区保留）。

## 17. Bootstrap 单图重构：bootstrap_app + SqliteSaver 持久化/--resume（2026-08-16）

- **难点**：Bootstrap 编排散在三处——`run_bootstrap.py`（脚本引擎：阶段 1 逐篇 `extract_app.invoke`、阶段 2 直接调 `inducer_node`、阶段 3 `curate_app.invoke`）+ 三张独立编译图（`pipeline_app`/`extract_app`/`curate_app`）。"一个 agent 一次跑完全流程、可断点续跑"要求把编排收敛进唯一一张图，并让 checkpoint 跨进程持久化。
- **方案**：唯一编译图 `bootstrap_app`（`Agent/app.py`）——`story_loader →[continue_extraction]→(preprocessor→observer→bank_adder→retrieval→pairs_collector→story_loader 循环)→cluster→[continue_induction]→(induce_step 循环)→evaluator→[route_after_evaluator]→(revise 循环/final_review)→[route_after_final]→export→END`；`no_revise` 时路由直接走 final_review/export。CLI 收敛 `python -m Agent.app`（删除 run_bootstrap.py 与三图）。`--resume` 用 `SqliteSaver`（`data/checkpoints/bootstrap-<ns>.sqlite3`，thread_id=`bootstrap-<ns>`）：fresh 清空 Bank/Registry/checkpoint，resume 跳过清理、`invoke({})` 从最后 checkpoint 续跑（`Bank.add` 按 `obs_id` 去重保证幂等）。
- **环境约束**：全局 site-packages 不可写（沙箱用户 ACL RX-only）→ `langgraph-checkpoint-sqlite`/`sqlite-vec`/`aiosqlite` 以 `--no-deps --target Code/vendor` 本地安装，`Agent/app.py` 在 `vendor/` 存在时前置 `sys.path`（`langgraph.checkpoint` 是命名空间包，天然合并）；`SqliteSaver.from_conn_string` 是上下文管理器，改用手持 `sqlite3.connect + setup()` 供图实例长生命周期使用。
- **验证**：13 项图测试通过（新增 `test_bootstrap_app.py`：全流程 no-revise、interrupt→新实例同 DB 续跑、单篇失败跳过、空 story 直达评估；`test_revise.py` 3 个闭环用例改用 `bootstrap_app` + in-memory SqliteSaver）；torch-free 回归 33 项通过。**环境阻塞**：沙箱用户 `codexsandboxoffline` 无法加载 `torch_python.dll`（WinError 5；其依赖 shm/python313/torch_cpu 均可加载，复制到临时目录同样失败，ACL 为 RX、无签名差异）→ 依赖 Embedding/torch 的测试（test_confidence/test_evaluator 大部分、真实 Embedder 路径）本轮无法运行；图逻辑用 Embedding 桩（sys.modules 注入字符袋 Embedder）+ FakeEmbedder 验证。
- **状态**：代码与图逻辑已落地；需在可正常加载 torch 的环境跑全量回归（`python -m pytest test/ -q`）验收。

## 18. LLM 结构化输出 JSON 数据层加固（observer JSON 失败整图崩溃，2026-08-17）

- **难点**：重构为单图后，旧 `run_bootstrap.py` 的"逐篇 try/except 继续"丢失——observer 的 LLM 输出 JSON 解析失败（缺 `affected_aspect`/非法控制字符/缺逗号）抛 pydantic ValidationError，直接中断整张图（首跑 120 篇第 2 篇崩溃，前 2 篇白跑）。
- **根因**：preprocessor 有 2 次重试 + 规则兜底（ValidationError ⊂ ValueError 被捕获）、inducer/evaluator/revise 都有异常边界，唯独 observer 无保护；单图把逐篇链放进图内后没有外层异常边界。
- **方案（迭代）**：先尝试 `story_process` 子图节点（try/except 跳过整篇），被用户否决——图已按"简洁"诉求收敛，且整篇跳过丢全部 obs；最终改为**加固 `llm.py` JSON 数据层**（根因修复）：`chat_structured` 解析/校验失败时把错误反馈给 LLM 自动重试（最多 2 次）+ 轻量修复（剔除非法控制字符、去尾逗号）；图保持原始拓扑，不新增任何节点。
- **验证**：新增 `test_llm.py` 5 项（正常解析 / 坏 JSON 反馈重试 / 尾逗号修复 / 缺字段反馈重试 / 仍失败抛 ValueError）；图测试 13 项、torch-free 回归 38 项全过。
- **状态**：已落地。120 篇旧产物（61 functions，3 篇因旧代码跳过）不受影响，重跑可补回；abstraction 0.7541 < 0.80 未达标问题（3 轮修订上限内未收敛）另记，供 Evolve 或加轮处理。
- **补充（同日）**：响应"重构后 pydantic 字段要不要改"——除 JSON 层加固外，落地既有 schema drift 修复：`ObservationItem` 补 `source_sentence_indices: list[int]`（缺省 `[]`，对齐 Observer 提示词，供 Evolve obs↔句子 可追溯）；历史 obs 需重跑回填。
- **全量复验（同日）**：120 篇 0 跳过（observer 121 次 = 120 + 1 次 JSON 重试成功，对比上版 3 篇跳过）；978 obs 全部含非空 `source_sentence_indices`；85 functions；39.4min；PASS 4/6（abstraction 0.7647 仍受 3 轮上限约束、evidence 贴线）。
- **近义检测去阈值（同日续）**：余弦 0.85 漏检近义碎片、0.78 串假簇 → 用户定调"合并全交给 LLM"。迭代：① `_detect_merge_groups` 全量检测函数被否（"加限制代码"）；② 改为抽象复核响应字段 `merge_groups`（无独立调用）；③ Separation 维度改由 LLM 合并组计分（0 组达标），删除 `compute_separation` 及全部 SEP 阈值/诊断。verdict 仍 ≥4/6。残留风险：按批检测跨批漏检 + LLM 偶发过度合并（再评估兜底）。
- **O_0 未达标舍弃（同日尾）**：设计文档 §4.6 本意"不通过不进入 Evolve"，但实现此前"3 轮上限照常入库"（残差只写报告）。用户定 B 类严格语义：达上限或 `--no-revise` 后 `FAIL`/仍有可执行问题 → 舍弃（清空命名空间、删快照、退出码 1、无备份）。实现复用 `export_node`（不新增节点，被否的 `discard_node` 方案回退），`route_after_final` 路由不变。影响：带残差的运行不再落库，收敛到"完全达标"才产出 O_0。
- **checkpoint 膨胀（同日尾）**：单图单线程全量状态（`all_pairs` 含完整 obs 字典）被逐超步序列化进同一 SqliteSaver → checkpoint 超线性膨胀，74 篇时 2.6GB 且写死锁（2h 未到 75 篇）。修复：`all_pairs` 改存 obs_id 三元组、聚类前从 Bank 重建 → 全量 120 恢复 39.5 分钟。教训：把完整对象放 checkpointed state 会随超步数平方级膨胀，持久化状态应只存可重建的引用。
- **严格舍弃 vs LLM 非确定性（同日尾）**：全量 120 中途 6/6，final_review 全量复核暴露 2 组近义 + 2 混叠 → PASS 5/6 带残差 → 舍弃。矛盾：全量复核的 LLM 判定总会挑残差、3 轮上限常排不完 → 严格语义下多数全量跑会被舍弃（需加轮/放宽/重跑）。
- **舍弃语义修正（同日尾）**：用户澄清"舍弃 = 舍弃不达标的 function，不是全部舍弃"——整批清空是理解偏差。改为 `export_node` 逐函数移除（`merge_groups` 每组保留 supporting obs 最多者），幸存者导出、被移除函数写 `discarded_<ns>.jsonl` 留档；仅全部被移除才判定"无 O_0"。教训：把"剔除坏函数"误实现成"整批丢弃"，应在实现前确认用户意图的粒度。
- **全量 120 验收（同日尾）**：75 候选 → 逐函数舍弃 16 → 幸存 59 导出为 O_0；PASS 5/6。稳定性：① 分离进程 + 文件重定向规避"shell 中断→断管道→孤儿进程空转"；② checkpoint 体积 162→469MB 稳定（all_pairs 三元组修复生效）。教训：长任务用重定向直写文件 + 心跳监控，别用管道 + 前台阻塞。

## 19. 结构化 Observation embedding + 语义化 surface_diversity（2026-08-19）

- **难点（用户提出）**：① `surface_diversity` 靠精确字符串去重（`len(set(surface_form))/3`）——同义改写被算成多个模式、同串误判一个；② obs 被拼成一句（`before | event | after | …`）再 embedding——字段结构丢失、语义权重不分，结构化数据拼起来算不合理。
- **方案**：
  - `Embedding/embedding.py` 新增 `encode_observation`：逐字段 `encode_single` 加权平均 + L2 归一化（`OBS_FIELD_WEIGHTS`：event/after=1.5、before/effect=1.0、affected=0.8、surface=0.6——核心结构字段高、表层低；空字段跳过、全空返回零向量）+ `encode_observations` 批量版；
  - 统一替换所有"拼串→encode"调用点：`Bank.add`、`Retrieval.query_by_observation`、`confidence._compute_semantic_coherence`、`Evaluator coverage/cohesion`、`revise SPLIT 分配`；
  - `_compute_surface_diversity` 改为 embedding 贪心语义去重（`SURFACE_SIM_THRESHOLD=0.80`：与已选模式 centroid 余弦 ≥ 阈值视为同一模式），替代精确 `set()`。
- **验证**：新增 `test_embedding.py` 3 项（同义改写算 1 个模式 / encode 维度·归一化·空字段·单字段等价 / confidence 结构化重算）；`test_evaluator` 的 weak-fit 用例适配结构化编码（离群更难触发，改 8 支持 obs + `[1,9)` 索引）；**79 项全过**。快照抽样 4 函数：新 coherence 0.81-0.84 vs 旧 0.54-0.64（结构化更稳定）；surface 均到上限 1.0。
- **状态**：已落地。Chroma 向量空间变更：旧库 obs 向量仍是旧"拼串"空间，fresh 跑整体重建 Bank 无混合；coverage 阈值 0.65 可能在结构化编码后偏移，验证时若偏差明显同步校准。

## 20. Evolve v1：Matcher 五分类 + 直写 + Pools + FunctionOccurrence 对齐（2026-08-19）

- **背景**：Bootstrap 完成后进入 Evolve。用户给出 `structure-rules.mdc`（完整 Evolve 结构：Matcher→Critic→Pools→触发→Curator→Human Review→Evaluator_final）与 `Plan.md`（大项目方向：Part A 从文本归纳 Function、Part B 用 Function 写大纲），并澄清"Evolve 仍是从文本归纳功能，Plan 是据功能写大纲"。
- **关键决策**：本轮只做 Matcher+直写+Pools（Critic/Curator/触发留后续轮，Pools 格式为其预留）；MATCH/EXTEND 直写 Registry（对齐 rules"更新 exemplars"）；每 obs 落 FunctionOccurrence（对齐 Plan.md 阶段二"obs→Function 映射"，NOVEL=OTHER 不强行分类）；Human Review 自动+留档。
- **实现**：`evolve_app` 单图复用 bootstrap 节点；Matcher = embedding 召回（`encode_observation` vs definition，top-k=5，无硬阈值）+ LLM 按批判定（10 obs/批共享函数卡片）；`RegistryStore.replace_all` 幂等 enrich Card 字段（function_id/status/version_history）。
- **踩坑**：① `MatchDecision` 的 str 字段不允许 null → LLM 常输出 null 触发大量校验重试，改 `str | None` 后重试 20+ → 3（39 obs）；② 残留 `python -m Agent.app` 进程 fresh 启动会清空 bootstrap 命名空间/Bank，必须先终止并从快照恢复（30/1062）+ 迁移；③ 首次冒烟（Tee-Object 管道）后 bootstrap 命名空间消失、二次复现（文件重定向）稳定——疑似管道环境偶发，已恢复并改用重定向。
- **状态**：已落地并验收（90 测试全过；9 篇冒烟 coverage 0.461 / novelty 0.067）。

## 21. Evolve v2：Evaluator_mid 周期体检（每 20 obs 触发，2026-08-19）

- **背景**：用户问"match 之后需要 evaluator 吗"——澄清 Evolve 阶段 Evaluator 不是门禁而是触发式体检（structure-rules：累计 ≥20 obs → Evaluator_mid）；用户方案"MATCH/EXTEND 给 Evaluator、CONFLICT/UNCERTAIN 给 Critic"等价于"证据累积到阈值再整体体检 + 单条不确定走复检"，粒度不同、时机不同，最终都喂 Curator。
- **实现**：`evolve_app` 的 `collector` 累加 `obs_since_eval`，达 `MID_OBS_THRESHOLD=20` → `evaluator_mid_node`（薄包装复用 `evaluator_node`）→ 报告 `evaluation_mid_<n>.json` + `match_report.mid_evaluations` 汇总；滚动触发（体检后归零），不足阈值不体检（Evaluator_final 后续轮）。
- **验证**：93 测试全过；冒烟 3 篇/22 obs 触发 1 次体检 FAIL 3/6（separation 8 组近义是真实信号，diversity/evidence 小样本未达标属预期）。
- **状态**：已落地。Curator/Critic/Evaluator_final 为后续轮。

## 22. Evolve v3：Critic 边界复检 + 待应用区（2026-08-19）

- **背景**：用户定调"MATCH/EXTEND 之后需要 evaluator 不是直接 update"→ 证据应用收口到 Curator；用户给的 Critic 参考表把复检输出细化为四类（match/extend/novel/resolved），并强调用 Hard Negatives 边界反例校验，减少假匹配/假扩展。
- **实现**：`matcher_node` 删直写（MATCH/EXTEND → `pending_evidence`，`_apply_evidence` 保留给 Curator）；新增 `Agent/Critic/critic.py` + `Prompt/Critic_prompt.py`（图 `matcher→critic→collector`，四类分流）；`evaluator_mid_node` 用"当前函数 + pending 证据"的临时 registry 快照评估（应用后视图，`pending_applied` 记录）。
- **验证**：96 测试全过；冒烟 3 篇/30 obs——Critic 复检 15 边界 → match 5 / novel 2 / resolved 8，coverage 0.633（v1 直写 0.318，Critic 归函数后提升），pending 19 / challenge 8 / novelty 3，Registry 未被直写。
- **状态**：已落地。Curator（应用 pending + 消费 pools/体检问题 → 增删改方案 → Human Review 自动留档）为下一轮。

## 23. Evolve v4：Curator 收尾维护（按动作分门槛，2026-08-19）

- **背景**：用户问"非空就触发会不会样本不够"——采纳**按动作分门槛**：APPLY_EVIDENCE 无门槛（纯累积）、ADD 需跨故事 ≥2 且 ≥3 obs、MERGE/REVISE 需 supporting ≥3；不足记 SKIP_SMALL_SAMPLE 保留累积，避免小样本误改本体。
- **实现**：新增 `Agent/Curator/curator.py`（图 `report → curator → END`）：应用 pending（复用 `_apply_evidence` + version_history）、novelty 归纳（复用 `cluster_similar_pairs` + `inducer_node`）、体检修订（复用 `_llm_merge/_llm_revise`）；方案写 `curator_plan.jsonl` 自动留档后 Apply，清空已消费 pending。
- **验证**：101 测试全过；冒烟 3 篇/27 obs——Curator 应用 pending 18 条、novelty 2 obs 样本不足 SKIP、19 动作留档、IRREVERSIBLE_LOSS version v1→v2。
- **状态**：已落地。Evaluator_final（终期全面评估）为后续轮。

## 24. 正式 Evolve（60 篇 5 领域）+ Curator 体检问题消费缺陷（2026-08-19）

- **背景**：用户删 120 原始语料、加 60 篇 5 领域语料（5 类 × 12 篇 + manifest）并重跑 bootstrap（新 O_0 仅 3 函数）；正式 Evolve 要基于旧 O_0（30 函数）——从 `data/functions_export.csv`（DB 导出，payload 整存）恢复，清空失效 supporting。
- **发现缺陷**：`evaluator_mid_node` 的 `mid_reports` summary 没保存 `recommendations` → Curator `_revise_from_report` 拿到的报告无 merge_groups/revise 问题 → 体检问题永远消费不到（冒烟未暴露，正式跑暴露）。修复：summary 增加 `recommendations`。
- **正式跑结果**：542 obs / 21 次体检（末次 PASS 4/6）；Curator 414 动作 → 33 函数（22 旧 + 5 新增 + 2 合并 + 2 组拆分 - 1 移除）。长任务 1h 超时中断、report 后 curator 未执行 → 手动补跑。
- **状态**：数据流完整验证（提取→匹配→复检→体检→维护→写回）。Evaluator_final 为后续轮。

## 25. Evolve v5：Evaluator_final 终期评估 + 最终 Ontology 定稿（2026-08-19）

- **背景**：structure-rules 终期要求 Evaluator_final 全面评估、输出 Final Report + 最终 Ontology；用户确认"图内收尾 + 独立可跑（--final-only）"与"Final Report 含演化前后对比"。
- **实现**：`evaluator_final_node`（`curator → evaluator_final → END`）复用 `evaluator_node`（`force_full_review=True`），Final Report 含六维终评 + 前后对比（基线 `functions_<ns>_start.jsonl` → 最终）；导出 `functions_<ns>.jsonl` + `bank_<ns>.jsonl`；`main --final-only` 独立终评。
- **踩坑**：`--final-only` 验收时活体 Bank 已被 pytest 清空 → coverage/evidence 全 0；修复：`evaluator_final_node` 优先读 `bank_<ns>.jsonl` 快照，并从 `occurrences.jsonl` 重建 542 obs 快照。
- **验证**：102 测试全过；`evolve_official` 终评 PASS 4/6（coverage 0.985 / abstraction 0.97 / diversity 60），对比 30→33（新增 11 / 移除 8 / 保留 22）；终评发现拆分产物镜像近义（RULE_ESTABLISHMENT≈PARANORMAL_RULE_OPERATION）与题材绑定残留。
- **状态**：Evolve 阶段闭环完成（提取→匹配→复检→体检→维护→终评定稿）。后续：Plan.md 阶段一（Story Profile / Function 前置条件角色位置状态变化 / Instance Card）。

## 26. 近义碎片处理：向量预筛失败 → 全量 LLM 扫描（2026-08-19）

- **问题**：用户指出 evolve_official 内部有近义碎片（资源/真相/关系/压力族），Evaluator 的 `merge_groups`（LLM 附加字段）漏检。
- **尝试 1（失败）**：definition 向量余弦预筛——0.85 漏检（MiniLM 中文对"用词不同但同义"不够近）、0.78 假簇（把 ANOMALY_OMEN 连进真相族、FATAL_INCIDENT 连进资源族，LLM 确认也挡不住过度合并）。**教训：MiniLM 中文定义向量不适合做近义判定**（bootstrap 时代 0.85 漏/0.78 假簇的根源）。
- **方案（落地）**：Curator 每批 `_full_merge_scan`——全量函数卡片喂 `Abstract_merge_prompt`（专门任务：识别同一结构作用组，宁少勿滥 + 超大类防护）→ 每组 `_llm_merge` 重新归纳。这是 bootstrap abstract_merge 验证过的机制（59→30），比 Evaluator 的"附加字段"更专注。
- **验证**：40 篇碎片 24→19（5 组合并，1 组门槛 SKIP）；终评 PASS 6/6（separation 0 / abstraction 1.0）。测试 104 项全过。
- **状态**：近义收敛机制已入 Curator（每批自动跑）；demo 结果干净（19 函数）。

## 27. Embedding 换中文模型（text2vec-base-chinese，2026-08-19）

- **背景**：MiniLM（all-MiniLM-L6-v2）对中文"用词不同但同义"的近义余弦不够（向量预筛 0.85 漏、0.78 假簇的根源）。用户要求换适合中文的模型。
- **选择**：`shibing624/text2vec-base-chinese`（中文语义相似度 STS 基准，768 维）。实测近义对 0.853 vs MiniLM <0.78，不同结构 0.422——区分度显著改善。
- **影响**：维度 384→768 → Chroma 重建（Bank 365 obs 重嵌入）；测试 FakeEmbedder 默认维度对齐 768（4 文件）；coverage/cohesion 阈值基于 MiniLM 分布，text2vec 下偏保守（coverage 0.986→0.748，仍 PASS 6/6）。
- **状态**：104 测试全过；终评 PASS 6/6。Curator 近义收敛用 LLM 扫描（不依赖向量），不受换模型影响。阈值如需对齐可后续校准。

## 28. 按 text2vec 分布校准阈值（2026-08-19）

- **实测**：text2vec 下相似度整体上移（跨故事 obs 对 mean 0.63、非 supporting obs 与定义 P50 0.61）——MiniLM 时代阈值偏严/偏松。
- **校准**：`COVERAGE_SIM_THRESHOLD` 0.65→0.60（coverage 0.748→0.847）；`BATCH_EDGE_SIM` 0.60→0.65（聚类连边 65%→40%）；cohesion 阈值保留（supporting fit P10=0.777，0.70 weak-fit 正好抓真离群）。
- **验证**：104 测试全过；终评 PASS 6/6（coverage 0.847）。
- **状态**：阈值体系已对齐 text2vec 分布。

## 29. Curator 近义收敛改 Agglomerative + LLM 确认（2026-08-19）

- **用户思路**："先拎出近义组，再 LLM 处理"——早期向量阈值拎组失败（MiniLM 不可靠），text2vec 换模型后拎组可行；再用 Agglomerative（complete 链接）替代固定阈值连通，解决链式串簇（A-B 近、B-C 近但 A-C 远被强并）。
- **实现**：`_full_merge_scan` 拎组 = `scipy` pdist(cosine) → linkage(complete) → fcluster(距离 0.25)；候选组喂 `Abstract_merge_prompt` 确认；确认组 `_llm_merge`。抽出 `_agglomerative_candidates` helper（单测不串簇）。
- **验证**：19 函数拎出 3 候选组（= text2vec 实测 3 对），LLM 只确认合并关系族（→RELATIONSHIP_DEEPENING），拒绝 KDR~TC（可区分）与 PHS~SI（不同结构）——拎组全而稳、LLM 准而不误并。终评 PASS 6/6（18 函数）。测试 106 项全过。
- **状态**：近义收敛 = Agglomerative 拎候选 + LLM 确认 + `_llm_merge`，每批 Curator 自动跑。

## 30. 函数定义向量缓存（2026-08-19）

- **背景**：text2vec（768 维 BERT）比 MiniLM 慢 ~4 倍，40 篇 Evolve 82min（每篇 123s）。优化 ① 换小模型 bge-small-zh-v1.5、② 缓存函数定义向量。
- **bge 受阻**：hf-mirror 与 huggingface.co 均 SSL UNEXPECTED_EOF（网络对 HF 不可达）——bge 无法下载，暂留 text2vec。
- **已落地**：`Embedder.encode_cached`（文本→向量缓存）+ Matcher/Evaluator/Curator 的函数定义 encode 改用它——单次运行中函数定义不变，跨节点复用，消除每篇重复 encode 30 定义。
- **状态**：106 测试全过；bge 切换待网络恢复（改模型名 + 重建 Bank）。

## 31. 切换 bge-small-zh-v1.5（512 维，2026-08-19）

- 网络恢复后 bge 下载成功；换 `BAAI/bge-small-zh-v1.5`（512 维）替代 text2vec（768 维）——embedding 快 ~4 倍（重建 Bank 34s vs 133s），中文效果接近。
- 终评 PASS 6/6（coverage 0.888 / separation 0）；106 测试全过。函数定义向量缓存（encode_cached）继续生效。
- **状态**：模型链 text2vec → bge（更小更快），40 篇结果 24 函数保留。

## 32. 两 Agent 边界与不可变 OntologySnapshot（2026-08-20）

- **关键判断**：Bootstrap 与 Evolve 是 Function Knowledge Agent 的两个生命周期工作流，不需要合并成一张大图；套路提取与应用属于后续 Story Pattern Agent。
- **边界契约**：两者通过只读、不可变的 OntologySnapshot 交接，避免下游直接读取持续变化的 Registry；v1 只发布 Functions 与最终评估，不打包 Observation Bank，也暂不建立父版本谱系。
- **发布语义**：仅最终终评 `PASS` 自动发布；Bootstrap 的 `abstract_merge` 原本发生在终评之后，现改为合并后再全量终评，确保 PASS 与实际发布的 Function 集合严格对应。
- **状态**：契约、发布器、loader、完整性校验和双流程自动发布已落地；下一步可基于冻结快照实现 Story Pattern Agent 的只读 Corpus Mapper。

## 33. Story Pattern Agent 从已有 Observation 起步（2026-08-20）

- **关键修正**：Story Pattern Agent 不重新运行 Preprocessor/Observer；Bootstrap/Evolve 已经完成原文到 Observation 的转换，新 Agent 直接消费 `bank_<namespace>.jsonl`，只在冻结 OntologySnapshot 下重新统一映射 Function。
- **第一节点**：新增独立 `StoryPatternState` 与只读 `load_inputs`，严格校验 Snapshot、Observation 必要字段/唯一性/连续编号及 manifest 归属，再按 manifest 顺序建立故事分组和 Function 双索引。
- **真实数据验证**：`evolve_official` 23 Functions + 60 篇 manifest + 502 Observations 全部通过，无重复、越界或编号断裂；节点不调用 LLM、不访问 Registry/Bank。
- **状态**：`load_inputs` 与 `select_story` 已完成；下一节点是只读 `map_observations`，从当前故事 Observation 召回并判断冻结 Snapshot 中的 Function。

## 34. FunctionOccurrence 应从上游发布，而非下游重算（2026-08-20）

- **用户反问**：Evolve 的 Matcher/Critic 已产生 `MATCH/EXTEND/CONFLICT/UNCERTAIN/NOVEL`，Story Pattern 再跑一次映射是否重复？答案是重复；问题根源是旧 occurrence 没有绑定最终 `snapshot_id/function_id`。
- **关键修正**：最终 Function 的 `supporting_obs_ids` 是经过 merge/revise/split 后仍保留的权威证据，可在 Bootstrap/Evolve 发布边界反向生成最终 FunctionOccurrence，不需要维护脆弱的函数改名映射。
- **多对多语义**：FunctionOccurrence 只是某 Function 在某故事中的一次实例；一个 Function 可在不同故事中反复出现并参与多个模板，模板也由多个 Function 组成。Snapshot 冻结样本版本，不定义 `Function → 单一模板`。
- **后续边界**：Story Pattern 应读取同一 Snapshot 内的 Functions + occurrences，先按故事形成序列，再跨故事提取多个 motif/template；只复检 `UNCERTAIN`，不全量重跑 Matcher。

## 35. 两个 Agent 平级，契约单独归档（2026-08-20）

- `FunctionExtract-Agent/StoryPattern` 会错误表达从属关系，也会造成两个 Story Pattern 实现并行维护。
- 最小清晰结构是 `Contracts/`、`FunctionExtract-Agent/`、`StoryPattern-Agent/` 三个平级目录。
- `Contracts` 只负责 Snapshot 和 FunctionOccurrence 的跨 Agent 数据格式；业务节点仍归各自 Agent 管理。

## 36. FunctionOccurrence 的最小下游步骤（2026-08-20）

- 不再从 Observation 重新匹配 Function；Story Pattern 先读取 Snapshot 内已发布 occurrence。
- 先按故事分组，再按原文句子位置恢复序列；`OTHER/UNCERTAIN` 保留为序列节点，供后续边界复检和模板提取使用。
- 模板提取尚未开始；本轮只建立可验证的逐故事序列输入。

## 37. 目录迁移的兼容策略（2026-08-20）

- FunctionExtract 已迁移为 `FunctionExtract_Agent` 后，旧测试和 CLI 仍使用 `Agent.*` 及顶层模块导入。
- 不复制模块或恢复旧目录；使用 `Code/Agent/__init__.py` 设置兼容包路径，并将唯一源码根加入 `sys.path`。
- 这样既保持新目录架构，也避免一次性改写大量历史导入；全量回归恢复为 153 项通过。

## 38. 重复不是去重，而是 repetition run（2026-08-20）

- 用户追问“为什么压缩重复”后明确：occurrence 层的每次出现都是真实证据，不能删除；结构层只把连续同 Function 标注为一个 run。
- `F1 → F1 → F2` 可表示为 `F1×2 → F2`，但 `F1 → F2 → F1` 必须保留回环；未决节点永远切断 run。
- raw sequence 与 structural sequence 同时存在，`repeat_count + occurrence_ids` 保证结构统计和证据追溯兼得。

## 39. Function 是索引入口，故事是顺序证据（2026-08-20）

- 用户追问为何按 60 篇故事运行：连续性和前后关系只能在故事边界内恢复，但模板查询应以 Function 为入口。
- 因此先按故事建立有序结构序列，再在循环结束后反向建立 `function_id → contexts`；两种视角不是二选一。
- 未决节点切断片段，避免把边界两侧伪造成直接连接；Function context 保留完整 MATCHED 片段和锚点位置，供下一步精确 motif 提取。

## 40. 精确重复稀少是数据事实，不是需要降低标准的错误（2026-08-20）

- 首版 motif 严格定义为长度 3–6 的连续 Function 局部结构；不允许跳步，也不用 repetition 次数拆分身份。
- 60 篇真实数据产生 321 个精确候选，但只有 1 个被至少 2 篇不同故事支持；320 个单故事候选只是后续语义变体聚类的证据，不能直接发布为稳定套路。
- 下一阶段才引入 Embedding 召回近似结构、LLM 审查合并与总结；确定性提取层保持为可审计的基线。

## 41. Embedding 只召回 motif 变体，不裁决套路（2026-08-20）

- 整句 motif 向量会弱化步骤顺序；本轮改为逐 Function 编码并按位置对齐，保留“哪一步与哪一步相似”的可解释证据。
- 长度差与缺省步骤不再作为硬限制；3–6 步序列通过保序动态对齐允许多个潜在可选步骤，但召回层仍不判定哪些是核心/可选步骤。
- `Top-5 + 最低 0.75 + 0.85 分层` 在真实数据上生成 1,126 条边并覆盖 317/321 个候选；EXPANDED 层占多数是高召回的代价，后续 LLM 应优先审查 HIGH，再分批处理 EXPANDED。
- 这些相似边可能存在误报和链式传播；下一节点需由 LLM 基于 Function 定义与故事证据逐对审查，不应直接对 Embedding 边做连通分量并发布为套路。

## 42. LLM 审查应是可续跑的逐对循环（2026-08-20）

- 1,126 条召回边若在一个节点内串行审查，会造成长事务、失败后难以恢复，也无法清晰控制 HIGH/EXPANDED 的调用预算。
- `review_motif_pairs` 因此每次只处理一对，由 State 索引推进；后续 Graph 可通过 `has_next_motif_pair` 条件边循环并接 checkpointer，先运行 HIGH，再按预算处理 EXPANDED。
- LLM 只裁决 pair 语义，不改写候选、不计算最终支持度、不直接聚类；只有 `SAME_PATTERN` 审查边才能进入后续 cluster 构建，支持度仍由规则基于不同 story_id 重算。

## 43. 真实 LLM 审查暴露了“同构判定”与“发布充分性”混淆（2026-08-20）

- 10 对真实抽样中，Embedding HIGH 5 对只有 1 对被判为 `SAME_PATTERN`，其余多为 `RELATED`；低阈值末端样本被判 `DIFFERENT`，说明召回分层有区分度。
- 但模型对“核心三步完全一致、只多一个潜在可选步骤”的 pair 仍以“跨故事证据不足”为由判 `RELATED`。这是职责越界：pair reviewer 应只判断结构是否同构，最终套路能否发布应由 cluster 后的 story support 规则决定。
- 在批量审查 156 条 HIGH 前，应进一步收紧 prompt：禁止用样本数量/发布充分性影响 `SAME_PATTERN` 判定，并用少量金标 pair 做真实 LLM 校准；否则审查会系统性偏保守。
- 收紧 prompt 后，同一 5 条 HIGH 的 `SAME_PATTERN` 从 1 条提升到 4 条，说明职责分离修正了系统性偏保守；但原本判 SAME 的“外援→部分真相→外援 / 外援→完整真相→外援”在复测中变为 RELATED，显示单次 LLM 判定仍有随机性和边界误判。
- 因此批量运行前仍应建立少量金标 pair；对于 HIGH 边界案例，可考虑两次独立审查或仅对低置信/判定冲突项复审，而不是默认相信单次 verdict。

## 44. LLM 不应被要求誊写无语义主键（2026-08-20）

- HIGH 全量审查中，1 条 pair 两次将长 `variant_pair_id` 誊写错一个字符，尽管语义输出有效；把 ID 放进 LLM 输出只增加脆弱性，不增加审查质量。
- 审查节点已改为从当前 State 绑定 `variant_pair_id`，LLM 只返回 verdict、置信度和解释。这样仍能保证结果与输入 pair 的一一对应，也避免同类的无意义重试。
- 156 条 HIGH 的真实结果为 SAME_PATTERN 31、RELATED 109、DIFFERENT 16。下一阶段只应以 31 条 SAME_PATTERN 边构建候选 cluster；RELATED 仍保留为审计与后续人工/二次审查证据，不能直接连边聚类。

## 45. 项目 MVP 必须是端到端大纲闭环，而非只发布套路目录（2026-08-20）

- 用户要求将项目的完整规划和 MVP 后路线写入交接文档。需要区分两个层次：PatternCatalog 是当前分析链的 MVP-A；真正面向目标用户的 MVP-B 必须从用户约束出发，经过 Pattern/Function 规划、角色和状态约束、实例化、验证，产出一份可解释大纲。
- 不能把 31 条 SAME_PATTERN 边直接称为 31 个套路或直接用于生成；中间仍需 cluster、支持度重算、模式总结与发布，再补齐 StoryProfile、Function 状态变化和 InstanceCard 等生成前置知识。

## 46. 四个已发布模板暴露 Function 本体可能偏少（2026-08-20）

- 用户提出：真实故事中应有更多 Function 组合，当前 23 个 Function 是否过少。
- 当前证据支持“本体偏少/偏粗，但发布数量还受到下游过滤”的双重判断：Snapshot 有 23 Functions、384 个 MATCHED occurrence、115 个 UNCERTAIN occurrence；只看 156 条 HIGH review 后，31 条 SAME_PATTERN 形成 12 clusters，严格链式传播检查后只有 4 个 clean cluster，最终发布 4 个模板。
- 四个已发布模板的支持故事全部为 2，且每个只覆盖单一题材；这更像当前 Function 抽象和审查覆盖不足的信号，不能当作稳定的跨题材 Pattern 基线。
- 不能直接凭感觉增加 Function。下一次本体审计应同时检查：115 个 UNCERTAIN 是否包含缺失 Function、现有 Function 是否把多个状态变化合并得过宽、是否缺少结局/目标达成/失败/回报等故事阶段，以及 970 条 EXPANDED 候选中是否存在被 HIGH 截断的组合。
- 在本体审计前，不应把当前 4 个模板当作完整套路库，也不宜直接进入生成验证；应先决定是补充/拆分 Function，还是仅扩大 Pattern review 覆盖。

## 47. 历史 O_0 数量不能与当前冻结本体混用（2026-08-20）

- 用户追问“DB 里不是有 52 个 Function，为什么 Phase 1 说只有 23 个”。核查后，52 是 2026-08-18 全量 120 篇旧运行产物 `O_0` 的导出数量，不是当前活跃 `evolve_official` 命名空间，也不是本轮 Phase 1 的输入。
- 当前 SQLite Registry 以 `(namespace, function_name)` 隔离：`bootstrap` 有 30 条、`evolve_official` 有 23 条，合计 53 条物理记录；两命名空间复用了 18 个名称，故跨命名空间去重后仅 35 个名称。不能把任一口径称为“当前 52 个”。
- Phase 1 绑定的 PASS OntologySnapshot 明确冻结 `evolve_official` 的 23 个 Function 和 502 个 occurrence。将旧 O_0 或其他命名空间的 Function 直接混入会使既有 occurrence 标注、motif 和 PatternCatalog 的可追溯链失效；扩充本体须经重新标注/评估并发布新 Snapshot。

## 48. 历史本体重跑依赖可恢复的精确输入（2026-08-20）

- 用户决定以历史 52-Function 本体重新运行 Phase 1，并询问为何不覆盖现有 23-Function Snapshot。已明确：Published Snapshot 必须保留，旧 Pattern/occurrence/review 均通过其 `snapshot_id` 追溯；新本体只能发布新版本，之后才清理旧 Story Pattern 的生成产物。
- 恢复审计显示原始 52-Function 导出当前不可得：`functions_export.csv` 已在后续 60 篇语料流程中覆盖为 30 条，历史 120 篇原语料也已删除；工作区数据、Git 历史和悬挂对象均未找到 52 条完整定义。不能以 93/96 条实验备份任意裁剪来伪造“历史 52”。
- 后续只能二选一：取得原始 52-Function JSONL/CSV 后精确重跑，或明确改为在当前 60 篇语料上重新归纳新本体。两种路径都要重新发布 Snapshot，不能覆盖 23-Function 版本。

## 49. Function Card 补全：实例级 vs 类型级、悬空成因与证据口径（2026-08-27）

- 用户反问“为什么要 Function Card？Observation 已有模板需要的参数”：Observation 是单故事实例级（participants 是“太子/皇后/竹马”等故事角色标签，before/after 是单篇具体状态），模板/大纲按 Function 组织，需要的是类型级结构约束（角色槽位、跨故事状态变化）。MVP-A（套路目录）不需要 Card；MVP-B（大纲生成）需要。
- 用户追问“为什么 53/62 函数有悬空”与“每次 Bank 都是新建的吗”：机制是 Function 本体跨语料继承（种子复制、supporting 只增不删、MERGE 并集传播）vs Bank 语料本位重建/累积（bootstrap 清空重建；evolve 复用累积、按 obs_id 去重），两个存储生命周期不同步。660 条悬空 = 401（evolve_clean）+ 258（bootstrap）+ 1（无出处）。
- 证据口径决策：`supporting ∩ Bank` 为准；occurrences 的 `candidate_functions` 不可用（align_occurrences 的 `occurrence.update(prior_by_id...)` 残留旧 match 候选字段，实测 350 条带 candidates、真多支持仅 8 条）。
- 卡片带 dangling 完整性指标（declared/resident/dangling），让下游能区分“证据本来就少”和“证据被丢弃”。
- state_transition 用结构化 `{before, after}`（便于 Outline Realizer 状态账本消费）；story_stage 暂缓；本轮不改 Inducer/Merge/Revise schema，等 62 张卡片格式验证后再同步，避免格式返工。
- 用户确认目标为 MVP-B（做大纲），Function Card 补全作为 Phase 2 首步落地；62 张卡片一次性补全完成（62/62 OK）。
- 用户结论：语料继承并不等于 Bank 继承——Bank 从不清空且语料延续才能避免"换语料型"悬空；但即使 Bank 全继承，提取配置漂移（V1→V3 分句、Observer 输出调整产生不同 obs_id）、MERGE 并集传播、以及从未持久化就写入 supporting 的引用（本次 660 条中 1 条）仍会造成悬空。彻底根治需在发布新快照时做函数侧 supporting 清理（校验 ⊆ 当前 Bank），已记为待解决。

## 50. MVP-B 首轮盲评暴露 Pattern 闭合性问题（2026-08-27）

- 三组中，完整系统 `full` 总均分 3.22，低于 `function_only` 的 3.44 和 `direct` 的 3.94；核心三项均值为 3.33、3.67、4.22。
- 这不是简单的文笔问题：悬疑 full 停在“危险暴露/逃脱”，末世 full 停在“自由被剥夺”，二者都没有完成主线解决；而 Validator 仍可给出结构层面的 `overall_ok`。
- 当前优先级应从“增加机制检索或 Best-of-N”转为“Pattern/Planner 选择可闭合故事链”。需要把解决/结局能力作为候选 Pattern 的硬约束，或让 Planner 在核心链之后明确规划结局阶段。
- 该结论来自单评审，适合作为工程诊断，不作为论文级统计结论；修复后应沿用同一协议复测，并补充多人评审一致性。

## 51. Pattern 是局部 motif，不应直接等同完整故事骨架（2026-08-27）

- 临时白名单实验中，full 的结构完整性由 3.33 升至 4.00，总均分由 3.22 升至 3.50，说明“过程链直接充当完整故事”是有效诊断，但不能据此把 Function 固化为“结局型/非结局型”。
- 但“末端 Function 有结果方向”和“具体实例真正闭合”仍是两层：本轮 9 个 full 全部通过末端硬约束，仍有 2 个被语义 Validator 判为没有兑现 `ending_direction`。前者属于 Planner，后者属于 Realizer。
- full 仍低于 function-only 和 direct，说明 Function Card、状态账本和机制检索目前更多保证了结构约束，没有稳定转化为更具体的人物目标和不可替换的事件机制。
- `_CLOSING_FUNCTIONS` 把语境依赖的链路属性错误地下沉成 Function 名称属性，扩展新文本时必然需要人工维护，因此已撤回；`closure_v2` 只保留为临时启发式实验。

## 52. Function 发布变换合同，闭合由组合链路判定（2026-08-27）

- 单个 Function 的职责是声明“在什么角色/状态条件下，产生什么状态变化，并开启、推进或解除哪些义务”，而不是声明“自己能否作为结局”。同一 Function 在不同前置状态和后续组合中，可能处于开端、中段或末端。
- `FunctionContract` 必须由 Function 的驻留 Observation 证据归纳，并绑定 Function 定义哈希；Function 经 MERGE/REVISE/SPLIT 后，旧合同不能继续沿用。
- 正式发布时机只能在 Function 集合稳定且终评 PASS 之后：Bootstrap 位于 `abstract_merge` 之后，Evolve 位于 Curator 与 `Evaluator_final` 之后；合同和 Function 一起进入不可变 Snapshot v3。
- StoryPattern 后续应根据合同的状态效果和义务效果组合可执行链；Outline 再把类型级角色槽位绑定到实例角色，并检查故事终态是否解决目标冲突和未清义务。这样新增文本改变的是证据和合同，不需要扩充人工结局名单。

## 53. 发布链闭合不等于消费链闭合（2026-08-27）

- v3 Snapshot 探针可以读回 FunctionContract，但 StoryPattern 的 State 没有合同字段，说明合同目前停留在发布物层，没有进入 Pattern 归纳输入。
- Outline 的 Planner/Mechanism/Validator 仍分别读取 PatternCatalog、Function Card 和 transition index；即使 Snapshot 含有合同，合同中的状态效果与义务也不会影响选链、实例化或终态校验。
- 因此下一步不是立即重跑盲评，而是先建立唯一的合同消费路径：Snapshot loader → StoryPattern Pattern → Outline Planner/Mechanism/Validator，并用可观测字段验证状态/义务是否完整穿透。

## 54. FunctionContract 已穿透消费链，但真实词汇仍需验收（2026-08-27）

- 现在合同已经不是只读发布物：v3 loader → StoryPattern State → Pattern 核心链 → Outline Planner → Mechanism Contract Ledger → Validator/Export 全部有实际字段传递和确定性测试。
- 合同与旧 Function Card 的职责分开：v3 合同是角色槽位、状态前置/效果和义务的权威来源；Card/transition index 仍可提供自然语言和真实机制提示，但不能覆盖合同状态。
- Contract Ledger 解决的是“类型级效果是否能在实例链中连续、义务是否清偿”，不是从文本中自动证明每个 beat 真的实现了该状态；这仍由 Validator LLM 的情节复核承担。
- 下一验收点是生成真实 62-Function v3 Snapshot 并跑 StoryPattern 全流程，观察合同中的状态词汇是否足以支撑 Pattern 链；确认通过后再重跑三组盲评，比较合同消费前后的实际质量变化。

## 55. 真实 FunctionContract 先暴露词汇问题，再决定是否重评（2026-08-27）

- 真实 62-Function v3 Snapshot 已发布并通过校验：62/62 合同、2193 条 Observation；合同词汇包含 94 个 aspect、398 个 state、139 个 obligation key。说明发布链能承载真实数据，但当前大写格式约束不是语义词汇约束，`EDANGER` 这类漂移仍可进入合同。
- 用同一 Function 集合的历史 71 个 Pattern 做严格链间检查，226 条相邻边的 exact compatibility 为 0。这个结果不能直接解释为 71 个 Pattern 全部不成立，因为检查把未区分的世界初始条件也当作链内前置条件；它确认的是当前合同还没有形成可直接拼接的状态接口。
- 因此闭合问题仍应在系统层解决：先在 `FunctionExtract_Agent` 的合同发布阶段建立证据约束的 canonical StateVocabulary、别名/拼写归一化，以及“初始条件 vs 上一步产物”的边语义；再让 StoryPattern 只发布可组合链，最后才重跑三组盲评。不能用新的手工结局名单替代这层本体约束。

## 56. MVP 先冻结，合同语义改进列入后续（2026-08-27）

- 当前 MVP 的交付目标是证明“真实 Function → Snapshot → Pattern/Planner → 大纲 → Validator”能够运行并产生可审计产物，不要求第一版合同词汇已经达到论文级的跨 Function 组合质量。
- 后续改进按依赖顺序排列：`StateVocabulary` 与证据绑定 → 初始条件/链间条件的边语义 → 合同约束下重新发布 PatternCatalog → 同协议三组盲评 → 多人一致性评审。这样可以把当前 `0/226` 当作待解决的本体接口问题，而不是用启发式名单掩盖。
- 需要保持的架构判断：闭合属于组合链和实例终态属性，不属于 Function 名称属性；合同生成器负责发布可验证的变换接口，StoryPattern 负责组合，Outline/Validator 负责实例化和终态兑现。
- 需要保持的 MVP 取舍：暂不做 Best-of-N、正文生成、全量 StoryProfile、人工结局标签和论文级评审扩展；这些工作依赖合同词汇稳定后再评估。

## 57. MVP-B 收尾，后续从实际使用问题开始（2026-08-27）

- 当前阶段可以收尾。MVP 的判定标准是从真实 Function 到可审计大纲的链路跑通，而不是要求状态合同一次性达到完整本体论质量。
- `StateVocabulary` 和链边语义属于后续架构增强，当前只记录问题，不把它们变成新的验收门槛；否则会让 MVP 在已能交付后继续无限延长验证周期。
- 下一阶段应先使用现有系统生成一批真实目标大纲，按具体失败案例选择一个小问题修复。只有当实际使用反复证明合同组合是主要瓶颈时，才启动状态词汇规范化。

## 58. 实际使用批次把下一步收窄为“结局段兑现”（2026-08-27）

- 用当前 MVP 生成 9 份 full 大纲，5 份通过 Validator，4 份未通过；失败不是抽象的合同兼容性指标，而是可以直接定位到大纲内容的重复和未完成结局。
- 其中 3 份停在营救、逃避、重建或后续行动，核心冲突没有真正解决；另 1 份是重复 Function 的情节完全复制。现代情感 3 份均通过，说明应先修复具体生成约束，不要扩大成全系统重构。
- 因此下一步选择“让最后一段兑现 seed.ending_direction 并稳定核心冲突”作为单一迭代目标：先检查现有 Seed/Realize/Validate 的数据传递与提示词，再做最小修改和小批复测。`StateVocabulary` 继续留在后续 backlog。

## 59. 结局要求应属于 Pattern 元数据，不属于 Function（2026-08-27）

- 实现时确认：Pattern 是可复用的局部结构，不能把一个结局 Function 硬塞进所有核心链；但当 Pattern 被当作完整故事模板使用时，需要在 Pattern 摘要阶段声明它要求解决的冲突和稳定终态。
- 因此新增的是可选 `ending_spec`，不是新的 Function。它沿 `Pattern → Planner → Seed/Realizer/Validator` 穿透；Realizer 产生结构化 `ending`，Validator 再判断具体情节是否兑现。
- 该方案保留局部 motif 的复用性：没有真实结局证据的 Pattern 可以保持 `ending_spec=null`，不被伪装成完整故事模板。旧 Catalog 不就地迁移，重新发布时再生成新版本。

## 60. ending_spec 已进入真实 Pattern 发布物（2026-08-27）

- 重新发布使用同一 Snapshot、Bank、manifest 和冻结 HIGH 评审，只重做 summary/catalog 层，因此可以把新增的 Pattern 结局元数据与旧版结果直接区分开。
- 真实发布结果为 `74` 个 summary、`74` 个 published Pattern，`10` 个带证据支持的 `ending_spec`；局部 motif 保持 `null`，避免把不完整结构强行包装成完整故事模板。
- 新 catalog 能驱动 Outline 生成结构化 ending，但一次冒烟仍暴露实例层问题：最后一个 Function 的状态效果没有在对应段落内完成，而是被延后到 ending。由此确认 `ending_spec` 是必要的模板约束，但不能替代 Realizer/Validator 对最后一段实际兑现的检查。

## 61. 正文生成应是大纲之后的独立实现层（2026-08-27）

- 普罗普 Function 规定的是叙事中的结构作用，不等于正文的自然场景；正文需要先把 Function 段、角色、机制、因果 beat 和结局要求转换成可写的场景计划。
- 首版只做 `大纲 JSON → 场景计划 → 整篇短篇正文`，不让正文 Agent 重选 Function 或改写核心冲突。场景必须保持大纲段顺序，最后场景实际兑现 `outline.ending`。
- 辅助要素、同化、逐场生成、自动修复和 Best-of-N 都属于后续质量增强，不纳入正文 MVP。

## 62. 普罗普约束应在场景与正文生成之前成为显式写作合同（2026-08-27）

- 仅把 Function 名称和大纲段传给正文，主要依赖模型自行理解结构作用；前置 LLM 节点应先把每个 Function 解释为本段必须造成的结构后果、角色位置、状态变化和对下一段的因果支持。
- 确定性程序负责不可协商的结构身份：段索引、Function 名称、数量和顺序；LLM 负责把 seed、机制、合同账本和结局要求转成实例级自然语言约束。这样既让普罗普思想参与生成，又不把开放语义误写成硬编码 Function 名单。
- 故事级约束把开端核心冲突与结局解决动作、可观察事实和稳定终态绑定，补足“最后一个 Function 段”和完整故事结局之间的接口。
- MVP 不增加正文后语义校验，因此前置约束能提高生成时的因果注意力，但不能证明正文一定逐项兑现；字符长度仍按现有规则统计和标记，不触发自动修复。

## 63. 正文分层在 9 组 A/B 中取得小幅结构优势（2026-08-27）

- 同一批 9 份大纲生成 A/B 正文后，`Function 约束 → 场景计划 → 正文` 获单一 LLM 评审优选 5 组，直接 `大纲 → 正文` 获优选 4 组；A 的结构完整性、因果连贯性、人物动机和冲突兑现均略高，新颖性相同。
- 这支持“Function 先转成实例级场景约束，再写正文”的工程方向，但差距很小，且不是多人评审结论；长度达标率 A 为 5/9、B 为 2/9，也只能作为生成稳定性的辅助信号。
- 历史 3×3 大纲与当前正文入口契约存在版本差异。为保持材料可比，评测只在内存中从最后一段和 `final_ledger` 投影 `outline.ending`，未修改原始大纲；后续若要做正式基准，应先固定新版大纲快照和 ending 来源。

## 64. 结局场景语义约束暂缓修正（2026-08-27）

- 当前 MVP 先保留现状：最后场景的 `resolves_ending` 只表示其位于计划末端，不能证明正文已经完成核心冲突的解决动作和稳定终态。
- 这不会阻止模型偶然生成闭合故事，但会使结局质量依赖 LLM 自行把 `outline.ending` 补入正文；当前仅作为已知限制，不把它当作本轮 A/B 对比的阻塞条件。
- 后续质量稳定化时再将 `resolution_actions`、`conflict_resolution` 和 `required_final_state` 绑定到最后场景的实际行动与状态变化，并增加对应的语义检查。

## 65. 正文批量生产可以先用自动诊断收集问题（2026-08-27）

- 10 篇正文批量运行证明当前 MVP 可以进入实际产出阶段：生成链全部完成，JSON/Markdown 导出稳定，内容诊断可以独立于生成链执行。
- 自动诊断比单看 `length_ok` 更能暴露正文问题：短篇幅是数量问题，人物动机、因果跳步和结局未兑现才是内容质量问题。第 10 篇的“对抗转合作”具体说明了前置约束仍不能保证正文执行结局动作。
- 当前诊断器的 `category` 由 LLM 自由输出，存在“因果连贯性/因果关系”“冲突解决/结局收束”等同义类别分裂；这不阻塞本批次，但后续若要统计趋势，应先建立固定问题类别枚举，再比较批次。
- 结论：当前阶段先积累真实正文和可复现问题，不自动重写正文；后续优先选择一个高频且影响结构的问题进行小步修复。

## 66. 重复 Function 的递进依赖位置身份，而不是名称（2026-08-27）

- 之前的设计判断仍然成立：重复 Function 应保留，并按 occurrence 逐次增加信息、风险或代价。
- 实际故障来自按 `function_name` 建字典的输出对齐：同名项互相覆盖，导致 Prompt 要求的递进内容在进入大纲前丢失。解决重复问题的最小正确边界是为每个链位置保留 `segment_index`，按索引对齐并用 Function 名做一致性校验。
- 正文质量诊断还暴露了一个入口边界：`validation.overall_ok=false` 的大纲可以作为失败样本研究，但不应进入正式正文生产。正式批处理现在先拦截；历史兼容材料仍需显式标记为诊断输入。

## 67. 两项最小修复通过真实链路回归（2026-08-28）

- 真实 LLM 回归中，5 份含重复 Function 的通过大纲都保留了独立 occurrence，重复项的 Mechanism 与 beats 均不同；因此可以确认问题根因是输出对齐，而不是“重复 Function 不应递进”。
- 真实 `overall_ok=false` 大纲被正文入口跳过，5 篇生成正文的源大纲全部为 `overall_ok=true`。正式生产入口和历史失败样本研究入口由此分开。
- 这两个修复没有改变正文质量：5 篇中只有 2 篇达到长度目标，说明篇幅、动机、因果和结局兑现仍需后续正文层改进，不能把本轮结构回归结果解释为整体质量已经解决。

## 68. 短篇与长篇应采用不同的正文上下文策略（2026-08-28）

- 当前 3000–5000 字短篇可以在一次调用中容纳完整场景计划；整篇生成更利于统一文气、铺垫和结局，不必为未来长篇提前引入逐场状态管理。
- 短篇正文的最小质量改进应优先发生在单次调用的输入约束：明确各场景篇幅、行动后果、相邻因果和结局终态，而不是增加生成节点或正文后修复循环。
- 场景篇幅只是软目标，能够改善模型对篇幅分配的注意力，但不构成长度保证；是否有效仍需通过真实批次观察，不能仅凭 Prompt 变更宣称解决。

## 69. 单次 Prompt 能改善平均篇幅和结局注意力，但不能精确控制长度（2026-08-28）

- 同一 5 份大纲重生成后，平均篇幅从 2853 增至 3928 字，结局闭合自动评分达到 5.0；完整输入与明确结局动作有助于模型统筹全文。
- 达标率仍为 2/5，因为软预算同时产生超长和略短样本。下一步若只靠继续堆叠字数措辞，收益可能有限；长度精确性与内容结构质量应分开衡量。
- 当前更稳定的正文缺陷不是 Function 顺序，而是局部实现：动机铺垫不足、关键转折缺少预示、高潮和终局压缩。后续 Prompt 迭代应针对这些可观察行为，避免扩大成逐场上下文架构。

## 70. 情节实现 Prompt 的收益与输出服从性需要分开验收（2026-08-28）

- 强化动机、铺垫和转折步骤后，同大纲复测的因果与人物动机均分各提高 0.4，问题数量减少，说明把要求放在场景计划与正文执行两层具有局部效果。
- 同一批次却出现平均篇幅下降、结局闭合分回落和内部角色 ID 泄露。Prompt 对某一维度施加更多注意力，可能挤压模型对篇幅、结局或格式规则的服从，不能只看目标指标定版。
- 本次不是固定采样参数下的多人盲评，仍包含生成随机性。正确结论是“值得继续验证的积极信号”，而不是“Prompt 已解决情节实现问题”。

## 71. 动机、伏笔和因果应从正文 Prompt 中分离为前置场景增强（2026-08-28）

- 当正文 Prompt 同时负责规划和写作时，规则之间会竞争模型注意力；新增 `enrich_scenes` 将“为什么行动、前场如何导致本场、后续需要什么铺垫”单独结构化，正文只负责自然表达。
- 该节点不是第二个大纲生成器：它只能按既定 `scene_id` 补充解释，伏笔必须指向后续已有场景，且不能改变 Function、beats、state_change 或结局。
- 真实烟测确认增强结果能完整进入导出物并支持一次性正文生成；但单篇烟测不能证明内容质量提升，仍需同一批大纲的对照评估。

## 72. 场景字数应让位于叙事完整性，但不能取消全篇篇幅保护（2026-08-28）

- Function 和场景是结构作用单位，不是等长的篇幅单位；情感递进、证据建立和结局兑现所需篇幅本来就可能不同。
- 同一现代情感大纲去掉 `scene_char_targets` 后，新正文的局部情感展开略自然，但总长从 `3087` 降到 `1766`，证明“取消每场字数”本身不能解决压缩问题。
- 适合短篇 MVP 的约束应分两层：场景层要求关键事件完成触发、行动、阻碍、选择和结果；故事层保留全篇最低篇幅，避免模型用过度概括满足结构字段。
- 因此不应恢复场景平均字数，而应把全篇下限和语义完整性作为正文输出的联合验收条件。

## 73. 全篇下限和场景语义闭合应联合约束正文（2026-08-28）

- 去掉场景字数表后，模型可能用较短正文完成全部结构字段；因此“自然分配篇幅”需要全篇最低输出保护。
- 全篇下限不能替代情节约束：长度可以通过空泛描写增加，只有场景目标、行动、转折和结果都实际发生，才能改善完整性。
- 结局尤其需要展开解决行动、对抗结果、人物反应和稳定终态，不能把“危机解除”当作结果本身。

## 74. reasoning effort 主要改善统筹，不是篇幅控制器（2026-08-28）

- 仅给 `write_story` 开启 `reasoning_effort=high` 后，正文把人物过去、危险前因、证据链和结局后果展开得更充分，说明推理档位对跨场景统筹有积极作用。
- 同一实验生成 `6374` 字，超过 `5000` 上限；高推理可能让模型更愿意补全，但不会自动遵守中文字符区间。
- 因此 reasoning effort 应作为质量变量单独评估，不能替代全篇长度控制，也不应默认对 Function 约束、场景计划、增强和正文全部开启。

## 75. 纯 LLM 对照显示结构输入影响的是展开程度（2026-08-28）

- 同一基础素材下，纯 LLM 直写可以自行生成“受压迫—受助—合作—揭露—确认关系”的表面主线，但正文只有 `2395` 字，人物动机、危险升级和情感转折被快速交代。
- 结构化链路提供的 Function 约束、场景计划和动机/伏笔/因果增强，不只是告诉模型“发生什么”，还把跨段落的前因、行动和后果显式化，因此更容易得到完整展开；它不能自动解决长度上限问题。
- 本次配置名为 `medium`，但当前提供商将其映射为实际 `high`，后续若要测试真正较低推理强度，需要使用提供商实际区分的档位，否则比较结论会混入配置语义误差。

## 76. 纯 LLM 即使提高长度下限也不稳定（2026-08-28）

- 对照版本《在风暴中靠近》只接收基础素材，生成 `4781` 字；相比结构化链路《夜色里的灯火》的 `6374` 字，长度更接近但仍少 `1593` 字。
- 纯 LLM 可以自发形成完整的表面事件链，但关键证据、援助来源和反派升级机制更容易压缩或临时引入；这支持“结构输入主要改善展开与衔接”的判断。

## 77. 跨题材对照仍显示结构化链路的优势（2026-08-28）

- 在末世科幻题材上，结构化版 `3495` 字、纯 LLM 版 `2873` 字，长度差 `622` 字，已足以进行同量级比较。
- 纯 LLM 能生成有吸引力的背叛反转，但把多个关键机制集中到后半段；结构化版更稳定地把受伤、怀疑、识别、策反、迁徙和新家园串成连续因果。
- 这说明比较时应优先保持输入素材与长度量级一致，再分别观察“结构闭合”和“局部戏剧性”，不能只用标题或字数判断质量。

## 78. 最终正文 Prompt 已携带大部分结构信息（2026-08-28）

- 将结构化正文产物中的完整 `STORY_PROMPT` 与 Function 约束、场景计划、动机/伏笔/因果增强一起直接交给 LLM 后，生成结果与结构化原文在宏观情节和因果路径上高度接近。
- 这说明前置节点的价值不只在于“调用顺序”，更在于把结构判断转译为可执行的正文输入；如果最终 Prompt 已包含全部中间结果，直接调用与经过图执行的质量差距自然会缩小。
- 本次直接调用仍泄漏 `P3` 角色 ID，并压缩了部分行动和结局过程，表明结构化链路的剩余价值主要体现在中间结果的对齐、角色 ID 自然化和输出稳定性，而非必然改变故事主题或宏观情节。

## 79. 结构化正文 Prompt 可以作为独立复现实验输入（2026-08-28）

- 结构化正文产物虽然没有保存原始 prompt 字符串，但保存了重建 prompt 所需的全部中间结果；因此可以准确恢复 `write_story` 的系统规则和用户输入。
- 这使实验可以区分“结构信息本身的作用”和“LangGraph 节点编排的作用”：前者可通过直接复用完整 prompt 测试，后者再通过实际链路对照。

## 80. 纯 LLM 对照不能机械复用含有情节方向的 seed 字段（2026-08-28）

- 当前现代情感 `world_setting` 和 `core_conflict` 已包含“从误解到信任”“危险升级”“公开介入”“确认情感”等顺序和结果信息，直接复制仍会泄漏结构。
- 严格的纯 LLM 对照应只保留题材、静态人物条件和故事开始时的核心矛盾，并让模型独立决定事件顺序、关系发展和结局。

## 81. 反应区间规则有效但不足以单独控制情感节奏（2026-08-28）

- 新 Prompt 使正文出现了流言后的回避、袭击后的照料和数日共同生活，说明“Function 由场景组整体兑现”确实能释放反应场景。
- 但模型仍可能在一个场景组内快速完成受伤、创伤坦白和表白；因此“重大事件后安排反应”只能提供节奏方向，不能保证关系阶段逐级推进。
- 当前短篇 MVP 可先接受这种改善；如果后续继续修正，应把关系阶段和重大事件后的最小间隔作为场景计划中的显式字段，而不是继续堆叠正文 Prompt 规则。

## 82. 正文长度应服从情节完整性（2026-08-28）

- 固定上限会把“超过几百字”误判为失败；在结构复杂、需要反应区间的故事中，正文长度应由完成情节所需的展开量决定。
- 完全删除最低提示又可能使模型过早结束，因此 MVP 保留最低展开量作为软提示，但不再设置目标字数和最大字数，也不把超长直接视为质量失败。

## 83. 去掉长度上限确实释放了反应区间（2026-08-28）

- 新版正文从上一轮的 `5098` 字增至 `5588` 字，并加入医院恢复、一周共同生活等事件后消化过程；这不是单纯增加景物描写，而是增加了人物关系和状态变化。
- 但模型仍可能使用类型化的快速表白和公开示爱完成结局；因此取消长度上限解决的是展开空间，不等于自动解决关系阶段跳跃。

## 84. 状态幅度必须在 mechanism、outline 与 story 三层分别守住（2026-08-28）

- 将 mechanism_plan 限制为每段最小状态变化，并让 outline 校验机制幅度后，大纲中的关系递进已从终点式跳跃收敛为首次互动、初步好感、经验证信任、暴露脆弱和明确承诺。
- 但正文仍把“明确承诺”放大成当众求婚和半年后婚礼，说明上游状态正确不代表下游一定服从；没有正文后语义校验时，单次写作模型仍可能自行强化类型化结局。
- 后续若继续修复，应只处理正文对 ending 与 scene_plan 的越界，不回退或继续堆叠 mechanism_plan 规则。

## 85. 同一大纲的正文质量仍有显著采样方差（2026-08-28）

- 同一份新大纲第一次生成 `2639` 字并越界到求婚与婚礼，第二次生成 `9121` 字且按半个月互动、创伤暴露和再次共同危机后才确认交往。
- 第二次结果说明新 mechanism_plan 和大纲本身能够支持自然递进；第一次结果不能单独证明上游骨架失败。
- 但字数和结局强度差异过大，也说明当前一次性正文节点的稳定性仍不足，后续质量评估不能只依赖单篇样本。

## 86. 核心关系不能只有主角弧线（2026-08-29）

- 只为主角规划变化，而把其他核心人物固定为触发者、接收者、对手或支持者，会迫使正文默认其态度和行动；这不是文笔问题，而是上游缺少这些人物的动机和状态变化。
- 人物目标回答“想得到什么”，人物动机回答“为什么愿意为此承担代价”，两者必须分开；核心人物还需要以稳定 ID 记录故事开始时的关系和态度，避免 `love_interest` 被误解成开场相爱。
- 关系变化必须为双方分别提供可观察的触发证据。总体 Function 状态变化仍负责结构后果，逐人物状态变化负责解释行动与态度，二者不应互相替代。
- 全题材不能共用固定的恋爱关系阶梯。应根据实际故事选择熟悉程度、信任、利益立场、权力、责任、依赖或亲密等状态维度，并让每个动作只改变其证据直接支持的维度。

## 87. 跨题材稳定性首先受大纲入口通过率限制（2026-08-29）

- 在 3 个题材各取 3 个 Pattern、每份大纲重复生成 2 次正文的批次中，9 份大纲只有 3 份通过 `overall_ok`，6 份在正文生成前被阻断。当前最先暴露的不是同化或辅助要素缺失，而是部分 Pattern 实例化后仍不能把 `ending_direction` 转换成最后一段已执行的解决动作和终态。
- 通过校验的 3 份大纲都能完成两次正文，但同一大纲的正文长度差达到 `651–2214` 字；这说明上游人物动机和状态字段已经能够提供可写骨架，但一次性正文节点的稳定性仍需独立评估。
- 因此下一阶段应先按题材统计大纲阻断原因并修复最高频的一个上游问题，再决定是否扩展同化或辅助要素。现阶段不把同化标签化，也不把辅助要素扩展为逐句标注；已有 `enrich_scenes` 的动机、前场因果和伏笔字段足以继续做短篇 MVP 验收。

## 88. 结局应是 Function 链之后的独立收束单元（2026-08-29）

- 当前 FunctionContract 描述的是结构作用，不保证链上的最后一个 Function 就是全局结局。要求调查、误解、暴露或关系推进等非终结 Function 同时完成所有冲突，会把合法的 Function 链判成无法闭合。
- 结局闭合的系统接口应拆成两层：Function 段形成结局所需的事实和条件，独立 `ending` 执行解决动作、写出冲突结果并声明稳定终态。这样保持 Function 顺序，也不需要维护手工 `CLOSING_FUNCTIONS` 名单。
- Pattern 的正式 `ending_spec` 是选择和校验结局的合同信号，因此默认 Pattern 选择应优先使用带 ending contract 的链；但不能因有 `ending_spec` 就放宽语义校验，ending 仍必须满足其中的 `resolves`、`must_show` 和 `final_state`。
- 复测中大纲通过率从 `3/9` 提升到 `8/9`。唯一失败样本仍然是 ending 与其 ending contract 不一致，说明通过率提升来自接口修正和 Pattern 选择，而不是降低闭合标准。

## 89. 大纲通过后，正文首要问题是“动作兑现”而非结构重排（2026-08-29）

- 复用 8 份通过大纲生成的 16 篇正文进行独立诊断，平均结构 `4.75`、因果 `4.50`、人物动机 `4.62`、冲突解决 `4.75`、结局闭合 `4.81`、可读性 `4.81`；说明当前正文骨架已经能够稳定承接大纲。
- 唯一高严重度问题出现在《零号信号》：大纲要求的“逮捕”在正文中变成叙述性告知，没有展示执行动作。它不是 Function 顺序错误，而是 `resolution_actions` 的叙事兑现不足。
- 其余缺陷集中于局部因果跳步、配角动机薄弱和终局展开偏快。因此下一步应在 `STORY_PROMPT`/结局场景写作规则中要求“每个解决动作必须有可观察的执行、即时后果和稳定状态”，而不是重新设计 Function 链或引入同化/辅助要素。
- 诊断器的 `category` 仍允许自由文本，因果类和动机类问题存在同义类别分裂；这影响跨批次统计，但不阻塞本轮正文质量判断。

## 90. 结局动作需要区分核心解决与后续社会结果（2026-08-29）

- 《零号信号》的核心结局是公开零号信号、修复备用能源系统、阻止穹顶崩溃，并完成 P1/P2 脱险与关系确立；P3 被议会逮捕属于证据公开后的社会后果。
- 因此，正文不需要为每个 `resolution_actions` 逐项展开同等篇幅。质量判断应先区分“核心冲突解决动作”和“可自然概述的后果/尾声”，只有前者未实际发生时才判定为高严重度。
- 本篇“逮捕动作未充分展开”的自动诊断不应作为主要缺陷，也不应据此修改正文生成规则。

## 80. raw 正文可以反向提炼为情节创作 Prompt（2026-08-28）

- 从 raw 正文提取的不是系统规则，而是人物、事件因果、冲突升级、关系变化、高潮和稳定结局组成的自然语言情节输入。
- 这种输入适合测试“完整情节说明直接交给 LLM”与结构化正文链路的差异；它保留故事内容，但不暴露 Function 和状态账本。

## 91. 形态学辅助标签与叙事展开必须分层（2026-08-29）

- 按 `structure-rules.mdc`，辅助要素是 Function 提取阶段的形态学定语：衔接、同化、三重化、倒置和省略；同化用于判定“结构后果相同、表面形式不同”，不能泛指题材化改写。
- 动机铺垫、重大事件反应和伏笔回收属于生成阶段的叙事支架。`mechanism.why`、`state_change` 和 `connects_to_next` 是结构约束，Outline `scaffold` 只把这些约束展开成 `genre_realization` 与可观察的叙事事件。
- 正式辅助标签应由 `FunctionExtract_Agent` 依据原文逐句识别并随 occurrence 发布；当前上游尚未发布这些字段，因此 Outline 不生成或冒充形态学辅助标签。
- 重复 Function 的题材实现保持独立是生成质量规则；只有同一 Function 第 3 次出现时，才可能在提取结果中标为“三重化”。

## 92. 题材不能替代关系 Function（2026-08-29）

- “关系向好”只描述变化方向，不描述关系类型；题材、性别或类型惯例也不能把它自动解释为亲密关系。
- 每个 Function 只能改变证据直接支持的关系维度。关系类型的切换、新阶段的确立和稳定承诺都是新的结构变化，不能由 ending 或表白句补做。
- 结局的职责是清偿已开启冲突并稳定已建立状态，不是为了类型圆满而创造新的人物关系终点。

## 93. 场景结构与叙事开发应分成两个节点（2026-08-29）

- `plan_scenes` 回答“故事由哪些场景组成、每场发生什么”，`develop_scenes` 回答“既定事件应如何展开和被人物消化”；把两类判断塞入同一个 Prompt 会让结构覆盖与文学呈现争夺注意力。
- `pacing_mode + expand_points` 决定叙述资源分配；`reaction_decision` 只用于需要重新选择的重大刺激；`causal_moments` 只把关键态度或行动变化写成刺激、理解和回应；`exit_aftereffect` 把已确定的状态变化传递到下一场。
- 该节点属于正文表现层，不负责同化、形态学辅助标签、动机/伏笔设计或 Function 修订。正文节点只执行最终场景合同，避免重新解释上游计划。

## 94. 上游计划应以 schema 作为接口（2026-08-29）

- `mechanism_plan` 和 `narrative_plan` 是跨节点传递的正式中间产物，不是图节点；它们应在 `Story_Agent` 的输入边界使用类型化 schema 校验，而不是以任意 `dict` 进入正文链路。
- 正文生成仍只消费 `scene_plan` 与 `scene_developments`，因此 schema 化不会把上游计划重复注入 `write_story`，只是在入口处保证字段完整、索引明确和状态变化可用。

## 96. Agent 之间需要顶层编排入口（2026-08-29）

- 当前每个 Agent 内部已经是自动 LangGraph，但 `Outline_Agent` 与 `Story_Agent` 原先通过人工命令和路径衔接；要实现一键生成，应增加顶层编排图，而不是复制或合并两个 Agent 的节点。
- 一键生成从已发布 PatternCatalog 开始。`FunctionExtract_Agent` 和 `StoryPattern_Agent` 属于知识库/Pattern 发布流程，不应在每次写故事时重新运行。
- 顶层编排只负责传递大纲文件路径、阻断失败大纲和汇总产物；结构约束、场景开发和正文生成仍由各自 Agent 负责。

## 97. 公开 CLI 应区分知识库构建与故事消费（2026-08-30）

- Function 提取、StoryPattern 发布和故事写作不是同一轮生成：前两者构建可复用知识和模板，正文阶段应消费已发布 Snapshot、Pattern 和 Outline。
- 因此统一入口采用 `function → template → story` 三组子命令；`template build` 内部按 `StoryPattern → Outline` 顺序执行，并用 Template Bundle 固定跨阶段路径和 manifest。
- Outline 是 Pattern 的一次具体实例化，不是与 Pattern 并行生成的空模板。故事阶段没有新要求时复用已有 Outline；有新要求时只固定 Pattern、重新实例化 Outline。
- 这层编排不吸收任何 Agent 内部 Prompt 或节点职责，只负责输入整理、产物传递、失败大纲阻断和运行 manifest。

## 98. 统一库应按知识实体组织，不按 Agent 阶段组织（2026-08-30）

- Bootstrap 和 Evolve 是同一 Function Ontology 的构建与演化流程，不是两种 Function；它们应记录为运行来源，不能把每轮完整 Function 集分别堆成知识表。
- 累计递增应保存新的 Story、Observation、Function 版本与演化事件、Snapshot 映射、Occurrence 和 Pattern 版本；同一实体重跑保持幂等，语义内容变化时新增版本。
- Snapshot 是冻结视图，同一 Function 可被多个 Snapshot 引用；同一 Observation 在不同 Snapshot 下也可以有不同 FunctionOccurrence 映射。Pattern 必须绑定产生它的 Snapshot 和真实故事证据，不能改写来源版本。
- 真实语料知识在 FunctionExtract 与 StoryPattern 的正式发布边界写入统一库；Outline 和 Story 属于生成产物，不进入 Corpus Knowledge Base。

## 95. 文学表达属于正文场景开发层（2026-08-29）

- `StoryPattern` 负责抽象 Function，`Outline_Agent` 负责题材化情节；修辞、环境、感官和句式节奏依赖具体场景，放在 `Story_Agent.develop_scenes` 才能避免上游过早固定文风。
- 文学表达不能只作为 `STORY_PROMPT` 的一句“写得有文采”。先为每场发布有限的 `literary_plan`，再由正文节点执行，能把环境和修辞绑定到行动、反应和状态变化。
- `literary_plan` 是呈现约束，不是新的情节层：它不能新增人物、冲突、线索、解决方案或关系承诺；非关键场景允许留空，修辞必须服务叙事。

## 99. 统一知识库是正式发布源，Registry 是 Evolve 工作区（2026-08-30）

- Agent 不能只在运行结束时把文件复制进数据库，同时在下一轮继续读取旧 namespace；否则数据库只是备份，无法形成连续演化。正式数据流必须从已发布 Snapshot 开始，并把新发布结果写回统一库。
- Evolve 仍需要可变 Registry 来执行匹配、证据累积和 Function 修订，但该 namespace 只代表一次运行的工作区。其初始 Function 必须来自统一库中的指定或最新正式 Snapshot，不能成为独立知识源。
- StoryPattern 必须在同一 Snapshot 视图中读取 Function、Occurrence、Observation 和故事证据，才能保证 Pattern 可追溯；Outline 则消费该 Snapshot 的 Pattern，并按稳定 Function ID 取得可用的正式 Contract。
- Story 正文只依赖已经冻结的 Outline JSON。让正文直接查询完整知识库会扩大上下文和职责，并破坏大纲作为生成合同的边界。

## 100. 未规范化的合同状态只能作为语义警告（2026-08-30）

- 历史 Pattern 与后来发布的 FunctionContract 通过稳定 Function ID 可以关联，但合同中的状态仍是自然语言，如“资源匮乏或危机”和“关键资源匮乏或面临危机”。在正式 `StateVocabulary` 建立前，用字符串完全相等推断链断裂会产生系统性误报。
- 门禁应区分确定性结构错误和待规范化语义差异：缺角色绑定、缺状态变化等结构错误阻断；状态同义词、粒度差异和非人物参与项保留为警告，由大纲语义校验结合实际机制判断。
- 这种分级不等于忽略 FunctionContract。合同、实例账本和警告仍完整进入大纲产物；未来发布规范化状态词汇后，可以把能够确定比较的状态冲突重新提升为阻断错误。

## 101. 关系校验必须按关系类型判断证据（2026-08-30）

- “稳固”描述状态强度，不等于亲密关系。盟友关系可以通过持续合作、共同承担风险、共享关键资源、保护和明确互信达到稳定；如果校验器一律要求情感基础，会把合法的非爱情关系误判为跃迁。
- 相同证据不能自动支持恋爱、婚姻或更高承诺。校验应先识别目标关系类型，再判断该类型所需证据是否出现，而不是把所有积极关系放进同一阶梯。
- 审计 warnings 不应进入 LLM 的内容合格性判断，否则模型可能把已确定为非阻断的词汇差异重新解释成失败理由。warnings 应留在产物中供后续 StateVocabulary 治理。

## 102. 大纲是冻结的生成合同，也应成为可寻址实体（2026-08-30）

- 用户追问“生成后的完整大纲文本是否应储存在 DB，StoryAgent 读取 DB 是否更方便规范”。关键不是让 StoryAgent 查询 Function/Pattern 全部知识，而是把已经冻结的完整大纲作为独立实体保存。
- `outline_id` 比文件路径稳定，能明确绑定 Snapshot、Pattern、校验状态和后续正文运行；StoryAgent 仍只消费一份冻结大纲，不重新解释上游知识，因此职责边界不变。
- JSON/Markdown 适合查看、交换和审计，数据库适合程序引用与完整性约束。两者并存时以数据库记录为正式输入，导出文件不是正文链路依赖。

## 103. Pattern 使用限制应绑定稳定 ID，而不是名称或 Snapshot（2026-08-30）

- 用户确认 Pattern 需要“全库只能使用一次”，并追问新 Snapshot 出现同名 Pattern 时是否算重复。名称是展示字段，Snapshot 是知识版本；两者都不能单独承担全局身份。
- 最小明确规则是以 `pattern_id` 全库原子领取：相同 ID 永久只能生成一份大纲；新 Snapshot 中出现同名但不同 ID 的 Pattern 视为新的结构实体。
- 领取发生在 Planner 选定之后、生成正文性内容之前。这样校验失败仍能消耗 Pattern，避免批量任务反复重试同一结构，同时数据库唯一键可以防止并发重复领取。

## 104. 统一知识库结构精简暂缓处理（2026-08-31）

- 当前统一库约 25.9 MB，查询、生成和完整性检查均无明显问题；表数量带来的主要成本是理解和维护复杂度，不是运行性能或存储压力，因此暂不迁移数据库结构。
- 后续精简优先核对 `run_observations` 与 `observation_versions` 的语义是否可以合并，并考虑把 `snapshot_functions.position` 合并进 `function_versions`；这两项收益明确且影响范围相对集中。
- `pipeline_runs` 当前虽然与 `snapshots` 基本一一对应，但被运行来源、故事和 Observation 版本外键引用，数据量又只有 3 条，暂时保留比合并更稳妥；`run_stories` 继续承担运行语料成员和顺序关系。
- 未来实施时应作为正式 schema 迁移处理：先备份数据库，事务内迁移和重建外键，再核对 Snapshot、Pattern、大纲及关系表数量，执行 `PRAGMA foreign_key_check` 和全量回归测试，不能直接在数据库界面删表。

## 105. 端到端实验由 CLI 判定，AI 只审查节点与数据流（2026-08-31）

- 用户确认实验应由 CLI 自动执行 Bootstrap、Pattern、Outline 和 Story，不由外部 AI 人工验证或替代程序门禁。
- AI 的职责是检查每个节点的处理思路、状态字段、输入输出和落盘去向，并区分代码定义的数据流与本次实际执行到的节点。
- 小样本若无法满足 Pattern 的结构条件，应保留真实断点并解释证据，不得复用旧 Pattern、手工编造 Pattern 或绕过门禁继续生成正文。

## 106. 增量批次、工作状态和正式 Snapshot 必须分开描述（2026-08-31）

- Evolve 的输入可以是单独的新文本批次，运行本身也有独立目录，但它会从指定父 Snapshot 初始化 Function，并在持久 Bank 上追加 Observation，因此计算语义是增量，不是独立 Bootstrap。
- Evolve 运行完成不等于增量已经进入正式知识库。只有终评通过并发布子 Snapshot 后，新 Function、Occurrence、Contract 和父子版本关系才成为正式累计版本。
- 终评失败时，应同时说明三种状态：新批中间产物仍可审计；活体 Bank 可能已经包含新 Observation；正式知识库仍停留在父 Snapshot。不能把活体 Bank 数量当成已发布 Snapshot 数量。
- 任何依赖 manifest 的评估字段都必须沿 LangGraph state 或 `evaluation_context` 显式传递；输入文件含 category 不代表 Evaluator 实际收到 category。

## 107. 流程回归测试必须隔离持久 Bank（2026-08-31）

- Evolve 测试若直接调用默认 `get_bank()`，测试前后的 `clear()` 会作用于真实持久目录，破坏正在审计的运行状态。
- 流程测试应把 `Agent.app._bank_instance` 注入测试临时目录中的 ObservationBank；节点仍走正式接口，但清理只影响测试数据。
- 中期和终期评估上下文分别需要回归断言，确保 `manifest_path` 不会在节点为本轮设置 `registry_file`、`bank_file` 或 `report_path` 时被整体覆盖。

## 108. Pattern 的增量单位是故事序列和 Motif 证据，不是整库重算（2026-09-01）

- 用户明确 Pattern 必须像 Function Evolve 一样累计进化：Bootstrap 建初库，Evolve 只处理新增或 FunctionOccurrence 签名变化的故事，未变化 sequence 和结论从父 PatternSet 继承。
- Snapshot 是全量冻结视图，不等于 Pattern 每轮全量计算。子 Snapshot 与父 Snapshot 的 occurrence 签名差决定真正 delta；Function 库变化导致旧故事重新对齐时，该故事应标为 changed 并局部重建。
- Cluster 是 Snapshot 间识别结构变化的中间实体，稳定 `pattern_id` 才代表逻辑 Pattern。证据增加、结构扩展、合并、分裂和退役通过父子 Cluster overlap 与 anchor motif 决定版本动作。
- 生成的大纲和正文不是 Pattern 证据。Pattern 只从真实故事的 Function sequence 学习；只有首次发布的 `new_pattern_ids` 才进入后续创作候选。

## 109. Motif 提取必须使用累计故事视图（2026-09-01）

- 新批次没有产生长度 3–6 的连续 Function，不能解释为 Motif 提取失败；只要父故事序列仍在累计视图中，旧 Motif 应继续保留并参与 Cluster 演化。
- Pattern 的累计边界是父子 Snapshot 的故事序列集合：子 Snapshot 中出现的故事覆盖父版本，未出现的父故事继承；Motif 只对新增或签名变化故事重算。
- Function 名称或 JSON 文件的拼接不足以恢复 Motif，必须在 DB 中保留有序 FunctionOccurrence、稳定 Function ID 和故事证据，才能避免旧 Pattern 被误判退役。

## 110. 首个累计输入运行需要建立完整 Pattern 基线（2026-09-01）

- 累计输入修复后的首个真实批次从 DB 恢复 35 个故事序列，并生成 26 个 Motif 候选，证明 Motif 不再只看当前 5 篇文本。
- 因直接父 Pattern Snapshot 是修复前仅保存 5 条序列的结果，本次 Pattern delta 显示 30 条 new、5 条 unchanged；这属于一次性补齐基线，下一批才会表现为纯新增 5 条与其余故事继承。

## 112. 历史 Pattern Snapshot 必须显式重建（2026-09-01）

- 代码修复不会自动改写已经成功提交的 Pattern run；若父 Snapshot 由旧流程产生了不完整序列，必须显式重建该 Snapshot，再重建其子 Snapshot。
- 重建后 batch07 的 delta 恢复为 5 条新增、30 条继承，证明历史文章已进入父 Pattern Snapshot；当前 Pattern 被 blocked 的原因来自新增 Motif 的真实顺序冲突。

## 113. 正式库后续批次验证纯增量（2026-09-01）

- 修复父 Snapshot 后，正式库下一批 Pattern delta 为 5 条新增、35 条继承、0 条删除，累计故事达到 40 篇。
- 新增文本与历史 Motif 共同形成 2 个 published Pattern，说明累计输入不仅能恢复历史证据，也能在新批次满足发布条件时产生新 Pattern。

## 111. Pattern 表与文章证据是不同实体（2026-09-01）

- `patterns` 只保存达到发布条件的逻辑 Pattern，不是文章索引；新文章应在 `stories`、`run_stories`、`function_occurrences`、`pattern_story_sequences` 和 `motif_evidence` 中检查。
- 因此本批没有 published Pattern 时，`patterns` 不新增行并不表示 5 篇文章未入库。

## 114. 远程累计修复只闭合了 Pattern 输入边界（2026-09-01）

- 远程提交 `273b7a7` 通过 `load_story_pattern_inputs_cumulative` 沿父链继承故事、Observation、Function、Contract 和 FunctionOccurrence，并增加 `--rebuild`，解决了 Pattern 把只含当前批次的 Function Snapshot 误判为父故事全部删除的问题。
- 该修复没有改变 Function Evolve 仍向全局持久 Bank 直接追加、失败批次无提交状态、终评仍可能取活体 Bank，以及 `story_id/obs_id` 由文件名和序号决定的事实；因此“Pattern 能累计”不等于“Function 增量数据流可审计、可回滚”。
- 累计读取仍通过可变的 `stories` / `observations` 主表回读父 Snapshot；若同一 ID 后续被原地更新，旧 Pattern 输入仍可能漂移。另一个待验证边界是 occurrence signature 未包含 Function/Contract 版本，定义或合同变化不一定触发故事局部重算。
- 远程代码已拉取到本地，但 `Code/data/` 被 `.gitignore` 排除，正式 `story_knowledge.db` 和运行产物不随代码同步；最新代码、最新知识数据和 HANDOFF 中的实验状态仍是三个独立版本源。

## 115. Function Evolve 的隔离单位应是 Run，可发布边界应是 Snapshot（2026-09-01）

- 用户明确反问为何不能始终在同一个 Evolve DB 增量，并确认不需要按批次拆数据库；真正需要隔离的是未发布 `run_id` 的可见性。
- Bank 不应再承担正式知识边界。它只需要计算“父 Snapshot 的冻结 Observation + 当前 Run 暂存 Observation”，同一逻辑故事由当前 Run 版本覆盖。
- Snapshot 必须保存完整成员关系并绑定不可变 Story/Observation 版本；这样 Pattern 和后续读者只读一个 Snapshot，不再沿父链拼接，也不会因新批次更新逻辑 ID 而让旧 Snapshot 漂移。
- 失败不是删除运行历史：保留 FAIL Run 和报告用于审计，但清理其暂存版本；只有 PASS 提交才能把版本变成正式可见知识。

## 116. 严格 Snapshot 边界要求删除旁路，而不只是停止调用（2026-09-01）

- 用户要求删除旧的无用和冗余代码，避免后续维护者误走旧路径。仅让新入口“不调用”旧接口仍会留下两套合法写法，边界并未真正收敛。
- `record_snapshot`、PatternCatalog 文件导入和 `latest_by_function` 合同回退都会绕过当前 Snapshot 的完整版本成员，因此应删除，而不是保留为 fallback。
- Bootstrap 持久 Bank 与 Evolve 计算 Bank 职责不同，前者仍有生产调用，不属于冗余；清理依据应是调用关系和边界语义，而不是名称相似。

## 117. Bootstrap 的 FAIL 不能被描述为已产出 Snapshot（2026-09-01）

- 本次真实两篇故事运行中，Bootstrap 的中间 Registry/Bank 文件已生成，但最终评估为 FAIL，`publish_snapshot` 返回空，因此统一知识库没有可供 Evolve 使用的父 Snapshot。
- Pattern 独立回归可以使用已有 Snapshot 验证下游，但不能补足 Bootstrap 门禁；后续全流程必须先得到 Bootstrap PASS 和正式 Snapshot，再启动 Evolve。

## 118. Pattern 增量需要父 Snapshot 先有 Pattern 基线（2026-09-01）

- 真实 Evolve 子 Snapshot 直接运行 Pattern 时被正确拒绝，因为父 Function Snapshot 尚无成功的 Pattern Run；这不是 Function 数据缺失，而是 Pattern 增量无法从未初始化的父派生状态继承。
- 因此完整链路实际需要：Bootstrap 发布根 Snapshot → 根 Snapshot 建立 Pattern 基线 → Evolve 发布子 Snapshot → 子 Snapshot 运行 Pattern 增量。直接执行 `FunctionExtract_Agent` 时，根 Pattern 不会自动运行；`StoryCLI function bootstrap` 才会在发布后触发它。

## 119. Pattern Run 成功不等于产生 published Pattern（2026-09-01）

- 真实 10+5 故事链路中，根 Snapshot 生成 3 个 candidate Cluster，子 Snapshot 生成 5 个 candidate Cluster；所有 Cluster 的 `story_support=1`、Motif 最大长度为 3，虽然 `review_status=CLEAN` 且 FunctionContract 齐全，仍未通过发布门槛。
- 当前发布条件要求 `story_support>=2` 且 Motif 长度至少 4；因此本批的主要问题是跨故事同序结构不足，而不是 Pattern 节点失败或数据库写入失败。增加故事数量只有在形成可重复的 4 步以上 Function 链时才会产生 published Pattern。

## 120. 增量数据达到 30 篇后出现可发布 Pattern（2026-09-01）

- 在前两轮 15 篇基础上继续 Evolve 15 篇后，Pattern 仍保持直接读取完整子 Snapshot；delta 中有 15 条新故事、12 条未变化故事、3 条因 Function 本体扩展而重新对齐的故事，没有误删历史故事。
- 本批出现一个满足“至少两篇故事、至少四步结构、Pair Review CLEAN、Contract 完整”的 Cluster，发布 Pattern“秘密揭露与冲突升级循环”。这说明前一批 `published_patterns=0` 主要是结构支持不足，并非发布链路失效。

## 121. 增量主流程已闭合，但严格数据一致性仍有缺口（2026-09-01）

- 当前同一 SQLite 已实际跑通 Bootstrap 10 篇 → Evolve 5 篇 → Evolve 15 篇 → Pattern：3 个 PASS Function Run、3 个 SUCCESS Pattern Run、30 篇累计故事，最新 Pattern delta 为 `new=15、changed=3、unchanged=12、removed=0`。
- 因此 `run_id` 可见性、父 Snapshot + 当前 Run 的计算 Bank、PASS 才发布子 Snapshot、Pattern 按完整 Snapshot 读取这条主流程已成立；但还不能把四项增量要求称为完全闭合。
- 后续应优先修正稳定 Function ID、Observation/Occurrence 版本覆盖、Occurrence 与 Snapshot 成员的强绑定，以及异常中断后遗留 `RUNNING` Run；这些问题会影响旧新版本的严格追溯，不能先用 Best-of-N 或更多语料掩盖。
- 初始目标中的完整 Story Profile、独立 Instance Card、Propp 31 项/轮次/辅助标签、StateVocabulary、生成阶段 Best-of-N/局部优化和论文级人工/跨批次基准仍未完成。

## 122. 合并 Registry DB 与 Knowledge DB 不等于解决 Function 身份（2026-09-01）

- 物理上合并 SQLite 只能减少文件同步和备份边界，不能修复当前由 `function_name + definition` 生成 Function ID 的问题；定义变化仍会改变 ID，且 Story/Observation ID 和 Occurrence 覆盖问题也不会因此消失。
- 如果合并，必须在同一文件内保留“`run_id` 作用域的可变工作 Registry”和“Snapshot 作用域的正式版本表”两层；直接让 Registry 的 `replace_all` 写正式 `functions` 表会破坏失败回滚和旧 Snapshot 读取。
- 当前更小的正确方案是先让新 Function 一次分配 ID、REVISE 保留原 ID、MERGE/SPLIT 记录 lineage，再决定是否把 Registry 工作表迁入 Knowledge DB；数据库文件数量不是身份模型。

## 122. 合并 RegistryDB 与 KnowledgeDB 不等于 Function 身份稳定（2026-09-01）

- 用户提出将 RegistryDB 与 KnowledgeDB 合并。合并物理存储可以消除 Evolve 工作区到正式知识库的跨库复制，并让 Run 暂存与 Snapshot 提交共享事务；但如果仍按 `function_name + definition` 生成 ID，定义修订仍会改变 Function ID。
- 正确方向是“同库、分表、分语义”：逻辑 Function 身份只在首次创建时生成，REVISE 保留 ID，MERGE/SPLIT 通过演化事件记录新旧关系；当前 Run 只写工作表，PASS 才提交 `function_versions` 和 `snapshot_functions`。
- 数据库合并不能自动解决 Story/Observation ID 漂移、Occurrence 版本覆盖、Snapshot 强绑定、StateVocabulary 或论文级评测，这些仍需分别处理。

## 123. 旧 Snapshot 数字型 Observation ID 不进入新架构兼容层（2026-09-01）

- 用户明确不要求兼容旧 Snapshot 中的 `_obs_001` 数字型 ID，因此新 Pattern 输入边界应直接拒绝旧格式，而不是继续保留数字后缀解析和排序回退。
- 新架构只承认由原文句子锚点生成的稳定 Observation ID；旧数据库若要继续使用，应先显式重建或迁移，不在运行时隐式混用两套 ID 规则。

## 124. 清理应以调用关系为准，而不是按名称盲删（2026-09-01）

- 用户要求保持最新版本、删除冗余兼容代码后，确认了旧 Pattern 状态回退、Evolve `--final-only` 和无生产调用的一次性迁移/回填脚本可以直接删除。
- Bootstrap 的 `record_function_run` 虽然是旧式接口形态，但当前 Bootstrap 仍实际调用它；在 Bootstrap 尚未改为“创建 Run → 暂存 → 提交 Snapshot”前，删除它会直接破坏正式根 Snapshot 写入，因此暂不误删。

## 125. Observation 逻辑身份不能依赖抽取位置（2026-09-01）

- 用户指出，旧故事重新切分、插入或删除一个 Observation 后，顺序编号会使后续 Observation 看起来全部变成新记录；`observation_version_id` 的不可变性不能解决逻辑身份漂移。
- 当前最小稳定边界是：`obs_id` 绑定故事内原文锚点，而不是句子下标或 Observer 返回序号；同一原文事件的描述改写只产生新的 ObservationVersion。
- `observation_version_id` 不再包含 `obs_id`、`observation_order` 和 `source_sentence_indices`，所以重新排序或仅改变分句边界不会伪造内容版本。
- 若原文锚点本身被改写，系统不使用模糊相似度擅自认定为同一事件；这保留了新增事件与旧事件的可区分性。
- 当前正式库抽查仍是旧数字型 Observation ID，不能被新 ID 规则隐式接管；既然不做旧 Snapshot 兼容，后续真实增量前要显式重建根 Snapshot，而不是在运行时混用两套身份规则。

## 126. Occurrence 不继承旧版本字段（2026-09-01）

- 用户明确要求统一使用新版本，不需要旧版本，因此不再采用“新 Observation 覆盖旧 Occurrence、旧 Occurrence 补充派生字段”的合并策略。
- Occurrence 是当前 Observation 与当前 Function 对齐后的派生输出；历史版本由旧 Snapshot 保留，但不参与新 Snapshot 的 Occurrence 构造。

## 127. 强制中断的未完成 Run 应在下一次启动时收口（2026-09-01）

- 用户指出，进程被强杀、断电或宿主退出会绕过 Python 异常处理，留下 `RUNNING` 的 Function Run 及其暂存 Story/ObservationVersion；它们虽不进入正式 Snapshot，却会污染审计状态并占用暂存数据。
- 在当前单写入流程中，最小策略是在下一次 Bootstrap/Evolve 创建新 Run 前，把所有遗留 `RUNNING` Run 复用既有失败清理语义：删除其 `run_*` 成员和该 Run 创建的暂存版本，状态改为 `FAIL`，报告标明“启动时发现上次强制中断、未发布 Snapshot”。不引入超时、第二数据库或恢复执行。
- Snapshot 提交与 `pipeline_runs.status='PASS'` 已处于同一 SQLite 事务；因此恢复只处理没有 Snapshot 的 `RUNNING` Run，不会回滚已发布知识。

## 128. 正式库必须先重建才能进入新 Observation 身份链（2026-09-01）

- 用户确认清空并重跑同一批 10 + 5 + 15 篇故事，用于把正式数据库从旧数字型 Observation 身份切换到原文锚点哈希身份，同时保留可比较的语料基线；验证完成后旧数据库与旧 Snapshot 已删除。
- 实际重跑证明，Bootstrap 根 Snapshot 与两轮 Evolve 子 Snapshot 可以在同一个 SQLite DB 中连续发布；每轮只新增当前批次知识，但正式 Snapshot 是完整的累计知识边界。
- 最终库包含 287 个新格式 Observation，0 个旧 `_obs_001`，所有 ObservationVersion 都有 `source_text`，Occurrence 全部绑定当前 Snapshot 的版本映射。说明身份迁移不需要兼容层，但必须通过显式重建完成。
- Pattern 在最新 Snapshot 上成功发布 1 个 Pattern；本轮重点是恢复可信增量基线，不等同于已经解决 Function 新增反向重解释旧 Observation、StateVocabulary 和 Function 语义版本失效等后续结构问题。

## 129. Function 演化只回看父 Snapshot 未决 Observation（2026-09-01）

- 用户认为“新增/修订/拆分 Function → 只召回父 Snapshot 的 UNCERTAIN/OTHER → 只对高相似候选重新匹配 → 生成当前 Snapshot Occurrence”已经足够，不需要额外的 Function 语义签名或复杂边界系统。
- 按此决定，Evolve 只增加一个轻量 `rematch_unresolved` 节点，复用 Matcher；不重跑全部 Observation，不新增数据库表，也不修改父 Snapshot。

## 130. 语义 coverage 与正式 assignment 必须并列呈现（2026-09-01）

- 用户确认不应把 Evaluator 的“与 Function 定义相似即可解释”误读为 Pattern 可用输入覆盖；正式 Snapshot 应同时展示从最终 FunctionOccurrence 得到的硬分配率、未决率和 OTHER 率。
- 最小实现是保留 Evaluator 的语义 coverage 与既有 PASS 门槛，并在 Snapshot 发布前附加 assignment 指标；这不引入 LLM 调用或新的拒绝门槛。

## 131. Pattern 摘要失效应按 Cluster 语义输入，而非全量 FunctionVersion（2026-09-01）

- 用户要求只解决旧摘要错误继承，不让一次 Function 修订导致所有故事 sequence 和 Pattern 全量重算。
- 正确失效单元是 Cluster 摘要的真实输入：结构相同但涉及 Function 的定义或 Contract 变化时，仅重跑该 Cluster 摘要，生成 `SEMANTICS_REVISED`；未受影响 Cluster 继承旧摘要。
- 不应把完整 FunctionVersion 哈希进入故事 occurrence signature，因为支持证据或置信度等非摘要语义变化会制造不必要重算。

## 132. 50+50 真实重建暴露了增量后处理与 Pattern 超时问题（2026-09-01）

- 用户要求清空正式库并用同一语料重跑 50 篇 Bootstrap、50 篇 Evolve；结果证明同一 SQLite 上的根 Snapshot → 子 Snapshot 链路成立，新 Observation 身份与 `source_text` 已完整进入正式数据。
- 首次 Evolve 在 RetroMatch 阶段因 `encode_observations` 逐字段单条调用模型而长时间停滞；最小修复是一次批量编码，未改变字段权重或匹配逻辑。修复后 50 篇 Evolve 成功，回看父 Snapshot 的 313 个未决项，选中 136 个并新增 112 条归属。
- Pattern 子 Run 运行约 36 分钟后仍未完成，只能停止并标记 `FAILED`；后续只读复算证明它不是卡在单个请求，而是 370 个 Motif 产生了 1390 对语义变体，其中 754 对 HIGH 需要串行 LLM 审查。Pattern 的主要问题是候选对规模与串行执行策略，不能把失败 Run 解释成“100 篇仍无可发布 Pattern”。
- 真实数据再次显示 Pattern 输入覆盖不是故事总数：子 Snapshot 有 100 篇故事和 880 个 Observation，但根 Pattern 已出现 50 篇故事仅生成 49 条序列，因为零 Observation 故事被 `load_pattern_delta` 过滤掉。后续应决定是写入空序列还是明确报告缺失，而不能静默丢失。
- 真实 LLM 输出仍会把 Function 名称写入 Matcher 的 `label`、返回未声明的 `SEMI_SAME`，或产生非法 Contract 字段；结构化重试能恢复本轮，但这应作为输入约束/提示词稳定性问题单独处理。

## 133. Pattern 审查应先缩小候选，再验证端到端产物（2026-09-01）

- 用户要求精简 Pattern 审查。采用 `HIGH + Motif 长度至少 4 + 双方互相 Top-2` 后，子 Snapshot 的 Pair Review 缩小到 90 条，最终成功发布 26 个 Pattern。
- 这说明此前 `published_patterns=0` 的直接原因包含审查规模和执行时间，而不是“没有足够文本”；但该筛选是保守召回策略，不能把 26 个发布数当作完整候选覆盖率。
- 用同一子 Snapshot 生成 1 个 Outline 和 1 篇正文，证明当前链路已经实际贯通：Snapshot → Pattern → Outline → Story。后续性能优化应继续保持这个最小可验证闭环。
- 直接运行 Function Evolve 不会生成 StoryCLI 运行清单，导致文章入口需要补写 manifest；这暴露出 CLI 编排和 Agent 直调用两套流程的产物契约不一致，应统一产物生成位置。

## 134. Pattern 阶段超时应收口 Run，而不是引入复杂恢复层（2026-09-01）

- 用户要求先解决 Pattern 阶段长时间 `RUNNING` 和失败不可见问题。当前最小闭环是：Motif Review 和 Pattern Summary 阶段设置总预算，超时抛错；外层把异常/中断写为 `FAILED`；未到提交节点的数据不进入正式 Pattern 表。
- 这保留了现有“一个 Snapshot 对应一个 Pattern Run、成功才原子发布”的模型，也避免为了恢复单条 Review 而新增队列、分布式锁或第二数据库。
- 15 分钟预算足以覆盖本轮精简后的 90 条候选 Review，但仍保留保守失败语义：超时会丢弃本次未提交的 Pattern 派生结果，下一次可用 `rebuild` 重试。

## 135. Function lineage 只补现有事件 payload（2026-09-01）

- 用户要求先解决 Function 演化 lineage 不完整问题，并保持精简。
- 采用既有 `function_evolution_events.payload_json`：MERGE/SPLIT 事件写入稳定的 `source_function_ids` / `target_function_ids`，不增加 lineage 表、数据库或复杂迁移。
- 不生成父 Function 的额外反向事件；通过新 Function 事件中的 source/target 集合即可反查 `F_PARENT → F_C/F_D`，同时避免 Bootstrap 根 Snapshot 中父 Function 尚未进入知识库时的外键问题。

## 136. 清理旧 MERGE 事件而不修改不可变 Snapshot（2026-09-01）

- 用户要求删除 3 条旧代码生成的 MERGE 记录，避免旧事件影响当前系统。
- 只删除正式 SQLite `function_evolution_events` 中精确匹配的 3 行；不改已发布 Snapshot 文件或 FunctionVersion，避免破坏 Snapshot 哈希和不可变边界。
- 删除后旧格式 MERGE 事件为 0，外键检查通过；新 MERGE/SPLIT 事件由当前代码写入 source/target Function ID。

## 137. checkpoint 膨胀应移出累计工作集，而不是重设计知识库（2026-09-01）

- 用户要求解决 Bootstrap checkpoint 膨胀，同时保持当前精简架构、不新增数据库边界。
- 结论：`all_pairs` 的问题不是单条记录格式，而是累计列表被每个 checkpoint 重复保存；因此将它改为 `out_dir/pairs_<namespace>.jsonl` 工作文件，图状态只保留现阶段游标和 pair 引用型归纳分量。
- 这样仍支持中断后从同一工作文件进入 `cluster`，知识库和 Snapshot 数据流不变；fresh 重跑时清理工作文件并压缩 checkpoint 文件的空闲页。

## 138. Pattern 的故事覆盖应包含空结构，而不是静默丢失（2026-09-02）

- 用户要求先解决 Pattern 输入覆盖和失败 Run 残留两个结构性问题。
- 零 Observation 故事仍是真实输入的一部分，因此应保留为显式空 sequence；它不参与 Motif/Cluster，但必须出现在 Pattern story sequence 和运行统计中。
- 失败 Run 的清理边界可以保持简单：删除该 Run 产生的版本后，清掉没有任何版本归属的 Observation；不新增 `created_by_run_id` 或复杂孤儿状态表。

## 139. Snapshot 完整性保护先保持轻量，不立即增加数据库硬约束（2026-09-02）

- 用户指出，复合外键和多组不可变 trigger 可能使当前代码变得冗杂，因此决定先不执行。
- 当前单写入架构下，文件哈希、统一提交 API 和现有外键已经足以支撑当前增量验证；下一步若需要加强，只增加集中式完整性检查，不先扩展数据库结构。
- 数据库级不可变保护保留为后续优化，触发条件是多进程/外部写入或论文级约束证明，而不是当前功能链路的必要条件。

## 140. Outline 外部输入版本固定延后到复现性阶段（2026-09-02）

- 用户决定暂不固定 Function Card 和 Transition Index 的内容版本。
- 当前按 `snapshot_id` 分目录已经满足单机运行的基本隔离；真正需要严格固定的是 A/B 实验、跨批次比较和论文级复现。
- 后续采用 Outline 产物记录外部文件 SHA-256 的轻量方式，不新增数据库版本表，也不改变当前 Snapshot 数据流。

## 141. 删除 Agent 兼容 shim 后必须迁移隐藏的内部顶层导入（2026-09-02）

- 用户要求先清理无用硬编码和冗余入口，决定删除 `Code/Agent` 兼容命名空间，不保留旧导入兼容。
- 实际验证发现，旧 shim 不只提供 `Agent.*`，还把 `FunctionExtract_Agent` 内部目录注入 `sys.path`，使 `from Prompt`、`from Embedding`、`from Retrieval` 等隐式导入能够工作。
- 因此清理不能只删 shim；必须把这些内部导入一并改为 `FunctionExtract_Agent.*`，否则表面迁移完成、实际运行仍会在动态导入处失败。
- 删除失效 Snapshot 默认值后，入口暂时改为显式 Snapshot，避免在下一阶段上下文解析实现前引入全局最新 Snapshot 的隐式行为。

## 142. 先统一 Run 控制面，再引入最小协调 Agent（2026-09-02）

- 用户确认当前 Bootstrap、Evolve、Pattern 的衔接主要由 Codex 判断和执行，因此要求先完成前三项自动化基础：Bootstrap 提前登记 Run、Pattern 启动恢复悬挂 Run、入口返回机器可读结果；同时保持代码精简。
- 这三项的目标不是增加新的编排系统，而是使 SQLite 的 Run 与正式 Snapshot 成为协调器唯一需要读取的状态。后续协调 Agent 可据此决定 Bootstrap、Evolve、Pattern、重试或停止。
- 当前仍采用单机串行写入假设；不提前加入分布式锁、消息队列、心跳或第二数据库。多 Worker 并发成为真实需求时，再单独设计租约/互斥策略。

## 143. 真实单篇增量验证应以父 Snapshot 为起点（2026-09-02）

- 用户要求启动真实 LLM 并选一篇验证全流程接口。单篇不能形成有意义的 Bootstrap 根 Function，因此采用已发布的 100 篇 Function Snapshot 作为父，对一篇新故事执行真实 Evolve，再执行 Pattern；这既保持增量语义，也能验证 Run、Snapshot 和 Pattern 的真实衔接。
- 真实 Evolve 成功证明单篇批次可安全成为完整子 Snapshot；真实 Pattern 失败则表明现有摘要 LLM 仍可能不严格复用输入 Function 名称。该失败应由 Pattern Run 记录并保持 Pattern 表为空，不能回滚或否定已成功发布的 Function Snapshot。

## 144. Pattern Summary 不应让 LLM 负责 Function 身份选择（2026-09-02）

- 用户要求最小修复目标是让 Pattern Summary 不再依赖 LLM 精确复述 Function 名称。先改为让 LLM 返回 Function 索引仍会失败，因为索引同样要求模型稳定输出结构化选择。
- 最简且可追溯的方案是完全移除 Summary 的 Function 选择字段：Cluster 的 anchor motif 已经携带稳定 Function ID，系统直接绑定该链，并从当前 Snapshot 回填名称、定义和 Contract。
- 真实重试成功，说明该修复解决的是身份绑定边界问题，而不是增加 LLM 重试或名称模糊匹配；数据库结构和增量 Pattern 流程均无需扩展。

## 145. 单篇真实 Bootstrap 只能验证抽取与失败收口（2026-09-02）

- 用户要求只跑一篇真实 Bootstrap。实际结果是 Observer 产出 9 个 Observation，但因 Bootstrap 会清空 Bank 且 Induction 需要跨故事相似对，单篇没有可归纳分量，最终无 Function、无 Snapshot。
- 因此单篇可以证明真实 LLM、Run 登记、失败收口和机器可读结果通路，但不能证明 Bootstrap 成功发布分支；成功分支至少需要两篇故事。
- 为避免一次验证改写正式 Bank/Registry，使用隔离的真实验证目录和数据库；当前正式知识库和共享 Bank 不受影响。

## 146. 现有 Pipeline_Agent 不是 Function 协调 Agent（2026-09-02）

- 用户询问现有 `Pipeline_Agent` 是否已经承担最小协调职责。实际代码只固定编排 `Outline_Agent → Story_Agent`，生成内容侧 manifest，不读取 Function Run、Pattern Run 或 Snapshot 状态。
- 因此它不能直接作为 `Bootstrap → Evolve → Pattern` 的控制面；后者需要一个更上层但同样轻量的协调入口，复用三个 Agent 的现有接口和 `run_result`，按成功状态决定下一步，失败即停止并返回机器可读结果。
- 不应为了协调职责改造现有 `Pipeline_Agent` 使其同时承担两条不同的数据流；当前最小方案是不新增表、不引入队列，只增加 Function 流程的薄协调层。

## 147. Function 调度 Agent 采用 LangGraph 外层状态图，但不增加第二套持久状态（2026-09-02）

- 用户要求使用 LangGraph 范式或项目现有规则设计调度 Agent。结论是采用 LangGraph 的条件边表达 `Bootstrap/Evolve → Pattern`，但调度器本身不调用 LLM，也不新建 Run/Snapshot 表。
- 调度器状态只保留本次输入、Function `run_result`、Pattern `run_result` 和最终状态；正式 Run、Snapshot 与失败记录仍由各子 Agent 的 SQLite 控制面负责，避免 LangGraph checkpoint 与 KnowledgeBase 形成两套真相。
- Function 阶段只有 `status=PASS` 且存在 `snapshot_id` 才进入 Pattern；Pattern 只有 `status=SUCCESS` 才完成。Function 失败或 Pattern 失败都停止并返回结果，不回滚已经成功发布的 Function Snapshot。
- 现有 `Pipeline_Agent` 继续负责 `Outline → Story`；新的调度入口应作为独立的 Function Coordinator，复用可调用的 Bootstrap/Evolve/Pattern 接口，而不是混合两个职责。

## 148. 无 Codex 中间干预需要失败策略，不只是节点串联（2026-09-02）

- 用户明确希望以后由自动化 Agent 独立完成中间流程。仅有 `Bootstrap/Evolve → Pattern` 的 LangGraph 条件边只能自动衔接，不能处理失败后的判断与修复。
- Coordinator 需要把失败分为可安全重试的暂时错误、可自动修复的输入/格式错误、业务质量失败和不可安全推断的结构错误；前两类有限重试或重跑，质量失败停止并报告，不让 Agent 随意改 Function 或 Snapshot。
- 正式 Run/Snapshot 仍是恢复依据，Coordinator 不另建持久状态；只有节点返回机器可读 `run_result`、失败原因和可重试性后，才可能在不依赖 Codex 的情况下稳定运行。

## 149. 调度中枢不等于必须使用 LLM 的 Supervisor（2026-09-02）

- 用户从 Multi-Agent 架构询问 Coordinator 是否相当于大脑。它更准确地是调度中枢/指挥器：负责读取状态、路由专家 Agent 和收口结果；Observer、Matcher、Inducer、Evaluator、Pattern 才负责语义理解与生成。
- 当前 Function 流程的下一步由明确事实决定：`PASS + snapshot_id` 才能进入 Pattern，`FAILED` 停止，暂时错误有限重试。这类控制不需要 LLM；使用 LLM 反而会增加成本、非确定性和越权修改 Snapshot 的风险。
- 后续若出现无法用规则分类的异常，可采用混合模式：规则层先拦截和保护数据库，LLM 只在候选动作集合中提出 `RETRY/RESUME/STOP` 等建议，最终仍由规则验证和执行，而不是让 LLM 直接写库。

## 150. Coordinator 第一版应复用 CLI 的机器结果，暂不重构三个 Agent（2026-09-02）

- 用户要求按 LangGraph 方案增加调度 Agent。当前 Bootstrap/Evolve 的完整生命周期仍封装在 CLI 主流程，Pattern 已有可调用入口；为保持改动最小，Coordinator 通过子进程调用现有 CLI，并解析其最终 `run_result`，不复制任何业务节点。
- 该边界保留各子 Agent 的独立 checkpoint、Run 和失败收口，同时让 Coordinator 能实时转发阶段日志、按规则做成功/失败路由和有限重试。
- 如果后续需要同进程调用、细粒度恢复或多任务并发，再把 Bootstrap/Evolve 生命周期提取为公共函数；当前不提前引入这一层重构。

## 151. Coordinator 测试通过不代表真实子进程闭环已覆盖（2026-09-02）

- 检查发现新增 5 项测试主要 mock `_run_stage`，覆盖了 LangGraph 路由，却没有覆盖真实 CLI 启动、stdout `run_result` 协议、子进程退出码、Pattern 失败回写和 Coordinator 被中断后的恢复。
- 复核后确认 `_run_stage` 已在解析结果后检查子进程退出码：成功状态配合非 0 退出码会被改为 `FAILED`，因此该边界当前没有实际漏洞。
- 现有 Pattern CLI 在异常时只打印错误、不打印 `run_result`，虽然 `pattern_runs` 已写入 SQLite，但 Coordinator 只能返回 `MISSING_RUN_RESULT`，无法直接带出精确的 Pattern 失败原因。
- Coordinator 被中断时没有显式终止子进程，也没有阶段级 watchdog；重新启动时可能重复执行已经成功的 Function 阶段，增加成本，虽不会直接覆盖正式 Snapshot。
- 下一步应补一个不调用 LLM 的真实子进程协议测试、Evolve 参数传递测试和中断/重启策略；在此之前，`299 passed` 只能证明当前规则路由，不代表无人值守闭环已经完全验收。

## 152. 更适合本项目的是分层中枢，而不是单一 LLM 大脑（2026-09-02）

- 用户提出让调度 Agent 作为大脑统一处理整个自动化流程错误。结合 Snapshot 不可变、Run 可追溯和 Function 质量修订边界，不能让一个 LLM 直接决定任意修复；更合适的是“确定性 Coordinator 内核 + 受约束 LLM Supervisor + SQLite/Snapshot 黑板”。
- Coordinator 内核负责状态路由、恢复、重试上限、预算、Snapshot 完整性和停止；现有 Evaluator/Curator 负责 Function 语义修订，Pattern/Outline/Story 负责各自领域，避免总 Agent 越权修改专家产物。
- LLM Supervisor 只在错误无法由规则分类时工作，并只能从 `RETRY_STAGE`、`RESUME_RUN`、`REBUILD_PATTERN`、`STOP` 等有限动作中提出建议；规则层校验目标 Run、父 Snapshot、尝试次数和数据边界后才执行。
- 这样正常路径无需额外 LLM，已知错误可自动处理，未知错误可自动暂停并保留证据；正式知识边界始终由 SQLite Run 和不可变 Snapshot 决定。

## 153. 三个子 Agent 必须共享失败协议（2026-09-02）

- 用户要求先统一 Bootstrap、Evolve、Pattern 的错误结果。仅在最终成功/异常路径打印 `run_result` 不够，因为语料不存在、基础 Snapshot 不存在和不可恢复 checkpoint 等早期失败同样会被 Coordinator 消费。
- 最小做法是增加一个纯结果构造函数，不引入新的状态表或错误层级：所有失败均返回 `status=FAILED`、`stage`、`workflow`、Run/Snapshot 上下文、`error_code`、`error`、`retryable`。
- 数据库内部的 `FAIL` 与 `FAILED` 继续保持各表现有语义；统一的是跨进程接口 payload，不为适配器再增加一套持久状态。

## 154. Coordinator 需要真实验证跨进程协议（2026-09-02）

- 用户要求补 Coordinator 的真实子进程测试。原有测试只替换 `_run_stage`，只能证明 LangGraph 路由，不能证明子进程 stdout、JSON 解析和退出码组合真的闭合。
- 最小测试使用实际 Python 子进程输出 `run_result`，不调用 LLM、不新增测试 Agent；同时覆盖正常 Function → Pattern 路由和非零退出码覆盖成功报告两条边界。
- 这验证的是 Coordinator 的进程协议，不等同于真实 LLM 业务回归；后者仍由 Bootstrap/Evolve/Pattern 各自的真实运行验证负责。

## 155. 自动化先补阶段超时，不急于增加 Coordinator 恢复层（2026-09-02）

- 用户要求执行 Run 恢复、阶段级超时和有限错误分类。结合当前代码，Function/Pattern Run 已在各自 SQLite 启动时收口悬挂 Run；再增加 Coordinator 持久 Run 会形成第二套状态真相，因此暂不实现。
- 当前真正的自动化风险是 `Popen` 子进程可能无限等待。最小修复是 Coordinator 侧单一阶段超时，超时返回 `STAGE_TIMEOUT`，并复用已有有限重试次数。
- 错误分类只保护明确的永久失败码，其他情况继续尊重子 Agent 的 `retryable`。这样避免盲目重试质量失败，也不增加新的错误层级或 LLM Supervisor。
