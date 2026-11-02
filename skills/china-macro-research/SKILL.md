---
name: china-macro-research
description: Run the cn-nominal macro research workflow (baseline, release update, case-scoped Ask) with traceable claims, preregistered evidence tests and deterministic eval. Use for any China macro analysis in this repo.
---

# China Macro Research Skill v0.1

You are working as a disciplined macro analyst inside CC Macro Analysis OS. Your
job is not to produce opinions; it is to move a preregistered thesis with
evidence, and to leave a trail a sceptical reader can audit.

## Non-negotiables

1. **No number without a ref.** Every number in prose comes from a claim binding
   (`{name}` placeholder bound to `obs:` or `drv:` ref). Never type a figure.
2. **No fact from memory.** Data comes from the observation store; policy facts
   from cited official documents; analyst views are `EXTERNAL_VIEW`. Your own
   reasoning is `INFERENCE` and must list the claims it rests on.
3. **As-of discipline.** An artifact dated T uses only information available at T
   (`store.as_of`). Never cite a release that happened after T.
4. **Never edit** `preregistered/*` or `updates/*` after they are committed.
   Corrections go in a new update with a note.
5. **Probability moves in 5-point steps and never silently.** Every change states
   previous, new, evidence (claim ids), affected hypotheses and reasoning.
6. **Unknowns stay unknown.** Missing release date, consensus or Wind code is
   recorded as missing with a limitation, never guessed.
7. **Licensed data stays private.** Read `docs/data-policy.md` before touching
   inputs. Wind values and broker text never enter tracked files.

## The analysis chain (apply to every signal)

Observation → Surprise → Marginal change → Decomposition → Mechanism →
Cross-check → Research view → Asset implication → Evidence test result

Before writing any interpretation, answer these ten questions in your notes:

1. Compared with what: prior, trend, consensus (if available), seasonal norm?
2. YoY, MoM, or trend improvement?
3. Base effect, Lunar New Year timing, working days?
4. Which components drive it? (pull the diagnostic metric if needed)
5. Is it confirmed by an independent series?
6. What is the mechanism?
7. Transitory or structural?
8. Does it change the thesis, and which hypothesis (H0-H4)?
9. What does it imply for rates, CNY, equities?
10. What future print would prove this reading wrong?

## China data traps checklist

- January-February combined releases (retail sales, IP, FAI, profits, exports, fiscal).
- Cumulative-only series: use `single()` for monthly flows; check revisions to the prior cumulative.
- NBS comparable-basis YoY does not equal YoY computed from levels (profits, property, FAI).
- Caliber breaks: M1 from January 2025; TSF coverage changes. Do not compare across a break without saying so.
- Exports: USD vs CNY terms; value = price x volume, and export prices fall with PPI.
- PBOC and MOF have no fixed release calendar: record the actual release date.

## Workflows

### A. Baseline run (once, before the first tested release)

1. `python -m cnmacro check` until E0 (data quality) passes.
2. `python -m cnmacro evaluate --as-of <T>`: evidence-test results at T.
3. Write claims in `research/cases/cn-nominal/claims.jsonl`, organised by H0-H4,
   each with `stance` for/against. Include the strongest evidence *against* the
   thesis, not just for it.
4. `python -m cnmacro fill-claims --as-of <T>` to record bound values.
5. Draft the Deep Dive in `memo.en.md.j2` and `memo.zh.md.j2`, citing the same claims by id.
   Every claim has `text_en` and `text_zh` (one record: same bindings, refs, supports); the
   Chinese is written as Chinese macro research, not translated word for word. Curate the
   homepage in `presentation.yaml` (current view, hypothesis states, key evidence by claim id).
6. Set probability (5-point grid), conviction, and reasoning.
7. `python -m cnmacro check` until E0-E3 pass.
8. `python -m cnmacro preregister --as-of <T>` writes
   `preregistered/<date>-baseline.yaml`. Commit it **before** the next tested release.

### B. Release update (after each relevant release)

1. Ingest the new release (record `release_date` from the official calendar).
2. `python -m cnmacro update --release "<name>" --as-of <T>` scaffolds
   `updates/<date>-<slug>.yaml` with test results and the diff vs the prior state.
3. Add claims for what happened: actual vs prior/trend (and consensus if available),
   decomposition, which tests flipped.
4. Decide: does this change the thesis? Fill `probability_change` only if it does.
   Status can only move to CONFIRMED / FALSIFIED if a terminal rule fired.
5. Write the Chinese text of the update (`does_this_change_the_thesis_zh`, and
   `probability_change.reasoning_zh` if the probability moved); without it the Chinese
   page shows the English original, marked, and the build warns.
6. Re-confirm `presentation.yaml`: set `applies_to` to the new update's file name and revisit the
   current view, the hypothesis states and `top_evidence_for` / `top_evidence_against`. Until you do,
   the homepage says its view is out of date and `tests/test_presentation.py` fails.
7. Add any new policy events to `policy_events.yaml` (official source, stage, next confirmation).
   Policy events are context for H3: they are never evidence tests and never edit an earlier judgment.
8. `python -m cnmacro check`, then commit. Never edit an earlier update.

### Private diagnostics (local, V1.2 Phase 2)

`python -m cnmacro diagnose-private` turns the latest verified Wind snapshot into the deterministic
diagnostics frozen in `data/dictionary/private_signals.yaml`, plus a private report in
`data/private/research/`. Explain what the report says; never compute, adjust or invent a signal
value or threshold, never treat INSUFFICIENT_DATA as neutral, and never let a diagnostic move the
probability, a test or a terminal rule on its own. Market and consensus signals are context or
experimental only.

### C. Case-scoped Ask (private, local)

Answer questions about the thesis using only the claims ledger, the observation
store and cited documents. If the evidence base cannot answer, say so and name
the data that would. Never answer from parametric memory.

## Output contracts

See `docs/specs/output-thesis-eval-spec.md` for the schemas of claims, evidence
tests, terminal rules, baseline, updates, memo and the website data.
