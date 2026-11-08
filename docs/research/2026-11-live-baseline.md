# November live research baseline

Checked 2026-11-08 UTC. This records V2 Stage 0 / Issue #2 operational evidence; it is not an analyst update or a claim that G-A, G-B or G-C passed.

## Refresh and production

- [Actual all-route refresh 42506441793](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public/actions/runs/42506441793) succeeded on `main` at 17:46 UTC. It added one NBS Q3 nominal-GDP revision, no test flips and no analyst-judgment change: [immutable refresh record](../../research/cases/cn-nominal/refreshes/2026-11-08T1744Z.json).
- Its **real data commit**, [`684f267e208842c043ba5c29f88a3c8869c67c64`](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public/commit/684f267e208842c043ba5c29f88a3c8869c67c64), was authored by `github-actions[bot]`, with GitHub `verification.verified=true`, `reason=valid`. This is the post-PR-#15 refresh path, not a normal PR merge used as signing proof.
- Vercel production deployment [`dpl_2pj2Y2czrxv5cNpJWkzkVLy3xzPZ`](https://vercel.com/tasconyeric-slack/ccmacrors/2pj2Y2czrxv5cNpJWkzkVLy3xzPZ) reached **READY** on that exact SHA, with alias **https://ccmacro.byliyz.com/**. The public `/en/` page returned HTTP 200 and displayed build commit `684f267`. Require Verified Commits was not changed.
- The last scheduled run, [42501368336](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public/actions/runs/42501368336), was green. The later push-triggered [42502446896](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public/actions/runs/42502446896) was a no-change success. A no-change refresh correctly creates no data commit.
- Latest runner probe: NBS indicator API, agenda and press index; PBOC statistics; GACC; FRED returned HTTP 200. MOF budget index returned HTTP 502 (the preceding run returned 200). All-route ingestion still succeeded for NBS, PBOC, GACC and FRED. The optional CPI/PPI fast press-index parser reported no recognized link; the current first index page contains November 4–October 19 items and no CPI/PPI item, so this off-release all-route probe is not evidence of a parser defect. The NBS indicator route succeeded. No missing scheduled observation was due (`freshness=CURRENT`). The next CPI/PPI first print still requires a real November 9 refresh.

## Releases and analyst status

| Release | Official release (Beijing) | Actual refresh evidence |
|---|---|---|
| September CPI/PPI | 2026-10-14 09:30 | [6 new observations](../../research/cases/cn-nominal/refreshes/2026-10-14T0701Z.json) |
| Q3 GDP / September activity | 2026-10-19 10:00 | [5 new observations](../../research/cases/cn-nominal/refreshes/2026-10-19T0450Z.json) |
| October PMI | 2026-10-31 09:30 | [November 1 refresh](../../research/cases/cn-nominal/refreshes/2026-11-01T0923Z.json) |

There is **no analyst update since the October 4 baseline**: `research/cases/cn-nominal/updates/` is absent. Probability remains the analyst's baseline 0.30, conviction LOW, status ACTIVE. Automatic observations and test results are factual evidence updates, not reviewed research decisions. No missed update, blind take or model run is backfilled here.

## Next release and outstanding acceptance

The tracked [official calendar](../../data/dictionary/release_calendar.yaml) was re-verified against the [NBS November agenda response](https://data.stats.gov.cn/dg/website/publicrelease/web/external/queryAgendas?startDate=2026/11/01%2000:00:00&endDate=2026/11/30%2023:59:59) from [runner probe 42506786975](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public/actions/runs/42506786975) at `2026-11-08T17:48:33+00:00`: HTTP 200, 11 agenda rows, response SHA256 `ba9e896b9ac978f7b898087ffe00b57ee6de8d6b2662daf37fd93d1973628a91` (raw response in the run's `official-source-probe` artifact). All seven tracked November entries match. Only those entries' `verified_on` fields were updated.

Next: October CPI/PPI on **November 9 at 09:30 Beijing**, October activity on November 16 at 10:00, October industrial profits on November 27 at 09:30, and November PMI on November 30 at 09:30. Site/pipeline merges are frozen from **November 8 23:30 UTC to November 9 07:30 UTC** around CPI/PPI. Issue #2 remains open until the actual November 9 CPI/PPI refresh exists; future data cannot be certified in advance.

| Gate | Status and reason |
|---|---|
| G-A | Not passed: the three replay cases are unlabeled; committed sample records explicitly use hand-written fixtures, not genuine model runs; no live Shadow Run Record exists. |
| G-B | Not passed: no post-baseline analyst update, blind-take/review/published chain or scored track record exists. |
| G-C | Not passed: no analyst-labeled dev/test gold set, contamination probe or measured model evaluation exists. |

The Owner's current V2 authorization permits public-source product work alongside this unresolved research cadence; it does not waive analyst ownership or turn fixtures into live proof.
