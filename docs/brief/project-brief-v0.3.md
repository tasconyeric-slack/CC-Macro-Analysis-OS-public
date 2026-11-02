# CC Macro Analysis OS — Project Brief v0.3

> 2026-10-04. Supersedes v0.2. Incorporates the V1 Final Execution Brief (2026-10-03) and the
> empirical findings of the security gate and data-access checks.
> Specs: `skills/china-macro-research/SKILL.md` · `docs/specs/data-spec.md` · `docs/specs/output-thesis-eval-spec.md` · `docs/data-policy.md`.

## 1. What V1 is

A **research system with a polished static website as its showcase**. The website is the presentation layer; the research engine is the project.

- **Engine (private):** Claude Code + China Macro Research Skill + Wind MCP / local files + `cnmacro` Python library + versioned research artifacts.
- **Showcase (public demo):** a self-contained static site built only from tracked, redistributable artifacts. A visitor supplies nothing: no Wind account, no API key, no data upload, no local pipeline.
- **Not V1:** generic chatbot, public Ask, auth, user accounts, upload workflows, large dashboard, trading.

## 2. The research question

> **Is China forming a sustainable turning point in nominal growth?**

- **Target:** implied GDP deflator (nominal GDP levels vs real GDP YoY). Monthly price, demand, credit, property, external and market data are leading or confirming evidence.
- **Thesis statement:** the deflator turns non-negative and stays there for two consecutive quarters by the 2027Q1 GDP release, supported by broadening domestic demand rather than supply-side or imported price pressure alone.
- **Hypotheses:** H1 price turn · H2 domestic demand · H3 policy impulse · H4 external · **H0 supply-led bounce (competing)**.
- **The system does not assume the answer.** The baseline run determines the starting probability.

## 3. Product completeness vs thesis horizon

The thesis stays ACTIVE until its terminal window (2027Q1 GDP release, around mid-April 2027). **V1 does not wait for it.** V1 is complete after:

1. a valid preregistered baseline;
2. a working pipeline and website;
3. at least one genuine post-release update.

| Milestone | Official time (NBS calendar, verified 2026-10-04) | Role |
|---|---|---|
| Preregistered baseline committed | before **2026-10-14 09:30 BJT** | immutable starting point |
| September CPI/PPI | 2026-10-14 09:30 BJT | **first genuine update** (sufficient for V1) |
| Q3 GDP + September activity, 70-city prices | 2026-10-19 10:00 / 09:30 BJT | second update (desirable); first deflator print after baseline |

Source: <https://www.stats.gov.cn/sj/fbrc/bnxxfb/>. Re-verify before each release.

## 4. Metric budget

**23 core + 6 conditional diagnostics** (cap 24 + 6). Each declares its hypotheses and role. Full list: `data/dictionary/metrics.yaml`. Derived series are computed with lineage and are not metrics. The list is final for V1 unless the Wind spike shows a metric cannot be sourced at all.

## 5. Evidence tests ≠ thesis falsification

- **16 evidence tests** (H0–H4), each with indicator, rule, threshold, window, check release, direction, and threshold basis. A failed H1 test weakens H1; it does not falsify the thesis.
- **Terminal decision rules** decide CONFIRMED / FALSIFIED / ACTIVE / RETIRED, always combining price and demand evidence. Early falsification requires price momentum **and** demand to fail together.
- **Thresholds are natural** (0 for changes, 50 for PMIs), not fitted. Any replacement before preregistration must record its basis.

## 6. Thesis state, probability and audit trail

- `status` · `conviction` · `last_update_direction` are separate dimensions.
- Probability is an analyst judgment on a **5-point grid**. Every change shows previous, new, evidence, hypotheses and reasoning; the eval rejects silent changes.
- **Immutable preregistration:** `preregistered/<date>-baseline.yaml` is written once. Each release adds an append-only `updates/<date>-<release>.yaml`. Current state is folded, never hand-edited. The eval fails if git shows either was modified after its first commit.
- **Amendments:** decision logic is corrected only by `preregistered/<date>-amendment-<n>-<slug>.yaml`, which quotes the exact old and new value of each changed path, may change only `terminal_rules` and `horizon`, declares `informed_by_tested_data: false`, and must be committed after the baseline and before its `effective_before` release (E4). Amendment A-01 (commit `15421aa`, before the 2026-10-14 release) made FALSIFIED the exact complement of CONFIRMED; RETIRED now means only that a required terminal input is missing.
- **Two layers:** the automatic evidence state (observations, test outcomes, terminal check; `refreshes/*.json`) is updated by `cnmacro refresh-public`; the analyst judgment (probability, conviction, direction) changes only in an update file. An automatic job may change status only when a preregistered terminal rule fires, and never the probability.
- The website shows the baseline as-of time, latest update time and the commit SHA of each preregistered file.

## 7. Data model and sources

- `metric` (dictionary) · `observation` (append-only CSV with `release_date`, `retrieved_at`, `source_class`) · `derived` (runtime, with lineage).
- **No invented vintages or release dates.** Unknown release dates fall back to retrieval time and carry a `limitation` note. Forward vintage capture is the V1 vintage strategy.
- **Consensus is optional.** Without it, surprises are measured vs prior, trend and 3-month average.
- **Public-first:** core metrics come from NBS / PBOC / MOF / GACC / FRED where they publish them; Wind fills gaps privately. CGB 10Y is private until redistribution is clear.

## 8. Findings that shaped v0.3

| Finding (2026-10-03/04) | Consequence |
|---|---|
| Repo private; history clean (2 docs, no secrets) | Gate passed; `main` created; data boundary, pre-commit hook and CI check added |
| Branch protection unavailable on a private repo without a paid plan | "PR + green CI" is a documented convention, not a claimed control |
| Cloud sessions cannot reach NBS/PBOC/FRED (network policy) | Initial history was ingested on the researcher's PC |
| **GitHub-hosted runners reach every official source** (probe on 2026-10-04: NBS portal and agenda, stats.gov.cn, PBOC, GACC, MOF, FRED all HTTP 200; a full dry-run fetched NBS 208, PBOC 80, GACC 20, FRED 80 rows) | Scheduled public refresh runs in GitHub Actions; no PC or VPN in the loop |
| **Wind MCP is not connected to Claude** on the researcher's PC (terminal installed, no MCP, WindPy not importable) | Wind is **deferred** and does not block Public V1; nothing in the architecture depends on it |
| The frozen FALSIFIED rule was not the complement of CONFIRMED | Amendment A-01, before any tested release (§6) |
| FRED works only with date-windowed requests; DBnomics NBS mirror reachable | Fetchers request in windows; DBnomics is a fallback for NBS history |

## 9. Eval

Deterministic gate (E0–E5: data quality, citation integrity, derived lineage, as-of leakage, preregistration immutability, thesis discipline) runs before research generation, on every refresh and in CI. A failure fails CI and blocks the automatic commit; warnings do not. The site shows the latest eval status. An LLM method rubric, if added, is labelled secondary.

## 10. Repository structure

```text
docs/              brief, specs, data policy, wind capability note
skills/china-macro-research/SKILL.md
src/cnmacro/       store, derive, claims, evidence, thesis, checks, ingest, render
data/dictionary/   metrics.yaml (tracked)
data/demo/         public observations + SOURCES.md (tracked)
data/private/      licensed inputs (gitignored)
research/cases/cn-nominal/   case, claims, memo template, preregistered/ (baseline, amendments), updates/, refreshes/, eval/
site/              static website build
tests/             engine, case and boundary tests
```

## 11. Definition of Done (unchanged from the final brief)

Traceable baseline (observations → claims → thesis) · implemented Core/Diagnostic dictionary · immutable baseline and terminal rules · ≥ 1 genuine release update with thesis diff · citation, as-of and data-quality checks pass · private workflow consumes Wind or local files without exposing credentials · visitor needs nothing to understand the site · public build contains no restricted material · README in the order problem → method → system → evidence → live update → eval → architecture.

## 12. Status and open items

**Public V1 (current baseline release) is complete**: baseline preregistered (`bbd0b35`), amendment A-01, refresh pipeline and schedule, replay, CI gate, website. The first genuine release update follows September 2026 CPI and PPI (2026-10-14 09:30 Beijing), which completes the Definition of Done item "≥ 1 genuine release update".

Known data limitations (kept explicit; the E0 warnings are not suppressed):

- **CGB 10-year yield**: Wind-only; withheld from the public build until redistribution rights are clear.
- **Government-fund revenue (YTD)**: no public machine-readable route found; no observations.
- **Exports to the US (YTD)**: two months (2024-09, 2024-10) missing from the public GACC bulletin history.

Open items (owner):

1. Connect the repository to the static host once (see README, Deploy).
2. Wind MCP: deferred. Needed only for Private Research Mode; does not block Public V1.
