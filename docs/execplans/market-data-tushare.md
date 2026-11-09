# ExecPlan — T4: Market data via Tushare, cross-checked against public official sources

Branch `codex/market-data` · Authority: `docs/PRODUCT_STRATEGY.md` v2.0 (§0, §13.1, §15.2, §20) · Owner decision of 2026-11-09: Tushare data may be shown on the public site; credential only as the GitHub Actions secret `TUSHARE_TOKEN`.

## 1. Phase / Gate

**V2 Product Build — Public News & Official Data** (§0), serving the Data topic pages of the portal. It is not a Proof Gate (§14) item and does not touch the thesis, the preregistration, amendments, refresh/update history or `mechanical_delta`. The only P0 (§0: `refresh.yml` keeps succeeding, verified commits reach main, analyst updates within 48 h) is protected: market data runs in its own workflow, writes only `tushare_*.csv` and cross-check records, and never writes a refresh record.

§20.7 note for the Owner: §0 does not yet list Tushare among the allowed new sources; the Owner decision of 2026-11-09 is the authorization. **Proposed §0 wording (for the Owner, not edited here):** add "Tushare Pro daily market series (rates, FX, equities, Shenwan L1, commodity futures) with ChinaBond and CFETS cross-checks, public display permitted; token in Actions secrets only".

## 2. Prioritization Rule (§15.2)

| # | Question | Answer |
|---|---|---|
| 1 | Does it materially improve understanding of *What Changed and Why*? | **Partly.** Daily financial conditions are context for a nominal-growth question (rates, the yuan, upstream vs downstream). They are not evidence-test inputs. |
| 2 | Does it produce a new live proof, user result or evaluation data point? | **Yes.** A daily, vintaged, cross-checked series is a new real run record every trading day. |
| 3 | Is AI actually necessary here? | **No.** Everything is deterministic: fetch, derive, compare. No model is involved. |
| 4 | Does it come from a failure already observed? | **No.** It is an Owner-scheduled product task. |
| 5 | Would skipping it for two weeks weaken the current deliverable? | **Partly.** The Data hub has no market page; the Owner set 11-14 / 11-20 dates. |

One "yes" and two "partly" — the Owner scheduled this task explicitly (T4), so it proceeds as an Owner-directed exception to the "fewer than 2 yes" stop rule. Infrastructure test: *without the ingest, the Markets page would show gaps or guessed numbers; the product behaviour blocked is "see today's CGB 10Y, SHIBOR, USD/CNH and the upstream/downstream moves with provenance".*

## 3. What is reused

| Need | Existing component |
|---|---|
| Observation store, vintages, point-in-time | `store.OBS_COLUMNS`, `ingest.row`, `ingest.append_rows`, `refresh.new_rows` (a changed value becomes a new `revised` vintage) |
| Verified commit path | `scripts/commit_public_refresh.py` (reused with a narrower allowlist: `scripts/commit_market_data.py`) |
| Runner probe pattern | PR #33: probe on the branch, report to a temporary branch, delete it afterwards |
| Data topic page, chart, range switch, CSV | `data_portal`, `charts.line_chart`, `data-portal.js`, `write_data_assets` |

New code: `tushare_client.py` (stdlib HTTP, token scrubbed from every message), `market_data.py` (fetch → rows), `market_crosscheck.py` (ChinaBond / CFETS), `site/markets.py` + `data-markets.html`, `market.yml`.

## 4. Behaviour contract

- Token missing, endpoint not permitted, or any fetch error: that series is skipped and reported; the run is green. No guessed or substituted value is ever written.
- Reference period is the trade date. Tushare gives no publication time, so `release_date` stays unknown and availability is the retrieval time (point-in-time safe, `limitation` recorded).
- Page numbers are arithmetic on stored rows: latest level; change vs the prior trading day; change vs one month earlier (last observation on or before the same calendar day); share of the trailing 365 days at or below the latest level.
- Cross-checks: ChinaBond 1Y/10Y (tolerance 1 bp) and CFETS USD/CNY central parity vs the stored USD/CNH close (0.5%, a reference rate against a close, so a signal rather than an identity). A gap is a warning in the run log, the summary and the page; both values stay; nothing is overwritten. A Tushare value that is not stored yet (`yc_cb` updates at 20:00 Beijing) is `pending`, not a failure.

## 5. Acceptance status

See the PR description for the live checklist. Not claimable from a local run: the matrix with real account permissions, three consecutive trading days of 8+ instruments refreshing on their own, and passing cross-checks all need `TUSHARE_TOKEN` in Actions.

## 6. Deferred (not done here, §20.3)

- Event-window returns and scenario mapping (a later Research task); paid APIs other than the Owner's Tushare account.
- Roll-adjusted continuous futures (the page labels the main-contract series as not roll-adjusted).
- DR007, if no Tushare endpoint covers it (see the matrix).
- Compacting the daily series JSON (points + vintages duplicate the CSV) if page weight becomes a problem.
- Choice of the upstream/downstream index sets (3 + 3 Shenwan L1 here; edit `market_series.yaml` only).
