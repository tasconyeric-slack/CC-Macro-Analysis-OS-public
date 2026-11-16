# ExecPlan — W5: research view comparison (signed view vs. evidence since) and the EXTERNAL_VIEW boundary

Issues: #11 (FinLens / institutional views), #69 (parallel delivery sprint, W5) · Authority: `docs/PRODUCT_STRATEGY.md` §0, §8.4, §15.2, §20

## 1. Phase / Gate

**Research-First MVP (§0)** — the core user question "what changed, why, does it change our thesis". This slice adds the missing deterministic link between the evidence refreshes and the latest *signed* view: which hypotheses the evidence has moved on since the analyst last signed, and whether the signed view has kept up. It feeds #52's review step (W1) and the Research hub (W4/#58) as a read-only input.

#11's institutional radar stays deferred under §0: no permitted source is reachable (see §4). Issue #69 asks W5 to pursue it honestly and not to fabricate; the Owner noted in the sprint brief that institutional views may be shelved for lack of a source. This plan therefore ships only the validated, append-only *import boundary* for institutional views, with no adapter, page, empty chart or sample data.

## 2. Prioritization Rule (§15.2)

| # | Question | Answer |
|---|---|---|
| 1 | Does it materially improve understanding of What Changed and Why? | **Yes.** It answers "does this change our thesis?" per hypothesis, with the flipped tests and their refs. |
| 2 | New live proof, user result or evaluation data point? | **Yes.** On real committed records: 4 tests flipped in 35 days since the 2026-10-04 signed view (H1 now 6/6 supporting; H2 two flips that offset), and the signed view has not been updated. |
| 3 | Is AI necessary? | **No** — deterministic code is the right tool; no model is used. |
| 4 | From an observed failure? | **Yes.** Ten refresh records since signing each carry a one-refresh `suggested_direction`; nothing accumulates them against the signed view, so drift since signing is invisible. |
| 5 | Would skipping it weaken the deliverable? | **Yes.** Without it, the Weekly/Monthly and review flow cannot state whether the signed view is stale. |

Five "yes" → proceed.

## 3. What is built

- `src/cnmacro/views/compare.py` — `build_comparison(case_dir, …)`: latest signed document (baseline or `updates/*.yaml`) vs. the latest refresh record; per hypothesis: tallies at signing and now, flipped tests (with observed values, periods, refs), mechanical drift using `refresh.suggested_direction` (H0 support counts against the thesis); timeline of drift per refresh; bilingual text from `frozen_zh.yaml`. If the signed document carries no test results, the evidence at signing is the latest refresh **at or before** signing, never after. `render_markdown(c, lang)`.
- `src/cnmacro/views/external.py` — `EXTERNAL_VIEW` record validation and loading from `data/external/views/*.jsonl`: https source link, named institution, short quote (≤280 chars, no full text), point-in-time cutoff, `redistribution: private` excluded from public output, duplicate ids rejected, forecast median only at n ≥ 5 distinct institutions. Views sit beside the signed view and never touch tests, claims or probability.
- `data/external/access.yaml` — dated ledger of sources checked and why none is connected.
- `python -m cnmacro.views compare [--to REFRESH] [--json OUT] [--md OUT] [--lang zh|en]` — its own entry point, so the shared `cli.py` is untouched.

Not touched (Release Integrator owns them): `site/build.py`, templates, i18n, navigation, homepage, workflows.

## 4. Institutional sources checked (2026-11-11)

| Source | Result |
|---|---|
| FinLens research API (`macro.finlens.cn/research/v1`) | Not connected: no Owner token, redistribution permission unconfirmed, and the cloud network refuses the host (proxy 403), so `SKILL.md` / `contract.json` could not be read. No adapter is written against an unverified contract. |
| Tushare `research_report` | Error 40203, no permission on the current account. |
| Broker WeChat (Sogou / wechat2rss / RSSHub) | No reliable daily source (2026-11-09 test, `docs/research/wechat-collection-test.md`). |

## 5. Validation

`tests/test_view_compare.py`: real-case flips equal the outcome differences between the two committed records; same score as `suggested_direction`; earlier `--to` never reads later records; an update without results compares from the refresh at or before it; external rows fail closed (bad link, long quote, incomplete forecast, private, future-dated, duplicate); median withheld below n = 5; external views do not change any tally or score; CLI JSON/Markdown and exit code on bad rows.

## 6. Deferred

- Site wiring (Research hub / updates page card and `data/views/*.json` export) — Release Integrator, after W1/W4 land.
- FinLens adapter — after the Owner claims a token, confirms redistribution, and the contract can be read from an allowed network.
- Using the comparison as an input to W1's review draft and W6's Copilot context.
