# ExecPlan — Phase A: Release Copilot v0 + 2026-10-14 Shadow Live

Issue: [#11](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS/issues/11) · Authority: `docs/PRODUCT_STRATEGY.md` v2.0 (§0, §4, §8, §11, §14, §20)

## 1. Phase / Gate

**Phase A — Release Copilot v0 + Shadow Live → Gate G-A.** Next hard date (§0): **2026-10-14 09:30 Beijing, September CPI/PPI (Live #1)**. The only P0 (§0) is an analyst update within 48 h of each release; the Copilot is never on that path (P9, D-03).

G-A (§14): the Copilot produces a structured delta that passes every hard gate on a replay at `as_of=T`, and on 10-14 it runs at least in Shadow with a complete Run Record, even if the output is not public.

## 2. Prioritization Rule (§15.2)

| # | Question | Answer |
|---|---|---|
| 1 | Does it materially improve understanding of *What Changed and Why*? | **Yes.** A bounded delta against the standing thesis, with the strongest counter-case and "does not prove". |
| 2 | Does it produce a new live proof, user result or evaluation data point? | **Yes.** The Run Record is the evaluation substrate; 10-14 is the first uncontaminated run. |
| 3 | Is AI actually necessary here, or is deterministic code better? | **Yes, for interpretation only** (materiality, hypothesis mapping, counter-case, research questions). Everything with a deterministic answer stays in code: values, `as_of`, test flips, `mechanical_delta`, divergence flag, `vs_expectation`, rendering. |
| 4 | Does it come from a failure already observed in replay, live or user tests? | **Partly.** The observed gap is the one in Issue #11 (the public product has no visible AI role and the research loop has never run). No replay or live failure exists yet because no run exists. |
| 5 | Would skipping it for two weeks materially weaken the current deliverable? | **Yes.** Missing 10-14 permanently loses the first uncontaminated data point (§1 insight 3). |

Four "yes", one "partly" ≥ 2 → proceed. Infrastructure test: *without the Context Builder, validator and Run Record, the 10-14 Shadow run cannot be recorded or trusted.* Nothing else is built.

## 3. What is reused (nothing is rebuilt)

| Need | Existing component |
|---|---|
| Point-in-time information set, vintages | `store.as_of`, `load_observations`, `load_dictionary` |
| Derived values and lineage, ref grammar `obs:`/`drv:` | `derive.Deriver` (`resolve`, `series_for`, `ref_for`) |
| Test evaluation, flips, marginal changes, mechanical tally | `refresh.evaluate`, `refresh.diff_results`, `evidence.*` |
| Case in force (baseline + amendments), judgment fold | `thesis.effective_case`, `thesis.fold` |
| Sandbox replay on the production `as_of` path | `replay.replay` (unchanged) |
| Bare-number and period-token rules | `claims.bare_numbers`, `claims.period_tokens`, `claims.PLACEHOLDER` |
| Immutability evidence | `checks.git_history`, `checks.commit_time`, eval gate E0–E5 |
| Update workflow (manual analyst path) | `cnmacro update` / `fill-claims` / `check` (unchanged) |

Not touched: `refresh.py`, `replay.py`, `evidence.py`, `thesis.py`, the baseline, amendments, claims, refresh records, the refresh workflow, hosting.

One unrelated line is touched, in its own commit: a stale assertion in `tests/test_wind_cli.py` that fails on an untouched `main` (it expects `refreshes/` not to exist; the 2026-10-09 scheduled refresh created it).

## 4. Smallest vertical slice

```
existing store ─► deterministic delta (flips, marginal, new obs, trend features)
              ─► Context Builder  (bounded, as_of-clipped, allowlist, content hash)
              ─► Pass 1 Draft ─► hard validation ─┐ (fail ⇒ stop, no Pass 2)
              ─► Pass 2 Challenge ─► hard validation
              ─► code assembles result (mechanical_delta, divergence flag, vs_expectation)
              ─► deterministic renderer (placeholders ⇒ values)
              ─► append-only Run Record ─► analyst: blind take ─► reveal ─► decision
```

New code, all under `src/cnmacro/copilot/`: `context.py`, `contract.py` (schema, validation, rendering), `prompts.py`, `llm.py`, `runner.py`, `records.py`, `ops.py` (preflight, replay wrapper), `cli.py`. One `copilot` subcommand family added to `cnmacro.cli`. No new dependency: the model call is a stdlib HTTPS POST (repo contract §20.7; the Anthropic SDK is a deliberate non-choice, proposed in the PR for Owner decision).

### Responsibility boundary enforced in code

* **Code owns:** every number (rendered from allow-listed values), `release_id`, `as_of`, `mechanical_delta`, the divergence *flag* (derived from `mechanical_delta` × `ai_assessment`), `vs_expectation` (computed from the frozen Expectation Note), terminal-rule status.
* **AI owns:** interpretation, materiality, hypothesis mapping, divergence *reason*, counter-case, research questions, draft update wording and `direction_hint`.
* **The analyst owns:** blind take, Accept / Edit / Reject / Keep unresolved, probability, conviction, every thesis change. The Copilot has no write path to `updates/`, `preregistered/`, `claims.jsonl`, `presentation.yaml` or any public artifact.

### Interpretation choices beyond the §8.3 sketch (flagged for the Owner)

1. `release_id`, `as_of`, `mechanical_delta`, `vs_expectation` are never model output; a model that supplies them fails closed (stricter than "may not modify").
2. The divergence flag is checked, not trusted: a flag inconsistent with `mechanical_delta` × `ai_assessment` is a hard failure, so a divergence cannot be hidden.
3. No automatic retry or repair loop: a validation failure is a recorded failed run, so hard-gate failure counts stay honest. The analyst can start a new run.
4. Canonical language is English; Chinese is a constrained translation pass that is **deferred** (nothing from the Copilot is public in Phase A).

## 5. Deliverables and acceptance mapping

| Acceptance (task §9) | Evidence |
|---|---|
| Public refresh and deterministic logic unchanged | `refresh.py`/`replay.py`/`evidence.py`/`thesis.py` untouched; full existing suite + `check --public` green; test that `refresh` does not import `copilot` |
| One replay, grounded and validated | `cnmacro copilot replay --release-at 2026-08-09`: the production `as_of` path end to end (fixture-model sample committed and labelled `fixture`; **genuine run pending the Owner's API key**) |
| Three labelled 2026 replay cases | **Not met, by design.** `copilot/replay_cases.yaml` registers three 2026 CPI/PPI releases (no flip / two flips / one flip) with their deterministic facts; `copilot/labels/_template.yaml` and `replay --context-only` let the Owner label before any run. No label is written here (strategy §11.1: labels are human and precede the first run) |
| Draft and Challenge produce the expected fields | contract tests |
| Unsupported refs / ungrounded numbers fail | adversarial tests + committed failure samples |
| Model cannot mutate `mechanical_delta` or probabilities | tests |
| Genuine run ⇒ complete Run Record | record schema + `verify`; **no genuine run exists yet** (no credential in this environment) |
| Baseline and history unchanged | E4 + byte-hash checks |
| AI can fail without breaking refresh or manual publication | tests (model error, validation failure, corrupted records) |
| 10-14 procedure documented and executable | `docs/runbooks/2026-10-14-live-1.md`, `cnmacro copilot preflight` |
| Public site deployable | existing site tests + build; Method page gains "Where AI Is Used" only (canonical / Open Graph already point to Netlify and are tested: no change needed) |

G-A is **not claimed**: it requires a genuine model run on a replay and a Shadow run on 10-14, both of which need the Owner's credential.

## 6. Deferred (not done here, on purpose)

Research Journal implementation (spec only, Phase B) · homepage restructure · Track Record table and expectation scoring · AI scenario mapping for the Expectation Note (a third call) · constrained Chinese translation pass · contamination probe, gold set, dev/test split, second annotator, failure taxonomy (Phase C) · CI workflow that runs the Copilot with a repository secret · refusal fallback to a second model (it would blur model identity in the Run Record) · persistent research queue (Phase E) · Policy Delta (Phase D) · any provider abstraction.
