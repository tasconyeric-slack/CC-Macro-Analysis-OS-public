# CC Macro Analysis OS

A China-centred macro research system that states a falsifiable thesis in advance, tracks it release by release, and publishes the result as a static website in which every number traces back to an observation.

**Live site (production):** <https://ccmacro.byliyz.com/> (English and 中文). What is built, what is local-only and what is not built yet: [Status](#status).

## 1. The problem

Macro commentary on China is easy to produce and hard to audit. Views drift without being stated, numbers are copied by hand, rules for being wrong are written after the data arrive, and "the turn is here" is claimed on a single print. This project asks one question and holds itself to a public audit trail while answering it:

> **Is China forming a sustainable turning point in nominal growth?**
> 中国名义增长是否正在形成可持续拐点？

## 2. The method

- **Target.** The implied GDP deflator (nominal GDP growth relative to real GDP growth). Monthly price, demand, credit, property, external and market series are leading or confirming evidence.
- **Competing hypotheses.** H1 price turn, H2 domestic demand, H3 policy impulse, H4 external demand, and **H0 supply-led bounce**, the competing explanation that a price rise is imported or supply-driven and will fade.
- **"Sustainable" is defined before the data.** The deflator must be non-negative in 2026Q4 and 2027Q1, *and* at least three of six domestic-demand tests must pass at the 2027Q1 release. Price evidence alone cannot confirm the thesis.
- **Evidence tests are not verdicts.** Each hypothesis has tests with a rule, threshold, window and threshold basis. Only separate terminal decision rules can move the thesis to CONFIRMED or FALSIFIED, and they always combine price and demand.
- **Preregistration.** The baseline judgment (statement, tests, rules, probability, conviction) is frozen in a file that is never edited ([baseline](research/cases/cn-nominal/preregistered/2026-10-04-baseline.yaml), commit `bbd0b35`). Each release adds an append-only update that must show the previous and new probability, the evidence, and the reasoning.
- **Amendments are append-only too.** Decision logic can only be corrected by a separate amendment file that quotes the exact old and new rule, may touch only the terminal rules and the horizon, declares it was not informed by tested data, and must be committed before the next tested release (E4 verifies the timing). [Amendment A-01](research/cases/cn-nominal/preregistered/2026-10-04-amendment-01-terminal-rules.yaml) made the FALSIFIED rule the exact complement of CONFIRMED, so RETIRED now means only "the data cannot decide".

Full detail: [`docs/brief/project-brief-v0.3.md`](docs/brief/project-brief-v0.3.md), [`skills/china-macro-research/SKILL.md`](skills/china-macro-research/SKILL.md).

## 3. The system

```
official sources ──► observations (append-only CSV, release_date + retrieved_at)
                          │
metric dictionary ────────┤
                          ▼
                 derived series (yoy, single-month, moving average, deflator; with lineage)
                          │
          ┌───────────────┼──────────────────┐
          ▼               ▼                  ▼
   evidence tests    claims ledger      eval gate (E0–E5)
          │          (only place numbers     │
          ▼           enter prose)           │
   terminal rules ─► thesis state ◄──────────┘
                          │
                          ▼
                 static website (built from artifacts only)
```

- `src/cnmacro/` — data store with as-of views, derivations, claims, evidence tests, thesis fold, eval checks, CLI.
- `research/cases/cn-nominal/` — case definition, bilingual claims ledger, bilingual Deep Dive templates, preregistered baseline and updates, and the two presentation layers described in section 4.
- `site/` — static site generator (Jinja2, server-rendered SVG charts, light and dark themes), UI strings in `site/i18n/`.
- `skills/china-macro-research/` — the research skill Claude Code follows: analysis chain, China data traps, baseline and release-update workflows.

## 4. The evidence, in two languages

The website is built twice from one research state: `/en/` and `/zh/`, with a `中文 | EN` switch in the header that keeps the equivalent page and the `#fragment`. `/` is a small static selector (the choice stored by the switch, else the browser language, else English); the V1.0 flat URLs (`/evidence.html`, ...) forward to the right language and keep their fragment. There is no backend and no locale routing on the host.

Each language has six pages. The homepage leads with the **current macro view** (the question, the view in two sentences, the analyst probability with an explicit "discretionary judgment, not a model probability" label, confidence, status, evidence date and last refresh), then a qualitative state for each hypothesis, analyst-curated key evidence for and against, the policy picture, and only then the preregistration, audit trail, eval and data-source status. The other pages are the Deep Dive, Thesis and Evidence (tests, **Policy Context**, terminal rules in plain language), Release Updates, an Evidence Explorer of charts, and Method and Eval.

**Language never forks the research.** Observations, derived values, claim ids, bindings, refs, evidence outcomes, thresholds, probability and thesis state are computed once; a locale only chooses words:

| What | Where | Rule |
|---|---|---|
| UI strings | `site/i18n/en.yaml`, `zh.yaml` | identical keys and `{placeholders}`; a missing key fails the build |
| Claims | `claims.jsonl`: one record with `text_en` and `text_zh` | same id, bindings, refs, supports, stance; same placeholders and the same periods (eval E1) |
| Deep Dive | `memo.en.md.j2`, `memo.zh.md.j2` | written for each reader, citing the same claims; no typed numbers (E1) |
| Chinese for the frozen English artifacts | `frozen_zh.yaml` | translations of the case definition, tests, baseline rationale and amendment; the preregistered files are never edited |
| Current explanatory layer | `presentation.yaml` | the current view, hypothesis states, **key evidence chosen by the analyst** (never by file order), scenario matrix, limitations |
| Policy Context | `policy_events.yaml` | official events with stage, channel and next confirmation; context for H3, never an evidence test |
| Metric names and roles | `metrics.yaml` `name_zh`, `role_zh` | every metric needs both |

Presentation is separate from judgment on purpose. The preregistered baseline, amendments and updates are append-only; wording that improves on them lives in the presentation layer, and a baseline-era claim keeps its English text exactly as the baseline fingerprinted it. Better wording goes in `presentation.yaml`, or in a new claim id with a later `as_of` (`tests/test_claims_i18n.py` holds the line against the baseline's fingerprinted ledger). `presentation.yaml` names the judgment it was written for (`applies_to`); after an analyst update it must be re-confirmed, and until then the homepage says it is out of date.

By default the site shows sources in plain words ("National Bureau of Statistics · September 2026 Manufacturing PMI · released 30 Sep 2026"). `obs:` / `drv:` refs, source codes, derivation inputs and the raw terminal-rule JSON sit in collapsed **Technical lineage** sections.

Website numbers are never typed by hand. Every figure in prose is a placeholder in a claim bound to an `obs:` or `drv:` reference, filled from the data as of the claim's date and re-verified on every build. Every chart shows metric, period, unit, source and as-of time.

## 5. Live updates

Two layers are kept apart, on the site and in the files:

| Layer | Who changes it | Where it lives |
|---|---|---|
| **Automatic evidence state**: new observations, evidence test outcomes, terminal-rule check | `cnmacro refresh-public`, on a schedule | `data/demo/observations/`, `research/cases/cn-nominal/refreshes/*.json` |
| **Analyst judgment**: probability, conviction, direction, reasoning | the analyst, after reading the refresh | `research/cases/cn-nominal/updates/*.yaml` |

The automatic job never sets a probability. It may change the thesis **status** only when a preregistered terminal rule fires, and then it writes an update file that names the rule. It records a mechanical `suggested_direction` (which way the flipped tests point) for the analyst to accept or reject.

**`cnmacro refresh-public`** (idempotent; a rerun with nothing new changes nothing):

1. finds the metrics that are due from the release calendar (`data/dictionary/release_calendar.yaml` plus the live NBS agenda; publication lags for series without a calendar);
2. fetches them from the official public sources (NBS data portal, PBOC tables, GACC bulletin, FRED);
3. appends only new periods, or revised values as flagged vintages, keeping `release_date`, `retrieved_at` and provenance;
4. recomputes derived series and re-runs every evidence test of the case in force (baseline plus amendments) against the previous evidence state;
5. writes a refresh record: new observations, flipped tests, marginal changes, terminal check, suggested direction;
6. runs the eval gate (E0–E5) and rebuilds the site. Any eval failure exits non-zero and nothing is committed.

**Schedule.** [`.github/workflows/refresh.yml`](.github/workflows/refresh.yml) runs it at 10:20 and 18:20 Beijing time every day (and on demand), then commits the new public artifacts to `main` with an auditable message. The static host redeploys on that commit. Reachability of every source from GitHub-hosted runners is measured on each run, not assumed (all seven official endpoints answered on 2026-10-04).

**After a release**, the analyst reads the refresh record and appends the judgment:

```bash
python -m cnmacro update --as-of <time> --release "September 2026 CPI and PPI"
# write new claims and the "does this change the thesis" paragraph, then:
python -m cnmacro fill-claims --public
python -m cnmacro check --public
```

**Replay.** `python -m cnmacro replay --release-at 2026-08-09` replays an already-published release (July 2026 CPI and PPI) through the same path in a sandbox: old state, new observations, recompute, flipped tests, refresh record, eval, site. Every page it builds carries a REPLAY banner; it never touches the live case or its history.

## 6. Eval

A deterministic gate runs before research generation, on every refresh and in CI, and the site shows its status. Any failure fails CI and blocks an automatic commit; warnings are shown but do not block.

| Check | What it verifies |
|---|---|
| E0 Data quality | schema, duplicates, missing values, provenance, period format, gaps |
| E1 Citation integrity | every claim value matches the data as of the claim date; the memo contains no bare numbers |
| E2 Derived lineage | every derived value recomputes from existing observations |
| E3 As-of leakage | nothing cited was unavailable at the artifact's as-of time |
| E4 Preregistration | baseline, amendments, updates and refresh records were never modified after their first commit; amendments landed before the release they precede |
| E5 Thesis discipline | probability on the 5-point grid, every change explained, status moved only by terminal rules |

An LLM rubric may be added as a secondary signal. It never replaces these checks.

## 7. Data boundary

There are two modes. **Private Research Mode** consumes Wind and licensed research, kept in gitignored folders, and is not required for the public V1. Its Wind layer (V1.2 Phase 1) runs only on the researcher's machine: `python -m cnmacro refresh-private --provider wind` (Wind spends paid credits, so it runs only when named) verifies the officially installed Wind skill against a pinned runtime (`data/dictionary/wind_runtime.yaml`; the skill is never copied into this repository), fetches a pinned P0 set in five bounded calls, and publishes one immutable private snapshot to `data/private/observations/`, which the same research engine then reads alongside the public data. Its research layer (V1.2 Phase 2) is a separate local command: `python -m cnmacro diagnose-private` takes one verified snapshot and computes the deterministic diagnostics frozen in [`data/dictionary/private_signals.yaml`](data/dictionary/private_signals.yaml) (liquidity, credit, four-city property, market confirmation, and the domestic-demand, policy-transmission and H0 competing-explanation assessments), writing a private report to gitignored `data/private/research/`. The diagnostics never change a preregistered test, terminal rule or probability ([contract](docs/specs/v1.2-phase2-research-contract.md), [binding](docs/specs/v1.2-phase2-binding.md)). V1.2.1 then made that private layer provider-neutral: point-in-time source routes with an append-only route-history audit, multi-provider anchors and `refresh-private --provider` ([design](docs/provider/provider-independence-design.md#19-implementation-status-v121-core)). Wind is still the only provider adapter, no alternative route is active, and the public data path is unchanged. Neither command runs in CI. The public Method page labels Wind as private / local only (NBS, PBOC, GACC and FRED active), because nothing Wind-derived is public. **Public Demo Mode** uses only redistributable public data (NBS, PBOC, GACC, FRED, and MOF figures as republished by NBS) and is what this repository and the website contain. Licensed series are withheld from the public build and labelled as such. A pre-commit hook and a CI job block secrets and licensed file types. See [`docs/data-policy.md`](docs/data-policy.md) for what is and is not enforced.

## Quickstart

```bash
pip install -e ".[dev]"
git config core.hooksPath .githooks         # enable the secrets / data-boundary hook
pytest
python -m cnmacro check --public            # eval gate on the public data
python -m cnmacro refresh-private --provider wind --plan   # LOCAL ONLY: verify the Wind runtime, show the call plan; no Wind call
python -m cnmacro diagnose-private          # LOCAL ONLY: private diagnostics + report for the latest verified Wind snapshot
python site/build.py                        # writes site/dist/: index.html (selector), en/, zh/, legacy redirects
python site/build.py --preview              # synthetic data, watermarked, site/dist-preview/
python -m cnmacro refresh-public --dry-run  # what is due and what the sources serve now
python -m cnmacro replay                    # sandbox replay of a past release, site/replay/
python -m cnmacro copilot preflight --release "September 2026 CPI and PPI"   # release-day readiness, no model call
```

**Deploy.** The single public production entry is **<https://ccmacro.byliyz.com/>**, backed by the Vercel project [`ccmacrors`](https://vercel.com/tasconyeric-slack/ccmacrors) (production branch `main`). The canonical, `hreflang`, Open Graph and social-image absolute URLs are all generated from [`site/site.yaml`](site/site.yaml), not from the deployment's hostname. The site is static: no backend, runtime secret or Vercel Function is required. Scheduled public refresh commits to `main` trigger the Git-connected deployment.

- **Vercel (production):** [`vercel.json`](vercel.json) executes [`scripts/vercel_build.sh`](scripts/vercel_build.sh) and publishes `site/dist/`. The build uses Vercel's platform Python 3.14 and an isolated disposable virtual environment (PEP 668-safe). On a shallow clone, audit SHAs come from the validated audit manifest in `research/cases/cn-nominal/eval/latest.json`, not a guessed clone-tip commit. The production branch and public-access/firewall configuration are managed in the Vercel dashboard.
- **Netlify (legacy / optional):** [`netlify.toml`](netlify.toml) is retained for portability; if an existing Netlify deployment still builds, it is **not** the canonical site or release-acceptance target. Netlify availability or quota is not assumed. Do not remove its configuration merely to change the canonical domain.
- **Release acceptance:** Evaluate the production content, page URLs, metadata, bilingual switching, evidence freshness and audit-trail display on **<https://ccmacro.byliyz.com/>**, following [`docs/runbooks/production-site-acceptance.md`](docs/runbooks/production-site-acceptance.md). A successful preview or a green Vercel build alone is not sufficient.

## Status

State of the build on `main`, as of 2026-10-07. The research question and the preregistered judgment are in sections 1 and 2; this section only says what has been built.

| Layer | State |
|---|---|
| **V1.0: public deterministic research system** | Built and running. The thesis, tests and terminal rules were preregistered on 2026-10-04 at 30% probability with low conviction, before any tested release. Official-source pipeline with an as-of / vintage store, evidence tests, the E0 to E5 eval gate, a scheduled public refresh (twice daily) and the static site. |
| **V1.1: bilingual, insight-first presentation** | Built. `/en/` and `/zh/` are built from one research state; the homepage leads with the current macro view, then the preregistration, audit trail, eval and data-source status. Includes the Policy Context layer. |
| **V1.2: private Wind data and diagnostics** | Built, **local-only**. Phase 1 (`refresh-private --provider wind`) and Phase 2 (`diagnose-private`) write only to gitignored paths. Neither runs in CI, the public build never reads them, and no Wind-derived value is published. The diagnostics never change a preregistered test, terminal rule or probability. |
| **V1.2.1: provider-neutral core** | Merged (PR #9): point-in-time source routes, a route-history audit and multi-provider anchors for the private layer. Wind is still the only provider adapter and no alternative route is active, so it adds no new data source, public or private. |
| **Public site** | <https://ccmacro.byliyz.com/>, published through Vercel project `ccmacrors` from `main`. Official and open sources only (NBS, PBOC, GACC, FRED, and MOF figures as republished by NBS). |
| **Phase A: Release Copilot v0 (shadow)** | Built, **not yet verified against a live model**. `src/cnmacro/copilot/`: a bounded Context Builder, two DeepSeek Messages calls (Draft, Challenge), hard validation that fails closed (numbers only as allow-listed placeholders rendered by code, evidence allowlist, as-of check, code-owned `mechanical_delta`), append-only Run Records, and the analyst protocol (blind take, then reveal, then Accept / Edit / Reject / Keep unresolved). Output is never shown on the site; the deterministic pipeline never imports it; a model failure is recorded as `copilot: unavailable` and the analyst publishes anyway. A genuine run needs `DEEPSEEK_API_KEY`; default model `deepseek-flash`, with `--model deepseek-v4-pro` or `CNMACRO_COPILOT_MODEL` as an override. Gate G-A needs a genuine replay and October 14 Shadow run. Runbook: [`docs/runbooks/2026-10-14-live-1.md`](docs/runbooks/2026-10-14-live-1.md). |
| **Not built** | Research Journal (designed in [`docs/specs/research-journal-v1.md`](docs/specs/research-journal-v1.md), implemented in Phase B), Track Record, gold set and evaluation, Policy Delta Analyzer. No AI generation step runs in the automated pipeline: every number, test outcome and status is deterministic code. Claude Code is the authoring tool the analyst uses for claims and updates (section 3); the probability and conviction are the analyst's. |

**What comes next.** [`docs/PRODUCT_STRATEGY.md`](docs/PRODUCT_STRATEGY.md) (v2.0) is the roadmap authority. Its current focus is Phase A: a Release Copilot v0 (Draft and Challenge passes with a Run Record) run in shadow on the next live release, tracked in [Issue #11](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS/issues/11). The shadow-only Copilot is implemented (see the status table) but has not run against a live model. The strategy keeps the analyst update on time whether or not any AI is ready, and holds provider and infrastructure expansion until its Gate G-C.

The first live validation event is **September 2026 CPI and PPI on 2026-10-14 at 09:30 Beijing time**: the refresh job will pick it up and append a data record, and the analyst then appends the first post-baseline update. Until then, "no update since the baseline" is the correct state. The thesis stays open until the 2027Q1 GDP release. Known data limitations are listed on the Method page and in [`docs/brief/project-brief-v0.3.md`](docs/brief/project-brief-v0.3.md).

## Codex contributions and Vercel previews

For same-repository `codex/*` pull requests, [the verified-preview workflow](docs/ops/codex-verified-previews.md) publishes an identical-tree GitHub-signed checkpoint so Vercel can deploy a preview without disabling verified-commit enforcement. Local Codex can alternatively use native SSH commit signing; cloud commits are not retroactively signed.
