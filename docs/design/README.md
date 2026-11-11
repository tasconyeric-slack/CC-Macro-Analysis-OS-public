# CC Macro 设计指南

CC Macro 公开网站（https://ccmacro.byliyz.com/）的视觉设计以 **Masonry Red** 设计系统为准。今后所有页面、组件和样式改动都应按本指南执行。

- **设计系统原件：** [Masonry Red（Claude Design System artifact）](https://claude.ai/artifact/PS9FYxjTn9fDANfCXid8Cc)，仅 Owner 可编辑。
- **仓库内副本：** [`masonry-red/`](masonry-red/)，与原件 2026-11-10 版本一致。

## 1. 文件与权威顺序

| 文件 | 内容 | 用法 |
|---|---|---|
| [`masonry-red/tokens.json`](masonry-red/tokens.json) | 全部 token：颜色、字体、间距、圆角、阴影、尺寸 | **唯一数值来源**。与其他文件冲突时以它为准 |
| [`masonry-red/tokens.css`](masonry-red/tokens.css) | 由 tokens.json 生成的 CSS 变量 | 写样式时对照变量名和数值 |
| [`masonry-red/api/tokens.md`](masonry-red/api/tokens.md) | 每个 token 的数值与用途表 | 快速查表 |
| [`masonry-red/README.md`](masonry-red/README.md) | 品牌手册：原则、文案、颜色、字体、布局、层级、形状、响应式、Do/Don't | 设计决策依据 |
| [`masonry-red/components/<组件>/README.md`](masonry-red/components/) | 14 个组件的规范 | 做对应组件前必读 |
| `masonry-red/components/<组件>/preview.html` + [`bundle.css`](masonry-red/components/bundle.css) | 组件参考实现（`mr-` 类名） | 结构与样式参考，不直接引入站点 |

权威顺序：本文件第 3 节的站点适配 → `tokens.json` → 组件 README → 品牌手册 README → preview 参考实现。

## 2. 核心规则（摘要）

1. **一个主色，克制使用。** `primary` #6b1d2f（酒红）只用于主要操作按钮、当前页指示（导航下划线）和品牌字标。每一屏最多一个主色按钮。
2. **三种圆角。** `radius-md` 16px 用于几乎所有控件和卡片，`radius-lg` 32px 用于大卡片和弹窗，`radius-full` 用于胶囊、圆形按钮和头像。16 与 32 之间不加其他值，交互元素不用直角。
3. **默认扁平。** 卡片不加阴影；唯一阴影是弹窗下的 `shadow-modal`。层级靠 1px `hairline` 分隔线。
4. **用字重而非颜色区分层级。** 正文颜色统一 `body`，层级靠 400 → 600 → 700 和字号。
5. **双层焦点环。** 所有可聚焦元素使用 2px `focus-inner` + 外侧 `focus-outer` #435ee5。
6. **间距节奏。** 主要区块之间 `space-section` 64px（平板 48px，手机 32px）；内容最大宽度 `size-content` 1280px，两侧 24px。
7. **文案。** 简短、动词开头、句首大写；界面中不用感叹号。

完整规则见 [`masonry-red/README.md`](masonry-red/README.md) 的 Principles 与 Do & don't。

## 3. CC Macro 站点适配（优先于上游文件）

设计系统源自图片发现类网站的分析，CC Macro 是双语宏观研究站点，以下差异已确定：

| 项目 | 站点做法 | 原因 |
|---|---|---|
| `primary-pressed` | 使用 **#561726**（比 primary 深一级） | 上游值 #f1f5f9 接近白色，会让按钮上的白字不可读 |
| 浅色优先 | **站点默认且始终使用浅色 Masonry Red 主题**，不跟随操作系统的暗色外观（不使用 `prefers-color-scheme` 自动切换）。原有暖色暗色主题（底色 #161615、卡片 #1f1f1d、分隔线 #33332f、文字 #f4f3ef；字标、当前页下划线和主按钮改用 ink，主按钮为 ink 底、深色字）保留在 `:root[data-theme="dark"]` 下，仅供今后显式选择 | 设计系统只有浅色主题；黑色正文不等于黑色背景。系统暗色模式自动接管会让站点偏离设计意图；酒红在近黑底上对比度不足 |
| 警示色 | 状态中的“待定/警示”沿用站点原有 `--warn`（浅色 #a16207，暗色 #d39a2c） | 设计系统没有警示 token；证据状态需要第三种语义色 |
| 图表 | 单序列折线用 `charcoal`（暗色为 #e5e5e0），网格用 `hairline-soft`，参考线用 `ash` | 主色只用于操作与品牌，不用于数据 |
| 字体 | `Inter` 仅在用户本机已安装时生效，其余回退到站点现有的中文友好字体栈 `--sans` | 不新增 Google Fonts 等外部依赖（PRODUCT_STRATEGY §20.7）；中文需要 CJK 字体 |
| CSS 变量 | 站点内使用 `--mr-` 前缀（如 `--mr-primary`），定义在 `site/static/style.css` 开头的 “Masonry Red foundation” 段；旧变量名（`--surface`、`--ink`、`--rule`、`--accent` 等）作为别名指向这些 token | 各页面与样式表读取同一套取值 |
| 共用控件 | `.mr-btn`（`--primary` / `--tertiary`）与 `.mr-chip`（放在 `.mr-chips` 行内，`aria-current` 或 `aria-pressed="true"` 为选中）定义在 `style.css`，页面直接复用 | 不为每个页面重复写按钮和筛选样式 |
| 导航主按钮 | 站点没有注册功能，导航右侧放语言切换（胶囊分段控件），不放主色按钮 | 不虚构不存在的功能 |
| 图片类组件 | PinCard、MasonryGrid、CategoryTile、FeatureCard 的“图片即卡片”规则只在有真实图片时使用；数据卡片、图表沿用 16px 圆角、扁平、hairline 的通用规则 | 站点以数据和图表为主，不使用装饰性图片 |
| 导航结构 | **Research-First MVP 目标：Overview · Research · Data**；News、Daily、Policy、Evidence、Updates 继续保留实际页面和深链，作为研究的次级资料入口，首页不突出新闻热榜 | PRODUCT_STRATEGY §0（2026-11-10 Owner-directed revision）；Research-First Blueprint |

**已应用：** 页眉与页脚（PR #38）；全站 token、排版、卡片、表格、标签、按钮与筛选控件（Masonry Red foundation）。各栏目页面布局在后续改动中逐步迁移。

## 4. 上游文件中已知的不一致

更新上游设计系统时一并修正；在修正前按下列解释执行：

- `masonry-red/README.md` 正文仍写 `primary` 为 `#e60023`（红色），并称其为“red”。**以 tokens.json 的 #6b1d2f 为准。**
- `primary-pressed` 为 #f1f5f9，见第 3 节，站点使用 #561726。
- `error` 与 `primary` 同为 #6b1d2f；用途说明中的对比度数字（4.8:1、8.6:1、3.2:1）是旧值，未随颜色更新。
- `error-deep` 的说明称其“与 primary-pressed 同值”，现已不成立。

## 5. 如何使用与更新

**做页面或组件改动时：**

1. 先读本文件第 2、3 节，再读相关组件的 `components/<组件>/README.md`。
2. 颜色、间距、圆角、字号只取 `tokens.json` 中的值（或第 3 节的站点适配值），不手写新数值。
3. 新组件先尝试用现有 token 和组件组合表达；确需新 token 时，先在上游设计系统中添加，再同步到本目录。
4. 改动需通过浅色（含操作系统为暗色外观时仍显示浅色）、中文、英文，以及 1440px 与 390px 宽度的检查，且无横向滚动；若改动涉及 `data-theme="dark"`，另查暗色。
5. 页面改动仍须遵守 `docs/PRODUCT_STRATEGY.md`（§0 范围、§15.2 优先级规则、§20 Agent Operating Contract）。设计指南不扩大任何任务范围。

**更新设计系统时：** 在上游 artifact 中修改 → 将 `project/` 下的 README、tokens.json、tokens.css、api/tokens.md、components/ 同步到 `masonry-red/` → 如适配关系变化，更新本文件第 3、4 节 → 同一 PR 内提交。

## 6. 与 V2 benchmark 的关系

[`v2/benchmark-spec.md`](v2/benchmark-spec.md) 记录的信息架构、内容取舍（Adopt / Adapt / Skip）和实现约定继续有效。其中的视觉选择（深蓝/金色配色、12px 圆角、68px 深蓝页眉等）由本指南取代。
