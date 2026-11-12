# Market data source matrix (T4, Step A)

Status: **Step A is done for what the Owner's Tushare account can call, and it shows the account cannot supply most of the requested list.** Observed from a GitHub runner with `TUSHARE_TOKEN` set: run [42759975862](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public/actions/runs/42759975862), 2026-11-10T05:06Z (round 1, permissions and depth) and run [42760322801](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public/actions/runs/42760322801) (round 2, mostly blocked by rate limits, see below). The first run, 42657525872 (2026-11-09), had no token and called nothing.

Probe: `scripts/probe_market_sources.py` run from branch `codex/market-data` by a temporary workflow (since removed). The report goes to a temporary branch that is deleted after reading; the token is read from the environment only and never printed or written (the probe refuses to write a report containing it). Endpoint names, parameters and fields are from the Tushare interface documentation; every "Observed" column is from the runs above.

## Result in one table

| Series wanted | Endpoint | Account may call it? | Observed history in one call | Rows (cap) | Fields observed |
|---|---|---|---|---:|---|
| CGB 1Y / 10Y yield | `yc_cb` (`ts_code=1001.CB`, `curve_type=0`, `curve_term`) | **No** (permission error) | — | — | — |
| 10Y − 1Y slope | derived from `yc_cb` | **No** (inputs missing) | — | — | — |
| SHIBOR ON, 3M | `shibor` | **Yes** | 2018-09-27 → 2026-11-09 (from 2018-01-01, so truncated by the cap; start 2020-01-01 fits) | 2000 (2000) | `date, on, 1w, 2w, 1m, 3m, 6m, 9m, 1y` |
| DR007 | none identified; `shibor_quote` (permitted, bank-by-bank SHIBOR quotes, 107 rows in 10 days) is not DR007; `repo_daily` **not permitted** | — | — | — | — |
| USD/CNH, USD/CNY | `fx_obasic`, `fx_daily` | **No** | — | — | — |
| CSI 300 | `index_daily` (`000300.SH`) | **Yes** | 2018-01-02 → 2026-11-09, not truncated | 2146 (10000) | `ts_code, trade_date, close, open, high, low, pre_close, change, pct_chg, vol, amount` |
| Shenwan L1 (up/downstream) | `sw_daily`, `index_classify` | **No** | — | — | — |
| Copper, rebar, iron ore main | `fut_mapping`, `fut_daily` | **No** | — | — | — |
| US Treasury 1Y / 10Y | `us_tycr` | **Yes** | 2018-11-05 → 2026-11-09 (truncated by the cap; start 2020-01-01 fits) | 2000 (2000) | `date, y1, y10` (also `m1…y30`) |

Other endpoints probed (round 2): permitted — `shibor_lpr` (monthly 1Y/5Y LPR, 2 rows in 120 days), `hibor` (`on…12m`, 20 rows in 30 days), `us_trycr` (US real yields `y5…y30`, 20 rows), `fut_basic` (listing only, 3613 SHFE contracts). Not permitted — `repo_daily`, `index_global` (SPX), `sge_daily` (Au99.99).

Update times are the documented ones (shibor ~14:00; index_daily 19:00; yc_cb 20:00; fx_daily 08:30; sw_daily 18:30; futures 17–18:30 Beijing).

## What this means for the task

- **Instruments the account could supply:** SHIBOR ON/3M (and the other 7 tenors from the same call), CSI 300, US Treasury 1Y/10Y (+ a 10Y−1Y slope computed from them), and the extras above. Counting SHIBOR ON, 3M, UST 1Y, 10Y, CSI 300 gives **5** of the requested instruments; the 8-instrument acceptance bar cannot be met from the requested list with this account.
- **Not available with this account:** every China government-bond yield, all FX, all Shenwan industry indices, all commodity futures. The ChinaBond 10Y cross-check therefore has no Tushare series to compare against, and the CFETS check has none either.
- **Rate limit (important):** the account answers "frequency exceeded" for `shibor`, `shibor_quote`, `index_daily` and `us_tycr` on a second call about 20 minutes after the first. The reply states one call per period (the unit is unreadable in the stored report; for `index_daily`, `shibor_quote` and `us_tycr` it is per hour). Consequences built into the ingest: each interface is read in **one** call per run (history from 2020-01-01 fits every row cap in one call); only a *per-minute* limit is retried; an hourly limit skips the series and reports it. `index_daily` can therefore serve one index code per hour, not a basket.
- **DR007:** no Tushare endpoint exists for the interbank fixing among the interfaces probed. Dropped from scope rather than substituted.
- **Futures main contract / USD-CNY:** moot until the account is permitted for `fut_mapping`/`fut_daily` and `fx_daily`.

### Decision (Owner, 2026-11-10): smaller Tushare-only set

The Owner chose to stay within what the account can call. **Eleven series are ingested** (acceptance bar of 8 is met on count):

| Interface | Series (metric ids) |
|---|---|
| `shibor` | `mk_shibor_on`, `mk_shibor_1w`, `mk_shibor_3m`, `mk_shibor_1y` |
| `us_tycr` | `mk_ust1y`, `mk_ust10y`, `mk_ust_slope_10y_1y` (derived, same date) |
| `us_trycr` | `mk_ust_real10y` |
| `hibor` | `mk_hibor_on`, `mk_hibor_3m` |
| `index_daily` | `mk_csi300` |

That is five interface calls per run, one per interface, each inside the hourly limit. History starts 2020-01-01 and fits every row cap in one call.

The thirteen series that need a blocked interface (`yc_cb`, `fx_daily`, `sw_daily`, `fut_mapping`, `fut_daily`) are **parked** in `data/dictionary/market_series.yaml` with their full metric definitions. They are not fetched, not in `metrics.yaml` and not on the page. Their fetchers are still tested, so a points upgrade is a spec edit, not new code. The ChinaBond and CFETS cross-checks are parked with them (their parsers and tolerances stay tested on captured real pages).

**Cross-check now in force:** the monthly mean of the stored Tushare daily US Treasury 10Y values against the FRED GS10 monthly value already in the store, for the latest month present in both with at least 15 trading days; tolerance 0.05 percentage points (FRED publishes two decimals). It needs no web page and runs on every market run; a gap is a warning in the log, the summary and on the page, never an overwrite.

## Public cross-checks (observed from the runner)

Probed 2026-11-09T16:42Z from `ubuntu-latest` in the run above. Fixtures of the two accepted responses are in `tests/fixtures/market/`.

| Check | URL (host) | Result from the runner | Shape used |
|---|---|---|---|
| CFETS USD/CNY central parity, history | `https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew?startDate=…&endDate=…&currency=USD/CNY` | HTTP 200, JSON, 1 KB, UTF-8 | `records[].{date, values[0]}`; 10 dated values in the 14-day window (latest 2026-11-09 = 6.7188) |
| CFETS central parity, latest | `…/data/fx/ccpr.json` | HTTP 200, JSON, 11 KB | `records[]` with `vrtEName: "USD/CNY"`, `price`; not used (history gives the date explicitly) |
| ChinaBond treasury curve table | `https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/more?locale=cn_ZH` | HTTP 200, HTML, 17 KB, UTF-8 | table `#gjqxData`: header date `2026-11-09(%)`, terms 3月…30年, first row "中债国债收益率曲线" (1Y 1.1667, 10Y 1.5874) |
| ChinaBond yield page | `…/cbweb-mn/yield_main` | **timed out at 40 s** | not used |
| ChinaBond "latest curve" JSON | `…/cbweb-czb-web/czb/queryGjqxInfo` | HTTP 200 but an empty table shell | not used |

Assumption to confirm with the first token run: that the ChinaBond treasury row is the **maturity** curve and equals Tushare `yc_cb` `curve_type=0`. The page's own note describes the chart as maturity yields; the cross-check will show a gap if that is wrong, and it is reported, not silently corrected.

Tolerances (design choices, to be reviewed by the Owner):

| Cross-check | Compared | Tolerance | Why |
|---|---|---|---|
| ChinaBond 10Y and 1Y vs `yc_cb` | same trade date, percentage points | 0.01 (1 bp) | the same curve at 4 decimals; 1 bp absorbs rounding only |
| CFETS USD/CNY parity vs `USDCNH` mid | same date, relative | 0.5% | the parity is a 09:15 reference rate and the stored value is a close, so a small spot-to-fixing distance is normal; a larger one is a signal |

## Still to do

1. The temporary probe workflow is removed; `scripts/probe_market_sources.py` stays as the record of how the matrix was produced (run it manually only after the account's points change, and mind the hourly limit).
2. If the Owner later raises the account's points, re-run the probe, then move the parked series into `series` and `metrics.yaml`.
