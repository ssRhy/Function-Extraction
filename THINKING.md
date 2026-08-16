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
