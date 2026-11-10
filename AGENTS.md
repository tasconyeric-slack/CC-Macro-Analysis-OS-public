# Agent Instructions

**Before writing any ExecPlan or starting any task, read `docs/PRODUCT_STRATEGY.md` and follow its §20 Agent Operating Contract.**

- `docs/PRODUCT_STRATEGY.md` is the roadmap authority. Where it conflicts with any other doc (implementation reports, specs, ExecPlans), it wins.
- Start every ExecPlan by stating the Phase/Gate it advances and answering the Prioritization Rule questions (§15.2). If fewer than 2 answers are "yes", write a Deferred note instead of code.
- Check §0 Current Focus first; it is updated by the Owner only.
- Do not edit `docs/PRODUCT_STRATEGY.md`; propose changes in the PR description.
- For any change to the public site's look (templates, CSS, components, charts' chrome), follow the design guide `docs/design/README.md` (Masonry Red). Take values only from `docs/design/masonry-red/tokens.json` and the guide's ccmacro adaptations; do not invent new colors, radii or spacing. The guide never widens a task's scope.

- Codex PRs that need Vercel Preview must use a same-repo `codex/<topic>` branch targeting `main`. `.github/workflows/codex-verified-preview.yml` appends a GitHub-signed identical-tree checkpoint when the PR head is unsigned. It never signs the original Git commit; local Codex should prefer native SSH commit signing where configured. Details: `docs/ops/codex-verified-previews.md`. Do not disable Vercel verified-commit enforcement or force-push to make previews work.
- When updating an existing `codex/*` PR, sync with its latest remote head before pushing again (for example, `git fetch origin` then rebase on `origin/<branch>`). The signed checkpoint advances the remote branch; do not force-push or discard that checkpoint.
