# CC Macro Analysis OS — 产品战略与路线图

**版本：** v2.0（Final）
**日期：** 2026-10-07
**取代：** v1.0（2026-10-06）
**文档地位：** Product North Star / Roadmap Authority。现有 implementation report、data policy、provider spec 只说明“已经实现了什么”。**未来做什么、先做什么、不做什么，一律以本文为准。** 本文与任何其他文档冲突时，以本文为准。
**修改权：** 只有 Owner可以修改本文。Coding agents 只能在 PR 描述中提出修改建议，不能直接改写。

> **放入 repo 的方式：** 本文保存为 `docs/PRODUCT_STRATEGY.md`，并在 `AGENTS.md` / `CLAUDE.md` 顶部加入一行：
> `Before writing any ExecPlan, read docs/PRODUCT_STRATEGY.md and follow §20 Agent Operating Contract.`

---

## 0. Current Focus（由 Owner 更新；每次 ExecPlan 必须先读这一节）

| 项 | 当前值 |
|---|---|
| 当前 Phase | **Phase A — Release Copilot v0 + Shadow Live** |
| 下一个硬日期 | **2026-10-14 09:30 北京时间：9 月 CPI/PPI（Live #1）** |
| 之后的硬日期 | 2026-10-19 10:00：2026Q3 GDP + 9 月经济活动（Live #2）；10 月底：10 月 PMI（Live #3，以 NBS 日历为准） |
| 下一个 Gate | G-A（见 §14） |
| 唯一 P0 | 每次 release 后 48 小时内发布 analyst update，Copilot 是否就绪都不影响这一条 |
| 冻结事项 | 见 §15 |

---

## 1. 一页纸 Charter

**North Star：** CC Macro 把可信的宏观事实转化为有纪律的研究更新。确定性软件回答“发生了什么”，AI 研究“这意味着什么”，分析师决定“应该相信什么”。

**这个项目要证明的产品命题：**

> 在高风险研究场景中，AI 应该放在哪里、不该放在哪里，以及怎样证明它确实创造了增量价值。

**我们押注的产品洞察：**

1. 宏观研究的瓶颈不在数据，而在**相对于既有观点的边际解释**。
2. LLM 在三件事上明显强于传统程序：解释、提出替代假说、识别语义变化。在三件事上明显弱于传统程序：数字、时点、一致性。系统应按这个边界切分。
3. **真实运行记录不能事后补造。** 每错过一次 release，就永久失去一个数据点。

**我们不做的：** 宏观 chatbot、自动观点生成器、多 agent 编排演示、数据终端。

**当前研究问题（不变）：** 中国名义增长是否正在形成可持续拐点？

---

## 2. 战略判断：哪里对了，哪里偏了

### 2.1 已经做对、并且应当保留的

官方数据抓取、point-in-time 与 vintage、预注册、lineage、evidence tests、自动刷新、public/private 边界、E0–E5 确定性 eval。这些已经构成一个**可信的事实层**，在个人项目中少见。

### 2.2 偏离的地方

过去的进展是用“系统更不可能出错”来衡量的，而不是用“系统更有用”来衡量。结果有三点：

- 公开站点读起来像一个严谨的数据系统，**AI 的角色几乎不可见**；
- 预注册之后，**真实的研究循环还没有跑过一次**；
- 首屏服务的是一位想象中的审计者，而不是三分钟内想看懂结论的读者。

### 2.3 本版的根本转向

> **从“先把系统做对，再证明它有用”，转为“用真实运行、真实评测、真实用户证明核心循环有价值；只有在真实使用中暴露的问题，才值得继续工程化”。**

进展只看三类数字：**Real runs、Evaluation results、Real users。** 版本号、测试数量、provider 数量都不算进展。

---

## 3. 用户与 Job-to-be-Done

### 3.1 初始用户

已经持有明确宏观观点、需要长期维护研究结论的专业或半专业研究者：宏观策略研究员、受中国宏观变量驱动的权益研究员，以及使用固定框架的个人研究者。

### 3.2 JTBD

> 新的宏观数据或政策出来时，帮我快速看清**相对于我之前的观点，到底变了什么**：哪些解释站得住，最强的反方解释是什么，下一步该研究什么。不要逼我重翻全部资料，不要编数字，也不要偷偷替我改观点。

### 3.3 当前替代流程与差异化

今天的流程：`等 release → 找数据 → 更新 Excel → 看图 → 翻政策文件 → 翻旧笔记 → 脑中映射 thesis → 重写一段观点 → 数周后忘记当时为什么改`

目标流程：`release detected → deterministic factual update → AI research delta → analyst review → versioned research state`

| 替代品 | 它做不到的 |
|---|---|
| 卖方点评 | 不针对**你的** prior；不记录你为什么改；不区分事实与解释 |
| ChatGPT / 通用 research agent | 没有持久研究状态；数字与时点不可信；容易被最新输入带着走 |
| Wind / 数据终端 | 只有数据，没有解释层和假设映射 |

**差异化一句话：针对一个明确的 prior belief，做有状态、可审计、可评测的边际研究。**

---

## 4. 产品原则（具有约束力）

**P1. Deterministic before probabilistic。** 有确定性答案的任务一律用 Python / API / SQL / rules / scheduler，包括数据抓取、解析、YoY/MoM/滚动均值/平减指数计算、as_of 与 vintage、阈值判断、发布日历、去重、lineage、版本管理、引用绑定和数据质量检查。

**P2. AI 是 Research Copilot，不是 Calculator。** AI 只进入传统程序最弱的环节：判断什么变化是 material、映射到哪个假设、提出替代解释、识别政策措辞的语义变化、排序下一步研究问题、指出哪些结论还不能下。

**P3. 事实、解释、判断三层分离。** `Observation → Interpretation → Hypothesis Impact → Analyst Judgment`。解释不能伪装成事实，AI 建议也不能直接变成人的 conviction。

**P4. 让幻觉在结构上无法表达（Unrepresentable Hallucination）。** AI 输出中的数字一律写成对观测值或派生值的引用占位符，例如 `{obs:cn_ppi_yoy@2026-09}`，由确定性 renderer 填入真实值。AI 不能直接写出任何阿拉伯数字形式的数据。目标是在构造上做到“数字幻觉 = 0”，而不是事后去抓。

**P5. Point-in-time 包括模型自身的知识。** 数据的 as_of 纪律不能阻止模型凭训练数据“知道未来”。Replay 和评测必须处理模型知识污染（见 §10）。

**P6. Closed-book by default。** Copilot 默认只使用 Context Builder 提供的上下文，不联网检索。它可以调用自身的背景知识来提出替代假说（这正是 LLM 的价值所在），但必须标注为 `background_knowledge`，不得携带数字，也不得作为 evidence 引用。

**P7. “不更新”是成功结果。** 噪音、尚不足以确认、替代解释仍然成立、thesis 不变，这些都是合格的产出。

**P8. Human owns the thesis。** 概率、conviction、Standing Thesis 只能由分析师修改。AI 不输出概率数字。

**P9. 节奏优先于功能（Cadence over Features）。** 发布节奏是不可补造的资产。**任何 AI 功能都不能阻塞 release update。** Copilot 不可用时，分析师照常手写 update，并标注 `copilot: unavailable`。这本身也是一个对照数据点。

**P10. Infrastructure 必须服务已观察到的问题。** 新的抽象、路由、数据源或部署工程，只有在以下情况之一成立时才进入优先级：真实 workflow 被阻塞；replay 或 live run 暴露了具体 failure；evaluation 显示它是主要质量瓶颈。

---

## 5. 产品架构：四层分工

### 5.1 四层

**Layer A — Deterministic Data Plane。** 构造可信、可重放的 point-in-time information set。输出包括新旧观测值、修订、派生指标、来源与发布元数据、evidence-test 状态及其**相对上期的翻转**、政策文档元数据和局限说明。这一层越 boring、越便宜越好。

**Layer B — Research Context Builder。** 由代码决定模型能看到什么，绝不整库 dump。上下文包括：Standing Thesis、H0–H4 的定义与当前状态、本次新增观测值、确定性趋势特征、test 翻转、相关政策事件、上一期 accepted update、未决的 Research Needs，以及可引用的 evidence ID 白名单。这一层是控制幻觉、成本和研究蔓延的关键。

**Layer C — AI Research Copilot。** MVP 只做一个 Release Copilot，分两次调用完成（§8）。Policy Delta 放到 Phase D。

**Layer D — Human Judgment & Publication。** 分析师选择 Accept / Edit / Reject / Keep unresolved。公开网站只展示**经人审核后的 research state**。

### 5.2 跨项目通用模式：Deterministic Diff, AI Interprets

凡是“变化检测”，一律先由代码算出 diff，再交给 AI 解释 diff 的含义：

- 数据 release：代码算出 level / marginal / breadth 变化和 test 翻转 → AI 解释其研究含义；
- 政策文本（Phase D）：代码对新旧官方文本做逐句 diff，标记新出现、消失和强化的措辞 → AI 判断意图、工具、执行阶段和传导状态。

AI 永远不负责“发现哪里变了”，只负责“变化意味着什么”。这能同时降低幻觉、成本和遗漏。

### 5.3 责任矩阵

| 工作 | 负责方 | 技术 | 验证方式 |
|---|---|---|---|
| 抓数、清洗、计算、阈值、test 翻转 | 代码 | Python / API / rules | E0–E3 |
| 发现变化（数据或文本 diff） | 代码 | 计算 / 文本 diff | 单元测试 |
| 判断 material 与否、映射假设 | AI | LLM + 有界上下文 | Gold set（§11） |
| 替代解释、反方论证 | AI（Challenge pass） | LLM | 分析师评分 |
| “不能推出什么” | AI | LLM | 分析师评分 |
| 下一步研究问题 | AI | LLM | 采纳率 |
| 数字渲染与引用校验 | 代码 | 占位符渲染、ID 白名单 | Hard gates（§11.2） |
| 概率、conviction、thesis 变更 | 人 | — | E5 |
| 终局规则判定 | 代码 | 预注册规则 | E4 / E5 |

---

## 6. 核心产品对象

| 对象 | 定义 |
|---|---|
| Research Thesis | 当前宏观判断，含概率、conviction 和 as_of |
| Hypothesis | H0–H4 等相互竞争的解释 |
| Release / Policy Event | 带时间、来源和信息边界的新事件 |
| Evidence Delta | 相对 prior state 的新增事实变化（确定性生成） |
| **Expectation Note** | release 之前冻结的预期与情景映射（§9） |
| Research Interpretation | AI 对 delta 的结构化解释 |
| **Divergence** | AI 的判断方向与确定性 test 方向不一致之处（§8.4） |
| Research Need | 尚待回答、且答案可能改变判断的问题 |
| Analyst Decision | 对 AI delta 的 Accept / Edit / Reject / Keep unresolved，含编辑 diff 与原因 |
| **Run Record** | 每次 AI 运行的完整、不可变记录（§6.1） |
| Research State Version | 某一时点真实有效的完整研究状态 |

### 6.1 Run Record（评测与审计的底座）

每次 AI 调用都写入一条 append-only 记录：

`run_id · run_at · as_of · release_id · model_id 与版本 · prompt/schema 版本 · context hash 与所含 evidence ID 列表 · raw output · validation 结果 · rendered output · tokens / cost / latency · analyst blind take（§11.4） · analyst decision 与 edit diff`

没有 Run Record 的 AI 输出，不得公开展示，也不得计入评测。

---

## 7. 核心循环与运营节奏

### 7.1 核心循环

```text
Release Calendar / Policy Event
        ↓
[T-1] Expectation Note 冻结（分析师预期 + AI 情景映射）
        ↓
[T0]  Deterministic Acquisition → Point-in-time Facts → Evidence Delta + Test Flips
        ↓
      Context Builder（有界上下文）
        ↓
      Release Copilot
        Pass 1 Draft：What Changed · Hypothesis Impact · Divergence
        Pass 2 Challenge：Competing Explanation · Does NOT Prove · Research Needs
        ↓
      Validation（占位符渲染 · ID 白名单 · as_of 检查）
        ↓
[T+≤48h] Analyst：Blind Take → 阅读 Copilot → Accept / Edit / Reject / Keep unresolved
        ↓
      Versioned Research State + 公开 Update + Expectation 计分
```

### 7.2 运营节奏（Operating Rhythm）

| 时点 | 动作 | 负责方 |
|---|---|---|
| T-1 至 T-3 天 | 冻结 Expectation Note：3–5 个关键读数的方向与区间，加 AI 生成的“若 A 则……/若 B 则……”情景映射 | 分析师 + AI |
| T0 | 自动抓取 → test 重算 → Copilot 运行（Shadow 或正式） | 代码 + AI |
| T+0 至 T+48h | Blind take（≤5 分钟）→ 审阅 → 决策 → 发布 | 分析师 |
| T+48h | Expectation 计分（确定性）；Run Record 归档 | 代码 |

**节奏纪律：** 每个被检验的 release 都必须在 48 小时内发布 update，包括“No material thesis change”的情况。这是 Phase B 之后最重要的运营指标。

---

## 8. Release Copilot MVP 规格

### 8.1 输入（全部由代码组装）

release identity 与时间戳；最新值与前值；确定性派生特征（3 个月动量、相对 6 个月前的变化、breadth）；本次 test 翻转；H0–H4 当前状态；Standing Thesis；上一期 accepted update；未决的 Research Needs；本期 Expectation Note；evidence ID 白名单。

### 8.2 两次调用，而不是多 agent

- **Pass 1 — Draft：** 生成 Executive Delta、Hypothesis Impact 和 Divergence。
- **Pass 2 — Challenge：** 只看到事实与 Pass 1 的草稿，任务是提出最强的替代解释、指出“这不能证明什么”，并给出最多 3 个 Research Needs。

把 Challenge 拆成独立的一次调用，目的是对抗同一上下文中的自我确认和 sycophancy。这不算 multi-agent architecture，不需要编排框架。

### 8.3 输出 Schema（结构化，不输出长篇 essay）

```yaml
release_id: cn_cpi_ppi_2026-09
as_of: 2026-10-14T01:30:00Z
executive_delta:            # 最多 5 条
  - id: X1
    template: "PPI 同比由 {obs:cn_ppi_yoy@2026-08} 变为 {obs:cn_ppi_yoy@2026-09}"
    lens: level | marginal | breadth | mechanism
    materiality: high | medium | low
    evidence_refs: [obs:cn_ppi_yoy@2026-09, obs:cn_ppi_yoy@2026-08]
    vs_expectation: inside | above | below | not_set
hypothesis_impact:          # H0–H4 每个都必须有一条
  - hypothesis: H1
    mechanical_delta: supports | challenges | unchanged   # 由代码填入，AI 不能修改
    ai_assessment: strengthen | weaken | unchanged | unresolved
    divergence: true | false
    divergence_reason: "..."   # divergence 为 true 时必填
    rationale_template: "..."
    evidence_refs: [...]
competing_explanation:
  claim: "..."
  why_plausible: "..."
  discriminating_observation: "下一条什么数据最能区分两种解释"
  evidence_refs: [...]
  background_knowledge: ["..."]   # 可选；不带数字；不作为 evidence
does_not_prove: ["...", "..."]
research_needs:             # 最多 3 条，按信息价值排序
  - question: "..."
    hypothesis: H2
    why_now: "..."
    decision_it_could_change: "..."
    resolving_data: "哪条数据或文件可以回答这个问题"
draft_analyst_update:
  text_template: "..."
  direction_hint: hold | consider_up | consider_down   # 不给数字；分析师完成 blind take 之后才显示
```

### 8.4 Divergence 是这个产品最有价值的输出

确定性 test 只看规则，AI 能看到规则看不到的东西，比如基数效应、口径变化、一次性因素和结构错位。规则如下：

- AI **不能修改** `mechanical_delta`；
- 当 AI 的判断方向与 mechanical 方向不一致时，必须设置 `divergence: true` 并说明原因；
- Divergence 在 UI 中置顶显示，并单独计入评测：**分析师认可的 divergence 所占比例**。

这正是对“AI 比 Python 多做了什么”的最直接回答。

### 8.5 双语规则

AI 只用一种 canonical language 生成内容，另一种语言通过受约束的翻译得到，所有占位符和数字绑定保持不变，继续复用 E1 的双语一致性检查。AI 不分别独立生成两种语言版本。

### 8.6 界面阅读顺序

**What Changed → vs Expectation → Divergence → Why It Matters → Counter-case → What We Still Don’t Know → Analyst Decision。** Technical lineage 保留，但放到第二层。

---

## 9. Expectation Note 与 Track Record

### 9.1 为什么需要它

thesis 级别的概率每年只能检验一次，样本太少。**release 级别的预期每月可以产生多个可计分的数据点。** Expectation Note 把每次 live run 都变成一次可计分的预测，同时也是对“事后合理化”的结构性约束。

### 9.2 内容

- **分析师预期：** 3–5 个关键读数的方向（相对前值）与区间，T-1 前冻结并提交 commit。
- **AI 情景映射：** 针对“若 PPI 环比转负”“若核心 CPI 回升”等 2–4 个情景，预先写出各自的研究含义。

### 9.3 计分与使用

- 代码对方向命中率和区间命中率做确定性计分，结果累积成公开的 Track Record 表；
- 发布后，比较 Copilot 的事后解释与它自己的事前情景映射。**如果事后解释和事前映射不一致而又没有说明理由，就记为“post-hoc drift”，计入 failure taxonomy。**

### 9.4 纪律

Expectation Note 是低成本的仪式：每次不超过 20 分钟。它不改变 thesis，不进入 evidence tests，不改变预注册规则。

---

## 10. Historical Replay 与两种“后见之明”

### 10.1 Replay 与生产使用同一条代码路径

Replay 不是一个单独的“模式”，而是**把时钟设为 T 的生产 pipeline**：`refresh(as_of=T)` → Context Builder → Copilot。这保证 replay 测试的就是生产代码，不需要维护第二套系统。

### 10.2 后见之明一：框架污染

H0–H4 是在 2026 年 10 月设计的，设计时已经看到了 2026 年的数据。所以用历史 release 做 replay，**评测的是“在给定框架下的解释能力”，而不是框架本身的预测能力。** 框架的预测力只能通过 live run 和终局规则来检验。这一局限必须在 Method 页面明确写出。

### 10.3 后见之明二：模型知识污染

数据的 as_of 拦不住模型凭训练数据“知道后来发生了什么”。缓解措施如下：

1. 对每个参与评测的模型，在 Run Record 中记录其公开的知识截止时间；
2. Replay 案例**优先选在所有被测模型的知识截止时间之后**，也就是优先使用 2026 年内的 release；
3. **Contamination probe：** 正式评测前，直接询问模型“T 之后该指标发生了什么”。若模型能答出来，该案例标记为 `contaminated`，单独报告，不计入主指标；
4. **只有 live run 是完全无污染的评测。** 这是坚持 live 节奏的又一个理由。

---

## 11. AI Research Evaluation

### 11.1 Gold Set 构建协议

- **规模：** 第一版 12–20 个 historical release 案例，优先 2026 年内（见 §10.3）。
- **标注先于运行：** 每个案例**先由人标注、提交 commit，再第一次运行模型**，否则标注会被模型输出锚定。
- **标注内容：** material changes、受影响的假设及方向、合理的替代解释、禁止推出的结论、价值最高的下一步问题。参考答案不要求唯一，但必须让分歧可以检查。
- **Dev / Test 划分：** prompt 和 schema 只在 dev 集上迭代，test 集只用来报告结果。test 集的结果不能反过来用于调参。
- **第二标注者：** 至少 1/3 的案例由第二位研究者独立标注，报告一致率。分歧大的项标为 `ambiguous`，不计入准确率。
- **小样本诚实：** 报告时同时给出计数与比例，例如“7/9”，不使用夸大的百分比，也不把第一轮结果包装成模型性能结论。

### 11.2 Hard Gates（目标为 0）

- 数字 grounding 错误（P4 已在构造上保证）；
- 无效的 evidence 引用（不在白名单内）；
- 未来信息泄漏（as_of 违规）；
- 修改 `mechanical_delta`；
- 经过 validation 后仍被发布的 unsupported factual claim。

### 11.3 研究质量指标

| 指标 | 定义 |
|---|---|
| Hypothesis attribution agreement | AI 映射的假设与方向和 gold set 的一致率 |
| Material-change precision | AI 标为 material 的变化中，真正 material 的比例 |
| Material-change recall | gold set 中的 material 变化被 AI 捕获的比例 |
| **Divergence validity** | AI 提出的 divergence 中，被分析师认可的比例 |
| Counter-case usefulness | 分析师 1–3 分评分 |
| Research-need adoption | AI 提出的问题真正进入后续研究的比例 |
| **Post-hoc drift rate** | 事后解释与自身事前情景映射不一致且未说明理由的比例 |
| Acceptance / edit rate | 各 section 的 Accept / Edit / Reject 分布与编辑类别 |
| Time-to-draft | release 可得 → analyst-ready draft 的时间 |
| Cost per release | 每次 release 的 token 与费用 |

### 11.4 AI 增量价值：Blind Take 协议

这是回答“AI 到底多做了什么”的核心测量：

1. 分析师在**看 Copilot 输出之前**，用不超过 5 分钟写下 3 行 blind take：最重要的变化、对哪个假设有影响、方向；
2. 然后阅读 Copilot 输出并做决策；
3. 代码记录 **AI marginal insight rate**：Copilot 提出了 blind take 中没有、且最终被 accepted 的 material point 的 release 所占比例。

这个指标直接衡量 AI 对人的增量价值，而不是衡量 AI 写得像不像人。

### 11.5 不作为核心证据的东西

单独的 LLM-as-judge（只可作为辅助，并且需要先与人工评分校准）、模型自评置信度、测试总数、provider 数量、生成文字长度。

### 11.6 Evaluation 必须驱动产品决策

每一轮评测至少产生一条记录：`Failure observed → Root cause → Change（product / prompt / schema / model / 接受的局限）→ Re-measured result`。

---

## 12. AI 明确禁止承担的任务

1. 写出上下文中不存在的数字，或直接写任何数据数字（P4）；
2. 用自然语言重算确定性指标；
3. 判断终局规则是否触发；
4. 修改预注册规则或 `mechanical_delta`；
5. 输出或修改概率与 conviction 数字；
6. 把模型置信度当作正确性；
7. 在 replay 中使用未来信息，或在未经 contamination probe 的案例上报告主指标；
8. 把没有 evidence 的解释作为事实发布；
9. 因为“有工具”而无限扩展检索（MVP 为 closed-book）；
10. 一条 release 只影响部分假设时，仍然重跑整个研究 corpus。

---

## 13. 公开网站叙事

### 13.1 硬约束

- **唯一对外域名为 `ccmacrors.vercel.app`。** canonical、og:url、og:image 全部指向vercel。
- 公开站点必须**始终处于可演示状态**，main 分支不能出现坏的首屏。

### 13.2 首页结构（服务三分钟读者）

1. **Current View**：thesis、概率、conviction、as_of；
2. **What Changed Recently**：最近一次 accepted research delta，包括 Divergence；
3. **Track Record**：Expectation vs Outcome 表、连续准时更新的次数；
4. **How AI Is Used**：本次 AI 做了什么、被禁止做什么，并链接到 Method；
5. **Hypothesis State**：H0–H4 的白话状态；
6. **Next Releases & Open Questions**；
7. Key Evidence；
8. Method / Audit（第二层阅读）。

### 13.3 Release Update 页面

每条 update 是一份 research decision record：

`Event → Expectation → Facts → AI Interpretation → Divergence → Counter-case → Analyst Blind Take → Analyst Action → Before/After Thesis → Unresolved Questions`

### 13.4 Method 页面新增

- **Where AI Is Used — and Where It Is Forbidden**：责任矩阵（§5.3）加禁止清单（§12）；
- **Two Kinds of Hindsight**：§10.2 与 §10.3 的公开说明；
- **AI Evaluation**：gold set 规模、指标表、failure taxonomy、一条 failure → change 的真实案例。

术语规则：首屏不出现 T-H1-05、RETIRED、amendment 之类的内部标识，这些只留在第二层。

---

## 14. Roadmap：按 Proof Gate 推进，不按版本号

### Phase A — Release Copilot v0 + Shadow Live（2026-10-07 至 10-14）

交付：
- Context Builder 加两次调用的 Copilot，带占位符渲染和 ID 白名单校验；
- Run Record；
- 3 个 replay 案例（2026 年内 release），完成标注后再运行；
- 10-14 的 Expectation Note；
- Method 页面加入 “Where AI Is Used” 初版；
- 修正 canonical / og 指向 vercel。

**G-A：** Copilot 能在 as_of=T 的 replay 上产出通过全部 hard gates 的结构化 delta；10-14 当天至少以 Shadow 方式运行，即使输出不公开，Run Record 也必须完整。

### Phase B — First Live Research Updates（2026-10-14 至 10 月底）

交付：Live #1（CPI/PPI）、Live #2（GDP + 活动数据，首次检验平减指数相关 test）、Live #3（PMI）；每次都走完整的 blind take → 决策 → 公开 update；首页按 §13.2 重构。

**G-B：** 至少 2 次 live release 完成 `deterministic → AI → blind take → human decision → published` 全链路，均在 48 小时内发布；Track Record 表上线。

### Phase C — Small AI Evaluation Set（10 月下旬至 11 月中旬）

交付：12–20 个案例的 gold set，含 dev/test 划分和第二标注者；baseline 指标；contamination probe；failure taxonomy；**至少一次由评测数据驱动的修改**。可选：在同一 test 集上对比 2–3 个模型（只需一个最小的调用适配函数，不建 provider 框架）。

**G-C：** 能用数据说明最常见的 failure mode，并展示一条完整的 `failure → change → re-measured` 记录。

### Phase D — Policy Delta Analyzer（G-C 之后）

只处理官方一手文本：政治局会议、国务院常务会议、PBOC、财政部。确定性逐句 diff 加 AI 语义判断（意图 / 工具 / 执行阶段 / 传导）。不做泛新闻摘要。

### Phase E — Persistent Research Queue

把 Research Need 变成长期对象：问题、状态、能回答它的数据、答案会改变什么。

### Phase F — Broader Macro OS（多次真实运行证明价值之后）

多个宏观 thesis、跨 thesis 的证据复用、宏观 → 行业 → 公司的传导（与 Living Thesis 的招商银行案例对接）、情景图、私有数据。

### 日历总览

| 日期 | 事件 | 产出 |
|---|---|---|
| 10-07 至 10-13 | Phase A 开发 | Copilot v0、3 个 replay、Expectation Note |
| 10-14 | 9 月 CPI/PPI | Live #1（Shadow 或正式） |
| 10-19 | Q3 GDP + 9 月活动数据 | Live #2 |
| 10 月底 | 10 月 PMI | Live #3 |
| 10 月下旬至 11 月中旬 | Phase C | Gold set、baseline、一次 eval 驱动的修改 |
| 11 月中旬 | 10 月 CPI/PPI、信贷数据 | Live #4、#5 |

---

## 15. 停止事项与优先级规则

### 15.1 G-C 通过之前默认冻结

新一轮 provider-neutral 抽象；通用 source routing；与研究问题无关的 Wind 扩展；更多宏观 thesis；大量新增指标；更多预注册机制；为提高测试数量而写的测试；非阻塞的部署完善；公开 chatbot；为显得 agentic 而引入的 multi-agent 编排。

只有 P0/P1 级别的真实 bug 可以越过冻结。

### 15.2 Feature Prioritization Rule

每个任务开工前回答：

1. 它是否显著提升用户理解 **What Changed and Why** 的能力？
2. 它是否产生新的 live proof、用户结果或 evaluation 数据点？
3. AI 在这里是否真的必要，还是用确定性代码更合适？
4. 它是否来自 replay、live 或用户测试中已经观察到的 failure？
5. 如果未来两周不做，是否会实质削弱当前的求职 deliverable？

**少于 2 个回答为“是”，默认 defer。** 如果是 infrastructure 类任务，还必须写明“没有它，哪一个具体的产品行为被阻塞”，写不出来就不做。

---

## 16. 成功指标

### 16.1 近期

- 准时更新连续次数（48 小时内发布的 release 数 / 被检验的 release 数）；
- 完整走通 end-to-end 的 live release 次数；
- Hard gate 通过率（目标 100%）；
- AI marginal insight rate；
- Divergence validity；
- 各 section 的 Accept / Edit / Reject 分布；
- Expectation 方向命中率（Track Record）；
- 由评测直接触发的产品修改次数；
- 不读技术文档就能理解核心价值的真实研究者人数。

### 16.2 长期

每次重要 release 节省的研究时间、漏掉的重要变化、虚假 materiality 比例、thesis 状态的稳定性与质量，以及研究状态在宏观、行业、公司之间的复用程度。

**不算进展的：** 页面数、provider 数、测试数、token 消耗。

---

## 17. Portfolio Evidence 与面试叙事

### 17.1 三分钟叙事

> “宏观研究是一个高风险场景：LLM 容易算错数字、丢失来源、被最新信息带着改写叙事。所以我把数据、计算、vintage、阈值和审计都交给确定性软件，并且让模型在结构上**无法写出**数字。AI 只用在程序最弱的地方：解释边际变化、映射相互竞争的假设、提出反方解释、决定下一步研究什么。它和规则判断不一致的地方，恰恰是它最有价值的输出。我还发现 point-in-time 不只是数据问题，模型本身也会凭训练数据‘知道未来’，所以评测优先用模型知识截止之后的样本，并且以 live run 为准。每次 release 之前，我会冻结自己的预期；看 AI 之前，我会先写下自己的判断，这样能直接测出 AI 比我多看到了什么。thesis 最终由我决定。”

### 17.2 必须具备的实物证据

- 一张真实的 live release 时间线（Track Record）；
- 一个 replay 的 before / after；
- 一条 `failure → change → re-measured` 记录；
- 一张 evaluation 表，含小样本计数；
- 一张 deterministic / AI / human 责任图；
- 一个 AI marginal insight 的真实案例：AI 看到了、我当时没看到。

### 17.3 按岗位调整重点

| 目标岗位 | 主讲 |
|---|---|
| AI PM（Kimi / DeepSeek 等） | 责任边界、无法表达的幻觉、两种后见之明、blind take 增量测量 |
| 公募宏观或策略研究 | Track Record、假设框架、Divergence 案例 |
| AI 方向的成长股权投资 | 研究纪律，以及 AI 如何改变研究的生产函数 |

---

## 18. 当前战略阶段的 Definition of Done

满足以下全部条件，CC Macro 才算完成从“严谨的数据系统”到“AI Macro Research OS”的跨越：

1. 至少 2 个真实的 post-baseline release 完整跑通，且都在 48 小时内发布；
2. Copilot 输出 grounded 的结构化 delta，hard gates 全部通过；
3. 至少 3 个 replay 案例完成 point-in-time 评测，并经过 contamination probe；
4. 有第一版 gold set、baseline 指标和公开的 failure taxonomy；
5. 至少一次产品修改由评测数据驱动；
6. 公开站点能讲清楚 AI 用在哪里、禁在哪里，以及两种后见之明；
7. 至少一位真实研究者不读技术文档就能理解并使用核心 workflow。

在此之前：**More infrastructure is not strategic progress.**

---

## 19. Decision Log（已决策事项；agents 不得重新讨论）

| ID | 决策 | 理由 |
|---|---|---|
| D-01 | 确定性优先；AI 只做解释层 | 可靠性与可评测性 |
| D-02 | AI 不写任何数据数字，一律使用占位符 | 构造上消除数字幻觉 |
| D-03 | Live 节奏永远不等 AI | 真实运行记录不可补造 |
| D-04 | 两次调用（Draft / Challenge），不做 multi-agent | 对抗 sycophancy 的最低成本方案 |
| D-05 | Replay 与生产共用 `as_of` 路径 | 测的就是生产代码 |
| D-06 | Closed-book；背景知识可用但需标注且不带数字 | 平衡 grounding 与 LLM 的推理价值 |
| D-07 | AI 不输出概率数字；direction_hint 在 blind take 之后才显示 | 避免锚定，保证可测量 |
| D-09 | Wind 私有模式冻结 | 与当前 proof 无关 |
| D-10 | 评测优先使用模型知识截止之后的样本，并做 contamination probe | 防止模型知识泄漏 |

---

## 20. Agent Operating Contract（适用于 Codex / Claude Code）

1. **先读后做。** 每次 ExecPlan 的第一段必须写明：本任务推进的 Phase 与 Gate（§14），以及对 §15.2 五个问题的逐条回答。
2. **不满足规则就停。** 回答“是”少于 2 个，或者 infrastructure 任务写不出被阻塞的产品行为时，只提交一份 Deferred 说明，不写代码。
3. **不允许自我繁殖任务。** 执行中发现的后续技术工作一律写入 PR 的 `Deferred` 列表，不得在同一任务中顺手完成，也不得自动开启下一轮任务。
4. **纵向切片。** 优先做能从数据一路贯通到公开 UI 或评测表的最小切片，而不是先把某一层做完整。
5. **AI 功能 PR 必须附带：** Run Record 样例、hard gates 结果、至少一个失败案例，以及对相关指标的影响（哪怕只是“尚无数据”）。
6. **不得破坏可演示性。** main 分支的公开首屏必须始终可用。
7. **不得越权。** 不得修改本文件、预注册文件或 `mechanical_delta` 逻辑；不得引入新的数据源、provider 或依赖，除非 Owner 在 Current Focus 中写明。
8. **硬日期优先。** §0 列出的 release 日期前后 48 小时内，只允许做服务于该次 live run 的工作。
9. **完成的定义。** 完成意味着在公开站点或评测表上可见，而不是“测试通过”。

---

## 附：相对 v1.0 的主要修订

1. 新增 **Unrepresentable Hallucination**（P4）：从“检查数字”升级为“结构上不能写数字”。
2. 新增 **模型知识污染**（P5、§10.3）：point-in-time 的定义扩展到模型自身的知识，并提出 contamination probe。
3. 新增 **Cadence over Features**（P9）：Live 节奏永远不等 AI，修正 v1.0 中“先 replay 再 live”可能导致错过 10-14 的风险。
4. 新增 **Expectation Note 与 Track Record**（§9）：把 thesis 级别一年一次的检验，变成 release 级别每月多次可计分的检验，并约束事后合理化。
5. 新增 **Divergence**（§8.4）：把“AI 比规则多做了什么”变成一个显式、可评测的对象。
6. 新增 **Blind Take 协议**（§11.4）：直接测量 AI 对人的增量价值。
7. 四个 Copilot 模块收敛为 **两次调用的 Release Copilot**；Policy Delta 推迟，并统一为“deterministic diff, AI interprets”模式。
8. Gold set 协议补充：先标注后运行、dev/test 划分、第二标注者、小样本诚实。
9. 新增 Run Record、Decision Log、Agent Operating Contract、带日期的日历和 Current Focus。
10. 明确 netlify.app 为唯一公开域名，并修正 canonical / og 指向。
