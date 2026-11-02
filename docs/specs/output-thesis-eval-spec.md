# Output, Thesis & Eval Specification v0.2

> Contracts between the research engine, the research artifacts and the website.
> Code: `src/cnmacro/{claims,evidence,thesis,checks}.py`. Case: `research/cases/cn-nominal/`.

## 1. Artifact layout

```text
research/cases/cn-nominal/
  case.yaml                      question, hypotheses, evidence tests, terminal rules (draft until frozen)
  claims.jsonl                   claims ledger (append; a claim id is never reused); one record per claim
                                 with text_en and text_zh sharing id, bindings, refs, supports, stance
  memo.en.md.j2, memo.zh.md.j2   Deep Dive templates, one per language; cite claims by id, no typed numbers
  presentation.yaml              current explanatory layer: current view, hypothesis states, curated key
                                 evidence (top_evidence_for / _against), scenario matrix, limitations.
                                 Not preregistered; names the judgment it applies to
  frozen_zh.yaml                 Chinese renderings of the immutable English artifacts (translations only)
  policy_events.yaml             Policy Context: official events (stage, channel, next confirmation); context
                                 for H3, never an evidence test
  preregistered/
    <date>-baseline.yaml         IMMUTABLE: frozen case + test results + initial state
    <date>-amendment-<n>-*.yaml  IMMUTABLE: correction to terminal_rules / horizon, before a tested release
  updates/
    <date>-<release>.yaml        IMMUTABLE once committed; analyst judgment after a release,
    <date>-terminal-<status>.yaml   or a status set automatically because a preregistered rule fired
  refreshes/
    <YYYY-MM-DDTHHMMZ>.json      IMMUTABLE: automatic evidence refresh (written by refresh-public)
  eval/latest.json               last eval report (generated), with the audit manifest of immutable files
```

Current thesis state is **never stored by hand**. It is folded from baseline + updates (`thesis.fold`).
The **case in force** is the frozen case with amendments applied in order (`thesis.effective_case`).
Each amendment change names a dotted path, quotes the exact `before` value (checked against the
frozen case) and gives the `after` value; only `terminal_rules` and `horizon` may change.

**Refresh record** (automatic; never changes the analyst judgment):

```text
kind: evidence_refresh · as_of · previous_evidence_as_of · case_in_force · calendar · due
sources{route: {ok, fetched, new, metrics}} · new_observations[]
flipped_tests[{test, hypothesis, from, to, effect_from, effect_to, period_from, period_to}]
marginal_changes[] · test_results{} · terminal{before, after: {status, rule_fired, window_open}}
analyst_judgment{probability, conviction, status, last_update_direction, as_of, changed_by_this_refresh: false}
suggested_direction{direction: toward_thesis | against_thesis | neutral, score, note}
```

## 2. Claims

```json
{"id": "C-H1-003", "type": "DERIVED", "as_of": "2026-10-13",
 "hypotheses": ["H1"], "stance": "for",
 "text": "The implied GDP deflator was {defl} in 2026Q2, up from {defl_prev} a year earlier.",
 "values": {"defl": {"ref": "drv:deflator_yoy(cn_ngdp_q,cn_rgdp_yoy)@2026Q2", "fmt": "+.1f", "suffix": "%"},
            "defl_prev": {"ref": "drv:deflator_yoy(cn_ngdp_q,cn_rgdp_yoy)@2025Q2", "fmt": "+.1f", "suffix": "%"}},
 "refs": [], "supports": [], "source": null, "public": true}
```

| type | must cite |
|---|---|
| `FACT` | ≥ 1 `obs:` ref |
| `DERIVED` | ≥ 1 `drv:` ref |
| `EXTERNAL_VIEW` | `source.institution`, `source.date` (one-line paraphrase only in public build) |
| `INFERENCE` | `supports`: the claim ids it rests on |

Bare numbers in `text` (decimals, %, bp, integers > 12 that are not years/periods)
are rejected by the linter. `recorded` values are written by `fill-claims` and checked by E1.

## 3. Evidence tests vs terminal decision rules

**Evidence test**: moves one hypothesis. Fields: `id, hypothesis, indicator, rule
(latest|change|streak|avg), op, threshold, n, window, check, if_true
(supports|challenges), description, threshold_basis`. Result: `true | false |
insufficient_data`, with the refs it read.

**Terminal decision rule**: moves the thesis. A boolean tree (`all / any /
at_least…of`) over test outcomes, always combining price **and** demand evidence.
Only a fired terminal rule can set `CONFIRMED` or `FALSIFIED`. Rules marked
`early: true` may fire before the decision window; others only at it. At the
window, if nothing fires, the thesis is `RETIRED` (inconclusive).

## 4. Thesis state

| Dimension | Values | Meaning |
|---|---|---|
| `status` | ACTIVE · CONFIRMED · FALSIFIED · RETIRED | lifecycle |
| `conviction` | LOW · MEDIUM · HIGH | how much the evidence base can bear |
| `last_update_direction` | STRENGTHENED · UNCHANGED · WEAKENED | direction of the latest evidence |
| `probability` | 0–1 on a 0.05 grid | analyst judgment that the thesis statement will be true at the window |

**Baseline file** (`preregistered/<date>-baseline.yaml`): `as_of`, `committed_before`
(the release it precedes), `case` (frozen copy of case.yaml), `test_results`,
`probability`, `conviction`, `status`, `last_update_direction`, `rationale`,
`claims_sha256` (hash of claims.jsonl at baseline).

**Update file** (`updates/<date>-<slug>.yaml`): `baseline`, `as_of`, `release`,
`test_results`, `flipped_tests`, `new_claims`, `probability`, `conviction`,
`status`, `last_update_direction`, `probability_change` (required if probability
moved: `previous, new, evidence, hypotheses, reasoning`), `terminal_rule_fired`
(required for CONFIRMED/FALSIFIED), `does_this_change_the_thesis` (one paragraph).

## 5. Outputs

| Output | Source of truth | Public build |
|---|---|---|
| Deep Dive Memo | `memo.{en,zh}.md.j2` + claims | rendered with demo data; private claims shown as withheld |
| Homepage | `presentation.yaml` + state + claims | yes; key evidence is the analyst's explicit selection |
| Policy Context | `policy_events.yaml` | yes; context, clearly separated from the frozen baseline |
| Thesis & Evidence | baseline + updates + test results | yes |
| Release Update | `updates/*.yaml` + claims | yes |
| Charts | observations + derived, via dictionary metadata | public sources only |
| Method & Eval | `eval/latest.json` | yes |

Every chart shows metric name, period range, unit, source and as-of.

## 6. Eval (deterministic first)

| Check | What it proves |
|---|---|
| E0 Data quality | schema, required fields, duplicates, period format, provenance or limitation present, gaps |
| E1 Citation integrity | every claim value equals the data as of the claim date; claim types cite the right evidence |
| E2 Derived lineage | every derived value recomputes from observations that exist |
| E3 As-of leakage | no artifact cites information released after its as-of time |
| E4 Preregistration | baseline, amendments, updates and refresh records were committed once and never modified; each amendment was committed after the baseline and before its `effective_before` release |
| E5 Thesis discipline | probability grid, explained changes, terminal statuses only via rules |

In CI and in the scheduled refresh any failure is blocking; warnings are reported, not blocking.

A method rubric scored by an LLM may be shown as a secondary signal, labelled as
such. It is never presented as proof of correctness.

## 7. Website data contract

`site/build.py` reads only tracked artifacts and `data/demo/`. It never reads
`data/private/`. Claims citing refs absent from the demo store render as
"licensed data, withheld". The site shows baseline as-of, latest update as-of,
and the git commit SHA of each preregistered file (from git, or from the eval report's audit
manifest when the host builds from a shallow clone). It keeps the **analyst judgment**
(probability, conviction, status from baseline and updates) visibly separate from the
**automatic evidence state** (test outcomes as of the latest observation retrieved).
