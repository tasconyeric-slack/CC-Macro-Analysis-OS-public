# Prices topic acceptance evidence

T3 / #28. One branch `codex/prices-depth`, one PR into `main`. This supports §0 V2 Product Build and does not claim a new G-B/G-C research run. Execution plan: [prices depth](../../superpowers/plans/2026-11-09-prices-depth.md).

## Verified backfill

GitHub runner [42662050695](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public/actions/runs/42662050695) read the archived pages in small independent batches, after bulk requests returned challenge bodies. The import accepted **144 monthly releases**, added **1,008 observations** and reported **zero parser errors**. All 21 new series have **48 months, 2022-11 through 2026-10**; incumbent longer histories are preserved. The fuel/energy classification break limits current comparable percentiles to 10 observations. All six temporary diagnostic result branches were deleted; temporary workflows/scripts were removed from the final change.

## Data and methodology

Only original NBS monthly CPI, PPI and manufacturing PMI release tables are parsed. The observation retains the canonical article URL, original published timestamp when present, and actual retrieval time. The collection summary records the actual transport URL. No interpolation, estimated contributions, paid data or prose-derived values.

Runner diagnosis found that a successful HTTP status alone is insufficient: some canonical URLs return JavaScript challenge bodies. The same official article with `?v=1` / `?_=20261109`, and the direct HTTP URL on the same official host, returned real tables from GitHub runner [42659428457](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public/actions/runs/42659428457). Production tries canonical HTTPS, the measured cache variants, then direct HTTP on the same official host (no credentials are sent). It uses these measured fallbacks and validates the title, monthly columns, exact rows, numeric cells and duplicate table agreement. A failure is logged in the workflow artifact and cannot replace the last valid store. Diagnostic result branches are temporary and removed after importing/verifying their bodies.

Price facts are added to one append-only public CSV. Existing research series are not replaced by an archived first print from a different incumbent source. Corrections to the same official release URL are captured as new vintages, with unknown revision date and retrieval-time availability, using the existing `new_rows` rules. No research rules, preregistration, amendment, update/refresh history or analyst judgment is edited.

The three-line chain ends at the latest month shared by producer-goods PPI, consumer-goods PPI and core CPI. Gaps are labelled in percentage points, not as measured causal pass-through. Each monthly table row states its own latest published month; prior means the immediately previous calendar month. Missing cells or months remain unavailable. Percentiles use average ranks scaled to 0–100 over the last 36 calendar months, with actual `n`, tied ranks averaged and constant samples at 50. Quarterly GDP deflator remains available below the monthly table and in the workbook.

**Classification break:** NBS publishes transport fuel (交通工具用燃料) through 2025 and transport energy (交通工具用能源) from January 2026. The fuel/energy chart breaks at that date, cross-break changes are unavailable, and current percentiles use only the comparable 2026 segment. This is neither a broad-energy aggregate nor an assumption of identical scope. Both official labels are retained in the observation limitations and metric notes.

XLSX is generated using Python's standard library. Sheets contain aligned series, current observations with lineage, all captured vintages and definitions/units/as-of. Missing cells stay empty; textual cells are inline strings, including formula-looking input. CSV/JSON exports and detail anchors remain available per metric; the composite also has a CSV.

## China Macro Monitor comparison

Reference inspected 2026-11-09: [China Macro Monitor](https://chinamacromonitor.com/), Inflation CPI/PPI and manufacturing PMI price-pressure panels. This is a feature comparison, not a data import.

| Reference feature | Status here | Reason / location |
|---|---|---|
| Headline and core CPI, YoY / MoM | Done | Official release table facts and individual charts |
| Food, pork, fuel/energy, services and goods decomposition | Done | Published components, both rates, with the 2026 transport classification break |
| Urban / rural CPI comparison | Not done | Outside the owner's T3 series list; no claim of parity |
| CPI contribution charts by category and urban/rural | Not done | No invented weights or contributions; outside T3 |
| Headline PPI YoY / MoM | Done | Existing series and official table refresh |
| Means of production vs consumer goods | Done | Composite plus individual charts; core CPI on same axis |
| Detailed PPI groups | Done for T3 | Producer/consumer goods, mining, raw materials and processing, YoY / MoM; not all reference sector lines |
| Purchasing PPI (PPPI) vs output PPI | Not done | Not in T3; PMI input prices are explicitly not a substitute for PPPI |
| Top five industrial sectors by absolute YoY | Not done | Sector-level selection not requested |
| Manufacturing PMI input / output prices | Done | Two published diffusion indices, separate from inflation rates |
| Historical range switches | Done | Reuse existing 2Y / 5Y / All controls; missing months break lines |
| 3Y / 10Y / 20Y presets and YTD / annual CPI/PPI measures | Not done | Existing range component and requested monthly YoY / MoM scope retained |
| This-month latest/prior/change/3-year context | Done | Deterministic table with period and actual sample size |
| Excel export of all price series | Done | One public XLSX, with observation/vintage lineage |
| Native linked Excel charts | Not done | Workbook exports tables; native Excel chart authoring is outside T3 |
| Per-chart CSV and metric-detail/source anchors | Done | Existing raw exports plus composite CSV |
| Bilingual desktop and mobile views | Done | 1440/390 px screenshots and browser checks in `acceptance/` |

## Validation artifacts

- `backfill.json`: exact imported release URLs, transport URLs, row counts and series coverage.
- `acceptance/browser-checks.json`: viewport overflow, range controls, detail anchors, exports and browser errors.
- Screenshots: `acceptance/{zh,en}-{1440,390}.png`, plus table and detail views.
- `public-eval.json`: E1–E5 pass; E0 has only the pre-existing private/missing/gap warnings.
- PR checks carry full test/evaluation/build results and a verified Vercel Preview.

## Deferred / boundaries

The not-done reference features above are explicitly deferred; no follow-on task is spawned. Official table/schema changes are operational failures, not permission to estimate a number. No merge is performed as part of this task. In particular, no site/pipeline merge is allowed 2026-11-16 08:00–16:00 Beijing (§20.8).
