# Global-to-China Macro Research System
## Project Brief v0.2

> 2026-10-03 · 基于 v0.1 修订。修订理由见 `critique-v0.1.md`。
> 核心变化：**V1 收窄为一个可证伪的 case + 一次真实数据发布后的 thesis 更新**；新增 eval、demo mode 和 Step 0 数据验证。

---

## 一句话定义

> **Build a China-centered, globally informed macro research system that converts data, policy and institutional research into traceable, falsifiable, continuously updated macro theses.**

V1 用一个问题证明这句话成立：

> **中国名义增长是否正在形成可持续拐点？**

---

# 1. 定位与目标

以中国宏观研究为核心，全球宏观作为显式的外生变量。系统首先是 **Research System**，其次才是 Agent / Dashboard / App。

**Goal A：真正可用的研究工具。** 长期服务于数据跟踪、发布点评、政策研究、thesis 维护和资产映射。V1 只要求在一个问题上真实可用。

**Goal B：AI × Finance 作品。** V1 需要让面试官快速看到：

1. 宏观研究能力：问题被正确地拆解、度量和证伪；
2. 把研究 workflow 转译为 AI 可执行流程的能力（Research Skill）；
3. Evidence / traceability / eval 设计；
4. 产品判断：知道什么不做。

> 作品集的说服力来自**一个做透的闭环 + 可检验的记录**，而不是功能数量。

---

# 2. 核心原则

```text
Reliable Evidence → Structured Analysis → Research Judgment → Thesis Updating → Investment Implication
```

1. **Research quality > technical novelty。** 不为做 Agent 而做 Agent。
2. **先用已有的 Wind MCP，** 不重复造数据基础设施；新数据源只有在低成本且解决明确缺口时接入。
3. **每个关键 claim 必须标注类型并可追溯：**

   | Claim type | 含义 | 必须链接到 |
   |---|---|---|
   | `FACT` | 官方 / 数据库原始数据 | observation |
   | `DERIVED` | 由原始数据计算 | 计算方法 + 输入 observations |
   | `EXTERNAL_VIEW` | 机构 / 分析师观点 | 文档 + 位置 |
   | `INFERENCE` | 本系统的判断 | 支撑它的 claims |

4. **As-of discipline：** 日期为 T 的研究只能使用 T 时点已发布的信息。
5. **Pre-registration：** thesis 与 falsifier 在数据发布**之前**提交到 git，事后不改写，只追加更新。
6. **每次新数据只回答一个核心问题：Does this change the thesis?**
7. **Build → Run Real Research → Identify Weakness → Iterate，** 而不是 Design Everything → Start Research。

---

# 3. V1 Scope

## V1 = 1 × 1 × 30 × 3 × 1

| 维度 | V1 |
|---|---|
| 研究问题 | 1 个（名义增长拐点） |
| Thesis | 1 个主 thesis（含子假设与竞争假设） |
| 指标 | ≤ 30 个（硬上限） |
| 输出 | 3 种：Deep Dive Memo、Thesis Card、Release Update Note |
| 真实更新 | ≥ 1 次（10 月数据发布后） |

## In / Out

| V1 做 | V1 之后（Deferred） |
|---|---|
| Wind MCP 取数 + 少量 FRED / 手工数据 | 通用 Data Provider 抽象层（第三个数据源接入时再做） |
| 指标字典（仅 case 所需） | 全量中国 / 全球指标库 |
| 政策证据：针对 case 的定向检索与引用 | 政策全量监控、Policy Note 模板 |
| 研报：5–10 篇与 case 相关的报告，人工辅助抽取观点 | Analyst Interpretation Library、共识 / 分歧地图 |
| Case Snapshot：case 图表生成的单页 HTML | 完整 Macro Dashboard |
| Case-scoped Ask：在 case evidence 范围内追问，强制引用 | 通用 Ask Macro |
| — | 新闻 RSS 管线、Weekly Memo |
| — | Multi-agent、Commander / Worker |
| — | 与银行股研究系统联动 |

V1 同样不做：DSGE、agent simulation、精确 nowcasting、regime 预测模型、自动资产配置 / 交易、React 大屏、实时数据基础设施。

---

# 4. The V1 Research Case

## 4.1 操作化定义（默认值，待确认）

| 概念 | 定义 |
|---|---|
| 目标变量 | 名义 GDP 同比、GDP deflator 同比（季度）；PPI 同比 / 环比作为月度高频代理 |
| 拐点 | deflator 同比由负转正，或连续两个季度明显收窄并转正 |
| 可持续 | 价格信号成立 **且** 至少两项需求侧确认（私人部门信用、核心 CPI、地产销售、内需型工业利润中至少两项改善） |
| 判定窗口 | 至 2027Q1 数据发布（约 2027 年 4 月中下旬） |
| 观点形式 | 概率化判断（例如"可持续拐点：40%"），而非是 / 否 |

> 注意：本 brief **不预设答案**。当前数据处于什么状态，由 Step 2 的 baseline run 回答。

## 4.2 拆解：名义增长 = 实际增长 × 价格

| 子假设 | 核心问题 | 关键证据 |
|---|---|---|
| **H1 Price** | 价格改善是否在发生？来源是供给侧还是需求侧？ | PPI（生产资料 / 生活资料）、PMI 价格分项、核心 CPI、大宗商品 |
| **H2 Domestic demand** | 私人部门内需是否企稳？ | 居民中长期贷款、企业贷款、M1、地产销售与房价、社零 |
| **H3 Policy impulse** | 财政与信用 impulse 是否足够且持续？ | 政府债净融资、社融存量增速、credit impulse、广义财政收支 |
| **H4 External** | 出口是支撑还是拖累？ | 出口（分国别）、新出口订单、美国 / 欧洲需求 |

**竞争性假设 H0：** 价格回升主要由供给侧（产能治理、大宗商品）驱动，缺乏需求确认，因此不可持续。系统必须同时为 H0 收集支持与反对证据。

## 4.3 Global transmission：只保留三条

```text
1. US / EU demand → China exports → industrial production / profits
2. Oil / metals → PPI → deflator
3. Fed / UST / USD → CNY → PBOC policy space → China rates / credit
```

## 4.4 指标集（≤ 30，草案）

| 组别 | 指标 | 频率 |
|---|---|---|
| 名义与价格 | 名义 GDP、实际 GDP、GDP deflator（派生）、CPI、核心 CPI、PPI、PPI 生产资料 / 生活资料、PMI 出厂价格 | Q / M |
| 活动 | 制造业 PMI、新订单、新出口订单、工业增加值、工业企业利润（累计 → 单月派生）、社零、固投（制造业 / 基建 / 地产） | M |
| 货币与信用 | M1、M2、社融存量增速、新增人民币贷款（居民中长期 / 企业）、政府债净融资、credit impulse（派生） | M |
| 地产 | 商品房销售面积 / 金额、70 城新房价格环比 | M |
| 财政 | 一般公共预算 + 政府性基金收支 | M |
| 外部 | 出口同比（美元计，分美 / 欧 / 东盟） | M |
| 全球与市场 | 美国 ISM 制造业 PMI、Brent、铜、USD/CNY、UST 10Y、**中国 10Y 国债收益率** | M / D |

10Y 国债收益率作为**市场隐含的名义增长判断**，用于与本系统观点对照。

---

# 5. Research Method

## 5.1 分析链

```text
Observation → Surprise → Marginal Change → Decomposition → Mechanism
→ Cross-check → Research View → Asset Implication → Falsifier
```

## 5.2 每次解读必须回答的十问

1. 相比什么？（预期、前值、趋势、季节性规律）
2. 同比、环比还是趋势改善？
3. 是否受基数、春节、工作日影响？
4. 哪些分项驱动？
5. 是否有其他独立数据确认？
6. 机制是什么？
7. 暂时因素还是结构变化？
8. 是否改变现有 thesis？改变了哪个子假设？
9. 对未来与资产意味着什么？
10. 什么数据出现意味着判断错误？

## 5.3 中国数据口径检查清单

- 1–2 月合并发布；
- 只有累计值的序列需推算单月值，并注意累计值修订；
- 春节错位与基数效应；
- 统计口径调整（如 M1 新口径、社融口径扩充、固投 / 工业利润的同比与水平值不一致）；
- 出口：美元 vs 人民币计价，数量 vs 价格；
- 名义 vs 实际。

（每条口径调整的具体时点在 Data Dictionary 中逐条核对官方说明后记录。）

---

# 6. Evidence & Data Layer

## 6.1 三个对象，而非一张大表

```text
metric        静态元数据（字典）
observation   带来源与时间戳的观测值
derived       运行时计算（趋势、分位数、surprise、单月化、credit impulse）
```

**metric**

```text
metric_id, name, economy, category, frequency, unit
transform: level / YoY / MoM / QoQ, SA / NSA, single_month / cumulative
source_primary, source_code (e.g. Wind EDB code), source_fallback
release_lag, typical_release_day
research_role: which sub-hypothesis (H0–H4), leading / coincident / lagging
caliber_notes: 口径调整、已知陷阱
```

**observation**

```text
metric_id, reference_period, value
release_date        市场何时知道
retrieved_at        我们何时取得（forward vintage capture）
source, source_code
consensus           若可得
quality_flag
```

**Forward vintage capture：** 不重建历史 vintage。从现在起每次取数都追加记录 `retrieved_at` 和值，自然形成自己的 vintage 历史。历史回测所需的 vintage 重建属于 V1 之后的工作。

## 6.2 数据源

| 用途 | V1 来源 |
|---|---|
| 中国结构化数据 | Wind MCP（primary） |
| 美国 / 全球 | Wind 或 FRED |
| 政策原文 | 官方网站定向检索（可参考 `policy-search-china-skill`） |
| 机构观点 | 用户自有研报（5–10 篇，case 相关） |
| 补缺 | 手工文件（CSV） |

V1 只保留一个薄的统一函数签名：`fetch(metric_id, start, end) → [observation]`，不建立多 provider 抽象层。

## 6.3 授权与可见性约束

- Wind 原始数据与券商研报**不提交到 repo**（gitignore），以各自授权条款为准；
- 公开展示用 demo snapshot、衍生结果，或可公开来源（统计局、人民银行、FRED）；
- repo 是 public 还是 private：**待确认**。

---

# 7. Thesis Framework

## 7.1 Thesis Card

```yaml
thesis_id: CN-NOMINAL-01
statement: 中国名义增长将在 2027Q1 前形成可持续拐点
probability: 0.40            # 示例
status: ACTIVE               # ACTIVE / CONFIRMED / FALSIFIED / RETIRED
conviction: MEDIUM           # LOW / MEDIUM / HIGH
last_update_direction: UNCHANGED   # STRENGTHENED / UNCHANGED / WEAKENED
sub_hypotheses: [H1, H2, H3, H4]
competing_hypothesis: H0
evidence_for: [claim_id, ...]
evidence_against: [claim_id, ...]
confirmers: [...]
falsifiers: [...]
asset_implications: [...]
created: 2026-10-xx
last_updated: 2026-10-xx
```

三个维度分开：**status** 是生命周期，**conviction** 是确信度，**direction** 是最新证据的方向。

## 7.2 Falsifier / Confirmer 标准格式

```yaml
- id: F1
  indicator: PPI YoY
  condition: 连续两个月环比为负，且同比回落
  threshold: <baseline run 后填写>
  window: 2026-10 至 2027-01 发布
  check_on: 每次 PPI 发布
  linked_hypothesis: H1
```

无法写成这种格式的 falsifier，不算 falsifier。

## 7.3 更新规则

- 每次相关数据发布后生成 Release Update Note，并对 thesis 产生一条 update log：哪个 falsifier / confirmer 被检查、结果、对子假设的影响、probability / conviction 是否变动及原因；
- status 变为 FALSIFIED 或 CONFIRMED 必须由预先登记的条件触发，而非主观判断；
- 所有变更通过 git commit 记录，git 历史即审计轨迹。

---

# 8. V1 Outputs

| 输出 | 回答 | 要点 |
|---|---|---|
| **Deep Dive Memo** | 名义增长是否正在形成可持续拐点？ | 按 H0–H4 组织；每个关键 claim 标注类型并引用；结论为概率化判断 + falsifiers |
| **Thesis Card** | 当前判断是什么？凭什么？何时会错？ | §7 格式；YAML 存储，渲染为 HTML |
| **Release Update Note** | 这次数据改变了 thesis 吗？ | What happened → Actual vs consensus / prior → Decomposition → 检查了哪些 falsifier → Thesis diff → What to watch next |

附带产物：

- **Case Snapshot**：由 case 图表生成的单页静态 HTML；
- **Case-scoped Ask**：用 Claude Code + Research Skill 在 case evidence 范围内追问，回答必须引用 observation / 文档，不允许依赖参数知识作答。

---

# 9. V1 Runtime（默认方案）

```text
Claude Code
  └─ Research Skill (SKILL.md)          ← 研究流程的可执行规格
       ├─ Wind MCP                       ← 取数
       ├─ small Python lib               ← 标准化、派生计算、图表、引用校验
       └─ files in git                   ← dictionary / observations / claims / thesis / outputs
```

建议 repo 结构：

```text
docs/                       brief, specs
skills/china-macro-research/SKILL.md
data/dictionary.yaml        指标字典（可提交）
data/raw/                   原始数据（gitignore）
data/demo/                  demo snapshot（仅可公开数据或衍生结果）
src/                        fetch / transform / charts / checks
research/cases/cn-nominal/  memo, thesis.yaml, claims.jsonl, updates/
```

**Demo mode：** 没有 Wind 账号的人可以从 `data/demo/` 运行并查看全部输出。

---

# 10. Eval

| # | 检查 | 方式 |
|---|---|---|
| E1 | **Citation integrity**：每个数字型 claim 链接到 observation，且数值一致 | 脚本自动 |
| E2 | **As-of discipline**：日期为 T 的输出只引用 `release_date ≤ T` 的数据 | 脚本自动 |
| E3 | **Method rubric**：§5.2 十问逐项打分 | LLM judge + 人工抽查 |
| E4 | **Forward record**：预注册 falsifier 到期计分 | git 时间戳 + 到期检查 |

E1、E2 在每次生成输出时运行；E4 是作品集中最有说服力的部分。

---

# 11. 执行顺序

**Step 0：Wind MCP capability spike（先于任何 spec）**
实测并记录：指标覆盖、历史长度、是否返回发布日期、是否有一致预期、调用限制、授权约束。输出一页 capability note。数据层设计以此为准。

**Step 1：三份 thin spec（每份 ≤ 3 页，只服务本 case）**
1. `China Macro Research Skill v0.1`：§5 的分析链 + 十问 + 口径检查，写成 SKILL.md；
2. `Data Dictionary v0.1`：§4.4 的 ≤ 30 个指标；
3. `Output & Thesis Framework v0.1`：§7–8 的三种输出 + thesis card。

Spec 与 Step 2 同步撰写、同步修改，不追求一次写完。

**Step 2：Baseline run**
取数 → 图表 → Deep Dive Memo → Thesis Card + falsifiers → E1 / E2 通过 → **在 9 月数据 / 三季度 GDP 发布前 commit**（通常在 10 月中下旬，以官方发布日程为准）。

**Step 3：Live update**
数据发布后生成 Release Update Note 与 thesis diff。

**Step 4：Package**
Demo snapshot、Case Snapshot HTML、README、eval 结果。

完成后再决定第二个 case 或模块。扩展顺序参考：Credit → Property → Fiscal → External → Global。

---

# 12. V1 Definition of Done

- [ ] Wind MCP capability note 完成；
- [ ] Data Dictionary 覆盖 case 全部指标（≤ 30），每个指标有来源代码、发布节奏、research role、口径备注；
- [ ] Deep Dive Memo 完成，所有数字型 claim 通过 E1，全文通过 E2；
- [ ] Thesis Card 含概率化判断与 ≥ 3 条标准格式 falsifier，且**在相关数据发布前**提交到 git；
- [ ] 至少 1 次真实数据发布后的 Release Update Note 与 thesis diff；
- [ ] Case-scoped Ask 能针对 thesis 追问并给出带引用的回答；
- [ ] 无 Wind 账号的人能通过 demo mode 在几分钟内看完全部输出；
- [ ] README 让面试官快速理解：**这是把宏观研究 workflow 转译为可追溯、可证伪 AI Research System 的项目，而不是套 prompt 的聊天机器人。**

---

# 13. 长期地图（不属于 V1）

保留 v0.1 的长期愿景，作为方向而非承诺：

- **Research modules：** Growth、Inflation、Credit、Liquidity & Rates、Property、Fiscal、External、Policy、Markets、Investment；
- **Full outputs：** Macro Dashboard、Policy Note、Weekly Macro Memo、Analyst Interpretation Library（共识 / 分歧地图）、通用 Ask Macro；
- **Global layer：** 扩展到全球流动性、更多经济体；
- **下游联动：** 作为 Bank / Equity Research System 的上游 Macro Engine：宏观变量 → 行业传导 → 银行经营驱动 → PPOP / Credit Cost / ROE → 估值；
- **开源参考：** `policy-search-china-skill`、`ai-economist-skill`（P0，V1 可参考）；`china-intelligence-agent`、`macro-analyst`、`CentralBank-LLM`（需要时再看）。原则不变：建自己的系统，选择性吸收模块，不 fork 改造。

---

# 14. 待确认事项

1. §4.1 的操作化定义与判定窗口是否接受？
2. repo 公开还是私有？（决定 demo 数据策略）
3. Wind MCP 是否提供发布日期与一致预期？（Step 0 回答）
4. 是否有 5–10 篇与本 case 相关的研报可用？
