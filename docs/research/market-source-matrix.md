# Market data source matrix (T4, Step A)

Status: **Step A is partly done.** The public cross-check pages are verified from a GitHub runner. The Tushare rows are **not yet verified**: the first runner probe found no `TUSHARE_TOKEN` in the Actions environment (`token_present: false`), so no Tushare call was made. Nothing below under "Tushare" is an observed account permission or history depth until the probe is re-run with the secret set. Endpoint names, parameters and returned fields are from the Tushare Pro interface documentation as exposed by its catalogue (the "documented" columns); every "observed" cell stays `—` until the runner fills it.

Probe: `scripts/probe_market_sources.py` via `.github/workflows/market-probe.yml` on branch `codex/market-data`. Run [42657525872](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public/actions/runs/42657525872), 2026-11-09T16:42Z. The report goes to a temporary branch and is deleted after use; the token is read from the environment only and is never printed or written (the probe refuses to write a report containing it).

## Tushare candidates

Row caps and update times are from the interface documentation. "Points" is whether this account may call it; unknown until probed.

| Series wanted | Endpoint | ts_code / key params | Documented fields used | Row cap per call | Documented update time | Observed history depth | Account points |
|---|---|---|---|---:|---|---|---|
| CGB 1Y yield | `yc_cb` | `ts_code=1001.CB`, `curve_type=0` (maturity), `curve_term=1` | `trade_date`, `yield` | 2000 | daily 20:00 | — | — |
| CGB 10Y yield | `yc_cb` | same, `curve_term=10` | `trade_date`, `yield` | 2000 | daily 20:00 | — | — |
| 10Y − 1Y slope | derived | `mk_cn_gov_10y − mk_cn_gov_1y`, same trade date | — | — | after both | — | — |
| SHIBOR ON, 3M | `shibor` | date range | `date`, `on`, `3m` | 2000 | daily ~14:00 | — | — |
| DR007 | none identified | — | — | — | — | — | — |
| USD/CNH | `fx_daily` | `ts_code=USDCNH.FXCM` (confirm in `fx_obasic`) | `trade_date`, `bid_close`, `ask_close` (mid used) | 4000 | morning 08:30 (GMT dates) | — | — |
| USD/CNY | `fx_daily` if `fx_obasic` lists a `USDCNY` code | probed dynamically | as above | 4000 | as above | — | — |
| CSI 300 | `index_daily` | `ts_code=000300.SH` | `trade_date`, `close` | 10000 | daily 19:00 | — | — |
| Shenwan L1 | `sw_daily` (SW2021 default) | `801050.SI`, `801040.SI`, `801950.SI` (upstream); `801120.SI`, `801110.SI`, `801880.SI` (downstream) | `trade_date`, `close` | 4000 | trading days 18:30 | — | — |
| Copper, rebar, iron ore main | `fut_mapping` + `fut_daily` | `CU.SHF`, `RB.SHF`, `I.DCE` → `mapping_ts_code` per day | mapping: `trade_date`, `mapping_ts_code`; daily: `close` | 5000 / 2000 | trading days 18:30 / 17–18h | — | — |
| US Treasury 10Y | `us_tycr` | date range | `date`, `y10` | 2000 | daily | — | — |

Notes on what is and is not known:

- **DR007**: the catalogue has `shibor`, `shibor_quote`, `shibor_lpr`, `hibor`, `libor`, and `repo_daily` (exchange-traded repo such as 204007.SH, a different instrument). No endpoint for the interbank DR007 fixing was found. The probe calls `shibor_quote` and `repo_daily` only to document that; neither is ingested as DR007. If the runner confirms there is none, DR007 is dropped from scope rather than substituted.
- **Futures main contract**: `fut_mapping` returns the mapped monthly contract per day; the ingest then reads that contract's `close` from `fut_daily`. The series is **not roll-adjusted**, so a roll shows as a jump; the page says so. Whether `fut_daily` accepts the continuous code directly is also probed.
- **USD/CNY**: Tushare's `fx_daily` is the FXCM offshore feed (bid/ask, GMT dates). An onshore USD/CNY series is only ingested if `fx_obasic` lists one. The CFETS central parity is therefore compared with USD/CNH as a *proxy*, a reference rate against a close.
- **Rate limits**: low-point accounts can be limited per minute. The client waits 62 s and retries twice on a rate-limit reply; a still-failing series is skipped and reported.

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

## Still to do before this document is complete

1. Owner adds the Actions secret `TUSHARE_TOKEN` (repository secret, not environment).
2. Re-run the probe (push to `codex/market-data`); fill the "Observed history depth" and "Account points" columns from the report; record any endpoint the account may not call.
3. Record, per series, the first trade date returned and whether the row cap truncated it.
4. Delete the temporary report branch and `market-probe.yml` once recorded.
