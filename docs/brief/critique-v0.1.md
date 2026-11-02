# Critique of Project Brief v0.1

> Reviewer: Claude · 2026-10-03
> 配套文件：`project-brief-v0.2.md`（修订后的完整 brief）

先说结论：v0.1 的**研究哲学是对的**，这是它最难得的部分：Research System 优先于 Agent、重视 information set（release date / vintage / consensus）、thesis + falsifier、Fact / Derived / External View / Inference 的区分、以及明确的"不做"清单。这些在 v0.2 全部保留。

真正的问题不在方向，而在**可执行性**：v0.1 口头上说"V1 只做一个 case"，但 Definition of Done、输出清单和数据层要求实际上描述的是整个系统的浅层版本。下面按重要性排序。

---

## 1. Scope 自相矛盾：说的是"一个 case"，要求的是"整套系统"（最重要）

数一下 v0.1 对 V1 的实际要求：

| 维度 | v0.1 的 V1 要求 |
|---|---|
| Research modules | 10 个 |
| Output 类型 | 7 种（Dashboard、Release Note、Policy Note、Weekly、Deep Dive、Thesis Tracker、Ask Macro） |
| Data providers | 5 个抽象接口 |
| Evidence 管线 | 数据 + 政策 + 新闻 + 券商研报结构化抽取 |
| 开源项目吸收 | 5 个 |
| DoD | Snapshot + Memo + Thesis Tracker + Ask Macro + 更新机制 + 陌生人可启动 |

第 14 节的 pipeline（Wind → … → research memo → dashboard → Ask Macro）里每一个箭头都是一个子项目。**"只做一个问题"并没有真正缩小范围，因为每一层都还要做出来。**

**为什么这是头号问题**：范围失控的典型结局不是"做得慢"，而是每一层都做到 60%，没有任何一层能拿出来展示。对 Goal B（作品）而言，一个深度做透的闭环远强于七个半成品。

**v0.2 的处理**：V1 = 1 个问题 × 1 个 thesis × ≤30 个指标 × 3 种输出（Deep Dive、Thesis Card、Release Update）× 1 次真实更新。Snapshot 降级为 case 图表的副产品；Policy Note、Weekly、新闻管线、研报库、通用 Ask Macro 全部移到 V1 之后。

---

## 2. 研究问题本身不可证伪

"中国名义增长是否正在形成可持续拐点？"是一个好问题，但目前**无法判定对错**，因为三个词都没有定义：

- **名义增长**：用名义 GDP 同比？GDP deflator？还是 PPI 作为高频代理？
- **拐点**：同比转正？二阶导转正？连续几期？
- **可持续**：多长时间？需要哪些需求侧确认？

如果目标变量和判定窗口不先定义，后面的 falsifier 只能写成"new orders materially weaken"这种无法检验的句子（v0.1 第 9 节的例子正是如此）。**一个无法被证伪的 thesis，配再多 traceability 也只是精致的叙事。**

**v0.2 的处理**：把问题操作化：目标变量（名义 GDP 同比、GDP deflator 同比，PPI 作月度代理）、判定窗口（暂定至 2027Q1 数据发布）、"可持续"的定义（价格信号 + 至少两项需求侧确认），并拆成 4 个子假设 + 1 个竞争性假设。

**一个值得注意的分析要点**：对中国名义增长而言，核心争议往往不是"价格有没有回升"，而是**回升来自供给侧（产能治理、大宗商品）还是需求侧（信用、地产、消费）**。供给侧驱动的 PPI 回升可以改善 deflator，但若没有需求确认，往往难以持续。所以 v0.2 把"supply-led bounce, not sustainable"明确写成竞争性假设，系统必须同时为两边收集证据。

---

## 3. Thesis 状态机把三个不同维度混在了一起

v0.1：`WATCH / CONFIRMING / STRONG / WEAKENING / FALSIFIED`

这五个词其实属于三个维度：

- **生命周期**（lifecycle）：WATCH、FALSIFIED
- **确信度**（conviction）：STRONG
- **最新证据方向**（momentum）：CONFIRMING、WEAKENING

一个 thesis 完全可能"确信度高，但本月证据走弱"。把它们压成一个状态，会让每次更新都变成 LLM 凭感觉挑一个词，**这恰恰是你想用系统消除的东西**。

**v0.2 的处理**：拆成 `status`（ACTIVE / CONFIRMED / FALSIFIED / RETIRED）+ `conviction`（LOW / MEDIUM / HIGH）+ `last_update_direction`（STRENGTHENED / UNCHANGED / WEAKENED），并规定每次变更必须写明触发的 evidence 和规则。Falsifier 统一格式为：指标 + 条件 + 阈值 + 窗口 + 检查日期。

---

## 4. Data Layer：方向对，但有两处会在落地时撞墙

**(a) 历史 vintage 基本拿不到，但这不重要。** 中国宏观数据的历史首发值（real-time vintage）大多数数据库不完整提供。v0.1 把 vintage 写成核心字段，容易让人以为要先重建历史 vintage 库。实际上 V1 是**前瞻性研究**，真正需要的是 **forward vintage capture**：从现在起，每次取数都记录 `retrieved_at` 和当时的值，自然形成你自己的 vintage 记录。历史回测才需要重建 vintage，那是 V1 之后的事。

**(b) 字段表混合了三类东西。** `3M trend`、`historical percentile`、`surprise` 是**计算结果**，不应存在指标字典里；`Wind_code`、`SA/NSA`、`unit` 是**静态元数据**；`actual`、`release_date` 是**观测值**。混在一张表里会导致计算结果过期、口径难以维护。v0.2 拆成三个对象：`metric`（元数据）、`observation`（带来源与时间戳的观测值）、`derived`（运行时计算，不入库或只缓存）。

**(c) 缺了中国数据最容易出错的部分：口径陷阱。** 比 vintage 更常见的错误来源是：

- 1–2 月合并发布；
- 只有累计值的序列（工业企业利润、固投等）需要推算单月值；
- 春节错位与基数效应；
- 统计口径调整（例如 M1 自 2025 年起的口径调整、社融历次口径扩充、固投基数调整导致"同比"与"水平值"对不上）；
- 名义 vs 实际、美元 vs 人民币计价（出口）。

这些应进入 Data Dictionary 的必填字段（`caliber_notes`），并进入 Research Skill 的检查清单。（具体调整时点建议在写 Dictionary 时逐条核对官方说明。）

---

## 5. 缺少 Eval：Goal B 提到了"Eval 思维"，但正文没有任何 eval

对 AI × Finance 岗位而言，**能说清楚"怎么知道系统输出是对的"**，比系统功能多少更有说服力。v0.1 的 traceability 原则是好的，但没有变成可检验的指标。

**v0.2 增加最小 eval 集**：

1. **Citation integrity**（可自动化）：每个数字型 claim 必须链接到一个 observation，且数值匹配。
2. **As-of discipline / leakage**（可自动化）：日期为 T 的 memo 只能引用 `release_date ≤ T` 的数据。
3. **Method rubric**：分析链十问逐项打分（LLM judge + 人工抽查）。
4. **Forward record**：falsifier 在数据发布前写入 git，commit 时间戳证明没有事后修改，到期后计分。

第 4 点特别值得强调：**git 历史天然就是"预注册"（pre-registration）的证据**。这对作品集的可信度价值很高，而且几乎零成本。

---

## 6. Demo 与 Wind 授权之间存在冲突

v0.1 DoD："一个陌生使用者能够启动系统……"。但：

- 陌生人（面试官）**没有 Wind 账号**，系统无法在他们那里实时取数；
- Wind 数据通常有**再分发限制**，原始数据不宜提交到公开 GitHub repo（具体以你的授权条款为准）；
- 券商研报有版权，同样不能进 repo。

**v0.2 的处理**：增加 **Demo mode**：从冻结的 snapshot 运行；原始数据与研报 gitignore；公开展示用官方 / FRED 等可公开数据或只展示衍生结果；repo 可见性（public / private）作为待确认项。

---

## 7. 架构上的过早抽象

- **5 个 Provider 接口**：V1 实际只需要 Wind（+ 可选 FRED + 手工文件）。建议遵循"rule of three"：先保持一个很薄的统一函数签名（`fetch(metric_id, start, end) → observations`），等第三个数据源真正接入时再抽象。
- **"Commander / Worker"** 与"不做 multi-agent"的原则有张力。V1 不需要。
- **最便宜的 V1 runtime 其实已经在手上**：Claude Code + Research Skill（SKILL.md）+ Wind MCP + 一个小 Python 库 + git 中的文件。"Ask Macro"在 V1 就是在 case evidence 范围内用 Claude Code 追问并强制引用，不需要另建 chat 应用。这本身也是 Skill 设计能力的展示。

---

## 8. 执行顺序有"spec 瀑布"风险

v0.1 第 17 节要求先完成三份 specification 再进入 case，同时第 18.10 条又说"Build → Run → Iterate，而不是 Design Everything"。这两条有冲突。

三份 spec 如果按"全中国宏观"来写，会变成第二轮 architecture planning。

**v0.2 的处理**：

1. **Step 0：Wind MCP capability spike**：在写任何 spec 之前，先实测 Wind MCP 能返回什么（序列覆盖、历史长度、是否有 release date、是否有一致预期、调用限制）。整个数据层设计取决于这个答案，而 v0.1 是在没有验证的前提下设计的。
2. 三份 spec 改为**薄、且只服务于这一个 case**（每份 ≤3 页），与 case 第一轮运行同步写、同步改。
3. **利用真实发布日历**：今天是 2026-10-03，9 月月度数据与三季度 GDP 通常在 10 月中下旬陆续发布（以官方日程为准）。如果能在这批数据发布前把 baseline thesis 和 falsifier 提交到 git，V1 就能在真实环境中完成第一次"Does this change the thesis?"更新。这比任何模拟都更有说服力。

---

## 9. 较小的问题

- **Global layer**：保留，但只保留与本 case 有明确传导路径的 3 条：外需 → 出口；大宗商品 → PPI；Fed / USD → CNY → PBOC 政策空间。"全球流动性"定义模糊，V1 去掉。
- **10 个 Research modules**：作为长期地图保留，但标明 V1 只用到每个模块的 2–4 个指标。
- **一个被遗漏的高价值交叉验证**：**10Y 国债收益率**本身就是市场对名义增长的定价。把它加入指标集，可以把"我们的判断"与"市场隐含判断"直接对比。
- **开源项目**：我没有逐个核实这些 repo 的现状与许可证。v0.2 只保留两个 P0 作为参考，其余降级为"需要时再看"。
- **银行研究系统联动（第 16 节）**：方向很好，但属于 V2+。v0.2 保留为一段长期愿景，不进入 V1。

---

## v0.1 → v0.2 Changelog

| # | 变更 | 类型 |
|---|---|---|
| 1 | V1 收窄为 1 问题 × 1 thesis × ≤30 指标 × 3 输出 × 1 次真实更新 | 收窄 |
| 2 | 研究问题操作化：目标变量、窗口、"可持续"定义、4 子假设 + 1 竞争假设 | 澄清 |
| 3 | Thesis 状态拆为 status / conviction / direction，falsifier 标准格式 | 澄清 |
| 4 | Data layer 拆为 metric / observation / derived；forward vintage capture 替代历史 vintage | 简化 |
| 5 | Data Dictionary 增加中国口径陷阱字段 | 补漏 |
| 6 | 新增最小 Eval（4 项，其中 2 项可自动化） | 补漏 |
| 7 | 新增 Demo mode 与数据 / 研报授权约束 | 补漏 |
| 8 | Provider 接口、multi-agent、通用 Ask Macro 推迟；V1 runtime = Claude Code + Skill + Wind MCP | 收窄 |
| 9 | 新增 Step 0 Wind MCP spike；三份 spec 改为 case-scoped 且与 case 同步 | 重排 |
| 10 | V1 时间锚定到 10 月真实数据发布，完成一次 live thesis update | 新增 |
| 11 | Policy Note、Weekly、新闻管线、研报库、完整 Dashboard 移入 Deferred | 收窄 |
| 12 | 增加 10Y CGB 作为市场隐含名义增长的交叉验证 | 补漏（1 个指标） |

净效果：**V1 的工作量明显减少**，新增的内容（eval、口径字段、demo mode、spike）都是让已有目标能被验证或能被展示的必要条件，而不是新功能。
