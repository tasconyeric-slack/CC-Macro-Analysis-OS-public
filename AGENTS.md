# Agent Instructions

**Before writing any ExecPlan or starting any task, read `docs/PRODUCT_STRATEGY.md` and follow its §20 Agent Operating Contract.**

- `docs/PRODUCT_STRATEGY.md` is the roadmap authority. Where it conflicts with any other doc (implementation reports, specs, ExecPlans), it wins.
- Start every ExecPlan by stating the Phase/Gate it advances and answering the Prioritization Rule questions (§15.2). If fewer than 2 answers are "yes", write a Deferred note instead of code.
- Check §0 Current Focus first; it is updated by the Owner only.
- Do not edit `docs/PRODUCT_STRATEGY.md`; propose changes in the PR description.

- **Commit workflow (Codex and Claude Code, local and cloud):** local clones sign with the workstation's SSH key; cloud sessions never receive that key. Cloud/agent work goes on a same-repo `codex/<topic>` or `claude/<topic>` branch with a PR into `main`; never push unsigned commits to `main`, use other branch names, rebase-merge, or force-push. Before relying on a commit to deploy, run `python scripts/check_commit_verified.py [REF]`; if it exits non-zero, report the commit path it prints and stop (no retry loops, never disable Require Verified Commits). Automated data commits reuse `scripts/commit_public_refresh.py`; do not add another commit mechanism.
- Codex/Claude PRs that need Vercel Preview must use a same-repo `codex/<topic>` or `claude/<topic>` branch targeting `main`. `.github/workflows/codex-verified-preview.yml` appends a GitHub-signed identical-tree checkpoint when the PR head is unsigned. It never signs the original Git commit; local Codex should prefer native SSH commit signing where configured. Details: `docs/ops/codex-verified-previews.md`. Do not disable Vercel verified-commit enforcement or force-push to make previews work.
- When updating an existing `codex/*` PR, sync with its latest remote head before pushing again (for example, `git fetch origin` then rebase on `origin/<branch>`). The signed checkpoint advances the remote branch; do not force-push or discard that checkpoint.
