# Source replacement matrix (V1.2.1 provider-independence audit)

> **Status: AUDIT, research only (2026-10-05).** Nothing here is implemented. No metric ID, signal definition,
> threshold or preregistered evidence changes. Inventory source: `data/dictionary/metrics.yaml` on `main` at
> 121874a. The inventory has **14 metric views on 13 Wind codes**. `cn_cgb10y` and `cn_cgb10y_daily` are two views of
> M0325687 (`same_series_as`), and `cn_cgb10y` is the only core-tier view.
> Companions: [`provider-migration-priorities.md`](provider-migration-priorities.md),
> [`provider-independence-design.md`](provider-independence-design.md),
> [`v1.2.1-implementation-plan.md`](v1.2.1-implementation-plan.md).
>
> **Final correction pass (2026-10-06).** The research findings are unchanged. The activation and access wording now
> matches the design:
> - semantic equivalence is not the same as activation readiness;
> - access fails closed.

## How to read this

**Evidence labels.**
- **VERIFIED_LIVE**: we fetched the page or endpoint and saw it.
- **VALUE_MATCH n/n**: candidate values compared with the Wind values in the private Phase 1 snapshot. The comparison
  used `data/private/observations/wind_20261004T195141Z.csv` and its raw run files, read locally; no Wind values
  appear in this document.
- **DOC_CLAIM**: the provider's documentation says so.
- **INFERRED**: our reasoning.
- **UNKNOWN**: not established. Each row says what would settle it.

**No Wind call was made during the audit.** Wind credits are exhausted: a run on 2026-10-05 failed with
"insufficient credits".

**TuShare.** Live checks went through the user's TuShare MCP on 2026-10-05. The account can read `index_daily` but
is throttled to 1 call/min, then 1 call/hour. `repo_daily`, `yc_cb` and `eco_cal` return "no permission" (error
40203). The token was never seen.

**Semantic scale.** EXACT, FUNCTIONALLY_EQUIVALENT (FE), APPROXIMATE, NOT_EQUIVALENT or UNKNOWN. Only EXACT, or
FE with a recorded justification, may replace a canonical metric without a new research-contract version
([design §7](provider-independence-design.md#7-semantic-equivalence-and-activation-gates)).

**Semantic equivalence is not activation readiness.**
- The `semantic_equivalence` field answers only one question: is this the same statistic?
- Activating a route for a canonical metric also needs:
  - a passed activation validation;
  - an access policy that permits it;
  - an appended, time-stamped route-history record.

  See [design §5 and §7](provider-independence-design.md#7-semantic-equivalence-and-activation-gates).
- `keep_wind_as: FALLBACK` means Wind becomes an *inactive* route once a substitute activates. Only another reviewed
  route-history record can make it active again. It is never an automatic fallback.

**Licensing.** Fetching, private use and redistribution are separate questions, and none of them is evidence of
equivalence. The proposed `access` values for each route are in
[priorities](provider-migration-priorities.md#access-policy-per-route-proposed-access-values-fail-closed). *API access, a paid key, or a
free endpoint is not a redistribution right.* Every view below stays `private_only`, as today. No row proposes a
change to that.

## Overview

| metric_id | Wind code | freq / unit | Phase 2 use | best non-Wind source | semantic_equivalence | evidence strength | recommended_primary | keep_wind_as | tier |
|---|---|---|---|---|---|---|---|---|---|
| `cn_cgb10y` | M0325687 (month-end) | M / % | core metric (public thesis tier; value private_only) | ChinaMoney SDDS 10Y, month-end derived from the daily view | **EXACT** | implied by the daily match (3/3 month-ends) | ChinaMoney SDDS (via `cn_cgb10y_daily`). **Activation is gated on CFETS written permission**; otherwise Wind stays active. | FALLBACK | A (conditional) |
| `cn_cgb10y_daily` | M0325687 | D / % | A2, D1 → R3, R4 | ChinaMoney SDDS `SddsIntrRateGovYldHis` (`tenRate`) | **EXACT** | VALUE_MATCH 48/48 (A, and confirmed in the adversarial review); 30/30 re-checked | ChinaMoney SDDS. **Activation is gated on CFETS written permission**; otherwise Wind stays active. | FALLBACK | A (conditional) |
| `cn_dr007` | M1006337 | D / % | A1 → R2, D1 | ChinaMoney `prr-chrt.csv` col DR007; TuShare `repo_daily` DR007.IB `weight` | ChinaMoney: **EXACT**; TuShare: **UNKNOWN** (no value comparison possible; no permission) | ChinaMoney VALUE_MATCH 47/47 (re-checked); TuShare doc only | ChinaMoney `prr-chrt.csv`. **Activation is gated on CFETS written permission**; otherwise Wind stays active. TuShare does not yet qualify as an authorised alternative. | FALLBACK | A (conditional) |
| `cn_loans_hh_short_flow` | M0057874 | M / CNY 100m | B1 → R1, R2, R4 | PBOC 金融统计数据报告: YTD(m) − YTD(m−1) | **EXACT** | VALUE_MATCH 2 months (2026-01, 2026-08) × 4 series | PBOC press release. Activation validation is PENDING: 13 months × 4 series. | FALLBACK | A |
| `cn_loans_hh_mlt_flow` | M0057875 | M / CNY 100m | B1 | same | **EXACT** | same | PBOC press release. Activation validation is PENDING: 13 months × 4 series. | FALLBACK | A |
| `cn_loans_corp_short_flow` | M0057876 | M / CNY 100m | B2 → R1, R2, R4 | same | **EXACT** (incl. the 100亿 rounding grid) | same | PBOC press release. Activation validation is PENDING: 13 months × 4 series. | FALLBACK | A |
| `cn_loans_corp_mlt_flow` | M0057877 | M / CNY 100m | B2 | same | **EXACT** (incl. the 100亿 rounding grid) | same | PBOC press release. Activation validation is PENDING: 13 months × 4 series. | FALLBACK | A |
| `mkt_csi300` | 000300.SH K-line MATCH | D / index points | D1 → R3, R4 | csindex `perf/index-perf` close; TuShare `index_daily` close; SSE `yunhq` | csindex **EXACT**; TuShare **FE** (identity after ROUND_HALF_UP to 2 dp); SSE **FE** | csindex VALUE_MATCH 28/28; TuShare 21/21 after ROUND_HALF_UP incl. ties (0/21 unrounded) | CSI (csindex.com.cn). Live collection and activation are gated on the project's use status. | FALLBACK | A |
| `cn_hf_prop_bj` | S0203228 | D / m² | C1.bj → C2 → R1, R2, R4 | 北京住建委 page 307749, 期房 + 现房 网上签约 area (latest day only) | **UNKNOWN** (FE if Wind = 期房 + 现房, all uses) | definitional only; no value match possible | own PIT daily collector (candidate route, after terms sign-off) | PRIMARY (historical) / CROSS_CHECK for activation | B |
| `cn_hf_prop_gz` | S0175476 | D / m² | C1.gz → C2 → … | 阳光家缘 `mrxjspfqyxx.ashx` (latest day; 4 uses) | **UNKNOWN** (FE if Wind = 4-use sum, integer) | definitional only | own PIT daily collector (candidate route, after terms sign-off) | PRIMARY (historical) / CROSS_CHECK for activation | B |
| `cn_hf_prop_sz` | S0048279 | D / m² | C1.sz → C2 → … | 深圳市房地产信息平台 `fdc.zjj.sz.gov.cn` | **UNKNOWN** | blocked from this host (HTTP 412 → 400) | none yet | PRIMARY | B (blocked) |
| `cn_hf_prop_sh` | S0146015 | D / m² | C1.sh → C2 → … | fangdi.com.cn `getFirstTransactionStat.action` `sign_area` | **UNKNOWN** (FE if Wind = 全市 一手 `sign_area`, end of day) | definitional only | **no acceptable automated route** (anti-bot JS challenge) | PRIMARY | C |
| `cn_cpi_consensus_wind` | M0061676 | M / % | X1 (EXPERIMENTAL) | none equivalent; jin10/wallstreetcn/TuShare `eco_cal` 预测值; RiceQuant CPI预测 | **NOT_EQUIVALENT** (others); RiceQuant **APPROXIMATE** | INFERRED / DOC_CLAIM | Wind (sole) | PRIMARY | C |
| `cn_ppi_consensus_wind` | M0061677 | M / % | X1 (EXPERIMENTAL) | same | **NOT_EQUIVALENT** / APPROXIMATE | same | Wind (sole) | PRIMARY | C |

**Count.** 14 views audited. **8 have an EXACT non-Wind alternative backed by a value match**: both 10Y views,
DR007, the four loan flows and CSI 300. CSI 300 also has two FE routes: TuShare `index_daily`, identical after ROUND_HALF_UP to 2 dp, and SSE. DR007 via
TuShare is **UNKNOWN** until an overlap check. `keep_wind_as` gives Wind's *target* role after activation. Until a route passes every activation gate, Wind stays
the active route. The gate is:
- for DR007 and both 10Y views, CFETS written permission;
- for CSI 300, the use-status decision;
- for the loans, the 13-month validation. **None of the four property views** can yet be shown equivalent: the first-party sites keep no
history, so no value comparison was possible. **Neither consensus view** has an equivalent.

---

## Per-metric detail (all 26 required fields)

### 1. `cn_cgb10y`: China 10-year government bond yield, month-end

| Field | Value |
|---|---|
| canonical_metric_id | `cn_cgb10y` (tier `core`; `redistribution: private_only`) |
| economic_concept | Market-implied nominal-growth benchmark: the 10Y CGB yield at month-end. |
| current_wind_code | M0325687 "中国:国债收益率:10年" (`aggregate: month_end`; one call, two stored views) |
| current_definition | The last Wind daily observation dated inside each completed calendar month, from the ChinaMoney series. The Beijing month of `retrieved_at` decides completeness (`wind.py:508-524`). |
| frequency | M (from D) |
| unit | % |
| current_research_use | Core metric for H1–H3 (benchmarking the thesis against the bond market). Not a preregistered evidence-test input. Phase 2 uses the daily view. |
| official_source | **CFETS / ChinaMoney SDDS 政府债券利率, 10年期国债收益率.** It is taken from the **CFETS 国债实时收益率均值曲线 at 11:30** each trading day (note-974). It is neither the 17:00 closing curve nor the CCDC 中债 curve. |
| official_access_method | Derived: the last `cn_cgb10y_daily` observation in each completed Beijing month, computed by provider-neutral code (design §4). |
| tushare_candidate | `yc_cb` (1001.CB, curve_type 0, term 10) is the **CCDC 中债 curve**, so APPROXIMATE. It needs a separately granted permission and returned "no permission" on this account. Not a candidate. |
| akshare_candidate | `bond_china_close_return("国债")` → ChinaMoney `ClsYldCurvHis` (CFETS **closing** curve): **APPROXIMATE** (+0.8 bp on 2026-09-30). `bond_china_yield` → CCDC: APPROXIMATE. Not candidates. |
| other_candidate | CCDC `yield.chinabond.com.cn` / MOF `czb/historyQuery` (CCDC-compiled, 2 dp): different curve builder, **APPROXIMATE**, so never a route for this ID (+0.72 bp on 09-30). RiceQuant `中债国债到期收益率曲线_10年`: CCDC, APPROXIMATE. |
| historical_depth | SDDS from **2015-01-04**, the same as Wind's `beginDate`. |
| update_latency | The day-D value is available at about **11:35 Beijing time** on D (`sdds-intr-rate.json` generated 11:34). The month-end is final once the month is complete. |
| point_in_time_quality | Current vintage. The curve point is not revised (INFERRED). Private as-of applies: `available_at = retrieved_at`. |
| api_stability | MEDIUM. Undocumented JSON endpoint. Queries cover at most 1 year; `pageSize` ≥ 100 returned a WAF 403; 15 and 50 work. |
| redistribution | **PRIVATE_ONLY.** The CFETS 法律声明 forbids reproduction **and obtaining content by "电子抓取系统"** without written authorisation, with no personal or non-commercial exception. Note-974 calls the SDDS rate a "public benchmark" users may "reasonably use", but only "in compliance with the site's information-use policy", so it does **not** authorise automation. **Automated retrieval needs CFETS written consent.** The legal footing of manual copying for private research is **unresolved**: the notice forbids reproduction without authorisation and has no private-use exception. Proposed access, failing closed: automated retrieval prohibited, manual import unknown, private use unknown. |
| cost | Free |
| implementation_complexity | LOW (derived from the daily view) |
| semantic_equivalence | **EXACT** |
| recommended_primary | ChinaMoney SDDS (via `cn_cgb10y_daily` + the shared month-end rule with a coverage guard). The access posture and activation gate are the same as for `cn_cgb10y_daily`. |
| recommended_fallback | Wind M0325687 (same series; paid; opt-in) |
| keep_wind_as | FALLBACK |
| confidence | HIGH on equivalence; MEDIUM on terms of automated access |
| evidence | The 3/3 month-end match (2026-07/08/09) is **implied by** the daily match below; it is not independent evidence. `https://www.chinamoney.com.cn/chinese/sddsintigy/`; note-974 (`rawA/note974.json`); `docs/wind-capability-note.md` row 1b. |
| notes | **Retire the latent hazard** `source_fallback: ChinaBond (CCDC) published curve` in `metrics.yaml`. CCDC is a different curve builder at a different time of day. It differed from SDDS by +0.72 bp on 2026-09-30, and its distribution over time is unmeasured. Any CCDC series must be a new metric. |

### 2. `cn_cgb10y_daily`: China 10-year government bond yield, daily

| Field | Value |
|---|---|
| canonical_metric_id | `cn_cgb10y_daily` (tier `supplemental`; `same_series_as: cn_cgb10y`) |
| economic_concept | Trading-day 10Y CGB yield, for 20- and 60-trading-day changes. |
| current_wind_code | M0325687 |
| current_definition | Wind daily observations of "中国:国债收益率:10年", source 中国货币网 |
| frequency | D (trading days, including make-up working days such as 2026-09-20) |
| unit | % |
| current_research_use | **A2** (20/60-obs change in bp, ±5 bp; CONTEXT_ONLY); **D1** bond leg (20-obs change) → R3, R4 |
| official_source | CFETS / ChinaMoney SDDS 10年期国债收益率 (11:30 real-time mean curve) |
| official_access_method | `POST https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/SddsIntrRateGovYldHis?lang=CN&startDate&endDate&pageNum&pageSize=15..50` → `records[].dateString, tenRate` (4 dp). Latest: `/r/cms/www/chinamoney/data/currency/sdds-intr-rate.json`. |
| tushare_candidate | None equivalent (`yc_cb` = CCDC, APPROXIMATE; no permission) |
| akshare_candidate | None equivalent (closing curve / CCDC: APPROXIMATE). AKShare's `bond_china_close_return` also truncates at 50 records and relies on a hard-coded robot-check key, so do not adopt it. |
| other_candidate | Same as for `cn_cgb10y`: CCDC, MOF, RiceQuant, all APPROXIMATE. Sina `CN10YT` quote OHLC: NOT_EQUIVALENT. |
| historical_depth | 2015-01-04 → present. A full backfill is about 12 one-year windows × pages of 50 rows. |
| update_latency | About 11:35 BJT on day D |
| point_in_time_quality | Current vintage; private `available_at = retrieved_at`. |
| api_stability | MEDIUM (WAF on large page sizes; undocumented) |
| redistribution | **PRIVATE_ONLY** (as for `cn_cgb10y`; the same terms) |
| cost | Free |
| implementation_complexity | LOW–MEDIUM (paging, throttling, 1-year windows, schema-drift checks) |
| semantic_equivalence | **EXACT** |
| recommended_primary | ChinaMoney SDDS, with **activation gated on CFETS**. Preferred posture, in order: (1) CFETS written permission for low-frequency automated retrieval; (2) otherwise an authorised structured provider, but none exists for this series, because TuShare `yc_cb` is the CCDC curve; (3) otherwise keep Wind active. A manual capture-and-import route is documented only, with **unresolved legal footing**, and is not recommended. In it, the researcher saves the page's query result, and it is imported with `retrieved_at` = import time at least every 5 days, because the A2/D1 staleness limit is 10 days. The page's download format was **not captured** in the audit and must be recorded before a parser is written. |
| recommended_fallback | Wind M0325687 (opt-in, paid) |
| keep_wind_as | FALLBACK |
| confidence | HIGH |
| evidence | VALUE_MATCH **48/48** days 2026-07-27..09-30, with the same date set (Subagent A). **30/30** re-checked independently from the saved pages (`rawA/sdds_p1.json`, `sdds_p2.json`) against `data/private/wind/runs/20261004T195141Z/raw/01_rates.a1.json`. |
| notes | The CFETS closing curve differed from SDDS by **+0.80 bp** on 09-30. Subagent A reported +8.0 bp, a ×10 scaling error caught in review. On the other three checked days the gap was below 0.5 bp in absolute value; re-derive these from raw before relying on them. The gaps are small, but these remain **different statistics**: a different curve, a different time of day (17:00 vs 11:30), or a different builder (CCDC). Their gap distribution is unmeasured, and splicing them into a 20/60-observation window would inject a level shift. So they are APPROXIMATE and never a route for this ID. |

### 3. `cn_dr007`: DR007

| Field | Value |
|---|---|
| canonical_metric_id | `cn_dr007` (supplemental, private_only) |
| economic_concept | Interbank liquidity: the whole-day volume-weighted average rate of 7-day pledged repo between **depository institutions**. |
| current_wind_code | M1006337 "DR007" (source 中国货币网) |
| current_definition | CFETS DR007 weighted average rate, daily |
| frequency | D (trading days). Some days have no official DR007 row: on 2026-09-30 the 日报 and the history CSV both omit it although the intraday board showed a rate. The cause is UNKNOWN; follow the official CSV. |
| unit | % |
| current_research_use | **A1** (median of the last 20 obs vs the prior 20, ±10 bp; CONFIRMATORY) → R2; feeds the D1 liquidity leg |
| official_source | CFETS / ChinaMoney 质押式回购 DR series |
| official_access_method | `GET https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/currency/prr-chrt.csv` (header-less; DR007 is **zero-based field index 7, the 8th field**. Counted from 1, "column 7" is a different series that matches Wind 0/47 and has a 2026-09-30 value). This is the file the chart page loads, **not a download the site offers to users**. Daily report `PrDlyBltn` (about 2 weeks). **Do not use** the intraday board `prr-md.json`: it showed a DR007 value on 2026-09-30, a day the official 日报 has none. |
| tushare_candidate | `repo_daily` (doc 256), `ts_code='DR007.IB'`, field **`weight`** "加权价 (%)". Needs **2000 points** (about CNY 200/yr for an individual). **This account: no permission (40203).** Do not use `close`, `R007.IB` or `GC007`. |
| akshare_candidate | **None.** `repo_rate_query` / `repo_rate_hist` → ChinaMoney `frr-chrt.csv`, `fdr-chrt.csv`, `FrrHis` give FR007 (all institutions, NOT_EQUIVALENT) and FDR007 (morning fixing, APPROXIMATE). |
| other_candidate | RiceQuant `econ.get_interbank_pledged_repo_rate` DR007 (decimal, ×100): FE per its docs; price unpublished. CFETS paid data service (CMDS) for deep history. |
| historical_depth | ChinaMoney public: **about 3 months only** (2026-06-30 →). That covers A1's 40 observations, but nothing earlier can be backfilled. TuShare: UNKNOWN (doc silent; DR launched 2014-12-15). |
| update_latency | ChinaMoney: 日报 note says 22:00–22:30 BJT on day D; the CSV's Last-Modified was 22:00 on one observed day (a single observation). TuShare: "18:30–19:00" per the MCP tool description (DOC_CLAIM, single source). |
| point_in_time_quality | Current vintage; not revised (INFERRED). Private `available_at = retrieved_at`. |
| api_stability | ChinaMoney CSV: MEDIUM (static file, about 3-month rolling window). TuShare: HIGH (documented API). |
| redistribution | **PRIVATE_ONLY.** CFETS 法律声明 forbids reproduction, redistribution **and** automated scraping without written consent. The legal footing of manual private copying is unresolved. TuShare licence: personal, non-commercial viewing only. TuShare's licence does not cleanse CFETS's upstream rights. |
| cost | ChinaMoney free. TuShare CNY 200/yr (2000-point tier, individual; ×10 for institutions). |
| implementation_complexity | LOW (either route) |
| semantic_equivalence | ChinaMoney **EXACT**. TuShare **UNKNOWN**: the doc sample behaves like a weighted average, but no DR007 value comparison was possible, and holiday-row behaviour is unchecked. |
| recommended_primary | **ChinaMoney `prr-chrt.csv` (EXACT), with activation gated on CFETS.** Preferred posture, in order: (1) CFETS written permission, then automated retrieval after 22:30 BJT; (2) otherwise an authorised structured provider, but TuShare does not yet qualify: its equivalence is UNKNOWN, this account has no permission, and TuShare's own upstream licence from CFETS is not established; (3) otherwise keep Wind active. A manual capture imported at least every 5 days (the A1 staleness limit is 10 days) is documented only, with **unresolved legal footing**, and is not recommended. **Window caveat:** the only capture (2026-10-05, during the holiday) starts exactly at the last quarter-end (2026-06-30). The file may be **quarter-to-date** rather than a rolling 3 months, and that is UNKNOWN until it is re-checked after the first trading day of Q4 (2026-10-09). If it is quarter-to-date, A1 survives each quarter roll only through our own accumulated publications, so a permitted route must collect continuously. The re-check is done by viewing the page, not by automated fetching. The 2026-10-05 capture (2026-06-30..09-29) stays in the private audit archive, and it is not imported unless a recorded decision permits manual import. |
| recommended_fallback | Wind, which stays active until a permitted route passes every gate. TuShare `repo_daily` could become a candidate only if the user buys the 2000-point tier **and** TuShare's upstream licence and the use status are settled. It would then need \|Δ\| = 0 on the 47 Wind days, with the same missing days. |
| keep_wind_as | FALLBACK |
| confidence | HIGH on ChinaMoney equivalence; LOW on TuShare equivalence until checked; MEDIUM on legal footing |
| evidence | VALUE_MATCH **47/47** (2026-07-27..09-29), independently re-checked (`rawA/prr.csv` vs `01_rates.a1.json`). TuShare doc 256 sample: DR007.IB 2020-08-04 `weight` 2.1144 vs FDR007 2.10 / FR007 2.14, consistent with a weighted average. Live MCP call → 40203. |
| notes | The CSV has **no header row** and a leading blank line, and holds about 67 data rows. The parser must check column positions against a known shape and fail closed (SCHEMA_DRIFT). Wind's deep history (2014 →) is not reproducible from free sources, but Phase 2 does not need it. |

### 4–7. PBOC new RMB loans, single-month flows (four views)

| Field | `cn_loans_hh_short_flow` | `cn_loans_hh_mlt_flow` | `cn_loans_corp_short_flow` | `cn_loans_corp_mlt_flow` |
|---|---|---|---|---|
| canonical_metric_id | `cn_loans_hh_short_flow` (supplemental, private_only) | `cn_loans_hh_mlt_flow` (supplemental, private_only) | `cn_loans_corp_short_flow` (supplemental, private_only) | `cn_loans_corp_mlt_flow` (supplemental, private_only) |
| economic_concept | Household short-term credit (consumer + operating) | Household medium/long-term credit (mostly mortgages) | Corporate working-capital credit | Corporate capex-type credit |
| current_wind_code | M0057874 | M0057875 | M0057876 | M0057877 |
| current_definition | "中国:金融机构:新增人民币贷款:居民户:短期:当月值" | "…居民户:中长期:当月值" | "…企(事)业单位:短期:当月值" | "…企(事)业单位:中长期:当月值" |
| current_research_use | B1 → R1, R2, R4 | B1 (dictionary `evidence_use: mirror` of `cn_loans_hh_mlt_ytd`, but consumed by B1) | B2 → R1, R2, R4 | B2 (mirror of `cn_loans_corp_mlt_ytd`, consumed by B2) |

Fields common to all four:

| Field | Value |
|---|---|
| frequency / unit | M / CNY 100m (亿元) |
| official_source | **PBOC 金融统计数据报告** (monthly press release, 新闻发布 list `/goutongjiaoliu/113456/113469/`). Section 五 states **YTD** increases by sector × maturity (住户: 短期, 中长期; 企(事)业单位: 短期, 中长期, 票据融资). |
| official_access_method | HTML press release. Single month = **YTD(m) − YTD(m−1)** within a calendar year; **January = YTD(Jan)** (the January release states "1月份" sector detail). Amounts ≥ 1 万亿 are printed in 万亿 to **at most** 2 dp (trailing zeros dropped, e.g. "1.1万亿" in 2025 Q3), so they are converted ×10000 and the ≥ 100亿 grain is kept. |
| tushare_candidate | **None.** TuShare has no loan table; `cn_m` and `sf_month` are money and total TSF only (full menu enumerated). |
| akshare_candidate | **None.** `macro_china_new_financial_credit` (eastmoney) and `macro_rmb_loan` (10jqka) carry **totals only**, so they are NOT_EQUIVALENT. |
| other_candidate | (i) **PBOC 金融机构人民币信贷收支表** balances (short-term rows exist; `scripts/fetch_pboc.py` reads only 中长期): balance differences are **APPROXIMATE** (household within about 1 亿, corporate within about ±80 亿; write-off and reclassification effects are not separable). Cross-check only. (ii) RiceQuant `econ.credit_financing` 金融机构新增贷款 住户/企(事)业单位 × 短期/中长期: likely FE, but whether the 住户 factors are monthly or YTD is UNKNOWN and the price is unpublished. |
| historical_depth | Press releases online back to **2016** at least (VERIFIED_LIVE). B1/B2 need 15 months. Older releases use different sector labels (住户部门, 非金融企业及机关团体), which the parser must map explicitly. |
| update_latency | No fixed calendar; usually the 10th–15th of month m+1, about 16:30–17:00 BJT (2026-02-13 17:00, 2026-08-14 16:30, 2026-09-14 17:00). |
| point_in_time_quality | First print as published. Pages are occasionally re-saved (`createDate` changes), but the values look unchanged (INFERRED). Private `available_at = retrieved_at`. |
| api_stability | MEDIUM: HTML text with sentence-level parsing; no fixed release URL; label drift across years. The label map must normalize full-width and half-width parentheses (企（事）业单位 = 企(事)业单位). pbc.gov.cn served curl with a browser User-Agent. A JS challenge exists for some clients: **stop on a challenge, never circumvent it.** |
| redistribution | Source: government statistics. PBOC's own terms page was not read, so **INFERRED** public. Project policy (`docs/data-policy.md`) already treats PBOC as a public source, and the demo republishes PBOC tables. The **metrics stay PRIVATE_ONLY** in V1.2.1; reclassification is a separate written decision (data-policy rule 2). |
| cost | Free |
| implementation_complexity | MEDIUM (press-release discovery, a robust Chinese-number parser for 亿/万亿 and 增加/减少, YTD differencing, January rule, label mapping) |
| semantic_equivalence | **EXACT.** Wind's 当月值 *are* the differences of PBOC-reported YTD figures, rounding included. |
| recommended_primary | PBOC 金融统计数据报告 |
| recommended_fallback | Wind (opt-in) for the same numbers. The 信贷收支表 balance differences are **cross_check only** (APPROXIMATE). |
| keep_wind_as | FALLBACK |
| confidence | HIGH |
| evidence | VALUE_MATCH **8/8**: Aug 2026 (from the 2026-07 and 2026-08 YTD releases) and Jan 2026, all four series. The Wind Jan–Aug 2026 monthly values also sum to PBOC's published Aug YTD for all four series. That is a weak, telescoping consistency check, not per-month evidence. All corporate values are multiples of 100, the fingerprint of differencing 2-dp 万亿 figures. `rawA/pbc_202607.html`, `pbc_202608.html`, `pbc_2026021314205610794.html`, `cmp_loans.py`. |
| notes | (1) Only **2 months** are individually verified. The local Wind snapshot covers **2025-08..2026-08** (13 months, from its narrower Phase 1 window), so **activation validation stays PENDING** until all 13 months are compared individually for all four series. Semantic equivalence is EXACT regardless. Candidate implementation may proceed before the check; production activation may not. The B1/B2 year-ago months before 2025-08 cannot be compared with Wind at all. (2) The ±50–100 亿 rounding noise in corporate flows is shared with Wind, so it is not a substitution artifact. (3) **Do not** reuse the public `cn_loans_*_ytd` balance-derived series for these IDs. They are APPROXIMATE, and that is **unsafe even as a fallback**: B1 and B2 classify on `delta > 0` with no dead band, so a ±80亿 definitional gap can flip a component. (4) The release itself equates 企（事）业单位 with 非金融企业及机关团体, so the label change across years is a renaming, not a population change. |

### 8. `mkt_csi300`: CSI 300 daily close

| Field | Value |
|---|---|
| canonical_metric_id | `mkt_csi300` |
| economic_concept | Market confirmation: the official daily closing level of the CSI 300 index |
| current_wind_code | 000300.SH via `index_data.get_index_kline`, `value_field: MATCH` |
| current_definition | K-line bar close, 2 dp, unitless index points |
| frequency | D (trading days) |
| unit | index points |
| current_research_use | **D1** equity leg (20-obs return, ±3 %; CONTEXT_ONLY) → R3, R4 (F2 flag) |
| official_source | **China Securities Index Co. (csindex.com.cn)**, the index owner and calculator. SSE disseminates 000300. |
| official_access_method | `GET https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=000300&startDate=YYYYMMDD&endDate=YYYYMMDD` (JSON: `tradeDate, open, high, low, close, …`). SSE: `https://yunhq.sse.com.cn:32042/v1/sh1/dayk/000300?...` (3 dp). |
| tushare_candidate | `index_daily` (doc 95), `ts_code='000300.SH'`, field `close` (4 dp). Needs 2000 points; this account is throttled to 1/min, then 1/hour. |
| akshare_candidate | `stock_zh_index_hist_csindex("000300")` → csindex (official; AKShare is only an adapter; known crash on empty frames). Sina, eastmoney and Tencent variants: FE but fragile, and Sina runs obfuscated JS. |
| other_candidate | SSE yunhq (FE on 3 dates only; 3 dp, rounding-edge risk at .xx5; the endpoint needs a Referer header that imitates the site, a mild access-control workaround). Cross-check at most. |
| historical_depth | csindex: 2002-01-04 → present in one request (pre-2005 values back-calculated). TuShare: 2005-01-04 (DOC_CLAIM/INFERRED; not live-checked because of throttling). |
| update_latency | Final after the 15:00 close (csindex home shows "15:00"); TuShare 15:00–17:00 / 19:00 (DOC_CLAIM) |
| point_in_time_quality | Official close, not revised. Private `available_at = retrieved_at`. |
| api_stability | csindex: MEDIUM (undocumented JSON, but stable and simple). TuShare: HIGH. SSE: MEDIUM. |
| redistribution | **PRIVATE_ONLY.** CSI terms allow browsing and downloading for **non-commercial** purposes; reproduction, redistribution or "电子抓取" for others needs written consent. **Whether this project's actual use is non-commercial is unresolved**: a work-related or public portfolio site is not assumed to be non-commercial. Live collection and activation wait on that decision. TuShare: personal viewing only. |
| cost | csindex free. TuShare CNY 200/yr. |
| implementation_complexity | LOW |
| semantic_equivalence | csindex **EXACT**; TuShare **FE**, with the stated identity transformation ROUND_HALF_UP to 2 dp (21/21 including tie cases; values saved as `tushare_csi300_20261005.json` in the private evidence archive); SSE **FE** |
| recommended_primary | CSI (csindex.com.cn). Candidate implementation proceeds now. Live collection and activation follow the use-status decision and validation. |
| recommended_fallback | TuShare `index_daily` (after the tier upgrade), then Wind (opt-in) |
| keep_wind_as | FALLBACK |
| confidence | HIGH |
| evidence | csindex VALUE_MATCH **28/28** (2026-08-21..09-30, 2 dp). TuShare live 2026-10-05: 21 overlapping days; unrounded max \|Δ\| = 0.005 (0/21 equal); after Decimal ROUND_HALF_UP to 2 dp, **21/21 equal**. `rawA/csi.json`, `csi_all.json`, `csidisc.js`; TuShare doc 95. |
| notes | csindex itself publishes 2 dp, so no rounding step is needed on the primary. The TuShare route must round half-up to 2 dp. Unrounded 4-dp closes would shift a 20-observation return by up to about 2.3e-4 pp, enough to flip D1 in a knife-edge case at the contract's 6-dp precision. Drop csindex's stray `20000101` row. |

### 9–12. Tier-1 city daily new-home transaction area (four views)

| Field | `cn_hf_prop_bj` | `cn_hf_prop_sh` | `cn_hf_prop_sz` | `cn_hf_prop_gz` |
|---|---|---|---|---|
| canonical_metric_id | `cn_hf_prop_bj` (supplemental, private_only) | `cn_hf_prop_sh` (supplemental, private_only) | `cn_hf_prop_sz` (supplemental, private_only) | `cn_hf_prop_gz` (supplemental, private_only) |
| current_wind_code / name | S0203228 "中国:北京:成交面积(签约):商品房" | S0146015 "中国:上海:成交面积:商品房" | S0048279 "中国:深圳:成交面积:商品房" | S0175476 "中国:广州:成交面积(签约):商品房" |
| Wind history | 2006-01-01 → | 2008-04-14 → | 2006-12-07 → | 2009-10-31 → |
| official_source | 北京市住建委, page 307749: **yesterday's** 期房网上签约 + 现房网上签约 area by use (住宅/商业/办公/车位), 4 dp | 上海市房地产交易中心 fangdi.com.cn: 全市 `sign_area` (today, all uses, 2 dp) plus `all_sign_area` YTD | 深圳市房地产信息平台 `fdc.zjj.sz.gov.cn` (legacy pages 404) | 阳光家缘 `zfcj.gz.gov.cn/ysqgk/Api/WebApi/mrxjspfqyxx.ashx`: latest day, 11 districts, 住宅/商业/办公/车位 area (4 dp; the page shows integers) |
| official_access_method | Plain HTML GET (http only) | XHR `POST /service/trade/getFirstTransactionStat.action` behind a **Ruishu-style JS challenge** (plain curl gets HTTP 412) | **Blocked from this host** (412, then 400 even in a browser) | Plain JSON GET/POST; date parameters are ignored |
| access verdict | Automatable | **Not automatable without bot-detection circumvention. Not acceptable.** | UNKNOWN (may work from a mainland IP) | Automatable |
| redistribution / terms | UNKNOWN (no statement found) → PRIVATE_ONLY | © 上海市房地产交易中心; terms not read → PRIVATE_ONLY | UNKNOWN → PRIVATE_ONLY | 网站声明: no commercial use, 转载 or 镜像 without written authorisation → PRIVATE_ONLY |
| semantic_equivalence | **UNKNOWN**. FE *if* Wind = 期房 + 现房 网上签约, all uses incl. 车位. The Wind name "(签约):商品房" fits, but it could be 住宅 only. | **UNKNOWN**. FE *if* Wind = 全市 一手 `sign_area` at end of day. On fangdi, 成交 = 网签. | **UNKNOWN** | **UNKNOWN**. FE *if* Wind = the 4-use 签约 sum truncated or rounded to integers (Wind values are integers). |
| recommended_primary | Own PIT daily collector as a **candidate route** until equivalence is verified. Automated collection needs human sign-off (terms UNKNOWN). | none (no acceptable route) | none until reachable and inspected | Own PIT daily collector, candidate route. Automated collection needs human sign-off (terms forbid commercial use and mirroring). |
| tier | B | C | B (blocked) | B |

Fields common to all four:

| Field | Value |
|---|---|
| economic_concept | High-frequency tier-1 new-home transaction volume, one city each, never summed (C2 compares momenta, not areas) |
| current_definition | Wind daily series from each municipal bureau; definitions differ by city (签约 vs 成交) |
| frequency / unit | D (calendar days, weekends included) / m² |
| current_research_use | **C1** per city (28-day mean vs prior 28, ±5 %; ≥ 20 observed days per window; staleness ≤ 7 d) → **C2** (requires **all four** cities) → R1, R2, R4 |
| tushare_candidate | **None** (TuShare has no property section) |
| akshare_candidate | **None.** GitHub scrapers are snapshot-only. Shanghai ones bypass Ruishu (lyt26/fangdi-collector) or OCR screenshots: **must not be used**. The Shenzhen one hard-codes a third party's session cookies: must not be reused. The Guangzhou ones track 5 projects: NOT_EQUIVALENT. |
| other_candidate | None found. RiceQuant has only monthly NBS city series (NOT_EQUIVALENT). No API anywhere offers daily city transaction history. |
| historical_depth | **None from first-party sources.** Latest day only, and the Wayback Machine has no captures in the Wind window. History accrues from the first capture. C1 needs ≥ 20 observed days in each of two 28-day windows. With the first observed date 2026-10-04 and no missed day, the earliest anchor is about **2026-11-20**. Its previous window then starts in Golden Week, so the first readings carry a strong holiday bias (caveated, not adjusted). |
| update_latency | BJ: the previous day. SH: "17:00之前为昨日数据" (the current day's value changes until about 17:00 the next day). GZ: the previous day. |
| point_in_time_quality | Capture-only. Real PIT vintages from our own retrievals; nothing earlier exists. `available_at = retrieved_at`. A city revising yesterday's figure would show as a second vintage (store `as_of` keeps the latest held). |
| api_stability | LOW (municipal pages change without notice; SZ already migrated once) |
| cost | Free |
| implementation_complexity | MEDIUM per city (parser + daily Task Scheduler job + drift checks) |
| recommended_fallback | Wind (when credits exist) |
| keep_wind_as | PRIMARY for history; CROSS_CHECK to activate the new routes |
| confidence | LOW (no value comparison possible) |
| evidence | `rawA/bj.html`, `bj307749.html`, `gzq.json`, `gzqy.json`, `gzstat.html`, `home.html` (fangdi). Wind names from `metrics.yaml:687-769`. C_akshare.md §4 repo table. |
| notes | (1) **Equivalence can only be proven against a Wind value for the same day.** The local Wind snapshot ends 2026-10-03 and the first own snapshot would be at least 2026-10-04 (BJ showed "2026/10/4" on 10-05), so a one-off Wind cross-check call is needed after the first own captures. That costs credits. **A credit-free first step:** the September 2026 Wind daily values are complete for BJ, SH and SZ (GZ is missing 3 days). Compare their monthly sums with any monthly or year-to-date totals the city publishes by use (BJ yearly tables split 住宅/非住宅; SH monthly or YTD; GZ statistics pages). This can establish *which uses Wind includes*. It cannot prove day-level identity. (2) **C2 requires all four cities.** Without Shanghai, C2 and the property legs of R1, R2 and R4 stay INSUFFICIENT_DATA under every non-Wind plan, and a three-city C2 would be a **new signal version**, not a substitution. (3) Start candidate collection early, once terms are signed off: history that is not captured now cannot be recovered later. (4) **Never splice** candidate city rows onto the Wind history under the canonical ID. A 10–20 % definitional level gap would show up as momentum beyond ±5 %. (5) Shanghai's YTD counter (`all_sign_area`) cannot rebuild missed single days: it gives a net multi-day total that cancellations (退房) distort, and assigning it to days would be imputation, which C1 forbids. |

### 13–14. Wind consensus forecasts (CPI YoY, PPI YoY)

| Field | Value |
|---|---|
| canonical_metric_id | `cn_cpi_consensus_wind`, `cn_ppi_consensus_wind` (supplemental, private_only, `experimental: true`) |
| economic_concept | **Wind's proprietary** consensus forecast for the target month's CPI/PPI YoY, snapshotted at each retrieval |
| current_wind_code | M0061676 "万得一致预测:中国:CPI:当月同比"; M0061677 "…:PPI:当月同比" |
| current_definition | Wind-compiled forecast panel aggregate; history looks frozen pre-release but this is **not validated** (capability note §6) |
| frequency / unit | M / % |
| current_research_use | **X1** only (EXPERIMENTAL_SNAPSHOT_ONLY; no values used; feeds nothing) |
| official_source | **None.** NBS, PBOC and MOF publish actuals only. |
| official_access_method | n/a |
| tushare_candidate | `eco_cal` `fore_value` (string; China CPI/PPI rows often blank; duplicated events with no timestamp; upstream not cited; no permission on this account): **NOT_EQUIVALENT** |
| akshare_candidate | `macro_china_cpi_yearly` / `ppi_yearly` → jin10 (hard-coded app-id; maintainer says Reuters-poll based); `macro_info_ws` → wallstreetcn; `news_economic_baidu` → Baidu (cookie harvesting + TLS impersonation: **avoid**). All **NOT_EQUIVALENT**. |
| other_candidate | RiceQuant `CPI预测` / `PPI预测` (aggregate plus about 57 per-broker series; different panel): **APPROXIMATE**. iFinD and Choice panels (INFERRED; not verified): APPROXIMATE; seat licences. |
| historical_depth | Wind: CPI 2007-12, PPI 2008-02 (current-vintage history; not PIT) |
| update_latency | Snapshot at retrieval |
| point_in_time_quality | Snapshot-only; pre-release freezing **not validated** |
| api_stability | n/a for substitutes |
| redistribution | PRIVATE_ONLY (Wind-proprietary; the highest redistribution risk per the capability note §10) |
| cost | Wind credits (exhausted) |
| implementation_complexity | n/a |
| semantic_equivalence | **NOT_EQUIVALENT** for every free candidate; **APPROXIMATE** for RiceQuant/iFinD/Choice panels |
| recommended_primary | Wind (sole). The metric *is* Wind's product, and the IDs name it. |
| recommended_fallback | **None.** Any other consensus would be a **new metric** (e.g. `cn_cpi_consensus_<provider>`) under a **new X-series contract**. |
| keep_wind_as | PRIMARY |
| confidence | HIGH that no equivalent exists |
| evidence | `docs/wind-capability-note.md` §6, §10; B_tushare §1.6; C_akshare §6 |
| notes | The release-time validation planned for **2026-10-14** (September CPI/PPI) needs Wind snapshots on 10-13/14 and a re-query afterwards. **With no credits it cannot run**, so `validation.status` stays `NOT_VALIDATED` and X1 stays a no-op. That is acceptable: X1 feeds nothing. |

---

## Cross-cutting findings

1. **The producer behind Wind is reachable for 8 of 14 views, and the values match exactly.** Wind republishes
   ChinaMoney (DR007, 10Y SDDS), PBOC (loans) and CSI (index). Going to the producer is not a proxy.
2. **History, not semantics, is the binding constraint.** DR007 has about 3 months of public history and the
   property views have none. Phase 2 needs only about 40 DR007 observations and 56 days per city, and our own
   publications accumulate honestly under `available_at = retrieved_at`.
3. **Legal footing for automated access is the main open risk**, and it is more binding than the redistribution
   question:
   - CFETS's 法律声明 forbids obtaining content by "电子抓取系统" without written consent, with no personal or
     non-commercial exception. That covers **both DR007 and the SDDS 10Y**: note-974's "reasonable use" defers to the
     same policy. The legal footing of manual private copying is unresolved, and `prr-chrt.csv` is a chart's backing
     file, not an offered download. **Access to these two routes therefore fails closed.** The preferred order is:
     1. CFETS written permission, or another clearly authorised retrieval;
     2. otherwise an authorised structured provider. None qualifies yet: TuShare's DR007 equivalence and its upstream
        licence are not established, and TuShare has no 10Y equivalent;
     3. otherwise keep Wind active.

     Manual capture-and-import stays documented as an option with unresolved legal footing. It is not recommended.
     The parser can be built and tested on synthetic fixtures now. Live retrieval and activation wait.
   - The municipal property collectors get the same posture. Guangzhou's terms forbid commercial use and
     mirroring, and Beijing's terms are UNKNOWN. Daily automated collection there has access status unknown, so it fails closed until a human gives
     sign-off.
   - CSI permits downloading for non-commercial purposes only, and whether this project qualifies is unresolved.
   - PBOC is a government publisher.
   - TuShare's API is licensed for personal use. It could be an automated DR007 candidate if the tier is bought.
     However, it does not cleanse CFETS's upstream rights, and its own upstream licensing is not established.
4. **AKShare should not be a runtime dependency.** It adds no data. Several of its functions embed third-party
   tokens or app-ids or work around bot checks, and its ChinaMoney yield wrapper silently truncates at 50 records.
   Its source is useful as endpoint documentation.
5. **Shanghai property and Wind consensus are the hard residual Wind dependencies.** C2 (four-city breadth) cannot be
   restored without Shanghai.

## Sources consulted

ChinaMoney: `/chinese/sddsintigy/`, `SddsIntrRateGovYldHis`, `sdds-intr-rate.json`, `prr-chrt.csv`, `PrDlyBltn`,
`FrrHis`, `ClsYldCurvHis`, `/chinese/legaldeclaration/`. CCDC: `yield.chinabond.com.cn` `czbChartSearch`,
`historyQuery`. PBOC: `/goutongjiaoliu/113456/113469/` (2026-01, 2026-07, 2026-08, 2025 Q1–Q3, 2016 H1 releases),
`/diaochatongjisi/attachDir/2026/09/2026091417342577618.htm`. CSI: `csindex-home/perf/index-perf`, disclaimer route.
SSE: `yunhq.sse.com.cn` dayk. Municipal: `bjjs.zjw.beijing.gov.cn` pageId=307749, `fangdi.com.cn` trade page,
`fdc.zjj.sz.gov.cn`, `zfcj.gz.gov.cn` `mrxjspfqyxx.ashx` and 网站声明. TuShare: docs 95, 149, 201, 233, 242, 256, 290,
310, 405, 409, 463 and the live MCP calls. RiceQuant: macro-economy docs and factor CSVs. AKShare at commit
`fac1e50` (`bond_china_money.py`, `bond_china.py`, `bond_em.py`, `repo_rate.py`, `macro_china.py`,
`macro_finance_ths.py`, `index_stock_zh_csindex.py`, `index_stock_zh.py`, `index_zh_em.py`, `macro_info_ws.py`,
`news_baidu.py`) and the GitHub scraper repositories listed in §9–12. Raw captures, research notes and the reviews are archived privately at `data/private/provider-audit/20261005/` in the main checkout (gitignored, never committed). They were also kept in the session
scratchpad, outside the repository.
