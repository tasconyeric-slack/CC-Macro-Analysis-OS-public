# Macro Release Benchmark MVP

Current Research-First MVP, small evaluation slice toward Phase C / G-C. Prioritization (§15.2) 1 yes, it explains how an apparent price signal can be misread. 2 yes, it produces a reproducible reliability result. 3 yes for interpreting the release, with deterministic validation for the checks demonstrated here. 4 yes, the archived fixture already shows an output rejected by the Release Copilot. 5 yes, the evaluation can be demonstrated in the next interview.

## Scope and protocol

Use the existing July 2026 CPI/PPI replay snapshot and archived hand-written Draft and Challenge. The fixed task asks for a source-backed note as of the snapshot, including PPI year-on-year and month-on-month, competing evidence and the implications for the research thesis. The scored units are output scenarios for that one release, all in the demo/dev split. Each negative changes one behavior of the same Draft, preserving the input information set. Each scenario records its expected verdict, actual verdict for three configurations, triggered violations and affected candidate field. Show gold evidence IDs, public values and source-release links next to the candidate.

1. JSON-only baseline accepts a syntactically valid response. It represents an integration with schema parsing alone.
2. Release Copilot validates Draft and Challenge with the existing contract, then renders evidence values from the frozen allowlist.
3. The demonstration adds an assertion for a field that explicitly promises to bind July PPI YoY in its first numeric slot. It checks that the expected reference is both rendered from a placeholder and declared. This is a task-specific assertion and runs outside the production validator.

Report rejected negative scenarios and accepted clean controls as counts with denominators. The central case substitutes core CPI for PPI in an otherwise valid reference binding, demonstrating the coverage gap between provenance and claim-evidence alignment. An ablation reports the same case before and after the assertion. Do not infer a production failure rate from curated scenarios or generalize the assertion to arbitrary analytical prose.

The October PPI evidence-only fallback is an independently archived real release workflow event. It records an unavailable model and yields no model performance sample. The replay and injected responses are controlled fixtures. The archived replay uses the project calendar availability convention, which can differ from official intraday first-release timing. The historical framework postdates the replayed data, and an unprobed model may have subsequent knowledge.

## Reproduce

```sh
python site/macro_benchmark.py > benchmark-results.json
python site/build.py
python -m http.server --directory site/dist 8000
```

The report includes the snapshot hash, release cutoffs, evidence references, scenario verdicts and diagnostics. Open `/zh/benchmark.html` or `/en/benchmark.html` from the built site. The page is static and self-contained apart from the site's own assets and source links. The build requires no model credential.

## Evidence needed for a model benchmark

Before running models, have a researcher freeze expected observations, defensible interpretations and forbidden conclusions. Divide distinct releases into dev and held-out test, then have a second reviewer label a subset. Pin model IDs, prompt and schema, use identical evidence and tool budgets, probe for historical leakage, and store per-run tokens and latency. Compare a source-backed rule summary, the same model with the evidence bundle, and the same model with the guardrails and Challenge pass. Report model and workflow effects separately where possible. Track citation/temporal failures, analyst-rated useful counterarguments and accepted insights missing from a blind take. Phase C remains open until these runs and labels exist.
