# 基于 Narrative Function 的中文短篇网文大纲自动生成：后续完整计划

## 一、项目目标

本项目希望从现代中文短篇网文中自动学习：

- 故事中有哪些 Narrative Function；
- 这些 Function 通常由什么角色完成；
- Function 通常怎样排列组合；
- 每个 Function 在不同题材、人物关系和故事阶段中怎样实例化。

在此基础上，建立一条尽量不需要人工参与的自动流水线：

```text
从真实故事中学习 Function 及其用法
→ 自动规划 Function 序列
→ 自动生成题材、人物和核心冲突
→ 将 Function 实例化为具体情节
→ 检测和修复
→ 批量生成并筛选
→ 输出故事大纲
```

目标质量是：

- 稳定生成符合中文短篇网文中规中矩水平的大纲；
- 大部分大纲结构完整、因果连贯、人物行为合理；
- 不强迫每个 Function 创新，而是先生成一版成立的故事；
- 再参考故事库，判断哪些地方有效、应该保留，哪些地方太弱、太像或太普通，需要局部调整；
- 通过批量生成和筛选，提高出现有趣、具有爆款潜质候选的概率。

项目暂时做到大纲，不生成完整正文。

---

## 二、目前已经完成了什么

目前已经跑通基本的 Function 构建流程：

```text
Story
→ Narrative Observation
→ 跨故事比较和归纳
→ Function
```

当前 120 篇故事已经得到一批保留下来的 Function。Observation 也记录了事件、参与者、前后状态、叙事效果和原文位置。

这说明“从故事中归纳 Function”的基本路线已经成立，不需要推倒重来。

但目前主要解决的是：

> 故事中可能有哪些 Function？

还没有解决：

> 这些 Function 由谁完成、怎样组合、怎样实例化，以及怎样用于生成完整大纲？

接下来的工作，就是补齐这条从“Function 发现”到“自动大纲生成”的链路。

---

## 三、现有部分需要优化什么

### 1. 补上人物角色

普罗普虽然把 Function 按结构作用定义，但同时还用“行动范围”说明主人公、反派、帮助者等角色分别承担哪些功能。

我们目前抽出的 Function 基本看不出：

```text
谁执行这个 Function
作用于谁
执行者与主人公是什么关系
```

如果以后采样 Function 序列生成大纲，却不知道每一步是谁对谁做什么，就无法保持人物关系、立场和行为动机的一致。

因此要补两层角色信息。

#### 故事级人物关系

记录：

```text
谁是主人公
主要人物分别想要什么
人物之间是什么关系
他们支持、阻碍还是部分支持主人公
```

#### Function 级角色位置

记录：

```text
谁发起行动
谁受到影响
谁提供信息或资源
谁从中受益
谁形成阻碍
```

这不意味着每个 Function 必须固定属于主人公、反派或帮助者。Function 应当规定需要哪些角色位置，再记录当前故事中这些位置分别由谁承担。

### 2. 把 Function 从“分析标签”补成“可生成结构”

现有 Function 有名称、定义和实现模式，但用于生成时还需要明确：

```text
什么情况下可以发生
需要哪些角色
发生后改变了什么
```

可以简单理解为：

```text
Function
= 在什么状态下
+ 由什么角色做什么
+ 使故事变成什么状态
```

因此，每个 Function 需要补充：

```text
前置条件
角色位置
状态变化
```

例如：

```text
Function：秘密被揭露

前置条件：
存在尚未公开的信息、隐瞒者和不知情者。

角色位置：
隐瞒者、发现者、受到影响者。

状态变化：
秘密从隐藏变为被关键人物知道，
人物关系、目标或行动策略发生改变。
```

这些字段暂时可以使用结构化自然语言，不必马上做成严格的形式逻辑。

### 3. 补上故事级信息

当前 Observation 主要分析局部片段，但局部片段通常看不出：

```text
谁是主人公
人物的长期目标是什么
人物之间是什么关系
同一人物在不同片段中是否保持一致
```

因此，每篇故事需要先生成一个简洁的 Story Profile：

```text
故事背景和世界规则
主人公
主要人物
人物目标和关系
核心冲突
结局状态
```

Observation 中的参与者要尽量对应到 Story Profile 中的稳定人物，而不是每个片段分别描述。

### 4. 根据新增信息重新检查当前 Function

加入人物关系、角色位置、前置条件和状态变化后，需要重新检查现有 Function：

- 是否存在含义重复的 Function；
- 是否有 Function 太宽，需要拆分；
- 是否有多个类别粒度不一致；
- 是否有 Function 只是表面动作；
- 是否有结构作用不同的事件被归到一起；
- 是否有定义混入了具体题材和背景。

这一步是在当前结果上修订，不是重新从零开始。

---

## 四、目前完全缺少什么

### 1. FunctionOccurrence

需要建立一个统一结构，表示：

> 某个 Function 在某篇故事中的一次具体出现。

它至少需要记录：

```text
属于哪个 Function
由谁完成、影响谁
具体发生了什么
采用了什么实例化机制
前后状态怎样变化
位于故事哪个阶段
对应哪段原文
```

例如：

```text
Function：秘密被揭露

具体事件：
妻子在丈夫手机中发现异常转账。

实例化机制：
通过意外获得的物证揭露隐瞒信息。

状态变化：
主人公从信任转为怀疑，并开始调查。
```

FunctionOccurrence 是后续 Function 序列、实例检索和生成的共同基础。

### 2. 每篇故事的 Function 序列

需要把每篇故事表示为有序序列：

```text
F03 → F11 → F27 → F08 → F41
```

现有 Function 无法覆盖的事件保留为：

```text
OTHER
低置信度
多个备选 Function
```

不能为了提高覆盖率而强行分类，因为这些案例是以后发现新 Function、拆分旧 Function的重要来源。

### 3. Function 的组合知识

需要从真实故事中统计：

```text
每个 Function 后面通常接什么
哪些 Function 经常一起出现
有哪些常见的局部组合
有哪些完整故事结构
不同题材中的组合有什么差异
哪些组合需要特定的角色或前置状态
```

其中，motif 可以简单理解为：

> 由连续几个 Function 组成的常见局部套路。

例如：

```text
遭受损害
→ 暂时忍耐
→ 获得证据
→ 开始反击
```

最终需要形成：

```text
Function 转移关系
Function motif 库
真实完整序列库
Function 位置和题材分布
```

这些知识以后提供给大模型规划故事，而不是用固定概率机械生成。

### 4. Function 的实例化知识库

每次 Function 出现，都建立一张 Instance Card，记录：

```text
具体实例
抽象实例化机制
题材背景
冲突主题
人物关系
故事位置
前后状态
原文证据
```

例如：

```text
秘密被揭露
├── 通过物证揭露
│   ├── 手机转账记录｜现代家庭
│   ├── 被篡改的账本｜古风宅斗
│   └── 隐藏实验日志｜末日故事
├── 通过第三者告知
├── 通过当事人失言
└── 通过主人公主动设局
```

为了方便管理和检索，标签需要分开：

```text
genre_tags：题材背景
conflict_tags：核心冲突
relation_tags：人物关系
mechanism：实例化机制
story_stage：故事位置
```

一个实例可以有多个标签，同时保留一句自由摘要。标签后续需要定期合并近义项，避免“家庭冲突”“家庭矛盾”“家庭纠纷”被当成完全不同的类别。

实例库按照两层组织：

```text
Function
└── 实例化机制
    └── 不同题材和人物关系中的具体实例
```

检索时先用结构化标签筛选，再用 embedding 做语义相似检索。

---

## 五、最终系统的完整流程

### Part A：从真实故事中构建 Function 知识

```text
真实故事
→ Story Profile
→ Narrative Observation
→ FunctionOccurrence
→ Function 定义、角色位置和状态变化
→ 每篇故事的 Function 序列
→ Function 转移、motif 和实例化知识库
```

### Part B：利用 Function 自动生成大纲

```text
LLM 规划候选 Function 序列
→ 自动生成多个 Story Seed
→ 选择 Seed 并回查序列是否适配
→ 为整条序列生成初步实例化计划
→ 顺序实例化并维护状态
→ 得到一版中规中矩的完整初稿
→ 与故事库比较结构和实例相似度
→ 判断哪些保留、修复或差异化
→ 只修改少量真正需要调整的位置
→ 重新检查全局一致性
→ Best-of-N 选择最终大纲
```

---

## 六、具体实施阶段

### 阶段一：补完整故事和 Function 表示

这是当前最高优先级。

#### 需要完成

1. 定义 Story Profile；
2. 让 Observation 中的人物对应到 Story Profile；
3. 为 Function 增加前置条件、角色位置和状态变化；
4. 定义 FunctionOccurrence 和 Instance Card；
5. 选择 5 篇不同题材的故事完整试验；
6. 根据试验结果修订当前 Function。

#### 这一阶段要回答

> 这个 Function 在什么情况下发生，需要哪些角色，由谁完成，并产生什么变化？

#### 完成标准

给定一篇故事，能够恢复：

```text
主要人物和关系
人物目标
主要事件
每个事件对应的 Function
Function 的角色绑定
前后状态变化
对应原文证据
```

### 阶段二：建立 Function 知识库

数据结构确定后，再处理当前全部故事。

#### 需要完成

1. 将每条 Observation 映射到 Function 或 OTHER；
2. 同时提取角色绑定和 Instance Card；
3. 得到每篇故事的 Function 序列；
4. 统计 Function 转移；
5. 提取常见 motif；
6. 整理和聚类每个 Function 的实例化机制；
7. 建立供后续 Planner 查询的接口。

#### Planner 至少需要查询

```text
某个 Function 的定义和角色位置
常见和少见的后续 Function
可连接的 motif
相似的完整故事序列
同一 Function 的常见实例化机制
不同题材中的实例
```

#### 完成标准

给定一个 Function 或部分序列，系统能够从真实故事库中返回与其组合和实例化有关的知识。

### 阶段三：实现自动规划和中规中矩初稿

#### 1. LLM-guided Function Planner

Planner 不机械选择出现频率最高的 Function，而是综合：

```text
当前部分序列
Function 的前置条件和状态变化
已有角色和冲突状态
故事处于什么阶段
还缺少升级、转折还是解决
常见后续 Function
可复用的 motif
```

大模型可以：

```text
FOLLOW：采用成熟组合
ADAPT：迁移其他 motif
EXPLORE：提出新的合理连接
```

但不要求每一步创新。首要目标是生成结构完整、能够实例化的序列。

规划时应保留多条候选序列，避免每一步只保留一个局部最优结果，最后无法形成合理结局。

#### 2. 自动生成 Story Seed

给定 Function 序列，自动生成多个候选：

```text
题材和世界
主人公
主要人物
人物目标和关系
核心冲突
结局方向
```

选定 Story Seed 后，需要回头检查 Function 序列是否仍然适合该题材和人物，必要时进行小范围调整。

#### 3. 先生成整条实例化草案

在写具体大纲前，先为所有 Function 生成一句粗略实例化草案：

```text
这个 Function 准备用什么事件实现
由谁完成
产生什么状态变化
怎样连接下一个 Function
```

这份 Mechanism Plan 的作用是先检查整条故事能否落地，避免完全边写边想，导致前面的情节把后面堵死。

它不负责提前规定哪些地方一定要创新。

#### 4. 顺序实例化

Mechanism Plan 通过后，再逐个 Function 生成具体情节。

生成过程中维护简洁的状态账本：

```text
人物目标
人物关系
已公开和未公开的信息
已有和失去的资源
未解决的冲突
主人公当前处境
世界规则
```

#### 5. 局部检测

每生成一个 Function，检查：

```text
是否真正实现目标 Function
前置条件是否满足
状态变化是否正确
人物关系是否一致
是否为下一个 Function 创造条件
是否重复使用相同机制
```

可以使用往返检测：

```text
目标 Function
→ 生成具体情节
→ 重新抽取 Function
→ 是否能够恢复目标 Function
```

#### 完成标准

在没有人工指定题材和情节的情况下，系统能够生成一版结构完整、因果基本连贯的中规中矩大纲。

### 阶段四：诊断、局部优化和筛选

初稿完成后，再判断是否需要创新或修改。

#### 1. 与故事库比较

分别比较：

```text
完整 Function 序列相似度
局部 motif 相似度
实例化机制相似度
具体情节相似度
文字表达相似度
```

结构相似不一定意味着具体故事相同；文字不同也不代表结构和实例真正不同，因此需要分层比较。

#### 2. 让 LLM 诊断

对每个关键节点或局部结构作出判断：

```text
KEEP：
常见但有效，保留。

REPAIR：
创新不是主要问题，但因果、人物动机或状态变化需要修复。

DIFFERENTIATE：
结构合理，但关键实例太普通或与故事库过于相似，需要换一种实现方式。

REPLAN：
问题来自局部 Function 组合，需要替换一个 motif。
```

普通连接和过渡情节只要合理，就没有必要为了创新而修改。

优先检查：

- 开头钩子；
- 冲突第一次明显升级；
- 关键证据或能力的获得；
- 中段重要逆转；
- 主人公反击或解决问题的方式；
- 结局中的关键兑现。

#### 3. 按最小修改原则修复

修改顺序是：

```text
先改具体事件
→ 再换实例化机制
→ 再调整相邻事件
→ 再替换局部 motif
→ 最后才重新规划完整序列
```

修改后必须重新检查前后状态和全局结构。

如果修改后的版本没有明显优于初稿，就保留初稿。

#### 4. 漏斗式 Best-of-N

批量生成时：

```text
先生成较多 Function 序列
→ 筛选少量结构候选
→ 为候选生成多个 Story Seed
→ 筛选少量实例化计划
→ 只为最有希望的计划生成完整大纲
→ 修复和排序
```

这样既能提高质量上限，也能控制 token 成本。

#### 完成标准

系统能够批量生成大纲，自动判断哪些位置应当保留或调整，并从多个候选中选出整体较好的结果。

### 阶段五：扩大故事库并持续完善

流程跑通后，再扩展到几千篇甚至更多故事。

随着故事增加，持续完成：

```text
发现新 Function 候选
修订 Function 边界
丰富 Function 转移和 motif
丰富实例化机制
改进 Planner
改进诊断和候选排序
```

当前 120 篇主要用于验证流程和数据结构，不用于得出最终的 Function 理论。真正稳定的 Function、组合规律和实例化规律，需要在大规模故事库中逐渐形成。

---

## 七、如何管理生成中的创新

真实故事知识和系统生成内容必须分开。

### Corpus Knowledge Base

只保存从真实故事中得到的：

```text
Function
Function 序列
Function 转移
motif
实例化机制
具体实例
```

它回答：

> 中文短篇网文实际上怎样写。

### Creative Memory

保存生成过程中产生并通过检查的：

```text
新 Function 转移
新 motif
新实例化机制
新 Function 候选
```

它回答：

> 系统提出了哪些值得继续尝试的创新。

大模型提出的新内容不一定是新 Function：

- 已有 Function 之间的新连接：new transition；
- 多个 Function 的新组合：new motif；
- 同一 Function 的新实现：new realization；
- 现有 Function 无法表达的新结构作用：才是 new Function candidate。

Creative Memory 可以继续用于生成，但不能直接当成真实故事规律。

---

## 八、评价方法

### 1. Function 构建评价

检查：

```text
主要故事事件是否被覆盖
相似结构是否映射到相同 Function
易混淆 Function 是否能够区分
角色绑定是否正确
OTHER 和低置信度案例是否合理
```

### 2. Function 序列评价

检查：

```text
前置条件和状态变化能否连接
是否存在冲突升级和关键转折
是否能形成合理结局
LLM 提出的新连接是否合理
序列是否能够被顺利实例化
```

### 3. 实例化评价

检查：

```text
是否能够往返恢复目标 Function
人物和世界是否一致
是否完成预期状态变化
实例化方式是否重复
与故事库是否过于相似
```

### 4. 大纲质量评价

至少比较三种方法：

```text
直接让 LLM 自动写大纲

让 LLM 使用 Function 序列，但没有故事库检索和检测

完整系统：
Function 知识库
+ LLM Planner
+ 实例检索
+ 检测修复
+ Best-of-N
```

主要评价：

```text
结构完整性
因果连贯性
人物动机
冲突和转折
新颖性
整体吸引力
```

前期可以使用小规模人工比较。积累足够数据后，再考虑训练排序器、奖励模型或使用强化学习。

---

## 九、工程原则

### 1. 原文尽量只处理一次

读取真实故事时，尽量一次性保存：

```text
Story Profile
Observation
人物关系
原文证据
FunctionOccurrence
Instance Card
```

以后 Function 合并、拆分或改名，尽量使用中间数据重新映射，不重新读取完整故事。

转移频率、motif 和实例统计由程序重新计算，不反复调用 LLM。

### 2. 数据必须可追溯

虽然不把系统分成多个临时版本，但工程上需要记录：

```text
使用了哪套 Function 定义
使用了哪个 Prompt
映射何时生成
数据来自真实故事还是生成故事
```

这样以后修改 Function 后，能够复现和解释结果。

### 3. 不为创新而创新

系统默认先生成一版成立的故事，再判断是否需要局部调整。

创新只有在以下情况下才有价值：

```text
关键情节太普通
与已有故事过于相似
当前机制无法支持有效转折
新的实现方式能够明显提升故事
```

常见但有效的内容应当保留。

---

## 十、RA 当前的任务顺序

当前按以下顺序推进：

1. 设计 Story Profile、Function 和 FunctionOccurrence；
2. 明确故事级人物关系和 Function 级角色位置；
3. 为 Function 补前置条件和状态变化；
4. 在 5 篇不同题材故事上完整试验；
5. 根据试验结果修订当前 Function；
6. 处理当前全部故事，得到 FunctionOccurrence、Instance Card 和 Function 序列；
7. 建立 Function 转移、motif 和实例化知识库；
8. 实现供大模型查询这些知识的接口；
9. 实现 LLM Function Planner；
10. 实现自动 Story Seed、角色绑定和 Mechanism Plan；
11. 实现顺序实例化、状态账本和 Function 往返检测；
12. 实现故事库比较、局部优化和 Best-of-N。

当前首先完成前 5 项。数据结构确认后，再批量处理当前故事；Function 知识库建立后，再进入自动生成部分。

整个项目可以压缩成一句话：

> 先把 Function 补成人物、前置条件和状态变化都明确的可生成结构，再从真实故事中学习它怎样组合、怎样实例化；之后让大模型利用这些知识生成一版成立的初稿，再参考故事库只修改真正需要调整的关键位置，最后通过批量筛选得到质量较好的大纲。

---

## 十一、MVP-B 当前状态与后续改进顺序（2026-08-27）

MVP-B 已完成一条可运行、可追溯的最小链路：

```text
真实 Function
→ FunctionContract / OntologySnapshot v3
→ Pattern / Planner
→ Mechanism Plan / Contract Ledger
→ Outline / Validator
```

当前 MVP 暂以“链路可运行、产物可审计、问题可定位”为交付标准。后续改进按以下顺序推进：

1. 在 `FunctionExtract_Agent` 建立证据约束的 `StateVocabulary`，统一 aspect、state、obligation key 的规范 ID、别名、拼写和粒度。
2. 明确链边语义，区分世界初始条件、Function 输入、上一步输出、持续状态和义务清偿，避免把所有前置条件都按字符串 exact 匹配。
3. 用规范化合同重新生成 PatternCatalog，并在发布时报告状态断裂、开放义务和未定义终态。
4. 让 Planner 依据目标冲突与终态规划完整故事链；闭合仍由组合链和实例终态判断，不增加 Function 结局白名单。
5. 在真实 v3 Snapshot 上重跑 StoryPattern 全流程，再沿用同一三组 A/B/C 材料协议进行复评；多人评审一致性留在后续质量评估阶段。

暂不纳入 MVP-B：Best-of-N、正文生成、全量 StoryProfile、人工结局标签和论文级评审扩展。

---

## 十二、MVP-B 收尾与下一阶段（2026-08-27）

MVP-B 到此收尾。当前交付包括：

- 真实 Function 与 OntologySnapshot v3；
- Pattern/Planner/Mechanism/Realizer/Validator 大纲生成链；
- 角色槽位、机制、状态账本和校验结果；
- 3 个题材 × 3 份完整大纲及 A/B/C 盲评材料。

已知的合同状态词汇问题、严格链兼容性不足、多人盲评一致性、Best-of-N 和正文生成均记录为后续优化，不作为当前 MVP 阻塞。

下一阶段先进入实际使用反馈：针对明确的生成目标批量生成大纲，收集可复现的失败案例，按影响最大的单一问题进行小步修复和复测。暂不启动完整 `StateVocabulary` 本体改造。

当前首个可复现问题已确定为结局段兑现不足：部分大纲停在营救、逃避、重建或后续行动，未解决核心冲突。下一轮只围绕“最后一段兑现 `ending_direction`”做最小修复和小批复测。

该修复已落地为 Pattern 级可选 `ending_spec`：下一次数据发布时重新生成 Pattern summary/catalog，使真实模板携带结局要求；在此之前，历史 Catalog 继续按旧 schema 使用。

本轮已完成新的 Pattern summary/catalog 发布：沿用同一 Snapshot、Bank、manifest 和冻结 HIGH 评审，在 `data/story_pattern_evolve_250/` 生成 schema v2 产物；旧目录保留在可恢复归档中。下一步使用该新 catalog 重新生成实际大纲批次，观察 `ending_spec` 对结局段兑现的实际改善。

## 十三、统一 CLI 与故事生成入口（2026-08-30）

当前公开使用入口分为三组子命令：

```text
StoryCLI function bootstrap/evolve
StoryCLI template build
StoryCLI story write
```

`function bootstrap/evolve` 在 Function Snapshot 发布后自动执行 Pattern Evolve；`template build` 只从统一 DB 的 published PatternSet 选择 Pattern 并生成 Outline，再把 Pattern、Outline、Snapshot 和来源 Function 运行 manifest 固定为 Template Bundle。`story write` 只消费该 Bundle，用户追加要求时固定 Pattern 并重新实例化 Outline。

## 十四、Pattern Evolve 增量主线（2026-09-01）

Pattern 以父 Snapshot 的 PatternSet 为基线，只更新新增或 FunctionOccurrence 签名变化的故事：

```text
父 PatternSet + 子 Snapshot delta
→ sequence 增量
→ motif evidence 增量
→ 新签名 pair 的 LLM 审查
→ cluster lineage
→ PatternVersion
→ 子 PatternSet
```

Exact Motif 由有序 Function ID 链确定，不调用 LLM；语义候选只判 `SAME_PATTERN / RELATED / DIFFERENT`。Pattern 的证据扩展和结构扩展分别产生 `EVIDENCE_EXTENDED` 与 `STRUCTURE_EXTENDED` 版本；未变化 PatternVersion 直接继承。正式输入与中间状态只从统一 SQLite 读取，不使用 Catalog 文件、JSON replay 或旧目录 fallback。
