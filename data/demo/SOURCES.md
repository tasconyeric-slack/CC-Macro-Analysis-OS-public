# Demo data sources

Every file in `data/demo/` must be listed here with its source, URL, licence /
redistribution basis and retrieval timestamp. Files not listed here must not be
used by the public build.

All files below are official public statistics, retrieved 2026-10-04 (UTC) from the
researcher's machine. Files are append-only: a later pull adds rows with a new
`retrieved_at` and never edits earlier rows.

**Release dates.** For the 15 NBS-source metrics, a second pull (05:22–05:25Z, plus
05:28Z for industrial profits) carries `release_date` from NBS's official release
agenda (`cnmacro nbs-agenda`; endpoint
https://data.stats.gov.cn/dg/website/publicrelease/web/external/queryAgendas,
`release_date_basis=official_calendar`). The agenda starts in 2018, so it covers every
period held (2019 onward). Not dated: PMI 2022-02, 2024-02 and 2025-03, because the
agenda has no entry for those releases. In 2023 the agenda lists some releases twice
on the same day (e.g. 00:00 and 09:30); these agree on the date and are accepted.
Test entries in the agenda ("测试", "aaaa") map to no metric. Rows from the PBOC tables,
FRED and the NBS-portal republications (M1, budget, exports) have no release date;
their availability is `retrieved_at`.

| File | Source | URL | Redistribution basis | Retrieved at (UTC) |
|---|---|---|---|---|
| `observations/fred_gl_*.csv` (4 files) | FRED gateway (original publisher differs by series) | https://fred.stlouisfed.org/graph/fredgraph.csv | **PUBLIC REPO REDISTRIBUTION NOT CLEARED.** Verify each producer's rights; IMF-origin POILBREUSDM and PCOPPUSDM are specifically flagged. Access/citation alone is not authorization. | 2026-10-04T04:49Z |
| `observations/nbs_*.csv` (18 files) | NBS data portal (国家数据); 3 files republish PBOC, MOF and customs statistics, see the route table | https://data.stats.gov.cn/dg/website/ | Official public statistics; cite NBS (and the originating agency) | 2026-10-04T04:59–05:03Z |
| `observations/inbox_pboc.csv` | PBOC 调查统计司 statistical tables | https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html | Official public statistics; cite PBOC | 2026-10-04T05:10Z |
| `observations/inbox_nbs_pmi_2026-09.csv` | NBS press release, 2026年9月中国采购经理指数运行情况 (published 2026-09-30 09:30) | https://www.stats.gov.cn/sj/zxfb/202609/t20260930_1965449.html | Official public statistics; cite NBS | 2026-10-04T05:32Z |
| `observations/inbox_pboc_m1_2026-08.csv` | PBOC press release, 2026年8月金融统计数据报告 (published 2026-09-14 17:00) | https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/2026091414593871200/index.html | Official public statistics; cite PBOC | 2026-10-04T05:32Z |
| `observations/inbox_gacc_exports_2026-08.csv` | GACC English site, preliminary release (1) Total Export & Import Values, Aug 2026 (in USD), dated 2026/09/09 | http://english.customs.gov.cn/Statics/f8da41eb-f559-4b41-988e-16a0a1869f0e.html | Official public statistics; cite GACC | 2026-10-04T05:32Z |
| `observations/inbox_gacc_us.csv` | GACC English monthly bulletin, table (2) Imports and Exports by Country (Region), one page per month | http://english.customs.gov.cn/statics/report/monthly2019.html … monthly.html (per-row page URL in `source_code`) | Official public statistics; cite GACC | 2026-10-04 |

**Public-release gate (2026-11-02).** `fred_gl_brent_usd.csv` (POILBREUSDM)
and `fred_gl_copper_usd.csv` (PCOPPUSDM) contain IMF-origin historical
observations obtained via FRED. Neither the public repository nor its historical
commits should be published until redistribution rights are confirmed or the
affected datasets are removed/replaced using a separately verified source.
EXCHUS and GS10 must also be checked against their per-series terms and attribution.
This note does not imply that deleting current files clears Git history.
The existing private site/build behavior is unchanged by this documentation.

## Route and coverage per metric

Coverage is the first and last reference period ingested. "Latest official" is the
latest period the originating agency had published as of 2026-10-04, so the lag
column shows how far each route trails the original release.

| Metric | Source | Route (`source_code`) | Rows | Coverage | Lag vs original release |
|---|---|---|---|---|---|
| cn_cpi_yoy | NBS | NBS portal, 3 base-period catalogs (2016-2020, 2021-2025, 2026-) | 92 | 2019-01 – 2026-08 | none |
| cn_core_cpi_yoy | NBS | NBS portal, 2 catalogs (2021-2025, 2026-) | 68 | 2021-01 – 2026-08 | none; **2019-2020 missing**: the portal's 2016-2020 CPI catalog has no core CPI series |
| cn_ppi_yoy, cn_ppi_mom, cn_ppi_producer_yoy, cn_ppi_consumer_yoy | NBS | NBS portal | 92 each | 2019-01 – 2026-08 | none |
| cn_pmi_output_price, cn_pmi_new_orders, cn_pmi_new_export_orders | NBS | NBS portal; 2026-09 from the NBS press release (columns checked against 12 overlapping portal months, all equal) | 93 each | 2019-01 – 2026-09 | closed |
| cn_ip_yoy, cn_retail_sales_yoy | NBS | NBS portal | 76 each | 2019-03 – 2026-08 | none (January-February published combined, so no single-month value for Jan/Feb) |
| cn_property_sales_area_ytd_yoy | NBS | NBS portal | 84 | 2019-02 – 2026-08 | none |
| cn_ind_profit_ytd_yoy | NBS | NBS portal | 84 | 2019-02 – 2026-08 | none |
| cn_ngdp_q, cn_rgdp_yoy | NBS | NBS portal (quarterly) | 30 each | 2019Q1 – 2026Q2 | none |
| cn_m1_yoy | PBOC | NBS portal republication of PBOC money supply; 2026-08 from the PBOC press release text | 92 | 2019-01 – 2026-08 | closed |
| cn_budget_exp_ytd_yoy | MOF | NBS portal republication (国家财政支出(不含债务还本)累计增长) | 83 | 2019-02 – 2026-07 | **1 month**: MOF published Jan-Aug on 2026-09-18, but its release host (gks.mof.gov.cn) is blocked from this network |
| cn_exports_usd_yoy | GACC | NBS portal republication (出口总值同比增长, USD); 2026-08 from the GACC English preliminary release | 92 | 2019-01 – 2026-08 | closed. GACC's monthly bulletin shows later revisions of up to 0.2 pt against the portal for some 2026 months |
| cn_exports_us_ytd_yoy | GACC | GACC English bulletin table (2), United States row, **published** year-to-date export % change taken as-is (no derivation); `scripts/fetch_gacc_us.py` | 89 | 2019-01 – 2026-08 | none. Missing: 2020-01 (published only as Jan-Feb combined), 2024-09 and 2024-10 (not posted on the English site). Release date = bulletin page date for 63 rows. Blank for 26: 18 pages carry no date, and 8 carry a date more than 45 days after the month (later re-uploads, e.g. six 2025 pages dated 2025-09-19). The bulletin page date is later than the preliminary release (~9th of the month) |
| cn_tsf_stock_yoy | PBOC | PBOC 社会融资规模存量统计表, published growth rate | 92 | 2019-01 – 2026-08 | none |
| cn_tsf_govbond_flow | PBOC | PBOC 社会融资规模增量统计表, 政府债券 column | 92 | 2019-01 – 2026-08 | none |
| cn_loans_hh_mlt_ytd, cn_loans_corp_mlt_ytd | PBOC | PBOC 金融机构人民币信贷收支表, **derived** | 92 each | 2019-01 – 2026-08 | none |
| gl_brent_usd, gl_copper_usd | FRED | POILBREUSDM, PCOPPUSDM | 91 each | 2019-01 – 2026-07 | IMF primary commodity prices are monthly with about a 1-month lag |
| gl_usdcny, gl_ust10y | FRED | EXCHUS, GS10 | 93 each | 2019-01 – 2026-09 | none |

**Not ingested (no working public route from this machine):**
- `cn_gov_fund_rev_ytd_yoy` (MOF). The release text is on gks.mof.gov.cn, which returns HTTP 502 to this network (CDN block, also in a browser), and the NBS portal does not carry government-fund revenue.
- `cn_cgb10y` (Wind, private by design).

**Rejected route: DBnomics (provider NBS).** It is reachable, but it holds a rolling window of about 13 months (2025-02 to 2026-02 when checked) and only 6 quarters of GDP. It was last indexed in March 2026, so it is about 6 months behind NBS and cannot supply history from 2019. Not used.

## Caliber notes found in the sources

- **NBS index series.** Indices published as "same period last year = 100" (CPI, core CPI, PPI and its sub-indices, real GDP index) and "previous month = 100" (PPI MoM) are stored as `value - 100`, so the unit is %. The `@idx100` suffix in `source_code` marks this.
- **CPI base periods.** NBS splits CPI into catalogs by base period (2016-2020, 2021-2025, 2026-). The YoY values in each catalog are NBS's own published figures, so they are stitched without adjustment.
- **GDP vintages.** GDP levels and growth are the portal's current (revised) values, not first prints. For example, history reflects later census and annual revisions. Use them for structure, not to reconstruct what the market knew at the time.
- **M1, January 2025.** PBOC footnote: from January 2025 data PBOC uses a revised M1 definition (adds household demand deposits and non-bank payment institutions' customer reserves). The published YoY from 2025-01 onward is on the new definition.
- **TSF.** PBOC footnote 1 defines AFRE stock and flow. The coverage changes recorded in the dictionary (`caliber_notes`) still apply. The stock growth rate is PBOC's published figure, not computed from levels.
- **Medium/long-term loans (household and corporate), year-to-date.** Derived as the month-end balance minus the prior December's balance in PBOC's RMB credit table. This can differ from PBOC's reported increments where loans were reclassified or written off, and each row says so in `limitation`. Before 2023 PBOC labels the corporate line 非金融企业及机关团体贷款; from 2023 it is 企（事）业单位贷款. The parser maps both.

## Retrieval note

The researcher's machine clock was 12 hours slow on 2026-10-04 (measured against HTTP `Date` headers from three servers: offset +12.003 h). All `retrieved_at` values in these files were shifted by +12 h to the true UTC time. Fix the machine clock before the next pull.

From 2026-10-04 new observations are appended by the scheduled public refresh on GitHub-hosted runners (clock synchronised by the runner), with `retrieved_at` set at fetch time and `release_date` taken from the official calendar.

## Rights review for the release candidate (2026-11-02)

The 29 tracked observation CSVs were inventoried by row-level `source` and
`source_class`: 4 FRED, 18 NBS series plus 2 NBS release inboxes, 3 PBOC files,
and 2 GACC files. The 18 NBS series include republished PBOC, MOF and GACC
observations. All rows label themselves public; that label is provenance metadata,
not proof of redistribution rights. The two `nbs_*release.csv` files and later
refresh additions postdate the original inventory above. Consult each row's
`source_code`, `retrieved_at` and release records for its route and vintage.

- FRED `EXCHUS` ([series](https://fred.stlouisfed.org/series/EXCHUS)) and
  `GS10` ([series](https://fred.stlouisfed.org/series/GS10)) identify the Board
  of Governors as producer and label the series public domain, citation requested.
- FRED [Brent](https://fred.stlouisfed.org/series/POILBREUSDM) and
  [copper](https://fred.stlouisfed.org/series/PCOPPUSDM) identify IMF Primary
  Commodity Prices and link to IMF terms. The IMF's [special statistical data
  terms](https://www.imf.org/en/About/copyright-and-terms) allow redistribution
  under conditions including attribution and preservation of integrity; they
  address data obtained from IMF sites and request permission for potential
  commercial reuse. The present files were obtained through FRED, not directly
  from an IMF site. Confirmation covering this route and unrestricted public
  redistribution is outstanding. No rights are inferred merely from access.
- [NBS terms](https://www.stats.gov.cn/english/nbs/200701/t20070104_59236.html)
  permit qualifying reprints with prominent attribution and list exclusions,
  including third-party works. Verify coverage and attribution for these data and
  distinguish original NBS series from republished PBOC, MOF and GACC series.
- Direct PBOC and GACC sources and NBS republications from PBOC, MOF and GACC
  remain subject to source-specific terms review. The current inventory does not
  establish blanket rights for redistribution or commercial use.

Do not publish this candidate pending the above rights decisions and the history
review. The public research rules and existing data are retained during review.
