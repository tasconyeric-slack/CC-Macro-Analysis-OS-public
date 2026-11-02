# Global-China Macro Data Dictionary & Input Spec v0.1

> Case-scoped. The dictionary itself is `data/dictionary/metrics.yaml` (machine-readable,
> validated by `tests/test_case_definition.py`). This document explains its rules
> and the input contract.

## 1. Budget

- **≤ 24 core metrics**, evaluated in every thesis run. Current: 23.
- **≤ 6 conditional diagnostics**, pulled only when a core signal needs decomposition or a cross-check. Current: 6.
- Every metric declares the hypotheses it serves (H0–H4) and a one-line `role`. A metric without a role in a test or a claim is a candidate for removal.
- Derived series (deflator, single-month flows, moving averages, percentiles) are **not** metrics. They are computed with lineage by `cnmacro.derive`.

| Hypothesis | Core metrics |
|---|---|
| Target / H1 price | nominal GDP (level), real GDP YoY, PPI YoY, PPI MoM, CPI YoY, PMI output prices |
| H2 domestic demand | core CPI, M1, household MLT loans, retail sales, property sales, industrial profits, PMI new orders |
| H3 policy impulse | TSF stock YoY, TSF government bond flow, budget expenditure |
| H4 external | exports (USD), PMI new export orders |
| Global / markets | Brent, copper, USD/CNY, UST 10Y, CGB 10Y |

## 2. Three objects

| Object | Where | Tracked in git? |
|---|---|---|
| `metric` | `data/dictionary/metrics.yaml` | yes |
| `observation` | `data/demo/observations/*.csv` (public) · `data/private/observations/*.csv` (licensed) | demo only |
| `derived` | computed at runtime by `cnmacro.derive`, never stored by hand | n/a |

## 3. Observation CSV contract

One row per (metric, period, pull). Files are append-only; a new pull appends rows
with a new `retrieved_at`, which is how forward vintages accumulate.

| Column | Required | Rule |
|---|---|---|
| `metric_id` | yes | must exist in the dictionary |
| `reference_period` | yes | `YYYY-MM` (M), `YYYYQn` (Q), `YYYY-MM-DD` (D) |
| `value` | yes | numeric, in the dictionary unit |
| `release_date` | if known | ISO date the market learned it |
| `release_date_basis` | yes | `official_calendar` · `source_field` · `unknown` |
| `retrieved_at` | yes | ISO datetime with timezone |
| `source` | yes | NBS · PBOC · MOF · GACC · FRED · Wind · manual |
| `source_code` | if any | FRED id, Wind code, or table name. Never guessed |
| `source_class` | yes | `public` or `private`. Wind is `private` |
| `consensus` | optional | blank if not reliably available |
| `quality_flag` | yes | `ok` · `revised` · `caliber_break` · `suspect` |
| `limitation` | if `release_date` blank | why availability cannot be verified |

**Availability rule.** An observation is available at its `release_date`, or, if that is
unknown, at `retrieved_at`. This is conservative: history pulled today without
verified release dates counts as known from today. That is correct for a forward
baseline and is disclosed rather than hidden.

**Consensus.** Optional. If absent, surprises are measured against prior, trend
and the 3-month average, and the memo says so.

## 4. Sources and modes

Two vantage points were measured on 2026-10-04: the researcher's PC (initial history) and a
GitHub-hosted runner (the scheduled refresh; `scripts/probe_sources.py` runs on every refresh).
From the runner, every endpoint below except DBnomics answered HTTP 200, including MOF, which
returns 502 from the PC's network.

| Source | Mode | Access status (2026-10-04) |
|---|---|---|
| NBS data portal (data.stats.gov.cn/dg/website/) | public | **Working.** NBS moved to a new portal in 2026; the old `easyquery.htm` returns 403 to every client. `cnmacro ingest-nbs` uses the new JSON API (`nbs-tree`, `nbs-indicators` to discover codes). The portal also republishes PBOC M1, MOF budget expenditure and customs exports, about 1 month behind the original release. `queryAgendas` exposes the official release calendar as JSON |
| NBS press releases / calendar (stats.gov.cn) | public | **Working for CPI/PPI** (first print): the refresh reads the release's 主要数据 table, because the data portal lags the 09:30 release (on 2026-10-14 it still ended at August three hours later) |
| PBOC statistics | public | Working: `scripts/fetch_pboc.py` reads the HTML tables (TSF stock/flow, RMB credit) into the inbox format |
| GACC customs | public | Chinese site: anti-bot challenge (HTTP 412). English site over plain HTTP (english.customs.gov.cn) works: preliminary releases (dated) and monthly bulletin tables, including trade by country |
| MOF | public | www.mof.gov.cn listing reachable, but release pages on gks.mof.gov.cn return 502 to this network (CDN block, browser too); budget expenditure comes via the NBS portal; government-fund revenue has no route yet |
| FRED | public | Working with date-windowed requests and Python's default User-Agent (FRED stalls on unrecognised UAs) |
| DBnomics (NBS mirror) | public | Reachable but unusable: rolling ~13-month window, about 6 months stale (checked 2026-10-04) |
| Wind | private | Wind terminal installed; **MCP not yet connected to Claude**. Deferred: needed only for Private Research Mode, not for Public V1 |

### Automatic refresh routes

`cnmacro refresh-public` fetches each public metric through one route: `nbs` (data portal,
including the PBOC, MOF and customs series NBS republishes), `pboc` (`scripts/fetch_pboc.py`),
`gacc_us` (`scripts/fetch_gacc_us.py`) or `fred`. For the six CPI/PPI metrics the `nbs` route also reads
the NBS press release (`ingest.nbs_release_rows`, into `nbs_release.csv`), only for periods not yet held;
the portal stays the route for history and revisions, and when it catches up an equal value is a no-op
and a different one is kept as a revised vintage. A layout the parser does not recognise fails loudly
(and the portal rows are still taken); it never yields a guessed number. A metric is due when the release calendar
says its next period has been released (repo calendar plus the live NBS agenda), or, for series
without a calendar entry, when its typical publication lag has passed. New rows are appended
only for new periods; a changed value for a held period is appended as a vintage with
`quality_flag: revised`, a blank `release_date` and a limitation note. Licensed series are
never fetched by the public refresh. If a source fails, the refresh records the failure and
continues with the others; `--strict` turns a source failure into a non-zero exit.

## 5. One-time input specification (if automated access stays blocked)

If NBS / GACC / Wind cannot be reached programmatically, the following one-time
export unblocks the baseline. Place files in `data/private/inbox/` (gitignored).

**Format:** one CSV per source (UTF-8), columns
`metric_id, reference_period, value, release_date, source, source_code`.
Use the `metric_id`s from `data/dictionary/metrics.yaml`. Leave `release_date`
blank if unknown. The ingester fills `retrieved_at`, `source_class` and `limitation`.

**Coverage:** monthly metrics from 2019-01 to the latest available; quarterly from
2019Q1. All 23 core metrics; the 6 diagnostics are optional.

**Public vs Wind:** export from Wind only for metrics the public demo cannot get
publicly (expected: CGB 10Y, possibly exports and fiscal). Mark those rows
`source=Wind`; they will be classed `private` automatically.
