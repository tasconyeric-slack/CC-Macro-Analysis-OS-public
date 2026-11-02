# Provider migration priorities (V1.2.1)

> **Status: AUDIT, research only (2026-10-05).** This ranks the 14 Wind-backed views by how much replacing Wind is
> worth and what it costs. Evidence: [`source-replacement-matrix.md`](source-replacement-matrix.md). Architecture:
> [`provider-independence-design.md`](provider-independence-design.md). Proposed first release:
> [`v1.2.1-implementation-plan.md`](v1.2.1-implementation-plan.md). Revised after the adversarial review, and again in
> the final correction pass (2026-10-06).
>
> **What the final correction pass changed.**
> - The tiers and scores are unchanged.
> - Semantic equivalence is now kept apart from activation readiness. Activation readiness has three parts:
>   - validation, against Wind's values;
>   - access, meaning the terms that let us fetch or import the data;
>   - point-in-time route history.
> - CSI 300 is now gated on the project's use status.
> - For DR007 and the 10Y, the preferred posture is now:
>   1. written permission;
>   2. otherwise an authorised structured provider;
>   3. otherwise keep Wind.
>
>   Grey manual import is no longer presented as a default.

## Scoring

Each criterion is scored from **0 to 5**, and a higher score is always better. For engineering effort, 5 means the
least effort. Rows are **ranked by total**.

| Criterion | 5 means | 0 means |
|---|---|---|
| **Information value** | The view feeds a CONFIRMATORY Phase 2 signal that R-assessments depend on (CONTEXT_ONLY scores lower; EXPERIMENTAL or none scores lowest) | — |
| **Replaceability** | EXACT non-Wind route with a value match (FE = 4, APPROXIMATE = 2, UNKNOWN = 1) | no candidate at all |
| **Reliability** | Documented, stable access; automated retrieval clearly permitted; enough history for the signal windows | no acceptable access route |
| **Cost reduction** | Wind codes and calls removed from routine refreshes, weighted by frequency | — |
| **Engineering effort** | A one-endpoint JSON/CSV fetch or a one-file parser | anti-bot, blocked, or unbuildable |

## Signal dependency (why information value differs)

```text
cn_dr007 ─────────────► A1 (CONFIRMATORY) ──┬─► R2 (CONFIRMATORY)
                                            └─► D1 (CONTEXT_ONLY) ─► R3, R4
cn_cgb10y_daily ──────► A2 (CONTEXT_ONLY); D1 bond leg
mkt_csi300 ───────────► D1 equity leg ─► R3 (CONTEXT_ONLY), R4 flag F2
cn_loans_hh_* (2) ────► B1 (CONFIRMATORY; H2 STRONG) ─┬─► R1, R2, R4
cn_loans_corp_* (2) ──► B2 (CONFIRMATORY) ────────────┘
cn_hf_prop_{bj,sh,sz,gz} ─► C1 per city ─► C2 (needs all 4) ─► R1, R2, R4
cn_*_consensus_wind ──► X1 (EXPERIMENTAL; feeds nothing)
cn_cgb10y (month-end) ─► core metric; in no evidence test or terminal rule
```

## Scores

| Rank | metric_id(s) | Info value | Replaceability | Reliability | Cost reduction | Effort | Total /25 | Tier |
|---|---|---|---|---|---|---|---|---|
| 1 | `cn_loans_hh_short_flow`, `cn_loans_hh_mlt_flow`, `cn_loans_corp_short_flow`, `cn_loans_corp_mlt_flow` | 5 | 5 | 4 | 4 | 3 | **21** | **A** |
| 2 | `cn_dr007` | 5 | 5 (ChinaMoney); TuShare 1 (UNKNOWN) | 1 | 3 | 5 | **19** | **A (conditional on CFETS written permission)** |
| 3 | `mkt_csi300` | 2 | 5 | 4 | 2 | 5 | **18** | **A** |
| 4 | `cn_cgb10y_daily` + `cn_cgb10y` (month-end view) | 3 | 5 | 2 | 3 | 4 | **17** | **A (conditional on CFETS written permission)** |
| 5 | `cn_hf_prop_bj`, `cn_hf_prop_gz` | 4* | 1 | 2 | 3 | 3 | **13** | **B** |
| 6 | `cn_hf_prop_sz` | 4* | 1 | 1 | 2 | 1 | **9** | **B (blocked)** |
| 7 | `cn_hf_prop_sh` | 4* | 1 | 0 | 2 | 0 | **7** | **C** |
| 8 | `cn_cpi_consensus_wind`, `cn_ppi_consensus_wind` | 1 | 0 | 0 | 2 | 0 | **3** | **C** |

\* The value of each property view is conditional on all four. C2, and the property legs of R1, R2 and R4, need all
four cities.

### Scoring notes

- **Loans (1).** Semantic equivalence is EXACT by construction: Wind's 当月值 *are* PBOC's reported YTD differences.
  **Activation validation is PENDING.** Two months are verified individually across all four series. Every other month
  available in the local Wind snapshot (2025-08..2026-08, 13 months in total) must also be compared individually for
  all four series before activation. Candidate implementation and collection may proceed first. The source is the
  most authoritative possible, and PBOC is already fetched by `scripts/fetch_pboc.py`. PBOC's own terms page was not
  read, and must be read before activation. Effort is MEDIUM: prose parsing, label drift, and 万亿 conversion.
- **DR007 (2).** Highest information value: A1 is the only liquidity signal and gates R2. ChinaMoney's file matches
  Wind exactly (47/47). Reliability scores 1 for three reasons:
  - CFETS's 法律声明 forbids automated retrieval ("电子抓取") and reproduction without written consent. The legal
    footing of manual private copying is unresolved.
  - The file is a chart's backing file, and its window may be quarter-to-date (UNKNOWN until checked after
    2026-10-09).
  - TuShare is UNKNOWN on equivalence, and this account has no permission.
- **CSI 300 (3).** EXACT (28/28) from the index owner. CSI permits downloading for **non-commercial** purposes only.
  Whether this project's actual use qualifies is unresolved, and a work-related or public portfolio site is not
  assumed to be non-commercial. Live collection and activation wait on that decision. The TuShare fallback is FE, with
  identity after ROUND_HALF_UP to 2 dp (21/21), and it raises the same use question. Low information value: D1 and R3
  are CONTEXT_ONLY, and the view touches only R4's F2 flag. Trivial effort.
- **10Y (4).** EXACT (48/48), with history back to 2015. Reliability scores 2 for the same CFETS reason as DR007. Note-974's
  "reasonable use" defers to the site's policy and does not authorise automation. The endpoint is also undocumented,
  and a WAF trips on page sizes ≥ 100. Moderate information value: A2 and D1 are CONTEXT_ONLY, and the month-end
  view is in no evidence test.
- **Beijing and Guangzhou property (5).** Plain HTTP, but equivalence is **UNKNOWN**: there is no first-party history
  to value-match, and Wind's use filter is unverified. Automated collection needs human sign-off on terms:
  Guangzhou forbids commercial use and mirroring, and Beijing's terms are unknown. A credit-free first test is to
  compare Wind's complete September 2026 daily values, summed, with each city's monthly or YTD totals by use.
  A fresh series gives its first valid C1 around **2026-11-20**, and that reading is biased by Golden Week.
- **Shenzhen property (6).** Answers 412, then 400, from this host. The only open-source lead reuses a third
  party's session cookies, which is never acceptable.
- **Shanghai property (7).** The only first-party route is behind a Ruishu-style JS challenge, and automating it
  would be bot-detection circumvention.
- **Consensus (8).** Wind's own product. Every alternative is a different panel, so it would be a new metric under a
  new contract. X1 feeds nothing.

## Tier A — replace first (4 replacements covering 8 views)

Every Tier A route is semantically EXACT. Each one is still activated only by its own reviewed, time-stamped
route-history record, once its activation gates pass
([design §7](provider-independence-design.md#7-semantic-equivalence-and-activation-gates)). Until then, Wind stays
the active route.

1. **PBOC loan flows ×4.** Source: 金融统计数据报告, using YTD differencing.
   - **No access gate**, apart from reading PBOC's terms page.
   - **Activation validation is PENDING** until every Wind month from 2025-08 through 2026-08 has been compared
     individually for all four series.
2. **DR007.** Source: ChinaMoney `prr-chrt.csv` (EXACT).
   - The parser can be built now, on synthetic fixtures.
   - Automated retrieval is prohibited without CFETS written permission. Live retrieval and activation are gated on
     that permission. The preferred posture, in order:
     1. CFETS written permission, or another clearly authorised retrieval;
     2. otherwise an authorised structured provider. None qualifies yet: TuShare's equivalence is UNKNOWN, this
        account has no permission, and TuShare's upstream licence is not established;
     3. otherwise keep Wind active.
   - Manual import remains a documented option. Its legal footing is **unresolved**, and it is not recommended.
3. **CSI 300.** Source: csindex.com.cn (EXACT). Possible second candidate: TuShare `index_daily`, with ROUND_HALF_UP
   to 2 dp.
   - Candidate implementation proceeds now.
   - **Live collection and activation are gated** on deciding whether this project's actual use is non-commercial.
4. **10Y daily (month-end view from the same rule).** Source: ChinaMoney SDDS (EXACT). It is gated like DR007, with
   one difference: there is no authorised structured alternative, because TuShare's `yc_cb` is the CCDC curve. In
   practice the choice is CFETS written permission, or keeping Wind.

### What Tier A restores without Wind (exact three-valued reading)

This assumes every Tier A route has passed its gates and is active, while all property stays missing:

| Signal | Restored? |
|---|---|
| A1, A2, B1, B2, D1, R3 | **Yes**, fully computable |
| R1 | POSITIVE can **never** be reached: it requires "property not negative", and property is missing. NEGATIVE is decided when B1 and B2 are both WEAKENING. MIXED is decided when no assignment of the missing property channel could produce two positives or two negatives, e.g. B1 MIXED and B2 MIXED. Otherwise the result is INSUFFICIENT_DATA. |
| R2 | NO_CLEAR_EASING whenever A1 is STABLE or TIGHTENING. Under EASING, only TRANSMISSION_VISIBLE can be decided, and only when B1 and B2 are both BROADENING. Otherwise the result is INSUFFICIENT_DATA. |
| R4 | Decidable only in narrow cases. A flag that needs property (real-demand weakness, R1) is undetermined unless the credit channels alone settle it. Expect INSUFFICIENT_DATA often. |
| C1, C2, X1 | **No** |

If DR007 and the 10Y stay gated, and Wind has no credits, A1, A2 and the bond leg of D1 are also lost. The loans and CSI 300 then restore B1,
B2 and the equity leg of D1 only. D1 is three-valued (`signals.market_regime` via `decide`). With the bond and liquidity
legs missing, it classifies only when the equity leg is FLAT (always MIXED); otherwise it is INSUFFICIENT_DATA. R2
becomes INSUFFICIENT_DATA.

## Tier B — replace later

5. **Beijing and Guangzhou property.** After human sign-off on terms, run candidate daily collectors now, so
   that uncollected days are not lost. Activate a route only after its definition is settled (the September-sum test)
   and a same-day value comparison passes, and only while its access policy permits collection. The comparison needs Wind credits or a Wind export.
6. **Shenzhen property.** Probe from a mainland network with no borrowed cookies, then proceed as for Beijing and
   Guangzhou.

## Tier C — keep Wind / unresolved

7. **Shanghai property.** Options:
   - a data agreement with 上海市房地产交易中心;
   - manual daily entry by the researcher;
   - a licensed vendor;
   - or Wind.

   **C2 needs all four cities.** A three-city C2 would be a new signal version under a prospective amendment.
8. **CPI/PPI consensus.** Keep Wind as the sole source. A substitute would be a new experimental metric under a new
   contract. The 2026-10-13/14 validation needs Wind credits.

## Access policy per route (proposed `access` values; fail closed)

These are access facts, kept separate from semantic equivalence
([design §12](provider-independence-design.md#12-how-access-and-redistribution-attach-to-the-route-and-the-observation-not-to-wind)).
`unknown` counts as not permitted. A conditional permission, such as "non-commercial only", stays `unknown` until a
human records that the condition is met.

| Route | automated_retrieval | manual_import | private_use | redistribution | Basis |
|---|---|---|---|---|---|
| CFETS / ChinaMoney (`chinamoney-dr`, `chinamoney-sdds`) | **prohibited** without written permission | unknown (legal footing unresolved) | unknown | prohibited | 法律声明: no reproduction and no "电子抓取" without consent; no private-use exception |
| PBOC (`pboc`) | permitted (INFERRED: government release; already fetched by the public refresh); stop on any JS challenge | permitted | permitted | unknown (metrics stay `private_only`) | terms page **not read**; read it before activation |
| CSI (`csindex`) | unknown until the use status is decided | unknown | unknown | prohibited | terms permit browsing and downloading for non-commercial purposes only |
| TuShare (`tushare`) | unknown (personal, non-commercial licence; tier limits) | prohibited (API only) | unknown | prohibited | licence: personal use. It does not cleanse upstream (CFETS/CSI) rights. |
| Guangzhou 阳光家缘 (`gz-zfcj`) | unknown (no commercial use, no mirroring) | unknown | unknown | prohibited | 网站声明 |
| Beijing 住建委 (`bj-zjw`) | unknown (terms not found) | unknown | unknown | prohibited | public disclosure page; no terms statement found |
| Shanghai fangdi / Shenzhen fdc | **prohibited** (anti-bot / blocked; circumvention is never acceptable) | unknown | unknown | prohibited | — |
| Wind (`wind`) | permitted (user's subscription) | prohibited (no Wind file parser) | permitted | prohibited | `docs/wind-capability-note.md` §10 |

**Use status (human question 3).** The CSI, TuShare and Guangzhou positions depend on whether this project's actual
use is non-commercial. A work context or a public portfolio site is **not** assumed to be non-commercial.

## Wind's residual role after V1.2.1

| Role | Views |
|---|---|
| `active` until a substitute's gates pass; then `inactive` from that record's `effective_at` (re-activatable only by another appended route-history record; same numbers; paid) | loans ×4 (after validation passes and PBOC's terms are read), `mkt_csi300` (after the use-status decision and validation), `cn_dr007`, `cn_cgb10y`, `cn_cgb10y_daily` (after CFETS written permission and validation) |
| `active`, with no acceptable substitute yet | `cn_hf_prop_sh`, `cn_hf_prop_sz`, `cn_hf_prop_bj`, `cn_hf_prop_gz` (BJ/GZ candidates run beside it once their terms are signed off), `cn_cpi_consensus_wind`, `cn_ppi_consensus_wind` |
| removed | none. Wind support stays, and no Wind contract is deleted. |

Every switch is point-in-time. Runs anchored before a substitute's `effective_at` keep using Wind, and replays of them
reproduce exactly.

If every Tier A route activates, routine Wind usage falls from 5 calls (13 codes) to **2 calls** (property and
consensus), and those run only when someone deliberately asks for them. Until credits return, the views whose active
route is still Wind report INSUFFICIENT_DATA honestly.
