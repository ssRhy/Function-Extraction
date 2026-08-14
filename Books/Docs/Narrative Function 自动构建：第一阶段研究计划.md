/# Narrative Function 自动构建：第一阶段研究计划

## 1. 我们现在要做什么

我们的长期目标，是从中文故事/中文网文中自动归纳一套类似 Propp《故事形态学》的叙事结构理论。

完整理论以后可能包括：

- Function：故事中反复出现的基本叙事功能；
- Function 之间的关系与组合；
- Character Role：不同角色承担什么叙事作用；
- Story Arc / Move：多个 Function 如何形成更大的剧情单元；
- 更高层的套路或 narrative grammar。

但这些内容有依赖关系。

**第一阶段只解决 Function。**

也就是：

\[
\boxed{
Chinese\ Stories
\rightarrow
Narrative\ Function\ Ontology
}
\]

只有 Function 本身比较稳定以后，再研究 Function 之间的关系、角色、轮次和套路。

---

# 2. 什么是 Function

先明确我们到底希望系统发现什么。

Function 不是一个具体动作，也不是一个动词类别。

例如三个故事分别出现：

> 主角在比武中展现隐藏修为。  
> 一个医生治好所有专家都无法治疗的病。  
> 一个学生解决所有教授都不会的问题。

表面动作分别是：

```text id="qyff56"
战斗
治病
解题
```

但如果三个事件在故事中的作用都是：

> 其他人原本低估这个角色的能力  
> → 某件事发生  
> → 其他人认识到这个角色其实能力很强

那么它们可能属于同一个 Function：

```text id="pczytt"
CAPABILITY_REVELATION
```

因此 Function 关注的不是：

> “发生了什么具体动作？”

而是：

> **“这个事件在故事的发展中起到了什么结构性的作用？”**

可以粗略理解为：

\[
Function
=
Recurring\ Structural\ Role\ of\ Narrative\ Events
\]

判断一个 Function 时，可以重点参考：

```text id="phb6vr"
事件之前是什么情况？
发生了什么事情？
谁影响了谁？
发生之后什么发生了变化？
这个变化对后续故事有什么意义？
```

---

# 3. 那么 Function 到底怎么从故事中构建出来？

这是整个项目最核心的问题。

我们的基本思想是：

> **Function 不是从单个故事中直接“想出来”的，而是通过比较多个故事中的具体叙事现象，找到其中反复出现的不变量。**

因此中间需要一个 Observation 层。

完整关系是：

\[
\boxed{
Story
\rightarrow
Narrative\ Observation
\rightarrow
Cross\text{-}Story\ Comparison
\rightarrow
Function
}
\]

---

## 3.1 第一步：先把故事变成 Narrative Observations

系统首先读一个完整故事或一个可以独立理解的故事单元。

这一阶段只回答：

> 故事中发生了哪些具有明显叙事意义的事情？

例如：

> 张凡一直被同门认为资质普通。宗门比试时，他突然一剑击败内门第一，周围弟子全部震惊。

可以表示成：

```text id="p473j7"
Observation O_137

Prior Context:
其他角色一直低估张凡的实力

Event:
张凡公开击败公认的强者

After:
其他角色认识到张凡实际实力很强

Affected Aspect:
其他角色对张凡能力的认知

Narrative Effect:
张凡的能力评价与声望发生改变
```

这一阶段**不需要给它取 Function 名字**。

因为单独看这一个故事，我们并不知道：

> “公开击败强者”

究竟是一个独立 Function，

还是某个更一般 Function 的一种具体表现。

---

## 3.2 第二步：把不同故事里的 Observation 放在一起比较

假设继续处理其他故事，得到：

```text id="prq06u"
O_137：
公开击败强者，
让其他人意识到真实实力

O_286：
炼出高级丹药，
让其他人意识到真实炼丹水平

O_431：
成功完成高难度手术，
让其他人意识到真实医术

O_782：
解决所有人不会的问题，
让其他人意识到真实智力水平
```

表面动作完全不同。

但比较以后，会发现一个共同结构：

```text id="jiwwfv"
Before:
相关人物不知道或低估某角色的能力

After:
相关人物认识到该角色具有较高能力
```

这时候才可以提出：

```text id="3cd7ho"
Candidate Function:
CAPABILITY_REVELATION
```

因此：

\[
\boxed{
One\ Observation
\neq
One\ Function
}
\]

真正的 Function discovery 是：

\[
\boxed{
Multiple\ analogous\ observations
\rightarrow
Abstraction
\rightarrow
Candidate\ Function
}
\]

---

# 4. 为什么整个语料需要分批处理

理解了上面的过程以后，才涉及“分批”。

假设有几百个故事。

两个极端都不理想：

### 极端 A：第一篇故事直接建立整套 Function

容易严重受到第一篇故事影响。

### 极端 B：一次让模型看全部故事并总结

很难保留具体证据，也无法知道某个 Function 为什么产生，更无法在后面系统地修改。

所以采用：

> **Bootstrap + Incremental Evolution**

也就是：

```text id="vx2l4g"
一小批有代表性的故事
↓
建立初始 Function Ontology O0

新的故事批次
↓
检验 O0
↓
更新为 O1

新的故事批次
↓
检验 O1
↓
更新为 O2

...
```

即：

\[
O_0\rightarrow O_1\rightarrow O_2\rightarrow\cdots
\]

这里的“批次”不是因为故事天然分成几批，而是一种让 ontology **可控地逐步形成和修正**的方法。

---

# 5. 第一轮：如何建立初始 Function Ontology

首先从 corpus 中选择一小批比较多样的故事作为 bootstrap corpus。

例如：

- 不同作者；
- 不同题材；
- 不同故事风格。

具体数量后面通过实验确定。

---

## Step 1：Observation Extraction

每个故事独立经过：

```text id="7y50e6"
Story
↓
Observer Agent
↓
Narrative Observations
```

所有 Observation 进入统一的：

```text id="b8i4k9"
Observation Bank
```

---

## Step 2：寻找相似 Observation

不是让 LLM 一次阅读所有 Observation。

我们先把每个 Observation 转换成比较抽象的结构描述，例如：

```text id="izrbn5"
prior context
event
participants
before state
after state
narrative effect
```

然后利用 embedding / retrieval 找：

> 哪些 Observation 在结构意义上比较相似？

例如：

```text id="fnjqod"
展示修为
展示医术
展示炼丹能力
展示智力
```

可能进入同一个候选集合。

---

## Step 3：Function Induction

Function Inducer 阅读一组来自不同故事的相似 Observation。

任务不是总结它们的主题，而是寻找：

> **去掉人物、世界观和具体动作以后，它们还共享什么叙事作用？**

输出：

```text id="qplvvr"
Candidate Function

Name:
CAPABILITY_REVELATION

Definition:
Previously unknown or underestimated competence
becomes recognized by relevant characters.

Supporting Observations:
O137
O286
O431
O782
...
```

---

## Step 4：建立初始 Function Registry

经过多组 Observation 的比较以后，形成：

\[
O_0=\{F_1,F_2,\ldots,F_k\}
\]

每个 Function 都不能只有名字，而应该保存成一个 Function Card：

```text id="p6eppi"
Function ID

Name

Definition

Structural Significance

Typical Context / Preconditions

Typical Consequences

Participant Roles

Typical Before / After State

Surface Realizations

Positive Examples

Hard Negatives

Confusable Functions

Status

Confidence

Version History
```

例如：

```text id="7mhonr"
CAPABILITY_REVELATION

Definition:
此前未知或被低估的能力，
被相关人物认识到。

Realizations:
展示修为
展示医术
展示炼丹能力
展示智力
...

Hard Negative:
角色独自突破境界

Confusable Function:
POWER_ADVANCEMENT
```

---

# 6. 初始 Function 如何防止一开始走偏

现在才进入“初始 ontology 怎么防止走偏”的问题。

主要采用四种办法。

## 6.1 Bootstrap Corpus 要有多样性

不能只用同一本小说或者同一种类型。

否则很容易得到：

```text id="1cazur"
获得异火
宗门大比
筑基突破
...
```

这种绑定仙侠表层形式的 Function。

跨不同类型比较，更容易逼迫系统寻找真正抽象的共同结构。

---

## 6.2 Function 必须有多个跨故事证据

不能因为一个 Observation 特殊，就立刻创建 Function。

一个 Function 至少需要多个不同故事的 supporting observations。

因此：

\[
single\ case
\rightarrow candidate\ evidence
\]

而不是：

\[
single\ case
\rightarrow Function
\]

---

## 6.3 第一轮可以独立运行多次

例如：

```text id="gej56u"
Run A → Ontology A
Run B → Ontology B
Run C → Ontology C
```

改变：

- bootstrap story sampling；
- story order；
- random seed。

然后比较不同运行中反复出现的 Function。

如果多个独立 run 都得到类似概念：

```text id="lnfokr"
能力曝光
能力被认可
隐藏实力展示
```

说明这个结构比较稳定。

---

## 6.4 初始 Ontology 不是最终答案

\(O_0\) 只是 provisional theory。

后面的故事允许：

```text id="g4sphf"
修改
合并
拆分
新增
删除
```

所以我们不要求第一次 induction 完美。

真正希望的是：

> **随着新证据加入，它能逐渐收敛。**

---

# 7. Prompt 中需要告诉 Agent 什么

需要给 Agent 明确的**方法思想**。

但是不建议直接把 Propp 的 31 个 Function 当成候选答案。

Prompt 应该告诉模型以下原则。

### Principle 1：根据 narrative significance 判断

不要根据单个动词判断 Function。

同一个动作在不同上下文里可能具有不同 Function。

---

### Principle 2：忽略表层实现

不要因为：

```text id="avyp9y"
法宝
丹药
金钱
股份
魔法
技术
```

不同，就自动创建不同 Function。

首先判断它们是否承担相同的结构作用。

---

### Principle 3：寻找跨故事 invariant

Function 应尽量解释来自不同故事的多个 Observation。

---

### Principle 4：控制抽象粒度

太具体：

```text id="45pl7h"
ACQUIRE_DRAGON_SWORD
```

不好。

太抽象：

```text id="wju8r1"
IMPORTANT_CHANGE
```

也不好。

希望找到中间层次，例如：

```text id="5xqo6r"
RESOURCE_ACQUISITION
CAPABILITY_REVELATION
IDENTITY_REVELATION
POWER_ADVANCEMENT
```

---

### Principle 5：必须考虑反例

定义 Function 时同时问：

> 什么例子虽然非常相似，但不属于这个 Function？

Function 的意义不仅来自 positive examples，也来自它与相邻 Function 的边界。

---

### Principle 6：允许理论以后修改

早期不要为了得到一个“漂亮、完整”的 taxonomy 而过度设计。

允许后续 evidence 驱动：

```text id="6k115m"
MERGE
SPLIT
GENERALIZE
SPECIALIZE
```

Prompt 给的是：

> **构建 Function 的方法论**

而不是：

> **Function 的答案。**

---

# 8. 新故事进入以后如何处理

有了 \(O_0\) 以后，新的故事继续进入系统。

新故事仍然首先：

```text id="ptyvc7"
Story
↓
Observer
↓
Observations
```

然后每个 Observation 与当前 Function Registry 比较。

允许五种结果：

### MATCH

已有 Function 可以很好解释。

→ 增加 supporting evidence。

### EXTEND

Function 是对的，但出现一种新的 surface realization。

→ 更新 Function Card。

### NOVEL

现有 Function 都解释不了。

→ 放入 Novelty Pool。

### CONFLICT

看起来接近某个 Function，但和当前定义存在明显冲突。

→ 放入 Challenge Pool。

### UNCERTAIN

多个 Function 都可能解释。

→ 放入 Challenge Pool。

---

# 9. Novel Observation 怎么变成新 Function

Novel 不意味着马上创建新 Function。

例如第一次出现：

> 主角故意隐藏自己的真实能力，让敌人低估自己。

先：

```text id="v5nffa"
Novelty Pool
```

以后又出现：

```text id="sbrylm"
隐藏财富
隐藏身份优势
隐藏真实修为
故意装伤
```

如果多个不同故事的 Observation 呈现类似结构：

```text id="670ifo"
主动制造错误认知
↓
对手因此做出错误判断
↓
角色获得战略优势
```

才由 Function Inducer 提出：

```text id="nr63to"
STRATEGIC_CONCEALMENT
```

因此：

\[
Novel\ Cases
\rightarrow
Accumulation
\rightarrow
Cross\text{-}Story\ Comparison
\rightarrow
New\ Candidate
\]

---

# 10. 整个工作流是循环进化的

是。

整个 Function ontology 不是一次生成，而是持续经历：

\[
\boxed{
Observe
\rightarrow
Compare
\rightarrow
Induce
\rightarrow
Test
\rightarrow
Revise
\rightarrow
Observe\ More
}
\]

Function 可以发生：

```text id="x3zx03"
ADD
MERGE
SPLIT
RENAME
GENERALIZE
SPECIALIZE
DEPRECATE
```

例如：

早期可能得到：

```text id="xmvtes"
REVELATION
```

随着数据增加，发现：

```text id="3pr04h"
能力曝光
身份曝光
秘密曝光
```

虽然相似，但前置条件和后续影响不同。

于是：

```text id="w87scr"
REVELATION
↓ SPLIT

CAPABILITY_REVELATION
IDENTITY_REVELATION
SECRET_REVELATION
```

反过来，如果出现：

```text id="2gtvrz"
ABILITY_REVEAL
POWER_EXPOSURE
COMPETENCE_DISCLOSURE
```

后来发现其实没有实质区别：

```text id="gjjpof"
MERGE
↓
CAPABILITY_REVELATION
```

这就是 Function Evolution。

---

# 11. Agent 架构

第一阶段不需要过多 Agent。

## Agent A：Narrative Observer

```text id="smrr2g"
Story
→
Narrative Observations
```

负责理解故事。

不创建 Function。

---

## Agent B：Function Inducer

```text id="2a532j"
Multiple Similar Observations
→
Candidate Function
```

负责抽象跨故事共同结构。

---

## Agent C：Matcher / Critic

Matcher：

```text id="ddymwv"
Observation
→
MATCH / EXTEND / NOVEL / CONFLICT / UNCERTAIN
```

Critic：

寻找 hard cases，检查 Function 的边界。

---

## Agent D：Ontology Curator

负责周期性修改 Function Registry：

```text id="x9cn6s"
ADD
MERGE
SPLIT
REVISE
DEPRECATE
```

只有 Curator 修改正式 ontology。

---

## Retrieval Module

使用 embedding / retrieval：

```text id="2fgyf2"
Observation
→ similar Observations

Observation
→ nearest Functions

Function
→ potentially duplicated Functions

Function
→ hard-negative Observations
```

---

# 12. Embedding 在系统中的作用

Embedding 主要用于**寻找候选比较对象**，而不是直接决定 Function。

推荐 embed 的不是原始小说全文，而是 Observation 的结构化描述：

```text id="k42ubt"
Prior Context
Event
Before State
After State
Narrative Effect
Participant Relations
```

这样可以减少：

> 同类型小说因为“修为、宗门、灵气”等词相似而错误聚类

的问题。

Embedding 有三个主要用途：

### 1. Observation clustering / retrieval

找到可能具有相同 Function 的跨故事实例。

### 2. Function redundancy detection

寻找定义高度相似、可能需要 Merge 的 Functions。

### 3. Hard-negative retrieval

寻找与某个 Function 非常接近但当前属于其他 Function 的实例，用于检查边界。

---

# 13. 如何评价最后得到的 Function Ontology

不能只靠 LLM 说“这套理论看起来不错”。

评价至少包括六个维度。

## 13.1 Coverage

在完全没有参与 ontology 构建的 held-out stories 上：

> 有多少重要 Observation 可以由已有 Function 合理解释？

\[
Coverage=
\frac{\#Covered\ Observations}
{\#All\ Observations}
\]

---

## 13.2 Novelty Rate

新故事中，有多少 Observation 无法由现有 Function 解释：

\[
NoveltyRate=
\frac{\#Novel}
{\#All\ New\ Observations}
\]

随着 ontology 逐渐成熟，Novelty Rate 应整体下降。

---

## 13.3 Intra-Function Cohesion

同一个 Function 下的 Observation embedding 应比较接近。

可以计算每个 Observation 与 Function centroid 的平均 cosine similarity。

越高说明同一 Function 内部语义结构越一致。

---

## 13.4 Inter-Function Separation

不同 Function 应该能够区分。

可以计算：

- Function centroid similarity；
- Silhouette Score；
- nearest-neighbor confusion。

如果两个 Function embedding 几乎完全重合，可能应该 Merge。

---

## 13.5 Stability / Order Robustness

这是非常重要的指标。

使用同一 corpus，但改变：

```text id="ptxbfs"
story order
bootstrap sample
random seed
```

运行多次：

```text id="nejpuo"
Ontology A
Ontology B
Ontology C
```

然后把 Function definition 转成 embedding。

使用 Hungarian Matching 等方法寻找不同 ontology 之间的最佳 Function 对齐：

\[
F_i^A \leftrightarrow F_j^B
\]

计算最终 Function 集合的 semantic similarity。

如果不同 run 最终仍然得到高度相似的 ontology：

> 说明 Function 不是某次 prompt 偶然生成的。

---

## 13.6 Compression

我们希望少量 Function 能解释大量具体叙事事件：

\[
Compression=
\frac{\#Observations}
{\#Functions}
\]

但 Compression 不能单独使用。

例如只有一个：

```text id="zn1ewf"
IMPORTANT_EVENT
```

虽然 compression 极高，却没有任何理论价值。

所以最终需要综合：

\[
\boxed{
Coverage
+
Cohesion
+
Separation
+
Stability
+
Compression
+
Low\ Novelty
}
\]

---

# 14. 整个算法最后可以压缩成这一条主线

```text id="89wg4f"
Stories
   ↓
Narrative Observations
   ↓
Cross-story Retrieval & Comparison
   ↓
Candidate Functions
   ↓
Initial Function Ontology
   ↓
New Stories
   ↓
MATCH / EXTEND / NOVEL / CONFLICT
   ↓
New Evidence + Hard Cases
   ↓
Function Merge / Split / Revision
   ↓
Updated Ontology
   ↓
New Stories
   ↓
...
   ↓
Stable Function Ontology
```

或者写成：

\[
\boxed{
Observe
\rightarrow
Compare
\rightarrow
Abstract
\rightarrow
Test
\rightarrow
Revise
\rightarrow
Repeat
}
\]

这就是第一阶段需要完成的核心算法。

---

# 15. 需要重点参考的文献

文献主要分两类。

## A. Propp / Computational Narrative

### 1. Propp — *Morphology of the Folktale*

重点不是记31个 Function，而是理解：

> Function 应根据行为在整个故事进程中的作用定义，而不是根据具体人物和表面动作定义。

这是我们的理论起点。

### 2. Finlayson — Analogical Story Merging / Learning Narrative Structure

这是最直接值得参考的工作。

核心思想：

> 从多个具体故事结构开始，通过跨故事 analogy 和 merging，逐步形成更抽象的 narrative categories。

与我们：

\[
Observations
\rightarrow Comparison
\rightarrow Function
\]

非常接近。

重点研究它：

- 如何表示故事；
- 如何做跨故事比较；
- 如何从具体结构 generalize；
- 如何控制 abstraction。

### 3. Finlayson — ProppLearner

重点研究：

> 从自然语言故事到 narrative theory 之间需要什么中间表示。

它说明不能简单：

```text id="z4ch53"
Sentence → Function
```

而需要 richer semantic representation。

我们对应设计：

> Narrative Observation。

### 4. Valls-Vargas et al. — Predicting Proppian Narrative Functions

该工作是在已知 Propp Function 类别情况下做 Function prediction。

与我们的 open-world discovery 不同。

适合作为：

> **Propp-31 closed-world baseline。**

---

## B. Skill Evolution

这里不是学习它们的具体任务，而是学习：

> 一个不断增长的知识/技能库应该如何演化和维护。

### 1. SkillWeaver

重点：

> discover skill 和 hone skill 分开。

对应：

> Function discovery 和 Function refinement 分开。

### 2. MemSkill

重点：

> hard cases / failure cases 推动 skill evolution。

对应：

> NOVEL / CONFLICT / UNCERTAIN 应该成为 Function 演化的主要信号。

### 3. EvoSkill

重点：

> 一个新的 skill proposal 必须经过验证后才能加入 library。

对应：

> Candidate Function 不能直接进入 Stable Ontology。

### 4. SkillOps

重点：

> library 不断增长以后会出现重复、冲突和 technical debt，因此必须周期性 maintenance。

对应：

> Function Registry 必须支持 Merge / Split / Revision，而不是只允许不断新增。

---

# 16. 第一阶段最终需要交付什么

第一阶段完成时，希望得到四个东西：

### 1. Narrative Observation Schema

能够稳定执行：

```text id="ez7ahx"
Chinese Story
→
Structured Narrative Observations
```

### 2. Function Card Schema

明确一个 Function 如何被定义、存储和版本管理。

### 3. Function Evolution Pipeline

能够完成：

```text id="q8l0ev"
Discovery
Matching
Novelty Detection
Hard-case Analysis
Merge
Split
Revision
```

### 4. Chinese Narrative Function Ontology v1

并且能够在 held-out stories、不同 story orders 和不同 random runs 上进行定量评价。

---

最终整个项目第一阶段只需要记住一个核心思想：

> **我们不是让 LLM 看一个故事后给它贴 Propp 标签，而是先把很多故事转成可比较的叙事 Observation，再从跨故事重复出现的结构中归纳 Function；之后继续用新故事挑战这些 Function，让它们通过新增、合并、拆分和修改逐渐稳定。**