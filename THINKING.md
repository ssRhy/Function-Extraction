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

## 156. Evolve namespace 必须由父 Snapshot 决定（2026-09-02）

- 真实 Coordinator 验证发现，使用临时 namespace 会使 Evolve 子 Snapshot 与父 Snapshot namespace 不一致，Pattern 的已有 lineage 检查因此正确拒绝启动。
- 这不是只针对测试的适配：Evolve 的 namespace 是 Snapshot lineage 的一部分，必须从 `base_snapshot_id` 的 manifest 继承；测试隔离应复制 KnowledgeDB，而不是改 namespace。
- 最小修复是在 Coordinator 入口读取父 Snapshot manifest并覆盖 Evolve namespace，Bootstrap 继续接受显式 namespace；不放宽 Pattern 的父子一致性检查。

## 157. namespace 修复后真实 Pattern 暴露 Function ID/名称错配（2026-09-02）

- 真实 Coordinator 复测证明 namespace 继承已生效：错误的命令行 namespace 被替换为父 Snapshot namespace，Evolve 成功发布子 Snapshot。
- Pattern 随后在 motif 输入一致性检查处失败，具体为 `MC_47c799047da2d87e` 携带的 Function ID `F_E7DF0FDE` 与当前 Function 名称映射不一致。这个问题位于 Evolve 产生的 Motif/Function 引用或 Pattern 输入校验，不是 Coordinator 路由问题。
- 由于该失败不可安全自动推断，Coordinator 正确停止且不重试。下一步应追查 Motif candidate 的 ID/名称来源和 Function lineage 映射，不能用放宽校验或模糊匹配掩盖错配。

## 158. Pattern 的 Function 名称是可变投影，不是引用身份（2026-09-02）

- 真实失败的根因是：未变化故事继承父 Snapshot 的 Motif 证据时，同时继承了旧 `function_names`；当前 Snapshot 对同一稳定 Function ID 执行 `REVISE` 后，名称已更新，导致 ID/名称校验失败。
- 因此 Pattern 的 Motif 数据流应以 `function_ids` 为唯一引用，`function_names` 只在当前 Snapshot 输入边界按 ID 重新投影。不能删除历史 Snapshot 或 FunctionVersion 来规避问题，因为它们仍承担不可变审计和 lineage 作用。
- 本次决定保持最小增量：不重跑 Observation、不增加 LLM 调用、不修改历史数据；每次 Pattern 运行自动刷新继承 Motif 的名称。Function ID 因 `MERGE/SPLIT` 消失时，仍需单独使用显式 lineage 重映射。

## 159. 真实 Pattern 验证名称重投影闭环（2026-09-02）

- 在上次真实 Coordinator 失败的同一临时子 Snapshot 上直接重跑 Pattern，未重跑 Evolve；`F_E7DF0FDE` 的 ID/名称错配不再出现，Pattern Run 成功发布 9 个 Pattern。
- 这证明该修复确实作用于真实增量继承路径，而不仅是单元测试；名称重投影是本地确定性处理，不增加故事抽取或额外 LLM 阶段。

## 160. Coordinator 在原路径新库上完成两轮真实自动化（2026-09-02）

- 为验证完整链路，清空并重建原路径的 KnowledgeDB、Bank、Registry、Snapshot 和 checkpoint 运行状态后，从 Bootstrap 10 篇开始，再由 Coordinator 自动执行 Evolve 新增 5 篇；没有中途由 Codex 修正或手动衔接。
- 两轮均返回成功：Bootstrap 根 Snapshot 后自动进入 Pattern，Evolve 子 Snapshot 后自动进入 Pattern；名称重投影修复未再触发 ID/名称错配。
- 根 Pattern 与子 Pattern 均没有 published Pattern（分别为 1 个和 16 个 candidate Cluster），这是当前小样本下的发布门槛结果，不是 Coordinator 流程失败。后续应区分“自动化链路成功”和“Pattern 业务质量达标”。

## 161. 同一正式库追加 10 篇后 Pattern 发布闭环（2026-09-02）

- 在同一 Snapshot 链和同一 SQLite 库上追加 10 篇真实故事，累计 25 篇后，Coordinator 自动完成 Evolve → Pattern；无需 Codex 中途修正。
- 本轮 Pattern 从此前的 0 published 提升为 4 个 published Pattern，说明前两轮样本不足是主要原因之一；但 Evolve 的 assignment coverage 仍为 57.78%，Pattern 发布数量不能替代 Observation 匹配质量指标。
- LLM 曾返回非法枚举和角色槽位校验错误，现有有限重试成功恢复；这支持当前“确定性 Coordinator + 子 Agent 自处理”的设计，暂不需要 LLM Supervisor。

## 162. 第一版可信增量质量基线显示主要矛盾已转为语义质量（2026-09-02）

- 对 25 篇故事、4 个 Published Pattern 和 60 个 Observation 完成第一版确定性抽样语义评审；自动引用、Snapshot 和 Run 一致性均通过，问题不再是新旧版本串线。
- MATCHED 样本严格正确率为 `20/30=66.7%`，另有 6 个部分可接受；UNCERTAIN 样本有 16 个值得用现有 Function 受限 RetroMatch，14 个保持 UNCERTAIN 合理。
- 4 个 Published Pattern 中至少 3 个共享揭示—威胁骨架，故事支持也集中在少数悬疑语料；Pattern 发布成功不等于模式已经独立、稳定或跨题材成立。
- 当前最小下一步是记录并比较质量基线，优先验证 RetroMatch 和 Pattern 去重；不因少量边界样本立刻增加 Function，也不引入 LLM Supervisor。
- 本次基线还确认 `source_text` 并非全量可靠：225 个 Observation 中 32 个为空。因此后续质量指标必须同时区分“结构字段可用”和“原文证据完整”，否则 MATCHED 的语义正确率会被高估。

## 163. 跨题材增量用于区分偶发问题与结构性问题（2026-09-02）

- 用户要求继续积累不同题材数据，观察基线问题是否重复。采用最小实验：同一 SQLite、同一 Snapshot 链、追加 10 篇非悬疑故事，由 Coordinator 自动完成 Evolve → Pattern。
- 结果显示 assignment coverage 在五类题材间均约 `57.1%~64.8%`，未出现只在悬疑语料中存在的异常；Evaluator 的 `abstraction_quality` 再次失败，并再次指出威胁与个人成长 Function 过宽，因此这是跨题材重复的结构性语义问题。
- 受限 RetroMatch 从父 Snapshot 的 95 个未决项中召回 5 个并新增归属 2 个，证明现有局部回看足以提供小幅增量收益，不需要每轮重跑全部 Observation。
- Pattern 重叠也重复出现：当前 5 个已发布模式中有两组共享关系破裂—威胁骨架、两组共享隐藏能力揭示—威胁骨架。现阶段先把它作为质量诊断记录，不立即引入 Pattern Dedup Agent 或新增持久化边界。
- 当前决策：继续积累至少下一批跨题材数据；只有同一问题连续批次重复且影响发布/匹配时，才做局部规则或阈值修复。

## 164. 第二批跨题材结果：质量问题部分重复、部分具有波动性（2026-09-02）

- 用户要求继续积累未处理的跨题材数据。因悬疑语料已耗尽，本批追加古风、现代、末世、家庭职场各 2 篇，共 8 篇，继续使用同一正式 DB 和父 Snapshot。
- 最终 `abstraction_quality` 从上一批的失败恢复到 `1.0`，所以“Function 过宽”目前不能仅凭连续两批最终报告判定为稳定故障；但中期再次指出 Threat Function 混合对抗与逃离，说明语义边界问题仍有波动性。
- assignment coverage 从上一批 `62.17%` 降为 `57.77%`，其中家庭职场 `50.0%`、现代情感 `53.8%`；说明跨题材累积并没有自动改善匹配率，低匹配可能是稳定问题。
- Pattern 阶段首次出现 1 次合并，并退休 2 个旧 Pattern；但已发布模式仍共享揭示—威胁—反思/资源骨架。去重机制开始发挥作用，但还不足以说明 Pattern 已经跨题材稳定。
- 当前决策保持不变：先继续观察至少一个批次；如果低 assignment coverage 和重复骨架继续出现，再做最小的 Matcher/Pattern 局部规则修复，不增加 Supervisor 或独立 Dedup Agent。

## 165. 第三批跨题材结果支持低匹配与 Pattern 重复为稳定问题（2026-09-02）

- 用户要求继续观察下一批。追加 10 篇未处理故事，保持同一 SQLite 和 Snapshot 父子链，Coordinator 自动完成 Evolve → Pattern。
- 最终 assignment coverage 为 `59.43%`，此前两批为 `62.17%`、`57.77%`；三批都处于约 58%～62% 区间。古风、现代和家庭职场持续偏低，低匹配已不宜再视为单批波动。
- Evaluator 最终连续两批 `abstraction_quality=1.0`，但中期和历史报告仍曾指出 Threat Function 粒度问题；当前更准确的判断是“最终质量门暂时通过，语义边界仍需专项诊断”。
- 当前 10 个 Published Pattern 仍共享揭示—威胁—反思/资源骨架；本批没有合并或阻断，说明已有 Pattern 合并能力并不能稳定消除相似模式。Pattern 重复已获得多批次证据。
- 当前决策：数据积累阶段的观察目标基本达到。下一步如果开始改代码，应只增加离线诊断/发布前相似度提示，先不改变 Pattern 生成、不引入新 Agent，也不自动删除 Pattern。

## 166. 生成—分析闭环证明 Pattern 是高层约束而非固定脚本（2026-09-02）

- 用户要求执行“现有 Pattern → 生成大纲 → 生成故事 → Evolve 分析”的实际闭环。为避免污染正式基线，在正式 KnowledgeDB 的副本上完成真实 LLM 生成和真实 Evolve/Pattern。
- 指定 Pattern 的四个目标 Function 均出现在生成故事的实际序列中，且保持相对顺序；但实际序列包含重复威胁、联盟、资源和个人成长。这说明 Pattern 能约束叙事方向，但不应被当作严格 Function 脚本。
- 生成故事的 12 个 Observation 全部 `MATCHED`，但 Evaluator 再次指出 Alliance/Deal 和 Threat/逃离的边界混合。生成闭环因此同时验证了当前 Function 可分析性和语义边界问题。
- 当前决策：不因为单篇生成结果修改代码；再用另一个 Pattern 做一篇验证，若目标结构保持和额外叙事扩展持续出现，则把该行为作为 Pattern 的设计语义，而不是故障。

## 167. 第二篇生成验证显示目标 Function 链尚不稳定（2026-09-02）

- 第二篇使用不同 Pattern `反思揭示与自立成长` 生成现实家庭职场故事，并在隔离副本中完成真实 Evolve → Pattern。
- 生成故事的 5 个 Observation 全部 `MATCHED`，但目标四步链只出现 2 个 Function；`INTERNAL_REFLECTION` 和 `RESOURCE_OR_SUPPORT_ACQUISITION` 缺失，额外出现 `RELATIONSHIP_BREAKDOWN` 与 `STRATEGIC_ALLIANCE_OR_DEAL`。
- 与第一篇 4/4 目标 Function 的结果相比，当前只能得出“Pattern 影响方向，但不稳定控制 Function 链”的结论。抽取匹配成功和 Pattern 遵循成功必须分开评估。
- 当前决策：暂不修改生产代码。若继续验证，应再选一个结构差异更大的 Pattern；只有偏离方向重复出现，才考虑调整生成提示或 Function 定义。

## 168. 三 Pattern 批次验证：方向性成立，精确保持不稳定（2026-09-02）

- 用户要求再用一批 Pattern 验证“目标结构保持、叙事内容扩展”。选择现代情感、末世科幻、古风仙侠三个不同 Pattern，各自使用正式 Snapshot 的隔离副本进行真实生成和 Evolve。
- 两篇完整成功样本的目标 Function 出现率分别为 `3/4`、`4/5`，都保留了主要方向但加入重复资源、威胁或内省环节；因此 Pattern 的高层约束作用可以复现，精确 Function 链不能复现。
- 第三篇在 Evolve 发布前因 `RESOURCE_OR_SUPPORT_ACQUISITION` 的 FunctionContract 格式错误失败。该失败没有污染 Snapshot，但说明结构验证必须把“生成偏离”和“发布接口失败”分开统计。
- 当前结论：不能宣称“目标结构保持”已经稳定，只能宣称“Pattern 对创作方向有稳定影响”。暂不调整生产代码；先处理失败样本的 Contract 发布边界或重新验证，再决定是否修改生成提示。

## 169. Contract 失败应通过父 Snapshot 复用解决，而不是降低校验（2026-09-03）

- 实际检查发现，Evolve 的新输出目录没有父 Snapshot 的 Contract 缓存，所以每轮都会重复生成未变化 Function 的 Contract；一次偶发的 LLM 格式错误即可阻断整轮发布。
- 采用的边界是：父 Snapshot Contract 已经过 Snapshot 校验，只有当前 Function 的定义哈希仍一致时才可复用；Function 定义变化、新增 Function 或父 Contract 不可用时仍重新生成并严格校验。
- 真实重跑支持该判断：原失败故事在隔离库成功发布子 Snapshot，并自动进入 Pattern；父子 `function_contracts.jsonl` 完全一致。该修复保持 Evolve 增量，不重跑旧 Observation，也没有增加新的 Agent、数据库或持久化边界。

## 170. 五领域跨题材增量第一轮：链路通过，Pattern 稳定性仍需观察（2026-09-03）

- 用户要求基于已有五领域执行可信增量验证。由于原 60 篇语料只剩 7 篇未处理，改从同来源 250 篇五领域真实语料中选取此前未进入正式 Snapshot 的 15 篇，每领域 3 篇；仍使用同一正式 SQLite 和当前 Snapshot，不清库、不新建库。
- Evolve Run `FR_a776252cdc4c44ad` PASS，子 Snapshot `real_coordinator_rebuild_20260902_20260903T080910344525Z_0bc8086d7c18` 累计 68 篇、588 个 Observation；五领域均进入子 Snapshot，最终 Evaluator 6/6，assignment coverage `58.5%`。受限 RetroMatch 仅召回 12 个旧未决项并新增 8 个归属，增量边界保持简洁。
- Pattern Run `PR_83b1ff049c7a8585` SUCCESS，13 个 Published Pattern，其中 12 个具有至少两个领域证据；但 41 篇旧故事被标记为 `changed`，并出现 11 个新建、8 个退休 Pattern。由此区分出两个结论：跨领域 Pattern 证据已经出现；Pattern 对 Function 演化仍敏感，尚不能称为稳定。
- 本轮真实暴露的语义提示是 `RELATIONSHIP_NEGOTIATION` 同时包含关系建立与破裂方向。该提示先记录，不立即增加 Dedup Agent、Supervisor 或新的持久化边界；下一批独立数据应观察该问题和 Pattern 大幅变化是否重复。

## 171. 第二批独立五领域数据：低匹配和关系边界问题重复（2026-09-03）

- 用户要求继续用下一批独立新数据观察问题是否重复。采用 500 篇五领域语料中尚未处理的 15 篇，每领域 3 篇；同一正式 SQLite、同一 Snapshot 链，由 Coordinator 自动完成 Evolve → Pattern。
- 本批最终 assignment coverage 为 `58.4%`，上一批为 `58.5%`；不同独立批次稳定落在约 58%～62% 的低匹配区间，不能再视为单批波动。RetroMatch 召回 39 个旧未决候选，新增归属 5 个，说明局部回看有效但收益有限。
- Function 从 6 个变为 7 个：`RELATIONSHIP_NEGOTIATION` 被拆成 `RELATIONSHIP_FORMATION` 与 `RELATIONSHIP_DISSOLUTION`，但 separation 仍失败并建议合并。这是关系语义边界的重复证据，而非单篇故事误判。
- Pattern 新建 10、退休 5、更新 4，11/16 个当前 Published Pattern 有多领域证据；共享“关系变化—揭示/威胁—反思或自我重建”骨架仍未消失。Pattern 发布链路正确，但稳定性和去重仍不足。
- 本批 Evolve 输出出现 1 个同故事重复 `obs_id`，数据库最终按唯一身份收敛，没有外键错误或孤立 Occurrence。暂把它视为输出文件层的轻微重复，不为此引入新的边界或复杂状态。
- 当前决策：跨批次观察目标基本达到；下一阶段不继续盲目堆数据，也不增加 Supervisor/Dedup Agent。保持生产架构不变，先做最小离线相似度诊断和人工抽样，确认哪些重复会影响 Pattern 发布或故事生成。
## 172. Pattern 驱动生成的正文回流验证：大纲保持，抽取保持不稳定（2026-09-03）

本轮用正式 Snapshot 的 3 个 Published Pattern 生成悬疑、现代情感、末世科幻各 1 篇故事，并将正文重新送入同一 SQLite 的 Evolve → Pattern。

真实结果：`FR_e1d387e7196f439a`、`PR_1d53bb856cfe27ee`，新 Snapshot 为 `real_coordinator_rebuild_20260902_20260903T090305538477Z_237159895d81`。Evolve 最终硬匹配率 59.5%，RetroMatch 新增 3 个归属；Pattern 产生 19 个 Published Pattern。

目标结构与实际 MATCHED 链的诊断 LCS 保留率为 75%、50%、0%。说明当前 Story/Outline 层能遵循目标 Function 链，但正文经 Observer/Matcher 回流后未必重新识别为同一条链。关系类 Function 在本轮从形成/解除收敛为 `RELATIONSHIP_STATUS_CHANGE`，是结果差异的重要来源。

判断：生成链路已经工程跑通，但结构保持尚未稳定。当前不增加 Supervisor、回流专用 Agent 或复杂校验；继续保留本轮结果作为基线，后续再用少量不同 Pattern 重复验证。
## 173. Pattern 应用阶段：成功路径可用，但大纲生成稳定性不足（2026-09-03）

基于最新 Snapshot 尝试使用 3 个未使用 Pattern 生成不同题材故事。现实家庭职场成功完成大纲和正文；悬疑因 `final_ledger` Schema 类型错误失败；古风因伏笔兑现位置非法失败。

这次失败没有进入 Evolve，也没有破坏 Snapshot。失败时 `claim_pattern` 会提前占用 Pattern，因此清理了本轮两个失败占用和一个失败大纲，防止测试影响后续应用。

结论：Pattern 应用链路的成功路径存在，但不能把生成层稳定性视为已解决。当前不增加 Supervisor；如果继续推进，最小改进应集中在大纲生成节点的受限重试/纠错，而不是扩展数据库或多 Agent 架构。

## 174. Pattern 应用失败应在节点内收敛，Pattern 占用应与大纲落库原子绑定（2026-09-03）

本轮将应用阶段暴露的两个确定性问题收敛为最小修复：LLM 的 `final_ledger` 只补充明确提示，不改变既有字符串 schema；伏笔位置错误只做一次带错误反馈的局部重试。Pattern 的领取从 Planner 前移状态改为 `record_outline()` 事务内的最终绑定，使生成、校验或导出中途失败不会留下孤立 `pattern_usage`。该方案保持现有单库和线性 LangGraph，不新增 Supervisor、数据库或复杂恢复层。

真实验证表明该修复已作用于正式流程：新 Pattern 成功生成并落库，大纲结构校验通过，`final_ledger` 为纯字符串，兑现位置全部合法；本次真实样本未触发业务级伏笔重试，但确定性测试已覆盖该分支。LLM 仍可能在字段格式上触发既有结构化重试，这属于正常收敛机制，不再扩展架构。

## 175. 生成—回流—再归纳应先建立批次基线（2026-09-03）

用户要求把已跑通的自动化闭环作为稳定使用流程进行真实回归，而不是继续扩展架构。本批用 5 个题材/Pattern 组合尝试生成，3 篇完整进入 Evolve，Coordinator 自动完成 Evolve → Pattern。结果显示链路、Snapshot 和 Run 可见性正常，目标 Function 链保留率为 75%～80%；但大纲最终成功率只有 60%，全 Snapshot assignment coverage 约 64%，且关系 Function 与调查/证据 Function 的粒度问题再次出现。由此确认下一阶段应以独立小批次回归和单指标比较为主，不应把一次成功闭环误判为语义质量稳定，也不需要立即新增 Supervisor 或数据库边界。

## 176. 当前链路可用后进入实际使用阶段（2026-09-03）

用户确认当前系统达到“可用即可，后续再优化”的标准。基于真实回归中 Coordinator 自动闭环成功、父子 Snapshot 正常、失败大纲未污染 Evolve、外键和悬挂 Run 检查通过，项目可以从架构验证切换到实际故事生产与跨题材数据积累。后续优化以真实使用中重复出现的问题为依据，不提前扩展 StateVocabulary、Best-of-N 或 Supervisor。

## 177. StateVocabulary 先做确定性规范化，不做 LLM 同义词推断（2026-09-03）

用户随后要求实现最小 StateVocabulary。为保持成本和架构边界，第一版从当前 FunctionContract 直接生成词表：aspect/key 沿用已有大写 ID，state 对 Unicode/空白/已有标识符做稳定规范化，非标识符使用稳定 canonical ID，并保留 aliases 与 raw_evidence。Ledger 以 canonical ID 做状态和债务比较，原始字段不变；新 Snapshot 保存词表并参与哈希，旧 Snapshot 不回写。该版本解决格式和追踪问题，但不声称能自动合并“关系紧张/关系恶化”等语义近义词，后者留待真实案例重复后再决定。

## 178. StateVocabulary 已通过真实 Evolve 发布验证（2026-09-03）

用户要求用一篇真实新故事验证 StateVocabulary 是否能进入实际数据流。单篇 Evolve 在同一正式 SQLite 上成功发布带 `state_vocabulary.json` 的新子 Snapshot，并自动完成 Pattern；词表哈希、Snapshot、外键和 Run 状态均正常。该结果确认实现可以作为后续增量流程的正式产物使用，但仍保持语义同义词不自动合并的最小边界。

## 179. StateVocabulary 不替代 StoryPattern 去重（2026-09-03）

用户指出 StoryPattern 已经存在相似结构去重，因此需要明确 StateVocabulary 的必要范围。结论是：Pattern 去重处理故事级 Function 结构，StateVocabulary 处理 FunctionContract 中单个状态、aspect 和义务字段的统一；前者可以发现整体相似，但不能保证 `before → after` 状态连接使用同一内部标识。若项目只做 Pattern 相似度分析，StateVocabulary 并非必需；当前保留最小确定性版本，仅服务状态比较、规划、统计和义务检查，不加入每轮 LLM 同义词推断。

## 180. 真实增量与质量基线阶段已完成（2026-09-03）

用户指出“继续真实增量使用与质量基线积累”此前已经反复完成。确认：25 篇故事的真实闭环、跨题材验证、生成—回流—再归纳基线，以及带 StateVocabulary 的真实 Evolve 发布都已完成。后续不应把再次跑一批数据当作新的必经验证阶段；新数据只在实际使用或需要回答具体质量问题时自然进入。当前阶段应转入 Pattern 驱动的实际故事生成/分析应用，架构扩展继续由真实故障触发。

## 181. 对 Plan.md 的阶段收敛判断（2026-09-03）

Plan.md 早于当前实现，不能把其中所有“后续计划”继续当作未完成任务。当前核心抽取、Occurrence、FunctionContract、Pattern 增量、Planner/Outline、生成回流、Coordinator 和最小 StateVocabulary 已经真实跑通。若以原计划的完整目标衡量，剩余最必要的能力是：补齐故事级人物/关系上下文（必要时采用轻量 Story Profile）、把高质量 Occurrence 投影为可检索的实例化案例，并确认 Function 转移、motif 和实例检索能被 Planner 实际使用；这些应优先服务生成一致性。Propp 31 项映射、Best-of-N、LLM StateVocabulary 和 Supervisor 都不是当前核心链路的必需项，只有明确的分析需求、生成波动或调度故障出现时再加入。

## 182. Story Profile 应复用 Observer 调用并与抽象参与者分层（2026-09-03）

本轮将故事级人物上下文放进现有 Observer 的结构化输出，而不是增加独立 Profile Agent；这样每篇故事只增加字段，不增加 LLM 调用和运行边界。稳定人物使用故事内 `participant_ids`，原有 `participants` 继续只承担跨故事角色类型抽象，避免具体姓名或人物身份进入 Function 相似度。生成侧则把 `character_names` 作为正文输出的显式合同，并用确定性校验保证覆盖和唯一；这解决的是人物引用稳定，不声称已经解决正文语义中的所有人物一致性问题。

## 183. Story Profile 已通过真实 LLM 隔离 Evolve 验证（2026-09-03）

为验证修改不是只在 mock 测试中成立，使用真实末世科幻故事执行 1 篇隔离 Evolve。Observer 实际返回 `P1/P2` Profile，5 条新 Observation 全部带稳定 `participant_ids`，并在 `story_versions.payload_json` 和临时 Snapshot 中可回读；整条 Evolve 最终 `PASS`，正式 Knowledge DB 未写入本次 Run。

真实输出同时暴露了边界：模型把“森森”写成“森余”。因此当前稳定性保证应理解为“引用同一个 ID 不漂移”，而不是“所有 mentions 字符串都经过事实级校对”。在出现重复的字面实体错误前，不增加额外实体解析 Agent；下一步仍应优先实现 MATCHED Occurrence 的实例案例投影和 Planner 检索消费。

## 184. Story Profile 接入 Story Agent 后，收益首先表现为身份锚定（2026-09-03）

本轮把 Profile 从 Outline 传入 Story Agent，并用同一份大纲、同一套场景计划进行真实 A/B。带 Profile 的正文沿用了 Profile 提供的两个主要人物称呼，未带 Profile 的正文重新生成了另一组姓名；两组都因 `character_names` 合同保持了各自姓名在场景间的一致。带 Profile 的正文更短更集中，但单个样本不能把篇幅或文学质量差异归因于 Profile。

重要边界是：Profile 已经参与生成，但仍不是完全硬约束。A 组把 Profile 中的 `韩主任/韩总` 具体化成 `韩宏`，说明如果要求字面称呼严格继承，应该增加确定性 canonical mention 校验；不应因为一个样本就引入新的 Agent 或 Best-of-N。

## 185. Story Profile 暂不执行具体功能，保留最小接口（2026-09-03）

用户根据真实 A/B 结果判断带 Profile 的正文没有显示出明确优势，Profile 当前与 Outline 信息重复，且只提供软约束。因此撤回其 Observer、Evolve、Outline 和 Story Agent 运行时链路，只在 `SourceOutlineDocument` 保留可选 `story_profile` 字段作为未来接口，不生成、不校验、不持久化，也不注入任何 Prompt。`character_names` 和场景人物 ID 校验属于 Story Agent 独立的一致性合同，继续保留。

## 186. Planner 尚未真正消费 transition、局部 motif 和实例案例（2026-09-03）

用户要求验证已有知识是否真的进入 Planner。对正式 Snapshot `real_coordinator_rebuild_20260902_20260903T130418047879Z_b21aaffdc548` 的只读运行时探针显示：知识库有 30 个 Published Pattern、294 条 motif evidence、193 个 motif cluster、8 个 FunctionContract 和 781 个 FunctionOccurrence，但 `load_cards()` 与 `load_mechanisms()` 均未加载到文件。Planner chain 有 Contract，却没有 motif、实例案例或非空 `state_transition`；Scaffold Prompt 中的 `reference_mechanisms` 键存在但所有值为空。

当前只能做如下区分：motif 已经被 StoryPattern Agent 间接压缩进 Published Pattern 的 `core_function_chain`，但 Planner 没有直接查询 motif；Function 记录中的 `realization_patterns` 尚未被 Planner 加载；`transition_index` 入口只取 `mechanisms`，没有消费独立 `transitions` 列表。因此不能宣称 Planner 已使用三类知识，后续若实现，应先补齐“读取 → Prompt 字段 → 输出可观测引用”这条最小链路。

## 187. Planner 通过同一 Snapshot 的只读投影消费三类参考（2026-09-03）

针对第 186 条审计暴露的缺口，采用最小实现：不另建 Instance Card 表，也不恢复当前数据中不存在的文件索引，而是在 Planner 运行时从同一 Snapshot 读取 `FunctionOccurrence`、Function 记录和所选 Pattern 的 motif evidence。这样 transition 保持真实故事顺序，实例案例保留 `occurrence_id/story_id/surface_form/event/before_state/after_state`，并且所有引用都能回溯到原始记录。

链路现在是：`load_planner_references()` → chain step 的 `reference_transitions/reference_instance_cases` 与顶层 `reference_motifs` → Mechanism/Scaffold Prompt → Outline JSON 的 `planner_references`。motif 不再只通过 `core_function_chain` 间接生效，transition 和 Occurrence 实例也不再停留在离线数据层。

正式 Snapshot 的真实 smoke 查询到 3 条 motif、9 条 transition edge 和 9 条实例案例，并成功进入真实 LLM 的 Mechanism/Scaffold 输入；一次样本足以证明“查询并传入”的运行时事实，但不足以证明生成文本对所有引用都做了高质量语义利用，因此后续质量结论仍需多样本评审。

## 188. 删除 Planner 的旧 Function Card 兼容分支（2026-09-03）

用户要求删除 Planner 中的冗余代码以避免干扰。审计发现正式 Snapshot 没有对应的 Function Card 文件，`state_transition` 也始终为空；而 Planner 已经有 Pattern 合同和 Snapshot FunctionContract，旧 cards 回退不再提供有效信息，反而让接口和 Prompt 携带无意义字段。

因此移除 `load_cards()`、Planner 的 `cards` 参数及 `state_transition` 字段，只保留 Pattern、FunctionContract 和三类真实 Snapshot 参考。这个清理不改变 Planner 的结构职责，也不删除任何真实知识来源；全量测试仍为 `318 passed, 1 skipped`。

## 189. 真实 LLM Planner A/B 的边界（2026-09-04）

用户要求用真实 LLM 验证 Planner 的 transition、局部 motif 和实例案例是否真的被使用。实际运行发现，当前 `planner()` 是确定性的链路编排函数，真正消费这些字段的是后续 Mechanism/Scaffold Prompt。因此实验固定同一 Snapshot、Pattern、Function chain 和 Seed，只对 A 组注入三类参考、对 B 组清空参考。

首轮和两轮复测都显示 A/B 的具体规划明显不同，但这只能证明“带参考的上下文会产生不同结果”，不能证明差异一定来自参考信息：`chat_structured` 当前没有固定 temperature/seed，且模型不会输出 motif/Occurrence ID 作为引用痕迹。故本轮结论是“查询与传入 PASS，语义利用的因果证明 INCONCLUSIVE”。这提示后续应优先补可复查的采样/盲评方法，而不是继续堆 Agent 或字段。

## 190. Planner 阶段收敛后的下一步（2026-09-04）

用户进一步明确希望推进结构性问题，暂时放下生成细节。由此将下一阶段从“生成失败的定向修复”调整为结构层推进：审计 Function 本体边界、transition 图、motif/Pattern 的抽象和跨题材泛化，并检查 Planner chain 是否表达完整结构；人物、格式、单个结局等问题保留为维护项。

## 191. 分层结构审计的核心缺口（2026-09-04）

对正式 Snapshot 的 Function—transition—motif—Pattern 审计显示：Pattern 的证据支持和跨题材分布已经成立，但 Contract 之间尚未形成可验证的状态组合。97 个 Pattern 相邻 Function 对没有精确的 effect-after 到 next-precondition 连接，只有 34 个共享 aspect。下一步结构工作应先定义 transition 兼容语义，再判断 Function 边界和 Pattern 是否需要调整；不能把当前共现频率直接当作因果结构。

## 192. 跨题材 transition 是目标而不是缺陷（2026-09-04）

用户指出项目本身就是跨题材抽取和泛化，因此 transition 跨越多个题材应被视为正向证据。审计中的风险仅指 transition 图较密、弱支持边和语义兼容关系尚未分层；后续应保留跨题材强骨架边，只降低低支持或语义不清边的结构权重，不能为了稀疏化而消除跨题材连接。

## 193. 现有状态/义务代码与 StoryPattern 的边界（2026-09-04）

代码核对发现，`Contracts/ledger.py` 已有 `check_contract_chain()` 和 `build_contract_ledger()`，可以检查前序 effect、当前状态和开放/推进/清偿义务；但它们只在 Outline 生成阶段使用。StoryPattern 会把 Contract 传入摘要 LLM，也会检查 Contract 是否存在，却没有用兼容结果参与 motif/Pattern 发布。因此“补足衔接”不是新增第二套账本，而是复用现有逻辑，把它以诊断方式接入 Pattern 结构评估。

## 194. 三个结构现象暂不升级为开发任务（2026-09-04）

用户追问 motif 候选碎片化、Pattern 近邻变体和 Contract 组合是否仍有必要。结合当前职责判断：三者都是有价值的审计观察，但都不是当前核心链路阻塞项。motif 碎片化主要是滑动窗口中间产物，Pattern 近邻可能包含有价值的变体，Contract 组合已有 Outline Ledger 处理；只有当它们分别影响成本、选择/解释或因果证明时才启动对应治理。

## 195. Pattern 归纳与 Function 驱动的 Pattern 合成必须区分（2026-09-04）

用户明确指出，当前系统已经完成的是“从真实故事中的 FunctionOccurrence 序列提取 motif，经 LLM 审查后发布 Pattern”，以及在生成时从 Published Pattern 中选择并固定 Function chain；这不等于“LLM 从全部 Function 中主动编排新的 Function 组合”。

当前真实数据流是：

```text
真实故事中的 FunctionOccurrence 序列
→ 程序提取 motif
→ LLM 审查 motif 变体
→ Published Pattern
→ Planner 选择已有 Pattern 并固定 core_function_chain
```

原始 Plan 仍要求的另一条能力是：

```text
Function 集合 + 规则/状态/故事目标
→ LLM 动态选择后继 Function
→ FOLLOW / ADAPT / EXPLORE 生成多条候选链
→ 验证候选链
→ 保存为候选 Pattern 或 Creative Memory
```

因此，当前 Planner 的准确定位是确定性的 Pattern 选择与结构上下文编排器，而不是 LLM-guided Function Planner。后续讨论完成度时，必须把“真实 Pattern 归纳/增量更新”与“从 Function 空间主动合成新 Pattern”分别统计，不能因为前者已经跑通就宣称后者已实现。

## 196. 动态候选先作为运行时产物（2026-09-04）

用户明确选择动态候选“仅本次使用”。因此本轮实现把候选链放在 `OutlineState.dynamic_candidates/dynamic_candidate`，只将最终大纲的动态来源和候选审计信息写入 Outline 文档；不把候选注册成 Pattern，也不让它参与 Pattern 使用计数或 Evolve。这样可以先验证“Function 空间主动编排 → 合同/状态校验 → 大纲生成”的闭环，再根据真实质量证据决定是否需要长期记忆。

## 197. motif 组合必须是序列合并，不是 Function 列表追加（2026-09-04）

用户指出动态 Planner 生成的链出现重复 Function，不能把它误认为 motif 组合已经成立。由此明确：LLM 负责选择 motif、组合顺序和结构意图，程序负责按 motif 的真实 Function 序列计算合法前后缀 overlap、消解边界重复，并检查新扩展不能重复带回已经完成的 Function；motif 内部原生回环可以保留。真实 smoke 已验证 `COMPOSE_MOTIFS`、overlap=1 和新的跨结构转移边同时进入动态候选，重复项可回溯到 motif 内部而非 Beam Search 的机械追加。
## 198. Beam Search 采用质量排序和结构去重（2026-09-04）

用户要求先删冗余，再落实 `beams = [空链]` 的多轮扩展流程。审计后仅删除无调用方的 `OPERATIONS` 常量；保留实际用于 Snapshot、motif、Contract 和 LLM 输出的逻辑。Beam 现在每轮对每条部分链请求多个扩展，先 canonicalize motif/overlap，再硬过滤，按故事目标、状态/义务、历史 transition 和结构新意评分，删除完全重复及 `SequenceMatcher >= 0.8` 的近似链，保留最多 4 条；若达到最小长度且没有合法后继，程序自动完成该 beam。真实 Snapshot smoke 留下 4 条不同候选，均无硬错误。

## 199. 重复 Function 的当前边界与 Planner 阶段收口（2026-09-04）

用户追问 motif 组合中的重复是否应转化为故事递进。记录当前实现是第一版安全阀：边界 overlap 会被合并，motif 内部回环会保留，但跨 motif 的重复 Function 目前直接作为硬错误；后续若继续提升递进表达，应改为检查状态、义务、角色目标和 transition 是否发生变化，再决定接受或拒绝。当前 LLM Planner 已完成动态编排、motif 组合、overlap、Beam 多样性、合同/状态校验、Outline 接入、CLI 和运行时边界，可作为阶段性收口版本；未完成项仅是递进式重复的更细语义判定、operation 配额和长期 Creative Memory，不阻塞当前 Planner 闭环。

## 200. 删除非核心 schema fallback（2026-09-04）

用户要求清理 LLM Planner 冗余代码和测试。结构化输出已要求严格使用 `extensions` 及正式字段，因此删除了 `candidates/options`、字段别名和 `overlap` 字符串转换等兼容 fallback，以及对应的 2 个测试；保留五种 operation、motif overlap、硬校验、Beam、图流程和持久化边界覆盖。清理后相关回归为 37 项通过。

## 200. 往返抽取与分层相似度不作为当前运行时硬门槛（2026-09-04）

用户询问真实 Function 往返抽取验证和生成后的分层相似度诊断是否必要。当前判断是：两者对研究结论和后续质量治理有价值，但都不是当前可用闭环的必需节点。

真实 Function 往返验证的价值在于检查“动态 Planner/大纲生成的结构”能否被 Observer/Matcher 从生成结果中重新识别；它不能替代已有的 Contract、状态/义务校验，也会受到 LLM 采样和匹配波动影响。因此采用小批量、定期回归的方式即可，不在每次生成中强制执行。已有生成—回流基线可继续作为比较依据。

生成后的分层相似度诊断只有在需要控制新颖性、避免实例重复、实现候选排序或支撑论文级质量结论时才有必要。当前动态 Planner 已有 Function chain 结构新意和 Pattern 近似去重，目标仍是先保证结构可生成，不为创新额外增加五层比较和自动修复。若后续确实需要，先增加只读的 Function chain/motif 与实例机制相似度诊断，不直接作为发布或生成阻断。

## 201. 人物立场与关系变化必须分层保存（2026-09-04）

用户明确要求按十步补齐人物信息，并进一步追问如何从真实故事库继承人物立场、长期目标和关系变化。由此确定：故事级 Profile 负责“谁、想要什么、开场与主人公的关系”，FunctionContract 负责“需要哪些标准角色位置”，FunctionOccurrence 负责“本次事件由谁对谁产生了什么有证据的变化”。不能把具体人物 ID 写进跨故事 Function 定义，也不能只靠 Outline LLM 自由记忆关系。

实现上继续沿用一个 SQLite 知识库和 Snapshot 冻结边界：Profile 随 story version 保存，evolve 用当前 Run 按 story 覆盖父 Snapshot；Planner 只从冻结 Snapshot 投影匿名的角色统计、长期目标/立场上下文和关系变化案例。关系账本作为生成期硬校验，防止一个 Function 借“受益/共同对抗”等弱事实自动推出信任、合作或亲密升级。

## 202. 严格跨字段校验会暴露真实 Observer 的重试成本（2026-09-04）

本轮 3 篇真实 LLM 重跑中，首篇第一次 Observer 返回了结构合法但语义不一致的结果：`role_bindings` 引用了人物，而 `participant_ids` 没有覆盖该人物。当前实现正确拒绝了它；外层重试后才通过，期间还触发了一次 JSON 自修复。由此确认人物绑定不能只依赖 Pydantic 字段校验，但也需要把这类确定性跨字段错误纳入 Observer 的有限重试/反馈机制，否则真实批处理会因单篇采样波动中断。当前先保留严格门槛，不自动并集合并人物 ID，以免掩盖模型遗漏。

## 203. 15 篇 Evolve 足以验证正式闭环，但不等于 Pattern 已成熟（2026-09-04）

用户将原计划的 108 篇 Evolve 收缩为 15 篇。最终选择根 Snapshot 后清单中的前 15 篇，保持目标可追溯；这批新增文本实际集中在悬疑题材，因此 27 个故事的三题材 diversity 主要来自 12 篇根样本，不能把本轮结果当成平衡跨题材评估。

正式链路已经得到可复核结果：schema 5 根 → 15 篇真实 Observer/Matcher/Curator/Evaluator → 子 Snapshot → Coordinator 自动 Pattern。失败的中止/重试 Run 均没有 Snapshot 且暂存清零，说明父子 Snapshot 边界有效；但 Pattern 只有候选 cluster、没有 Published Pattern，样本量仍不足以支撑下游 published Planner 的质量结论。

本轮发布失败揭示了一个重要层次区别：supporting evidence 命中 Function 不代表该事件已经满足 FunctionContract 的全部角色槽位。与其放宽 Contract 或根据参与者猜测 `affected`/`beneficiary`，应把这类 occurrence 降级为 `UNCERTAIN`；这样保留真实不确定性，同时让 Snapshot 的人物与契约校验继续成为硬边界。

真实 dynamic Outline 进一步验证了下游防线：角色统计、长期目标/立场和关系变化案例确实进入 Mechanism；当模型引入 seed 之外人物、或把关系变化放在契约未声明关系效果的 Function 上时，关系账本阻断输出。当前应把该结果解释为“引用传递与非法变化拦截通过”，而不是“已生成一个合格 Outline”；待 Published Pattern 形成后再做正常 published Planner 的端到端质量验证。
## 204. 人物连续性的证明必须分成数据继承、账本门禁和重复生成三层（2026-09-04）

- 用户提出：要证明系统能稳定生成保持人物立场、长期目标和关系连续性的 Outline，需要更多真实样本、更多 Published Pattern，以及至少一批通过关系账本校验的真实 Outline，并追问具体验证方法。
- 当前 schema5 正式库已经证明了 Function → Snapshot → Pattern → Outline 的工程链路，但 27 篇故事对应的 0 个 Published Pattern 和 1 份被账本阻断的动态 Outline，不能证明生成质量；关系账本也不能单独证明长期目标和立场没有跳变。
- 关键判断：必须先把“目标/立场变化”变成带人物 ID、前后状态、触发 Function 和证据的可检查账本项；然后用冻结 Snapshot、固定 Story Seed、同一案例多次真实 LLM 重复生成，分别测硬约束通过率、语义连续性和重复一致性。LLM 自评不能作为唯一证据。
- 最小正式验收建议：训练/Pattern 库至少 60 篇、至少 4 类题材；至少 5 个由 3 篇以上真实故事且覆盖 2 类题材的 Published Pattern；每个 Pattern 至少 3 个固定 Seed、每个 Seed 重复 5 次；所有硬账本错误为 0，且抽样人工/独立评审确认目标、立场和关系变化都有前序证据。重复评测使用临时数据库或不消耗 Pattern 的评测副本，以保留生产环境中 pattern_id 全库只使用一次的约束。

## 205. 27 份 Outline 门槛失败的含义（2026-09-04）

用户追问硬校验、关系账本和重复组均为 0 的原因。核对结果显示：27 份 Outline 全部生成成功，但每份都产生了 3～10 条关系变化（平均 5.15 条），且每份至少有一条关系双方没有被当前 Function 的 `role_bindings` 覆盖。23/27 份在没有 `RELATIONSHIP_STATUS` Contract 效果的 Function 上生成了关系变化，18/27 份的关系效果没有覆盖双方角色，25/27 份存在同一关系维度的 `before` 与前一步 `after` 不连续；这些计数相互重叠。

因此 0/27 首先说明“关系变化输出与 FunctionContract/角色绑定/前后状态不闭合”，不是 LLM 没有产出文本。硬校验采用合取门槛，任一合同错误或账本错误都会使单份 Outline 失败；3 次重复全部通过才算一个完整重复组，所以 0/9 不代表没有生成重复结果，而是没有一个 Seed 的 3 次结果全部过硬门槛。当前还确认选中的 Published Pattern 本身存在关系 Contract 未充分声明角色双方的结构缺口，不能把失败全部归咎于生成模型。

## 206. 关系连续性失败采用三处最小根修复（2026-09-04）

用户要求给出解决思路，并明确使用 Ponytail 收敛复杂度。当前不增加 Agent、数据库表或第二套关系系统，只处理三个根因：第一，FunctionContract 中凡声明 `RELATIONSHIP_STATUS` 的 effect 必须覆盖两个已有标准角色槽位，关系语义 Function 缺少第二方时应在新 Snapshot 中修正；第二，Mechanism 生成后立刻复用现有关系账本校验，带具体错误反馈最多重试一次，仍失败则在 Scaffold/Realize 前终止，避免继续消耗 LLM；第三，关系 `before` 不再由 LLM自由复述，而由 Seed 初始边、Contract 的 before 和前一步 after 确定性继承，LLM只负责 after 与 evidence。

现有冻结 Snapshot 不原地修改；合同生成/发布门禁修正后发布新 Snapshot 并重跑 Pattern，再复用同一批 27 个案例验证。当前“重复通过率”只是硬通过率的分组重复，和“硬校验 27/27”基本重复；若后续需要证明重复语义稳定性，应另行比较固定 Seed 三次输出的规范化目标、立场和关系终态，而不是继续扩大样本掩盖根因。

## 207. 不做全局重构，只收拢关系账本的真实重复与索引错误（2026-09-04）

用户要求用 Ponytail 判断是否需要重构。代码和真实评测产物确认无需重构 Snapshot、StoryProfile、KnowledgeBase、Outline 图或新增关系系统；但 `build_contract_ledger()` 当前按 `function_name` 建立 Mechanism 映射，同一 Pattern 重复 Function 时后一次会覆盖前一次。真实 Pattern `PAT_5507fe7dc2822593` 的第一段 `RELATIONSHIP_FORMATION(P1→P2)` 已被错误解析为第四段 `P3→P1`，必须改为只按唯一 `segment_index` 寻址并增加一个重复 Function 回归测试。

另一个必要的局部收拢是删除评测脚本对人物、绑定、关系效果等核心规则的重复实现：连续 `before/after` 检查应进入生产 `Contracts/ledger.py`，评测直接调用同一实现，仅保留 Snapshot 案例存在性等评测专属条件。除此之外不抽象通用重试框架、不拆新服务、不整理无关文件；现有 31 项相关测试全部通过，说明该真实重复 Function 错误目前缺少测试覆盖。

## 208. FunctionContract 与 Mechanism 的关系边界修复后，关系账本先达到稳定门禁（2026-09-04）

本轮没有把关系变化权限交给 Mechanism 的自然语言判断。Contract 的关系 effect 必须是两个不同标准角色槽位组成的二元边；Mechanism 只能绑定该 effect 的同一对人物，旧 Snapshot 中的单角色关系 effect 在运行时按“无关系授权”处理。这样区分了“Function 名称看起来像关系变化”和“Contract 实际授权关系边”两件事。

关系 `before` 也不再由 LLM 自由复述：第一条从 seed 的有向初始关系或 Contract before 取得，后续同一方向/维度继承前一条 after；Mechanism 只提供 after 与 evidence，账本继续检查未知人物、绑定、精确角色对、双方人物状态和证据。真实模型第一次输出若越界，最多获得一次确定性错误反馈。

使用上一轮同一冻结 Snapshot 与 27 个真实复评案例，关系变化从 139 条降到 39 条，且 39 条全部落在 `RELATIONSHIP_FORMATION`/`COMMUNITY_FORMATION` 的有效二元 effect 上；关系账本从 `0/27` 提升为 `27/27`。但 Validator 仍只通过 `12/27`，三次重复只有 `1/9` 组全部通过，人物目标/立场抽查 `12/14`，所以本轮结论仅是“关系变化边界与账本连续性修复有效”，不是“整体 Outline 已稳定”。

冻结 Snapshot 中仍有 `CONFRONT_OPPOSITION` 与 `SOCIAL_BOND_DISRUPTION` 两个历史单角色关系 effect；本轮没有偷偷修库，而是保守不授权。后续若需要正式数据本身通过新 Contract schema，必须以新不可变 Snapshot 重建/发布这些合同，再重新生成 Pattern；不能把兼容读取的复评结果当作已完成的数据修复。

## 209. 先校准 Outline 评测口径，再扩大真实样本（2026-09-04）

用户要求按前述方案落地。27 份复评显示，实际 `outline.ending` 已由输出 schema 强制存在，但 Validator 把可选的 Pattern `ending_spec=null` 误读为没有结局；另有一份人物审核的所有明细项均为 true、汇总却为 false。由此明确：LLM 汇总值不能覆盖确定性字段检查，评测必须拆分 structural、semantic、overall 三层，并由代码从人物明细计算审核通过值。

当前 3 个被测 Published Pattern 都没有有证据的 `ending_spec`。这不表示 Pattern 无效，而表示它们是局部结构证据，不能直接用于证明完整 Outline 的结局稳定性。完整稳定性评测应增加“有证据 ending_spec”的资格门槛；不能手工补写结局，应该继续 Evolve/Pattern 直到形成合格 Pattern。

本轮下游最小补强是让 SeedCharacter 显式携带初始立场，并把 Contract 关系 effect 的 before/after 上限传给 Mechanism；继续复用已有关系账本和 occurrence_index，不新增 Agent、数据库表或关系等级系统。下一步应先对现有 27 份产物只重跑 Validator，确认污染后的失败分布，再用合格 Pattern 重新生成 27 份。

## 210. 结局失败先收拢到 Validator 与一次性 Realize 回边（2026-09-05）

- 独立评审将剩余失败具体化为结局身份混淆、前序未支持的新真相/解决方案、`final_ledger` 与 ending 矛盾，以及低信任状态被写成互信/和解/稳定联盟。由此确认继续堆 Prompt 不够，但也不需要新增 Agent 或数据层。
- 结论：保留角色绑定/账本，集中修 Mechanism、Ending、Validator，不增加新层。当前代码只把高置信的未知人物/身份合并/关系状态越界收拢到现有 Validator 结果；因果充分性、证据是否真实支撑结局、义务是否包含可观察动作及后果，仍保留给语义 Validator。
- 采用一次性 `realize_retry_count` 条件回边，而非循环修复：结构合同或规则失败不重写，语义失败最多依据 `validation.issues` 重写一次，第二次仍失败保留诊断。这是第一版安全阀，不宣称替代独立语义评审。

## 211. 5 篇增量没有产生非空 ending_spec（2026-09-05）

- 用户选择先添加 5 篇新故事，完整执行一次增量 `Evolve → Pattern`，用真实数据判断是否需要区分“局部 Pattern”和“完整故事 Pattern”。这次 Evolve 与 Pattern 均成功，子 Snapshot 新增 5 个故事并发布 6 个 Published Pattern。
- 结果是 Published Pattern 的非空 `ending_spec` 仍为 `0/6`，本轮新增的 3 个 Published Pattern 也全部为空。由此暂不引入 Pattern 类型拆分、不手工补写 ending_spec，也不把 ending_spec 变成当前发布硬门槛；当前证据只说明结局规范还没有从这 5 篇样本中自然形成。
- 这次运行还确认了一个真实迁移边界：父 Snapshot 的历史非法 Contract 不能直接通过严格 `load_function_contracts()` 读取。增量 Evolve 需要显式读取旧合同、在子 Snapshot 规范化，再由新 Snapshot 严格校验；这保持了不可变父数据和新数据门禁，同时避免为了兼容旧数据放宽运行时关系授权。

## 212. 结局继续复用现有生成链（2026-09-05）

- 用户决定暂不扩展完整故事 Pattern 类型；继续保留证据态 `ending_spec` 与生成态 `ending_target` 的边界，并在现有 Seed → Realize → Validator 链内补强结局。无 Pattern `ending_spec` 时，`ending_target.must_show` 直接复用已经要求包含“解决动作 → 冲突结果 → 稳定终态”的 `seed.ending_direction`，不新增字段、Agent、数据库或回写路径。

## 213. 撤回重复的 seed must_show 映射（2026-09-06）

- 用户指出将 `seed.ending_direction` 同时写入 `ending_target.must_show` 和 `final_state` 会造成重复。确认现有 `outline.ending.resolution_actions` 已承担具体解决动作，故撤回该映射，不新增结局字段或解析规则。

## 214. Seed 结局方向约束的真实 smoke 结果（2026-09-06）

- 按当前最小方案，只要求 Seed 的单一 `ending_direction` 明确写出“可观察解决动作 → 直接冲突结果 → 稳定终态”；`ending_target.must_show` 继续为空，具体动作由已有 `outline.ending.resolution_actions` 生成。
- 4 份临时副本真实生成结果为 `outline.ending=4/4`、Validator `3/4` 通过。唯一失败来自结局使用了前文未建立的记忆、证据或义务，说明当前瓶颈是既有结局因果闭合，不是缺少 `must_show` 字段；暂不增加新层或新字段。

## 215. 结局完整性必须通过正文消费验证（2026-09-06）

- 用户明确指出：要用生成出的 Outline 验证是否真的有完整结局，不能只看 Outline JSON 的 ending 字段或 Validator 汇总值。由此把验收链收敛为 `Outline → Story_Agent → 正文最后场景 → 独立 LLM 质量诊断`。
- 本轮 5 份 Outline 中，1 份已被 Outline Validator 阻断，4 份进入正文尝试；其中 1 份虽 Validator 通过，却因场景计划引用 seed 未定义人物而在正文前置阶段失败，说明 Outline Validator 与 Story Agent 消费合同仍有真实缺口。
- 成功生成的 3 份正文都实际完成结局动作、冲突后果和稳定终态；独立质量诊断的 `ending_closure` 均为 `5/5`。古风仙侠的冲突解决为 `4/5`，指出 P3 和解转折稍突兀，说明“完整闭合”和“转折自然”仍需分开记录。
- 因此当前只能说结局生成已有正面证据，不能说整批 Outline 或生成稳定性已通过。先处理未定义人物引用这一已复现的消费问题，再决定是否需要进一步调整 Prompt。

## 216. 场景人物必须是 seed 的已定义角色（2026-09-06）

- 用户要求处理真实正文链复现的“场景计划引用 seed 未定义人物”问题。根因不是正文写作，而是 `SCENE_PLAN_PROMPT` 只禁止新增“核心人物”，却没有限制 `SceneDraft.characters` 的 ID 集合；模型因此输出了“P3 的手下”“村长”等临时角色。
- 最小修复是沿用现有 `_scene_plan_issues()` 硬校验，同时把 seed 的 `allowed_character_ids` 显式传入场景计划 Prompt，并禁止自然语言/临时角色进入 `characters`。对该确定性错误最多重试一次，避免静默删项或猜测角色映射；非核心人物仍可在 beats/setting 中被描述。
- 离线回归 `51 passed`。针对原失败 Outline 的真实 Story_Agent 重跑最终成功：4 个场景的角色列表只包含 `P1/P2/P3`，正文 `5060` 字符，独立质量诊断 `ending_closure=5/5`、`conflict_resolution=5/5`，无诊断问题。第一次重跑出现的是场景段对齐波动，不属于人物边界修复，未扩展为新的通用重试层。

## 217. 结局证据必须先进入 Pattern 输入，再判断是否值得扩 schema（2026-09-06）

- 用户要求按“接通既有 Profile → 小规模隔离 Pattern → 信息不足才扩 Profile → 正式重建”的顺序执行。验证显示，现有 `core_conflict`/`ending_state` 接入后确实让隔离 Pattern 产生了 `3/10` 个非空 `ending_spec`，但只有 `15/101` 条 motif evidence 触达故事尾部，且非尾部证据仍会混入摘要；不能把这一步误判为结局归纳已经可靠。
- 最小缺口不是新的 Function，也不是第二套 StoryEndingProfile，而是现有 StoryProfile 的三个字段：可观察解决动作、结局证据句子下标、`resolved/partial/open` 收束状态。`ending_spec` 暂不引入 obligation 字段，避免提前建立第二套义务系统。
- 3 篇真实故事的临时 Evolve 成功发布带新字段的不可变 Snapshot，但 Pattern 没有候选 cluster 达到发布门槛（`published_patterns=0`）。因此当前结论是“证据链已接通、样本不足以证明 Pattern 结局语义”，不是“需要继续盲跑全量 92 篇”；正式全量重建应等待 Observer 的既有越界失败先被单独处理或可控重试。

## 218. 先限制 Observer 越界，再完成同 namespace 正式重建（2026-09-06）

- 用户要求把 Observer 的证据下标越界作为前置边界处理，然后正式重提取 92 篇、复用 Function ID、重建 ObservationVersion/Occurrence、发布不可变 Snapshot，再重建 motif/Pattern；明确不重建 Function 本体，也不新增第二套结局或 obligation 系统。
- 首次 92 篇正式尝试暴露了 freeze 分支的真实缺陷：它清空了 pending MATCH/EXTEND，却没有把这些证据应用到现有 Function，导致最终评估支持数为零而不发布 Snapshot。修正为“冻结 Function 维护、仍应用 pending evidence”后，第二次 Run `FR_cf8b4b842ee44940` 成功发布新 Snapshot。
- 新 Snapshot 保持 14 个 Function 的稳定 ID/本体，生成 92 Profile 和 741 Occurrence；Pattern 成功发布 7 个 Pattern。由于全批没有至少两个跨故事证据同时满足确定性尾部触达、resolved、resolution actions 和 evidence indices，最终 `ending_spec=0/7`。这是证据不足的可审计结果，不以 LLM 猜测或人工补写填空。

## 219. 暂停 Pattern 结局归纳而不重建历史数据（2026-09-07）

- 用户确认当前最小行为是让 Pattern 停止生产 `ending_spec`，而不是继续补强结局证据链；故事结局仍由 Seed → Outline `ending` → Validator 负责。
- 因此删除三个结局证据字段在 Observer/Pattern 中的主动生产与传播，保留 `StoryProfile.core_conflict`/`ending_state`、`ending_spec` 读取兼容和下游 seed 回退；历史 Snapshot 中已有字段只在模型边界被忽略，不做数据库或不可变 Snapshot 重写。
- 该决策把“Pattern 无结局规范”和“故事没有结局”明确分开：新摘要固定 `ending_spec=null`，Outline 仍必须输出完整 `ending`。验证只覆盖固定摘要、seed 回退、Outline 结局、全量离线回归和当前 Snapshot/SQLite 只读完整性。

## 220. 结构审计应先处理持久边界，再做删除（2026-09-07）

- 用户要求同时检查结构冗余、代码冗余、多余测试和数据流一致性。审计结果显示，当前 SQLite/Snapshot/Pattern 的引用完整性通过，但“完整性通过”不等于所有持久工作态一致：Registry 保留的是父 Snapshot 的 14 个 Function payload，而 canonical Knowledge DB 已发布更新后的 14 个 payload。
- 这暴露出 Registry 作为持久 mutable workspace 的生命周期问题：Evolve 开始时会从父 Snapshot 重置，失败路径可能留下非 canonical 的 idle 状态。下一步若要改，应优先选择 run-scoped 临时 Registry，或在成功/失败边界明确同步与恢复；不应通过删除 Registry 或绕过 Snapshot 来掩盖漂移。
- 同一类问题出现在 ObservationBank：代码默认路径与 README 约定不同，现有嵌套 Chroma 还是空 collection/孤立物理目录，而 Evolve 已通过 Knowledge DB view 走另一条数据路径。应先决定保留 Bank 还是收敛到 Knowledge DB，再删除或迁移生成物；不能在未确定 canonical store 前清理 tracked Chroma 文件。
- 三套编排入口（Coordinator、StoryCLI、Pipeline）属于结构重复风险，但不是已证明的死代码；其差异在子进程协议、重试、Pattern 调用和 CLI 合同上，暂时保留。真正可删的代码只收敛到无调用的 `ScenePlanItem/ScenePlan` 与一个 unused import；没有找到可证明重复的 pytest 测试。

## 221. 先收敛持久边界，再做小样本重跑（2026-09-07）

- 用户要求优先清空重跑或保持最简洁，并明确少量验证即可。最终选择不清空正式库：Bank 默认路径改到 `Code/data/bank`，Evolve 在正常结束时把持久 Registry 对齐到发布 Snapshot，失败时恢复父 Snapshot；正式数据只用临时副本验证。
- 一篇真实 Evolve 在临时副本中成功发布子 Snapshot，保留 14 个 Function ID；SQLite 完整性通过，正式库未变化。该样本的 `MATCHED=358/739` 与 `UNCERTAIN=381` 说明流程门禁通过和语义分配质量必须分开报告。
- 清理范围收敛为两个无调用模型和一个 unused import；pytest 行为测试全部保留。后续若要清理旧嵌套 Bank 生成物，应先确认是否需要保留当前工作树中的 tracked Chroma，再进行可恢复迁移或删除。

## 222. 临时产物不再作为项目资产保留（2026-09-07）

- 用户明确不需要临时代码和数据，因此以正式数据流为边界清理：统一 SQLite 的 `knowledge/registry`、不可变 `ontology_snapshots`、正式 `checkpoints/evaluation` 和当前正式 run 产物保留；实验、smoke、retry、validation、eval、e2e、旧 rebuild 和重复 StoryCLI 输出移入 Trash。
- 旧嵌套 Bank 已确认是空 collection 加孤立物理目录，且 Evolve 使用 Knowledge DB 的 run-scoped view；清除它不会切断当前发布链，`Code/data/bank` 仅保留正式运行根目录。
- 一次性 harness 与缓存不属于正式代码；但 `clean_corpus.py` 是正式语料入口，`build_transition_index.py`/`story_pattern_loader.py` 仍被测试使用，所以继续保留。所有 pytest 测试按用户此前决定完整保留。

## 223. Serving 验证必须在 main 的真实运行上下文完成（2026-09-07）

- 用户要求把 Serving 修改同步到 main 后再验证。main 已有正式 StoryProfile 兼容字段和真实 `.env` 运行上下文；隔离 worktree 的失败分别来自缺少 `.env` 与旧 Profile schema，不代表 Serving 机制失败。
- 在 main 正式库完成真实链路：Evolve 默认读取旧 serving 并发布候选；提交后 serving 不变，默认 Planner 仍读旧版本；显式 promote 后 serving 和默认 Planner 一起切换到候选。这个顺序才是本次验证的有效证据。
- 验证过程只使用进程内 checkpointer 占位，没有修改仓库依赖；正式库新增的是受控验证 Run、候选 Snapshot 和一次明确 promote，所有结果以 SQLite 与 Planner 返回的 Snapshot ID 为准。

## 223. Serving 机制应在 main 的真实运行上下文验证（2026-09-07）

- 用户要求将 serving 相关修改同步到 main，再在 main 上执行正式库验证；原因是 main 已包含正式 StoryProfile 兼容字段和真实运行配置，隔离 worktree 的 Evolve 验证会被上下文差异阻断。
- 合并边界只包含 `serving_snapshots`、显式 promote、默认 serving 解析和对应测试；main 原有未提交改动不覆盖、不回滚。正式 Evolve 的候选提交、serving 保持和 promote 切换仍需以 main 实际运行结果为准。

## 224. 先建立 Generation Outcome，再决定是否需要 Supervisor（2026-09-07）

- 用户明确下一步先做生成经验反馈的最小闭环：真实 Outline 结果写入现有 SQLite，由有限规则影响后续 Pattern/Planner 选择；暂不做通用自动修复 Supervisor，也不让反馈层修改 Corpus。
- 本轮将反馈边界收敛为单表 `generation_outcomes` 和 Snapshot 内聚合分数。首次验证失败不惩罚，重复失败才降权；通过或重写成功保留/提高优先级；没有反馈的 Pattern 使用原有排序。
- 正式 Outline 真实验证已证明 outcome 写入、候选排序读取和知识边界隔离成立。当前 Pattern 仍有既有单次消费约束，因此反馈只影响尚未消费的候选，不绕过 `pattern_usage` 重新启用旧 Pattern。

## 225. Serving 就绪与 Pattern 消费边界必须同时闭合（2026-09-07）

- 用户指出候选 Snapshot 已被 promote，但该 Snapshot 没有成功 Pattern Run、Published Pattern 或本批 Outcome；因此 serving 指针不能只验证 Snapshot 存在，还必须验证下游可读的 Pattern 产物已经完成。
- 用户进一步明确 Pattern 的“一次性使用”只应是同一批次内的去重规则。跨批次复用由 `generation_outcomes` 反馈排序，`pattern_usage` 只记录审计；保留全局 `pattern_id` 主键会让审计表继续携带错误的全局消费约束，故迁移为自增审计行。

## 226. 真实小批次确认反馈确实跨批次生效（2026-09-07）

- 用户要求在当前 serving 上跑 `3～5` 份真实 Outline，并自然积累三类 Outcome；本次选定 `count=5`，不注入状态、不绕过 Planner。实际 6 次尝试得到 `accepted=3`、`rewritten=2`、`rejected=1`，其中 5 份有效 Outline 达到目标。
- 批次前后排序发生了可复现的结构变化：无反馈的 `PAT_7ef...` 从第 2 降到第 6，成功/重写的 `PAT_98...`、`PAT_dd...`、`PAT_eed...`、`PAT_fd...` 分别前移；已有正反馈的 `PAT_7d...` 因再次 accepted 从 `+1` 变为 `+2`。
- 这次运行同时证明两个边界：`pattern_usage` 允许同一 Pattern 在不同批次再次绑定新的 Outline，`generation_outcomes` 才是跨批次排序信号；Outcome 的流程状态已经闭环，但 accepted/rewritten 仍只代表当前验证链结果，不替代语义质量评估。

## 227. Outline Outcome 到正文的两篇下游验证通过（2026-09-07）

- 用户要求只选一篇 accepted 和一篇 rewritten Outline 进入 Story Agent，不改数据库；本次按数据库 Outcome 精确选择 `OUT_7aa06a1bbd727b8e` 与 `OUT_1f144f51ca114dca`，没有把 Manifest 的批次 `accepted` 标签误当作 rewritten 判定。
- 两篇正文都完成了既定场景结构和可观察结局动作，末场均承担结局，且输出通过当前 Story Agent 的结构合同。rewritten 只表示 Outline 生成阶段发生过一次重写，本次没有转化为下游消费失败。
- 因没有发现重复且现有规则无法处理的具体失败，当前停止继续增加 Story 反馈表、Supervisor 或额外规则；后续只有出现明确下游失败样本时才针对该失败补规则。

## 228. 真实闭环后停止结构扩建，转入正常使用（2026-09-07）

- 用户确认当前最合适的下一步不是继续增加架构，而是让正常使用自然积累 Outcome。现有证据已经覆盖 Pattern 排序、Outline Outcome 和 Story 正文消费/结局闭合。
- 后续继续工作的门槛限定为真实触发：同一 `failure_type` 重复出现；Outline 通过但 Story 连续消费失败；规则无法在重试/换 Pattern/停止之间作出判断；或多个合格候选需要择优。
- 这意味着当前 accepted/rewritten/rejected 只继续作为运行反馈留痕，不提前扩展为 Supervisor、Best-of-N 或新的持久化层；没有触发条件就保持实现不动。

## 229. 三题材生产批次暴露具体 semantic 重复触发（2026-09-07）

- 用户要求用当前 serving 做三题材最小生产批次，并只观察真实重复问题。本次各题材生成 3 份有效 Outline，共 9 份；古风仙侠为达到 3 份有效 Outline 实际尝试 5 次。
- 两个不同 Pattern 在古风仙侠中连续出现同一 `failure_type=semantic` 和同一关系状态越界原因；这满足“同一 failure_type 多次出现”的真实触发条件。由于两个 Pattern 后续都能恢复成功，尚未满足“某个 Pattern 连续失败”。
- 9 份有效 Outline 全部成功进入 Story Agent 并完成末场闭合，因此没有出现“Outline 通过但 Story 连续消费失败”。中间结构化重试均被现有机制吸收，不能把中间重试直接升级成 Supervisor 需求。
- 9 篇中仅发现一个孤立的正文末尾 `R` 噪声，没有重复到足以支持新规则；当前最小后续应是针对关系状态 semantic 门禁做具体审计，而不是扩建反馈层、评分层或 Supervisor。

## 230. 关系门禁先修同一分句否定，不扩建人物对上限（2026-09-07）

- 用户要求把两个真实重复 semantic 误判收敛到 `_has_unnegated_marker` 的同一分句否定识别：`并不代表彻底的和解或长久的联盟` 与 `未涉及婚恋等永久承诺` 都是否定表达，不应被当作强关系结局。
- 修复后两个正式库存档样本的确定性关系检查均无问题，说明当前证据只需要修正否定作用域；没有进入“按每对人物最终关系上限”这一更大的语义判断。
- 这次保持第三个 broader semantic Outcome 在范围外；后续只有出现否定修复后仍无法解释的具体关系样本，才重新评估是否需要更细的关系上限规则。

## 231. 固定 9 题 benchmark 未证明完整系统收益，停止增量（2026-09-07）

- 用户要求先从三题材既有生产批次固定 9 题，再做 Direct LLM 和盲化比较。核对发现原批次 9 个 Outline 的 `user_request` 全部为空；为保持输入真实性，benchmark 固定为 genre-only，并把这一限制写入 manifest，不事后把系统生成的冲突设定当成用户要求。
- Direct LLM 9 个逻辑基线中 8 个结构化成功、1 个因角色字段缺失失败。该失败属于流程/格式结果，不能直接当作语义质量结论；基线没有读 Function、Pattern、motif、Instance Case、Outline、正文或 Knowledge DB，正式 DB 前后哈希一致。
- 盲化过程中先发现人物 ID 未完全脱敏，后发现总体胜负聚合把 `A/B` 与 `full/direct` 混比；两处均在最终采用前修正。修正版 8 对中 A/B 各半，最终总体 `full=4、direct=4、tie=0`；full 在结构和人物动机各低 `0.375`，因果与冲突/结局持平，模板化/雷同低 `0.75`。
- 结论是“当前自动评审没有证明完整系统有明确、可解释的语义收益”，不是证明 Direct LLM 普遍更好，也不是证明完整系统失败。按门槛不进入增量 Evolve → Pattern，不改变 serving；当前缺口是有效创作要求样本和人工多人盲评，不能用一次小样本自动评审结果扩建 Supervisor 或新的质量层。

## 232. 先证明副本机械闭环，再讨论正式自动发布（2026-09-07）

- 用户把“全程自动化”与“优于 Direct LLM 的语义质量”明确拆开；因此新增的是薄控制入口，不新增 Supervisor、质量评分层或数据库。
- 真实副本运行证明：新故事能自动完成 Evolve → Pattern → 候选门禁 → promote → 默认 serving Outline → Story → Outcome；正式库前后 SHA-256 相同，旧 serving/Outcome/Pattern Usage 不变。候选可服务不等于候选质量更好。
- 实现中保留一个必要的安全边界：promote 后下游失败时回滚副本 serving；正式生产仍应把确定性检查后的候选标为 READY_TO_PROMOTE，人工确认最后一次 promote。
- 本次正文导出成功但 `length_ok=false`，说明流程自动化验收和正文语义/长度质量仍需分开报告；不能为了让“端到端成功”好看而把长度标志静默升级为通过。

## 233. 78 个旧故事变化来自 Contract 重算，先做候选回归拒绝（2026-09-07）

- 用户指出：新增 1 篇故事却让 78 篇旧故事 changed、MATCHED 从 353 降到 205、Published Pattern 从 7 降到 1，说明“Pattern Run 成功 + 至少 1 个 Published Pattern”不是安全发布门禁。
- 追查父子正式副本数据后，14 个 Function 的本体字段没有变化；副本 Pipeline 使用的临时 `snapshot_root` 没有父 Snapshot 目录，Evolve 的最终 `build_function_contracts()` 因而没有继承父 Contract，重新生成了 14 个 Contract。候选 Contract 的 role slot/precondition/effect 改变，`align_occurrences()` 按最终 supporting obs 和 Contract 重算旧 Observation，造成 218 条旧 Occurrence 状态变化，最终形成 78 个旧序列变化。这是当前退化的具体机制，不把它误判为新增故事本身改写 Function 本体。
- 因此本轮只把安全边界放在 Release Pipeline：smoke 使用显式 candidate Snapshot，父子指标检查后最后才 promote；旧故事变化超过约 10%、coverage 低于父值 90%、Published Pattern 低于父值 50%，或 Story `length_ok=false`，自动返回 `REJECTED_CANDIDATE`，Serving 不变。流程异常返回 `FAILED`，全部通过才返回 `PROMOTED`。
- 暂不修 Contract 生成器、不新增质量评分、Supervisor、自动修复或数据库；先用这个门禁继续积累明确的拒绝样本，再决定是否局部修复 Contract 生命周期。

## 234. 父 Snapshot 缺失是 Release Pipeline 的确定性输入缺陷（2026-09-07）

- 用户指出：临时 `snapshot_root` 每次都是空目录，因此父 Snapshot Contract 缺失会稳定复现；如果不处理，新增回归门禁后自动发布会变成稳定自动拒绝。
- 最小修复不是改 Evolve Contract 生命周期，而是在 Release Pipeline 准备阶段读取正式当前 serving Snapshot，先 `validate_snapshot()`，再复制完整父目录到副本 `snapshot_root`，并校验复制结果。这样 Evolve 能读取与正式运行一致的父 Contract 和 manifest。
- 现有回归门禁、`REJECTED_CANDIDATE` 和最后 promote 保持不变；本轮只修输入准备边界，不把父 Snapshot 复制失败误判为候选质量拒绝。

## 235. 父 Snapshot 复制修复通过真实全链路验证（2026-09-07）

- 第一轮修复后运行虽在 Pattern 外部连接错误处失败，但候选数据已显示 Function Contract 变化 `0`、旧故事 changed `0`；说明父目录复制已经切断了之前的 Contract 重算根因。
- 第二轮完整副本运行最终 `PROMOTED`：旧故事 changed `0`，coverage `0.4764 → 0.4727`，Published Pattern `7 → 6`，Story `length_ok=true`，Outline、Outcome、副本完整性和最后 promote 均通过。
- 因此当前 Release Pipeline 的结论是：父 Contract 复制、保守父子回归门禁和最后 promote 顺序已经同时成立；正式库仍未被副本验证改写。后续不把这次 `PROMOTED` 解读为候选语义质量优于 Direct LLM。

## 236. Pattern Connection error 只重试 Pattern，不重跑 Evolve（2026-09-07）

- 用户要求把真实运行中的 `Connection error` 归类为暂时错误，并把 Release Pipeline 的 Coordinator 重试从 `0` 调整为 `1`。
- 复用 Coordinator 已有的 `retryable` 路由，不新增通用异常层；测试确认第一次 Pattern 连接失败、第二次成功时，Evolve 只运行一次，Pattern 才执行第二次。
- 现有新增测试和 helper 均仍对应正式备份、父 Snapshot、回滚或候选门禁边界，没有找到可安全删除的孤立测试；不为“清理”删除这些保护性覆盖。

## 237. 先做单篇真实创作试用，不以全量验证替代收益判断（2026-09-07）

- 用户将评价责任明确交给 Codex：当前 Serving 生成后由 Codex 直接阅读并评价，再写入 `generation_outcomes`；优先少量测试，尽量不全量运行。
- 8 次试用得到 7 篇正文和 1 个被关系状态门禁阻断的 Outline。Codex 评价为 `accepted=5、rewrite=2、rejected=1`；两个 rewrite 原因分别是结局便利化和“寻药”主线偏移，不是同类重复问题。
- 因此不做局部修复、不扩充 5 篇、不 promote；Full 稳定优于 Direct LLM 的条件仍未满足，也不新增质量架构。

## 238. Story 正文只需要一次有边界的生成级修复（2026-09-07）

- 用户把自修复范围限定为生成级正文质量闭环，而不是通用 Supervisor：因此复用现有 LLM structured output、StoryState 和 `generation_outcomes`，只加一个 Validator 节点和一次条件回边。
- Validator 的语义检查覆盖用户主线、Function/Outline 因果、人物身份与动机、结局兑现、无依据临时方案；长度由确定性中文字符计数覆盖。重写只接收问题并固定上游结构，第二次失败不再尝试。
- 首次问题、修复发生、复验和最终 accepted/rewritten/rejected 都进入现有 Outcome payload；正文 Outcome 保留来源 Pattern 但不填 `pattern_id` 关系列，避免被现有 Pattern 反馈聚合重复计数。拒绝结果仍导出正文供人工处理，不把失败升级为 Pattern、Function 或 Serving 的修改。

## 239. 语义判断归 Validator，门禁不理解故事（2026-09-07）

- 用户指出：自修复的主要判断和修复应由 LLM 完成；门禁只限制次数并停止错误输出，不应借助状态词表或一组确定性故事规则替代 Validator。
- 因此只在 `StoryValidation` 增加 `repairable`，并要求 Validator 先检查固定 Outline、Function constraints、scene plan 和结局目标是否自相矛盾。固定输入矛盾返回 `repairable=false`；固定输入一致且正文可定向修复才返回 `repairable=true`。
- 代码删除六个语义字段到 `overall_ok` 的确定性聚合，保留 Schema、长度、人物/scene ID 和一次修复上限。若 Prompt 仍漏判，下一步优先考虑更强模型，不先扩张规则系统。

## 240. 一次真实三样本 smoke 没有自然覆盖 rewritten 路径（2026-09-07）

- 用户要求只做一次正式数据库副本上的真实 LLM 小批次。实际普通样本被 Validator 判为 `repairable=false` 后直接 rejected，寻药样本直接 accepted，固定输入互斥样本正确 rejected；三条都没有进入自动重写和复验。
- 这次结果不能证明自修复失败，也不能把回归测试替代为真实证据：它只证明当前模型在该批次没有产生可修复判断，且对固定输入矛盾完成了不可修复停止。若后续需要闭合 `rewritten`/二次失败证据，应先明确新的真实样本或模型选择，不在门禁层补规则。

## 241. repairable 必须只表达固定输入矛盾（2026-09-07）

- 用户定位到：LLM 把“正文缺少结局”误判为不可修复，根因是 Prompt 把 `repairable=false` 定义得过宽。最小修复是把它收窄为固定输入互相矛盾，正文层面的遗漏、偏离和因果问题全部可修复。
- 修正后的真实重跑已证明普通样本能够从 `repairable=true` 进入一次重写并在复验后 `rewritten`。寻药样本本次先命中 scene ID 硬边界，尚未进入 Validator；这不是继续扩展 Prompt 或门禁的理由，也不把该样本误记为语义判定成功。

## 242. Story scene ID 只需数量边界，正文顺序由 scene plan 接管（2026-09-07）

- 用户要求把 scene ID 对齐从“ID 集合必须先匹配”收窄为“数量一致即可按 plan 顺序覆盖 ID”；数量不一致仍是 Schema/结构错误。这样修复的是 LLM 输出元数据漂移，不引入故事语义规则。
- 修复后的寻药真实重跑成功进入 Validator 并 `accepted`。人工抽查确认正文实际完成寻药主线和固定结局，因此没有触发重写；之前的 scene ID 硬失败已被最小对齐逻辑消除。

## 243. 明确创作要求下仍未证明模板收益（2026-09-08）

- 为验证项目核心价值，固定 3 个古风仙侠具体请求，逐题比较当前 `Serving Pattern → Outline → Story` 与同模型 Direct LLM，并使用匿名 A/B 单模型评审。Full 三题均通过 Story Validator；但其中一题需场景规划重试，三题均未触发正文自修复。
- 评审结果为 Full 胜 1 题、Direct 胜 2 题；Full 的非模板化均分反而低于 Direct（`2.667` vs `3.333`），要求执行、因果动机和结局也没有形成稳定优势。该结果不能证明 Direct 普遍更好，只能说明当前模板链的核心收益尚未被小样本证明。
- 因此继续扩 Corpus 或增加 Supervisor/五层相似度/Creative Memory 都缺少决策依据。下一次若要继续验证，应优先做真正多人类盲评或增加同题配对数量；在此之前维持当前 Serving，正常积累 `generation_outcomes`，只对重复出现的问题做局部修复。

## 244. 一键生成入口必须保留用户创作要求（2026-09-08）

- 用户指出正式 Pipeline 入口把 `user_request` 固定为 `None`，导致明确创作要求无法进入 Outline 和 Story；这不是新增生成能力，而是已有两个 Agent 接口在控制层的断链。
- 最小修复是新增 Pipeline CLI `--request`，贯通状态和两次 Agent invoke，并把原始请求写入 `pipeline_manifest`；不新增数据库字段、质量层或兼容路径。

## 245. 真实 Pipeline 验证区分请求传递成功与 Story 模型失败（2026-09-08）

- 单次真实 LLM Pipeline 已证明 `--request` 能进入 Outline 并被写入副本 SQLite；Outline 校验通过后正常启动 Story，参数断链问题不再复现。
- 本次在 Story 正文结构化输出阶段失败，2 次重试分别得到非法 JSON 控制字符和空响应；因此没有 manifest、正文导出或 Story Outcome。该结果只说明本次模型输出未完成，不足以支持新增重试层或其他架构。

## 246. ending_spec 只能影响 Seed 创作，不能成为本轮硬结局（2026-09-08）

- 用户明确把结局优先级收敛为“用户要求 → Pattern/Function/Contract/真实参考 → LLM Seed → Outline/Story 具体结尾”。因此保留 `ending_spec` 的历史审计可见性，但移除它直接覆盖 `ending_target` 的路径；`ending_target.source=llm_seed`，`must_show` 继续为空，具体解决动作由现有 Outline ending 生成。
- 这不是放松结局约束：Seed 仍必须基于 core_conflict、Function chain、人物动机和前序边界创作“可观察解决动作 → 直接冲突结果 → 稳定终态”，Outline/Story Validator 仍检查前序证据、因果、稳定终态和临时方案，正文最多定向重写一次。
- 真实古风仙侠副本已出现完整闭环：`ending_spec=null`，Seed 生成水患疏导方向，Outline 与 Story 均按 `llm_seed` target 完成且 `ending_ok=true`。非空 `ending_spec` 的“不得覆盖 Seed”由离线端到端测试覆盖，不以本次 null 样本冒充非空生产证据。

## 247. 不用新的文学模板修复旧模板感（2026-09-08）

- 用户从《枯井新泉》提出：真相揭露像审讯笔录、后半段一路绿灯、古兽强钩子未兑现、主角始终正确；结合《渡渊》可归为“说得太明、收得太顺、主角太正”，根因位于 Seed/Narrative/Realize/Story 的创作偏好，而不是缺少更多 Validator 门禁。
- 最小修复采用条件性软原则，而不是给所有故事强制同一情节：只有人物成长/价值选择型冲突才优先安排盲点与错误选择；只有调查/旧案/秘密型故事才要求分散证据；强钩子进入核心因果；稳定终态允许系统余波。Validator 不评价含蓄程度或文学质量。
- 真实副本候选说明“人物改变”和“结构合同”必须区分：主角可以因事件放弃开场 goal，但不能在 Function 链只形成后又破坏关系时，于 ending 无证据恢复互信合作。前者是人物弧线，后者仍是结构越界；因此只纠正 Validator 对 goal 的误读，不取消现有关系上界。

## 248. Pattern 可以是局部的，但 Seed 不得制造无法清偿的完整故事规模（2026-09-08）

- 用户进一步指出《残玉照烽烟》的最大问题不是结尾文风，而是前半段提出战争、秘境、魔道、宗门和家族的“大阴谋”，后半段只解决玄诚旧案与个人追杀。该问题适用于整个系统：局部 Pattern/Function 链可以合理，但 Seed 把背景升级为核心冲突后，结局缺少同尺度能力。
- 只给 Validator 增加自然语言“尺度一致”提示不可靠：对原失败 Outline 的真实复验仍返回 `overall_ok=true`。因此将 `ending_requirements` 设为新 Seed 的显式必填输出，并复用已有 `ending_target.must_show`，让核心问题与结局后果从生成开始就逐项绑定。
- 该合同不要求宏大问题全部解决：战争或制度可以继续存在，但正文必须展示主角选择对该层面造成的可观察直接后果。若当前 Function 链承接不了，就应把宏大要素降为 `world_setting` 背景，而不是伪装成故事承诺。
- 新真实候选已证明合同生成和传递成立，但因另一项关系上界冲突被拒绝，尚未形成一篇最终 accepted 正文；不追加随机重跑，也不将“门禁正确拒绝”表述为文学质量已经提升。此前“Seed must_show 为空”的阶段决定由本轮显式 `ending_requirements → must_show` 取代。

## 249. 结局合同必须拥有独立的场景执行位置（2026-09-08）

- 用户追问真实样本为什么提前收束。追查发现问题不是 `ending_requirements` 没有生成，而是它只进入了 Outline 文本；Scene Plan 仍只按 Function 段生成场景，并把最后一个 Function 场景强行标记为结局。真实 S8 的 transition 明确是“为城破再见埋下伏笔”，却被当作已完成结局。
- 因此结局合同不能只是一组 Prompt 字段：必须在 Scene Plan 中有独立的 `ending` 场景组，位于所有 Function 场景之后；正文不得新增场景，但必须执行这组 Ending 场景。这样保留 Function 的结构约束，也保留 LLM 对具体结局行动的创作权。
- 为避免再次出现 Validator 只返回 `ending_ok=true` 的假通过，StoryValidation 增加 `ending_evidence`，要求每条 `must_show` 映射到独立 Ending scene_id 并提供正文证据。该校验只验证结局合同的执行位置和证据，不新增关键词规则或 Supervisor。

## 250. 真实 Ending 正文通过但暴露用户长度要求断链（2026-09-08）

- 用户要求用真实 LLM 生成一篇文章验证独立 Ending 修改。完整 Pipeline 的 Outline 成功，Story 首次请求超时；复用同一 Outline 单独运行 Story Agent 后导出《断臂辞》，`accepted`，3 条结局证据全部映射到独立 Ending `S5`。
- 正文 3489 个中文字符，而本次用户要求至少 3500；代码的 `_MIN_CHINESE_CHARS=3000` 使确定性门禁仍报告 `length_ok=true`。结论是 Ending 场景结构已在真实正文中生效，但“用户明确长度要求 → 确定性门禁”仍未贯通。
- 该问题应优先在请求解析/长度门禁的单一入口修复，不应靠 Validator 自由判断或继续增加文学规则；在修复前不能把本次结果表述为完全满足用户请求。

## 251. 中间 Schema 只保留跨节点必要事实（2026-09-08）

- 用户要求删除已确认的过度设计：`resolves_ending`、Story 侧未使用的 `story_profile`、LLM `length_ok`、`FunctionConstraintPlan.story` 结局副本，以及 SceneDevelopment 的文学调度字段。
- 处理原则是区分“结构合同”和“一次性写作建议”：`ending_requirements`、独立 Ending 场景和 `ending_evidence` 继续保留；结局副本不再重复生成；场景展开只保留节奏和需要展开的既定行动。
- 这样减少中间状态漂移和正文的作者控制痕迹，同时不改变 Function、Pattern、Serving Snapshot 或一次性 Story 修复边界。离线全仓验证通过后再决定是否进一步删除整个 `develop_scenes` 节点。
## 252. 结局证据不再承担第二套判定逻辑（2026-09-08）

真实样本显示，复合的 `ending_must_show` 被 LLM 拆成多个证据时，严格的一对一 `ending_evidence` 校验会把实际完成的结局误判为失败。结局证据保留为诊断输出；不再增加归一化、证据分组或额外评分，结局判定回到现有 Story Validator 与确定性结构/长度检查。

## 253. 正式三阶段 CLI 必须显式区分重置、候选和 serving（2026-09-08）

- 用户要求通过 CLI 依次执行批量 Bootstrap、批量 Evolve 和按用户要求生成 Story；入口收敛到三个独立命令，不把昂贵的 Bootstrap/Evolve 隐藏在每次 Story 生成中。
- 用户选择 Bootstrap 每次完整重置正式链路，但保留可恢复归档；因此 `--reset-formal` 成为 Bootstrap 的显式必填开关，归档 Knowledge DB、Registry、Bank、Snapshot 和 checkpoint，不自动删除历史生成报告。
- 用户选择 Bootstrap 成功后自动建立 serving，Evolve 仍只产出候选；Story 默认读 serving，候选必须通过显式 `--snapshot-id` 或人工 promote 使用。该边界避免 Evolve 成功被误认为语义质量已经通过。
- 用户选择 Story 只传要求并用关键词识别题材；明确复合题材短语优先，仍命中多个普通题材或没有题材时在 LLM 前报错，不增加题材识别 LLM 调用。

## 254. 公开 CLI 只暴露输入，不暴露版本控制细节（2026-09-08）

- 用户指出 namespace/Snapshot ID 是内部实现细节，公开入口应直接接受 Bootstrap 批量文本、Evolve 批量文本和用户要求。
- 因此新增单一 `StoryCLI run`，内部固定 namespace，自动把 Bootstrap 根 Snapshot 和 Evolve 候选传给下一阶段；不把候选自动 promote，保证本次生成可使用新知识但不改变正式 serving。
- 为兼顾开源用户和数据安全，完整重置仅由显式 `--reset-formal` 开启，默认保留正式历史。

## 255. Bootstrap 内含 Function 提取，公开 CLI 应按阶段独立执行（2026-09-08）

- 用户指出此前把流程写成 `Bootstrap → Pattern` 会掩盖 Bootstrap 内部的 Function 提取，而且一键 `run` 不符合实际的分阶段使用方式。
- 因此公开入口收敛为三个独立命令：`bootstrap` 完成 `Function → Pattern` 并建立 serving；`evolve` 基于 serving 完成增量 Function/Pattern，候选是否发布由无 ID 的 `--promote` 明确决定；`story generate` 默认消费 serving 生成 Outline 和 Story。
- 保留 `function ...` 等底层命令用于调试，公开教程不再要求用户接触 namespace 或 Snapshot ID。

## 257. 公开 Evolve 真实复用项目语料通过（2026-09-08）

- 用户要求直接选项目文本执行 Evolve。排除已登记的两篇后，选用 `04_末世科幻/1929371857_463723763.txt`，公开入口自动继承历史 serving namespace 并完成真实 Function/Pattern 增量。
- Run `FR_72e2015819d341e1` 产出候选 Snapshot `real_coordinator_rebuild_v5_20260904_20260908T121306266945Z_9289a8851c77`，9 个 Observation 中 7 条 MATCH/EXTEND、2 条 NOVEL；Function/Pattern 报告 PASS 但 diversity 失败，符合单篇 Evolve 的预期限制。
- 候选保持未发布，serving 指针未改变。该结果同时验证了简洁公开命令与历史正式 namespace 的连接；同一文本重复运行仍应受 StoryVersion 身份保护。

## 258. 正式主线只切 serving 指针，保留 Snapshot lineage（2026-09-08）

- 用户要求只保留一条主线并删除 CLI 副本。实际采用的边界是：将最新成功候选 promote 为唯一 serving，保留其父 Snapshot 和所有正式 SQLite lineage；旧版本不再 serving，但仍是候选的外键父节点。
- 删除 `data/story_cli/functions/` 下 5 个 `example_evolve_*` 运行副本，使用系统废纸篓保证可恢复；不直接删除 SQLite Snapshot 行或正式 Ontology Snapshot 目录。
- 最终核验为 `serving_snapshots=1`、Snapshot lineage 完整、候选正式目录存在；后续 Story 默认读取最新候选，Evolve 仍从该 serving 继续增量。

## 256. 公开 Evolve 应继承 serving 的 namespace（2026-09-08）

- 用户实际执行公开 Evolve 时暴露：正式 serving Snapshot 仍来自历史 namespace，而公开入口固定使用 `story_cli`，使无 namespace 的简洁命令无法复用已有正式库。
- 公开入口不应重新创建或猜测 namespace；Evolve 未显式指定时直接读取父 serving Snapshot manifest 并继承其 namespace。显式底层入口仍在 namespace 与父 Snapshot 不一致时拒绝执行。
- 修复后的真实运行进入 Function Evolve 后才发现输入故事已存在且人物画像不一致，Run 安全记为 FAIL、没有发布候选，原 serving 不变；这区分了 CLI 路由修复与故事身份边界。

## 259. Dynamic Planner 的价值必须在正文回收链上判断（2026-09-08）

- 用户要求把 Dynamic Planner/Beam Search 接入完整 Story 入口，并在固定 serving Snapshot 上对 3 个明确请求做正文→Observer→Matcher 回收；明确暂不新增 Best-of-N、Supervisor、独立 Instance Card 或 transition 表。
- 回收结果与人工阅读出现分离：两篇正文的因果结构和结局基本成立，但严格 LCS 保留率只有 `0.3333/0.7143`，顺序均不一致；Matcher 对全部观察返回 `MATCH`，没有 `UNCERTAIN`。因此当前不能把低回收率直接归因于 Story/Mechanism 丢结构，也不能把 Outline Validator 通过当作正文 Function 保留证明；优先定位 Observer/Matcher 的粗粒度观察或过度自信匹配边界。
- 第三题与一个替代题都在同一 `NarrativePlan.setup_payoffs[*].payoff=null` Schema 边界失败，现有 2 次重试未能恢复。暂不因两次就扩展兼容 Schema 或新增修复层；失败作为真实 Outline 阶段证据单独记录。
- 当前决策：不进入 Best-of-N，不修 Dynamic Planner，不新增架构；下一轮若继续，应先做可解释的 Observer/Matcher 对齐诊断，并保持“正文成立、人为结构回收失败”与“正文真的丢 Function”分开。

## 260. 第三篇失败先暴露的是接缝与 Contract 边界（2026-09-08）

- 第三篇悬疑请求先因 `scene_developments` 的模型场景 ID 标签与计划不一致而阻断；数量和顺序仍可确定时，按计划顺序归一化是现有正文场景规则的最小一致修复，不能把这类元数据漂移直接当成正文质量失败。
- 修复后同一请求只重跑一次，继续在 Outline/Mechanism 因 `CONFRONT_OPPOSITION` 的关系变化不匹配同一关系效果的 `P1/P3` 槽位而阻断。这个证据说明当前 Dynamic Planner/Mechanism 的候选关系边界仍未稳定，不能用两篇成功故事掩盖三篇样本尚未完成。
- 因此阶段决策更新为：不进入 Best-of-N；先修关系 Contract 边界并重新完成 3 篇样本，再判断低 LCS 是正文执行问题还是 Observer/Matcher 回收问题；不新增 Supervisor、Instance Card 或 transition 表。

## 261. 三篇正文成立但回收链仍不稳定（2026-09-08）

- 针对第三篇真实运行暴露的两个最小边界做修复：空的 `setup_payoffs` 未完成项在严格 Schema 前丢弃；Mechanism 关系账本失败时把当前允许的人物对带入既有修复提示。固定 serving Snapshot 后，三个原始创作要求均完成 Dynamic Planner → Outline → Story，三篇正文均 `accepted`。
- 正文人工阅读均能对应创作要求：水患故事通过勘察、协作和治理收束；雪山故事通过证据、风险和分别承担后果收束；疫城故事通过观察病情、资源交换、组织本地人和现实代价收束。因此不能把回收链低分直接等同于 Story 没有执行结构。
- 重新经过现有 Observer + Matcher 后，LCS 仅为 `0.5714 / 0.5000 / 0.2857`，顺序全部不一致。`fx_03` 的 10 条 `UNCERTAIN` 主要来自 Matcher 两次重试仍把 Function 名写进 `label` 的输出 Schema 失败，属于诊断管线失败；`fx_01` 的 2 条 `UNCERTAIN` 则是单条观察混合两个功能边界。
- 下一步只修 Matcher 现有输出合约/失败边界，再复跑相同三篇；确认回收结果后才决定是否修 Observer 边界。当前不修改 Dynamic Planner、Function 定义，不进入 Best-of-N，也不新增 Instance Card、transition 表或 Supervisor。

## 262. 合约错误修复后仍需区分 Function 边界与正文执行（2026-09-08）

- Matcher 的非法 `label=FunctionName` 已通过现有 Prompt/字段描述修复并验证。三篇正文复用回放均无最终 `matcher_errors`；这证明上一轮 `fx_03` 的批量 `UNCERTAIN` 主要是输出合约失败，不是正文语义本身。
- Observer 增加“一个 Observation 一个主导状态变化”的最小边界提示后，本次回放 LCS 提升到 `0.7143 / 0.7500 / 0.7143`，但顺序仍全部不一致，且 `COMMUNITY_FORMATION` 三篇都缺失、`RESOURCE_RELINQUISHMENT` 两篇缺失。不能把“保留率提高”表述为 Function 链已经保住。
- 当前证据不支持继续叠加 Prompt 规则，也不支持修改 Dynamic Planner 或 Story 执行。下一步应静态核对现有 Function 卡片的 definition、realization_patterns、hard_negatives、confusable_functions 是否覆盖这些具体实现；若确有输入缺口，只把已有字段接入 Matcher 当前卡片输入，仍不新增数据边界。
- 阶段决策：不进入 Best-of-N；先完成这一项现有卡片边界核对，再决定是否需要最小 Matcher 输入修复。

## 263. 现有边界卡片接入后仍不能驱动自动决策（2026-09-08）

- 用户要求执行最小下一步：复用现有 Function 卡片，把 `hard_negatives`、`confusable_functions` 传入 Matcher，不新增 Instance Card、transition 表、Supervisor 或评分层。
- 定向测试和全仓回归通过；同一 Snapshot、临时 DB、同三篇正文的真实 Observer + Matcher 回放无 Matcher 结构化错误，但 LCS 为 `0.5714 / 0.2500 / 0.4286`，顺序全部不一致，重复错配和系统性漏项仍在。Observer 重新抽取本身也出现输出波动。
- 因此恢复链目前只能作为诊断报告，不能作为 Best-of-N 排序分数、Pattern 自动反馈或自动闭环验证依据。下一步若继续，应先建立稳定的 Observer/Matcher Function 对齐证据；当前 Demo 可继续展示生成链路和实验性回收，不宣称可靠闭环。

## 265. 重新抽取不等于检查生成过程是否使用 Function（2026-09-09）

用户指出当前验证方向需要纠正：Story 生成后再次运行 Observer → Matcher 得到不同 Function 链，本质是一次新的、有损的结构抽取，不能用来证明正文生成时是否执行了目标 Function，也不能直接作为 Best-of-N、自动反馈或正文拒绝门禁。

因此删除 Matcher 目标链回收入口及其测试，改为复用现有 Story Validator：让 Validator 在已经同时看到 `function_chain`、`function_constraints`、`scene_plan` 和全文的情况下，逐 Function 输出正文行动与状态后果证据；代码只做数量、名称、场景归属、顺序和 `PASS/MISSING` 的确定性检查。三篇固定正文的 `7/7、8/8、7/7` 证据均通过，人工逐项核对也一致。这证明的是“这三篇正文的结构执行证据成立”，不是 Observer/Matcher 已经稳定，也不改变暂不实现 Best-of-N 的边界。

## 266. 最小文件数不能牺牲职责边界（2026-09-09）

用户追问为什么把校验代码堆在 `Story_Agent/app.py`。此前为了少新增一个文件，把纯 Function 执行校验放进了流程入口；这虽然减少了文件数，却让图编排和规则判断混在一起。最终只拆出一个 `Story_Agent/validation.py`，保留 `app.py` 的流程职责，不扩展架构、不改变行为。

## 267. Best-of-N 不重新抽取 Function，硬门禁由 Story Validator、软排序由一次 LLM 比较承担（2026-09-09）

用户明确纠正了 Best-of-N 的职责边界：候选不能在生成后再次运行 Observer → Matcher 来“证明”执行过 Function；那只是新的有损抽取。最终采用最小实现：复用 Dynamic Planner 已有 Beam 的两个不同候选，各自经过既有 Outline → Story → Story Validator；Validator 的用户要求、因果、人物、结局、临时解决方案和 Function 执行证据负责硬门禁，只有硬通过候选才交给一次 LLM 比较用户要求、因果连贯、结局兑现和正文质量。比较器不接收 Function 链、不输出数字分数、不新增表，结果写入现有 manifest/outcome payload。

唯一真实运行已完成两篇 `accepted` 正文并通过 `7/7`、`8/8` Function 执行证据，但比较提示漏写 `json` 导致 DeepSeek 400；缺陷已修复并经离线回归验证，按“不重跑制造成功”不再重做真实请求。因此本次只证明了候选生成、硬门禁和人工质量差异，不能宣称自动 winner 已经真实落库。

## 268. 修复后 Best-of-2 的 pair review、winner、manifest 与 outcome 均真实落地（2026-09-09）

第一次真实 smoke 暴露的比较 Prompt `json` 前置条件已修复。按用户要求只再执行一次真实请求：两个 Dynamic Beam 候选均完成 Story 并通过 Story Validator 的全部硬门禁，Function 执行证据分别为 `7/7`、`8/8`；唯一 pair review 成功返回 `winner=1`，选择理由集中在用户要求兑现、因果连贯和共同治理结尾，没有重新抽取 Function，也没有使用 Beam score 直接排序。`pipeline_manifest.json` 的 `selection`、winner 文件指针和 `selection_outcome_id` 均已写入，临时 SQLite 的 `generation_stage=best_of_2` outcome 也已落地；正式库 hash、serving 指针、计数和完整性均未变化。该结果验证了最小 Best-of-2 的流程和持久化闭环，但质量收益仍只由一个明确请求支持，不扩大为大样本结论。

## 269. Best-of-2 验证后应与 Pipeline 图编排分离（2026-09-09）

Best-of-2 最初暂放在 `Pipeline_Agent/app.py`，只为先用最小文件数验证候选生成、硬门禁、pair review 和持久化闭环。用户指出入口文件同时承担候选筛选、Validator 规则和正文比较后，职责已明显独立；在不改变行为的前提下，将这些逻辑移到 `Pipeline_Agent/best_of.py`，`app.py` 只保留图节点和导出编排。这样仍是最小实现，但不再把一次性验证代码当作 Pipeline 的固有职责。

## 270. Best-of-2 实验因成本退出运行路径（2026-09-09）

用户确认双候选正文生成与比较成本过高，要求恢复单候选默认流程。历史真实 Best-of-2 smoke 的候选、硬门禁、pair review、winner、manifest 和临时 outcome 仍保留在前文作为实验记录，但不再继续承担运行能力。

因此删除 `Pipeline_Agent/best_of.py`、`--best-of` CLI 参数、PipelineState 候选/选择字段、Pipeline/StoryCLI 双候选分支和专用测试；Dynamic Planner 的 Beam Search、top-1 Outline/Story Validator、Function execution evidence 和最多一次定向 rewrite 不变。后续若再次考虑多候选，必须先有明确质量收益足以覆盖真实生成成本的证据。

## 271. Dynamic Planner 只压缩 Beam Prompt 的原始角色关系块（2026-09-09）

用户明确限定成本优化顺序：只删除 Beam Prompt 中原始 `role_stats` 和 `relationship_cases`，保持 `BEAM_WIDTH=4`，用 3–5 个固定 Seed 只运行 Dynamic Planner，对照 token、候选、top-1、Contract/state/obligation、链多样性和关系型 Function。该边界不取消 Beam Search、Contract/状态/义务校验、成熟 motif 或真实 transition，也不引入缓存、Agent、Supervisor、数据库或 Best-of-N。

在当前 serving Snapshot 上用 3 个固定 Seed 完成真实 Planner-only 前后对照。空链 Prompt 为 `108,477 → 33,204` 字符；两个 raw 块合计 `75,219` 字符，基线 43 次调用至少重复发送 `3,234,417` 个该两块字符。真实 prompt token 为 `1,956,863 → 688,248`（`-64.8%`），总 token 为 `1,977,693 → 713,565`（`-63.9%`）；优化后虽然因模型路径调用 `53` 次而不是 `43` 次，成本仍显著下降。

质量信号不稳定：有效候选数 `4/4/2 → 1/4/4`，top-1 分数 `0.865417/0.834833/0.769000 → 0.771893/0.834833/0.959250`；Contract hard issue 两侧均为 `0`，聚合 state issue/state conflict/unresolved obligation 为 `64/40/62 → 57/38/63`。每个 Seed 的返回候选均包含关系型 Function，但候选数、链长度和多样性没有一致方向。因此只接受这处确定的成本收益，不把一次/Seed 的真实样本解释为质量回归或提升，不把 Beam width 从 4 降到 2。

## 272. Observation 身份不能用顺序编号补齐（2026-09-09）

用户明确要求：不得使用 `observation_order`、`obs_001` 或其他抽取顺序编号硬凑 Observation ID，否则会破坏当前基于稳定语义锚点的身份规则。后续遇到同一批重复 `obs_id` 时，只能对内容完全一致的记录去重；若同一 ID 对应内容不一致，必须报告身份冲突并阻断，不能通过追加序号生成新身份。

## 273. 用删除处理重复或无证据输出，不叠加约束（2026-09-09）

用户进一步明确：处理异常数据时用删除代替叠加约束。当前实现因此只删除同一批中后到的重复稳定 `obs_id`，不做内容冲突分支、不追加顺序后缀，也不修改 `observation_id()`；同时在 `ObservationItem` 解析前删除没有证据句子的 `relationship_delta`，保留现有有效关系项和既有身份规则。

按该边界重跑正式 Bootstrap 60 篇：根 Snapshot `story_cli_20260909T072949663195Z_c1b261029498` 已写入，60 个 story、511 个 Observation、36 个 Function 和 36 个 Contract，Snapshot 校验与 SQLite 完整性通过。Pattern 运行本身为 `SUCCESS`，但 8 个 cluster 全部为 candidate、没有 published Pattern，因此公开 Bootstrap 未能 promote serving，不能继续启动正式 Evolve；这属于 Pattern 发布条件未满足，不是数据库或 Observation 身份失败。

## 274. Pattern 门槛暂不动，先把固定回归暴露出的上游边界问题拆开看（2026-09-09）

用户明确要求暂时不改 Pattern 长度门槛，并把同一批 30 条 Observation 固定为回归样本；先处理 5 条多事件 Observation 拆分、6 条 Contract 槽位拦截和 2 条疑似召回遗漏，再用同一批 30 条重放。用户同时重申不能用 `observation_order`、`obs_001` 等顺序编号补 Observation 身份，也不能凭空补角色。

本轮证据把问题分成三层：top-10 中出现的 `ESCAPE_OR_RELEASE` 是 top-5 截断造成的真实召回遗漏；另一条目标 Function 未进 top-10，更像复合 Observation 未拆开而不是单纯 top-k；Contract 侧删除未被契约状态引用的角色槽位后，固定重放的槽位拦截明显下降。Observer 的二次拆分复核对 5 条样本仍有模型波动，因此只作为安全回退的候选改善，不能作为 Pattern 或生成质量的硬证据。

## 275. Contract 最小修复采用全局删除，不继续扩展其他边界（2026-09-09）

用户决定本轮只修改 Contract，Observer、top-k 和 Pattern 暂不继续。既然未被 preconditions/effects/obligation_effects 引用的角色槽位不是必需约束，就在共享 Contract 构建路径对所有 Function 统一删除，不维护已审计 Function 名白名单；当前正式 Snapshot 保持不可变，规则在后续子 Snapshot 构建时生效。

## 276. 先用定向 12 篇验证 Pattern 门槛，再判断完整 60 篇（2026-09-09）

用户提出的定向选择有效：10 篇原 Published Pattern 支持故事加 2 篇已知 NOVEL 故事，既覆盖旧 cluster 的跨故事假支持，也能同时观察 NOVEL 状态和 `story_type`。12 篇真实 Coordinator 链路完成后，`NOVEL→UNCERTAIN=0`，题材不再是 `uncategorized`，且 `published_patterns=0`；这不是要求 Pattern 必须为零，而是说明当前样本没有满足“同一 motif 跨两故事且长度至少 4”的可发布 anchor。

完整 60 篇在 Coordinator 的两次 1800 秒阶段窗口内均未完成 Evolve，最终没有 Snapshot，也没有进入 Pattern。这个结果只说明当前真实全量运行受 LLM 调用成本/阶段超时限制，不能反推三项修复在全量数据上失败；不能把超时副本的部分 StoryVersion 或旧的临时运行记录当作成功证据。后续若继续，应先单独处理可审计的运行时长/阶段超时边界，不借此扩大架构、修改 Pattern 门槛或提升正式数据。

## 277. 延长阶段窗口后暴露的是关系证据越界，而不是超时（2026-09-09）

用户要求从干净副本用更长运行时限重新验证完整 60 篇。新副本固定 Bootstrap 父 Snapshot，不传 top-k 覆盖，Coordinator 的 Evolve 阶段窗口设为 7200 秒。单次 Run `FR_4c77856882334204` 运行约 41 分钟，处理日志到第 50 篇入口，前 49 篇累计 465 条 Observation；因此上次 1800 秒截断的运行时问题已被区分出来。

本次在第 50 篇因 Observer 返回越界的 `relationship_deltas.evidence_sentence_indices` 触发现有句子范围校验，Run 以 `EVOLVE_RUN_FAILED` 结束，没有 Snapshot、没有 Pattern。失败副本 SQLite 完整性与外键检查仍通过，正式库未写入。这个边界不属于本轮三项修复；若要继续完整 60 篇，需先明确是否允许采用“删除没有有效句子证据的关系变化项”的最小防护，而不是默默重跑同一批输入制造成功。

## 278. 关系证据越界采用删除式最小防护（2026-09-10）

为完成完整 60 篇验证，采用最小 Observer 修复：在既有 `validate_event_roles` 前过滤越界关系证据索引；没有任何有效证据的 `relationship_delta` 直接删除。这个处理延续当前“删除无证据输出”的边界，不新增约束层、兼容字段、重试或数据库结构。

聚焦测试 `25 passed`，全仓 `402 passed, 1 skipped`。修复后的新 60 篇副本运行随后被用户主动中断，处理到 3/60 篇，没有 Snapshot 或 Pattern，不能宣称完整 Evolve 成功。

## 279. 完整 60 篇验证成功，但历史继承题材不回填（2026-09-10）

修复关系证据越界后，从干净副本固定 Bootstrap 父 Snapshot，使用长阶段窗口重新跑完整 60 篇。Evolve `FR_350dc918a3d4462a` PASS，Pattern `PR_3d1ed8a272013ba9` SUCCESS；最终没有 Published Pattern，319 个 cluster 全部保持 candidate。这与“核心 anchor 必须同时跨至少两故事且长度至少 4”的门槛一致，不需要为得到非零 Pattern 放宽条件。

本轮新增故事的 81 条 `label=NOVEL` 中，58 条没有最终 Function 支持并正确落为 OTHER；18 条被新 Function 支持后 MATCHED；5 条因 Contract 角色不完整而 UNCERTAIN。因而需要区分“无支持 NOVEL 的状态传递”与“后来被 Function 支持但契约失败”，后者不是本轮 label 丢失问题。

`story_type` 已正确进入新增故事的 motif evidence 和 category_counts；剩余 3 条 `uncategorized` 来自固定父 Snapshot 的历史继承记录。用户要求不迁移、不回写正式或父 Snapshot，因此当前不处理这 3 条。Snapshot、SQLite 完整性和 FK 均通过，正式 serving 数据未改变。

## 280. 零 Published Pattern 需要区分假支持修复与上游重复不足（2026-09-10）

用户质疑 60 篇故事最终没有 Published Pattern 是否合理。复查副本发现：324 个 motif 候选的 `story_support` 全部为 1；319 个 cluster 中 315 个只支持 1 个故事，只有 4 个 cluster 的故事并集为 2，但其中的成员 motif 仍分别只来自单个故事，因此没有任何 motif 同时满足 `story_support >= 2` 且 `length >= 4`。这正是本轮 anchor 门槛拦截的目标：cluster 的故事并集不能冒充完整核心链的跨故事支持。

因此零发布不是题材读取或 Snapshot 完整性失败，也不是“每篇文章没有结构”；它表示当前 Function 序列没有形成可复用的跨故事完整 motif。若产品要求 60 篇至少产出一个 Pattern，后续应单独诊断上游 Function 对齐/序列归纳为何没有产生重复 motif，不能直接放宽当前发布门槛或强行 promotion。

## 282. Observer 保留一次提取，移除重复的二次拆分防御（2026-09-10）

用户要求清除过度防御。复查后确认 Observer 主 Prompt 已表达独立事件拆分，后置二次 LLM 拆分复核只是同一职责的额外调用，并带有 4 次重试、上下文限制、角色重校验和失败回退；该路径模型波动且不能作为稳定质量证据。因此删除二次复核及其专用 schema/prompt/test，只保留关系证据和句子范围的必要边界过滤。相关回归 `13 passed`，全仓 `406 passed, 1 skipped`。

## 281. 采用稳定 anchor 回退，明确代表链与精确重复链的边界（2026-09-10）

用户明确选择恢复 `3dc5bb5` 的稳定 anchor 规则，而不是继续要求 anchor motif 自身 `story_support>=2`。最小回退只改变 anchor 选择：长度至少 4 的成员优先，没有时回退全部成员，再按支持数、长度和 motif ID 稳定排序；`CLEAN`、cluster 跨故事支持、长度和 Contract 发布门槛保持不变。Summary 仍不选择 Function，核心链继续绑定 anchor 的稳定 Function ID。

在固定的 180 篇验证 Snapshot 上重建得到 15 个 Published Pattern。15 个 anchor 均只由一个故事直接提供完整 motif，但其 cluster 由 2 或 3 个故事组成且通过 CLEAN 审查；因此结果应描述为“cluster 跨故事支持下的代表链”，不能描述为“同一 anchor 完整链被两个故事精确重复”。这是用户选择的发布语义边界，换取恢复可用 Pattern，同时保留 cluster review、长度和 Contract 门禁。

## 282. 将稳定 anchor 验证 Snapshot 迁移到正式 serving（2026-09-10）

用户明确选择把 `validation_anchor_revert_20260910` 的完整候选 Snapshot 切换到正式 serving，而不是只复制 15 条 Pattern。迁移前先归档正式 Knowledge DB、Registry 和 Ontology Snapshot；随后复制候选完整数据库、40 个 Function Registry 和 4 个相关 Snapshot 文件，并调用已有 `promote_snapshot()` 切换指针。

迁移后正式 serving 为 `bootstrap60_contract_20260910T034604743139Z_a1100a350fcf`，可读取 180 个故事、40 个 Function、2169 条 Occurrence 和 15 个 Published Pattern；Snapshot 校验、SQLite 完整性和 FK 检查通过。默认 KnowledgeBase catalog 读取 15 个 Pattern；Outline 模块导入验证因当前环境缺少 `langgraph.graph` 阻断，属于环境问题，不改变数据库迁移结论。旧正式 serving 数据保存在 `Code/data/formal_archives/20260910T123846_serving_before_anchor_revert/`，可恢复。

## 283. 用轻量窗口承接三条公开流程（2026-09-10）

用户希望通过人机交互完成 Bootstrap、Evolve 和文章生成，而不是记忆 Codex 或多层命令。最终选择不引入 Web 框架或新的 Agent：用 Python 标准库 Tkinter 做本地窗口，后台调用现有公开 StoryCLI；生成入口由用户选择 Dynamic 或 Pattern，Evolve 自动 promote，Bootstrap 重建保持显式勾选和二次确认。这样交互体验变简单，但正式 Run、Snapshot 和 Story Validator 的边界不变。

## 284. 交互窗口应先让 LLM 路由，再执行白名单命令（2026-09-10）

用户指出窗口直接按固定关键词进入 StoryCLI，不能满足“先传给 LLM，再调用命令行”的交互目标；`情感类：民国时代银行家和天才画家的相爱故事` 也因此在 LLM 尚未参与前被拒绝。最小改法是复用现有 `chat_structured` 做受限路由：操作必须匹配已点击的按钮，题材只能落在五个现有规范值，路径不接受模型改写，程序把规范题材前缀加入原始 `--request` 后用参数列表启动原有 StoryCLI。这样不修改 StoryCLI 的公开参数，仍解决入口顺序和“情感类”别名问题，同时没有把任意 shell 执行权交给 LLM。

## 285. Bootstrap 单故事不能形成跨故事 Function（2026-09-10）

用户用单个古风仙侠 `.txt` 执行 Bootstrap，最终日志为 `相似对=0、Function=0、Registry 为空`。这不是题材或 LLM 识别失败：当前 Evaluator 要求 Function 具有跨故事证据，单篇输入没有可比较的第二个故事。由于旧流程在收集文件后才清理工作 Registry/Bank/Checkpoint，单故事失败还会留下失败 Run 和未入 Snapshot 的临时数据。因此增加最小前置保护：Bootstrap 少于两个 `.txt` 时直接拒绝，不启动 FunctionExtract_Agent，也不归档或清理工作资产；已有 Snapshot/serving 不回写。

## 286. Dynamic 模式先形成故事再寻找结构（2026-09-10）

用户指出大纲应根据用户要求生成，而不是先有结构再贴合请求；随后明确当前只需要 Dynamic。决策：Dynamic 路径先由用户请求形成 Seed，再由 Dynamic Planner 寻找兼容 Function 结构；Published Pattern 暂不变更，用户要求一致性门禁与 Pattern 不兼容拒绝留作后续单独验证。

## 287. 生成窗口由用户选择 Dynamic 或 Pattern（2026-09-10）

用户明确不要求系统同时运行两条路径再自动选优，而是在“生成文章”窗口中自行选择 Dynamic 或 Pattern；选择只复用 StoryCLI 现有 planner mode，Pattern 仍走 Published Pattern 路径。

## 288. StoryUI 的问题首先是请求边界，不是正文展示（2026-09-10）

对同一 Snapshot 的真实运行进行复查后，StoryUI 与直接 Dynamic 入口都走 `Dynamic Seed → Dynamic Planner → ... → Story`，但 StoryUI 额外调用路由 LLM，并把 `情感类:战场上两位对手相爱，但爱而不得` 改写成 `现代情感：情感类:战场上两位对手相爱，但爱而不得`。对应 Seed 从战场敌对士兵漂移为当代公益项目对手，正文因此也完全换了冲突世界；直接入口保留战场语义。

这说明应先修正“用户要求进入 Seed 前被入口改写”的边界，再讨论正文 Prompt 或 StoryUI 展示层。Story Validator 对两份正文均判定通过，只能说明它们分别完成了各自 Seed/大纲，不能当作用户要求保真度的证据。当前不把额外路由调用单独认定为根因，也不在没有同输入对照实验前扩大为新的 Agent 或质量门禁。

## 289. StoryUI 只归一化题材前缀，不改写创作要求（2026-09-10）

按调查结论采用最小修复：路由 LLM 仍只识别 `genre`；程序在 `StoryCLI` 命令边界删除用户输入开头的已有题材别名及重复前缀，然后只加一次规范题材前缀。中间正文、标点和创作要求不由路由器重写，Dynamic Seed 收到的内容恢复为用户原文语义。

不新增 `--genre` 参数、Agent、Prompt 或数据库字段；用 StoryUI/StoryCLI 聚焦回归验证命令与路由顺序，真实 LLM 语义 A/B 留待后续固定同请求、同 Snapshot、同 DB 时再验证。

## 290. 操作由 UI 固定，路由 LLM 只负责 Story 题材（2026-09-10）

进一步收窄路由职责：UI 已经确定 Bootstrap、Evolve 或 Story，不再让 LLM 回显或判断 action；只有 Story 入口调用结构化 LLM 返回 `genre`。Bootstrap/Evolve 直接执行既有公开命令，减少一次无意义的模型调用和一个失败点。

## 291. 阶段内部自动串联，不在 Codex skill 间重复确认（2026-09-10）

用户指出阶段运行不应被拆成多次人工确认。Bootstrap skill 应直接使用已有公开 CLI 完成 `Function → Pattern → serving`；Evolve skill 应直接完成 `Function 增量 → Pattern`，必要时使用 `FunctionCoordinator_Agent` 的重试和超时；Story skill 应直接完成 `Pattern → Outline → Story`。三个 skill 只按用户选择启动一个顶层阶段，不把内部子阶段再次交回用户确认。清空正式库和切换 Evolve candidate 为 serving 仍是独立的正式状态变更，只有请求明确包含时才执行。

## 292. Evolve skill 成功后自动切换 serving（2026-09-11）

用户进一步明确：通过 Evolve skill 运行时，Evolve 和 Pattern 成功后必须自动 promote 新 Snapshot 为 serving，不再把 promote 交回用户确认。公开 `StoryCLI evolve` 调用固定带 `--promote`；若使用只负责 `Evolve → Pattern` 的 `FunctionCoordinator_Agent`，成功后由 skill 读取新 Snapshot 并调用既有 `promote_snapshot()`。失败时不切换 serving，Bootstrap、Story 的顶层边界保持独立。

## 293. 公开 Evolve 默认切换 serving，隔离发布流程保留 candidate 门禁（2026-09-11）

用户明确要求默认 serving。当前公开 `StoryCLI evolve` 在 Function 和 Pattern 成功、且 `promote_snapshot()` 的 Published Pattern 门禁通过后，自动将新 Snapshot 切为 serving；不再要求 `--promote`。Story 因而会直接读取本次成功的 Evolve 结果。`FunctionCoordinator_Agent` 仍保留 candidate 语义，因为 `release_pipeline.py` 需要在 Outline/Story/回归门禁完成后才正式 promote；这条隔离发布路径不随公开 Evolve 默认行为改变。

## 294. Story 生成前先选择 Pattern 或 Dynamic（2026-09-11）

用户要求 Story 启动时先询问规划方式，并简要说明差异。Story skill 现在在用户未明确指定时只询问一次：Pattern 使用 serving 中已发布结构，稳定且可控；Dynamic 先从用户要求生成 Seed，再动态组合兼容 Function，灵活性更高。选择后显式传入 `--planner-mode published|dynamic`，Outline 和正文不再插入确认。

## 295. 用户创作要求需要共享解析边界，但不应变成提示词改写器（2026-09-11）

用户提出是否应由 LLM 优化用户提示词，以及是否需要独立 LangGraph 节点。决策是保留原始 `user_request`，增加一个位于 Outline 分叉前的 `interpret_request` 节点，仅把一次结构化解析结果整理为 `creative_brief`；它不选择模式、题材、Pattern 或 Function，也不把推断内容写回原请求。`explicit` 与 `inferred` 分离后，Dynamic 和 Published 都能复用同一创作边界，同时保留可审计的原文。

这次只把 brief 接入已有 Seed、Pattern 选择、Outline/Story 校验和 manifest 传递，没有新增 Agent、子图、数据库或 Best-of-N。机械测试证明数据流与字段保留，仍不能证明真实模型在所有题材上能准确解析要求或生成高质量文学结果；后续若发现语义漂移，应先用固定请求、Snapshot 和 DB 副本检查 Seed/Outline/Story，而不是直接扩大解析层。

## 296. Function 因果结构与文学宏观结构如何结合（2026-09-11，待决策）

用户提出：如果把本项目的结构能力与文学性结合起来，二者应如何分工。当前思考是保持 `user_request → Seed → Dynamic Planner` 和既有 Function/Contract 因果边界，由 Function 负责可执行行动、状态变化、关系变化、义务与结局闭合；五幕节奏、人物缺点、环境参与、核心意象、伏笔类型和文风等文学要求应由 `creative_brief` 与 `NarrativePlan` 承接，并映射到 Function 段，而不是改写 Function 定义或把每一幕等同为一个 Function。

其中可观察的明确要求（例如五个阶段是否覆盖、海上因素是否实际改变选择、指定伏笔是否回收、结局动作是否发生）可以进入现有 Outline/Story Validator；克制、浪漫、余韵、自然对话等主观文学质量仍需直接阅读产物判断，不能由 `overall_ok` 或新增通用分数代替。本条仅记录架构问题和最小方向，尚未决定字段设计，也未授权修改 Prompt、Schema、Validator 或生成流程。

## 297. 用户要求直接进入 Seed，附件技巧只进入 NarrativePlan 与 Story Prompt（2026-09-11）

用户进一步确认：删除默认 Pipeline 开头的 CreativeBrief/`plot_hints` 处理，保留原始 `user_request → Seed`，把附件中值得借鉴的技巧直接融合到已有 NarrativePlan 和 Story Prompt。由此撤销上一条关于 `creative_brief` 中间层的试行设计：它增加了一次 LLM 解释和一套重复的意图边界，却没有提供结构上不可替代的信息。

新的职责边界是：user_request 是唯一创作意图来源；Seed 负责故事级落实；Function/Contract 负责可执行结构和状态闭合；NarrativePlan 负责在既定 Function 内安排人物动机、关系互动、反差、记忆锚点和伏笔回收；Story Prompt 负责通过行动、对话、物件和身体反应完成文本表达。附件中的平台套路、固定节奏、强制爽点和审稿分数不进入默认生成规则。

本次实现只做删层和 Prompt 清理，没有新增 Agent、Schema、存储或质量评分层；全仓测试为 `423 passed, 1 skipped`。该结果证明代码路径和机械约束回归通过，不等同于真实 LLM 生成的文学质量已被验证。

## 299. 先分配事件所有权，再进行文学实现（2026-09-11）

用户确认“一个结构上的情节写出来以后，再文学性地拓展润色”的方向后，进一步明确：文学层不能修复结构重复；同一个核心事件必须先由一个 Function 段或 ending 单独负责，LiteraryDesign 只为这一次事件安排动作、感官、潜台词、意象和节奏。

复查海上爱情真实产物时发现，最后一个 `REFUSAL_IMPACT` Function 已包含拒绝和下船，`ending` 又要求同样的拒绝和下船，Story 因此生成了两组重复场景。修复采用最小边界：ending 可以概述前序事件的结果，但不得把已完成的 Function 行动再次列为 ending 解决动作；Outline 和 Story 各自增加明显重复拦截，语义不确定部分仍由既有 Validator/人工审读处理，不新增第二个文学 Agent 或 Best-of-N。

## 300. NarrativePlan 先于 LiteraryDesign 顺序生成（2026-09-11）

用户追问“为什么合并、到底实现了什么”，最终将设计边界明确为真正的顺序依赖，而不是联合生成：先完成并校验 NarrativePlan，再让 LiteraryDesign 读取它并只设计呈现方式。两个对象仍保持独立，只有在 Realize、ScenePlan 和正文阶段被同时读取；“合并”只描述下游输入，不描述生成接口。

本轮实现还确认一个结构前提：文学层不能替结构层修复重复事件；只有一个 Function 段或 ending 先拥有某个核心行动，文学设计才能把这一次行动写深。由此新增的顺序测试证明 NarrativePlan 失败时 LiteraryDesign 不会调用，不能替代真实 LLM 产物的文学质量判断。

## 301. 结构结局与结局文学实现分别归属两层（2026-09-11）

用户进一步追问“ending 为什么不能在 NarrativePlan 一起写上”，由此把前一轮的顺序依赖继续收紧为清晰的双层接口：`NarrativePlan` 在 `steps` 之外、同一次调用中生成 `ending`，负责确定结局发生什么；`LiteraryDesign` 在第二次调用中读取完整 NarrativePlan，新增 `literary_ending`，负责确定这个既定结局如何被看见、听见和感受到。这里“独立”指字段和对象职责独立，不意味着再增加一次单独的结局 LLM 调用。

Realize 不再生成 ending，而是只实现 Function 段并产出 `final_ledger`，由代码把已校验的 `narrative.ending` 复制为最终 `outline.ending`。这样既保持最终大纲对 Story 的稳定输入，又消除了 NarrativePlan、Realize 两套结构结局互相漂移的可能；文学层也不能借 `literary_ending` 新增解决行动、关系升级或结局转折。

## 302. LiteraryDesign 的可选意象必须是完整分支（2026-09-11）

一次 Dynamic 运行暴露出：`motif_plan` 虽然允许为空，但模型可能返回缺少必需子字段的半对象；结构化重试又可能返回多个 JSON。由此确认可选嵌套对象不能只依赖 Schema 报错后的泛化提示，Prompt 必须明确 `null` 或完整对象的二选一协议，共享重试层也必须把字段路径和单对象边界反馈给模型。保持严格失败比静默删掉半个意象设计更安全；历史产物继续保留，但不作为本次运行结果。

## 303. 结局类型由 Dynamic Seed 自主决定（2026-09-11）

用户指出，若在 Prompt 中额外暗示分离、开放或团圆，会让 Seed 偏离原始创作要求。决策：保留 `ending_direction` 作为必须输出的结构接口，但删除对具体结局类型的预设；未指定结局时由 Seed 根据 user_request、人物目标和核心冲突自主选择。爱情题材只需明确回答关系终态，不预设相守或分离。

Dynamic 的顺序保持为 `user_request → Seed → Dynamic Planner`：Seed 先形成故事需要的冲突与结局方向，必须覆盖用户明确提出的所有主线；不再要求 Seed 迁就尚未生成的 Function 链，Planner 再选择能够承接该结局的 Function 链，不能反向改写 Seed。未提出的关系或主题不由 Seed 凭空加入。此次没有新增 Agent、Schema、存储或评分层。

## 304. Prompt 审计必须适配项目而不是照搬 Anthropic 规则（2026-09-11）

用户提出为 Function-Extraction 定制项目级 `prompt-audit` Skill。关键判断是：Anthropic 官方文档可以提供审计流程和过时模式目录，但其中关于当前 Claude 行为的删除理由不能直接套用到项目当前的 DeepSeek 请求。Skill 因此把实际 `messages` 组装、Pydantic/JSON 契约、阶段边界和历史 diff 纳入同一审计面，并将 Function/Contract、事件所有权、用户请求保真、文学结构分工和 Snapshot/正式库保护列为默认不可弱化的负载边界。

默认输出审计报告和 proposed diff，不自动改文件；明确要求落地时也必须逐个问题修改、逐个测试。文本变短不是质量证明，真实生成对照仍需固定请求、Snapshot、planner mode 和数据库副本后重复验证。
