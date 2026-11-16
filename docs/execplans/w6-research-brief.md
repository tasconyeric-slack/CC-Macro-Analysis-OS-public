# ExecPlan — W6 Research Brief (evidence-bound AI Research Copilot)

**Issue #69 W6 · advances #52 (the AI part of release → evidence → analyst decision) and reuses the #6 Copilot rules.**
**Phase:** Research-First MVP (§0), Release Copilot loop (§7–§8). **Gate:** G-A/G-B proof that the Copilot adds a
traceable explanation, counter-evidence and what's-next to a genuine release (#69 acceptance item 5).

## §15.2 Prioritization

1. Improves understanding of *What Changed and Why*? **Yes.** It explains a real release next to the official
   releases and policy notices collected around it, with every figure and link filled in by code.
2. Produces live proof or evaluation data? **Yes.** Each run, including a missing credential or a failed gate, is an
   append-only Run Record; a reviewed brief records a person's accept / edit / reject.
3. Is AI needed here? **Yes** for the explanation, the counter-reading and what to watch. **No** for the facts,
   the dates, the source list and the test direction, which code owns (the evidence pack).
4. From an observed failure? **Partly.** The Copilot context could not cite the news/policy/official items that
   #60 now collects, so a Copilot read could not say which document a claim rests on.
5. Weakens the deliverable if skipped? **Yes.** #69 lists AI Copilot as a category that must ship.

## What ships

- `src/cnmacro/copilot/brief.py`: Context Builder output (unchanged code path) plus up to 12 `src:<event_id>` items
  from the research-input bundle, filtered to what was knowable at `as_of`, figures masked. Explain pass (Release
  Copilot Draft schema and gates) and Challenge pass (competing reading, counter-evidence, does-not-prove,
  what's next pinned to the release calendar). Extra gates: no claim may rest on media reports alone; a
  what's-next date must be a scheduled release or `unscheduled`. No direction hint, probability or conviction.
- `src/cnmacro/copilot/brief_cli.py`: `python -m cnmacro copilot brief pack|context|run|show|review|export|list`.
- Review: a named person (automation and model names are refused) accepts, edits or rejects; append-only,
  hash-chained with the existing Run Record events.
- Export: the only JSON a page may show. Unreviewed, rejected, failed, synthetic (fixture) or no-model runs export
  the deterministic evidence pack with no AI text. A reviewed brief is labelled "AI-assisted interpretation,
  reviewed by …; not a signed thesis update" and keeps `signed_thesis_update: false`.
- Tests: `tests/test_copilot_brief.py` on the real 2026-10 CPI/PPI release (as of 2026-11-09T03:00Z) and the
  2026-11-10 bundle; fixtures in `tests/fixtures/copilot_brief/` are hand-written and never published.

## Not in scope (left to the Release Integrator or later)

- No site, template, i18n or `site/build.py` change. The integrator renders `copilot brief export` JSON.
- English is the canonical model language (§8.5); a constrained zh translation is a follow-up.
- No new provider: the existing DeepSeek transport (`DEEPSEEK_API_KEY`) is reused.

## Owner runbook (needs `DEEPSEEK_API_KEY`)

```bash
python -m cnmacro copilot brief pack --release "2026-10 PPI" --as-of 2026-11-09T03:00:00Z --markdown   # no key needed
python -m cnmacro copilot brief run  --release "2026-10 PPI" --as-of 2026-11-09T03:00:00Z --review-id 2026-11-09T0223Z
python -m cnmacro copilot brief show --run-id <run_id>
python -m cnmacro copilot brief review --run-id <run_id> --action accept --reviewer "<your name>"
python -m cnmacro copilot brief export --run-id <run_id> --out research/cases/cn-nominal/copilot/briefs/public/2026-10-ppi.json
```

Commit the run directory once it is written (its first commit time is part of the audit trail).
