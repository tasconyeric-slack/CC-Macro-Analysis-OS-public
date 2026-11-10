# Agent Instructions

**Before writing any ExecPlan or starting any task, read `docs/PRODUCT_STRATEGY.md` and follow its §20 Agent Operating Contract.**

- `docs/PRODUCT_STRATEGY.md` is the roadmap authority. Where it conflicts with any other doc (implementation reports, specs, ExecPlans), it wins.
- Start every ExecPlan by stating the Phase/Gate it advances and answering the Prioritization Rule questions (§15.2). If fewer than 2 answers are "yes", write a Deferred note instead of code.
- Check §0 Current Focus first; it is updated by the Owner only.
- Do not edit `docs/PRODUCT_STRATEGY.md`; propose changes in the PR description.
- Commits: work on a `claude/<topic>` branch and open a PR into `main` (cloud sessions have no signing key; the verified-checkpoint workflow handles previews). Never push unsigned commits to `main`, rebase-merge or force-push. Check deploy readiness with `python scripts/check_commit_verified.py [REF]`; on failure report and stop. Full rules: `AGENTS.md` and `docs/ops/codex-verified-previews.md`.
