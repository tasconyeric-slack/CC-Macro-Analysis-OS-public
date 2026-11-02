# Data Policy & Boundary

> Hard constraint for V1. Applies to every contributor, human or Claude.

> **Status of Wind:** Private Research Mode consumes Wind and licensed research. The V1.2 Phase 1 Wind private layer (`python -m cnmacro refresh-private --provider wind`, local only; Wind runs only when named) acquires a pinned P0 set through the officially installed Wind skill and writes it to gitignored paths. The V1.2 Phase 2 research layer (`python -m cnmacro diagnose-private`, local only) derives private diagnostics from those snapshots and writes them to gitignored `data/private/signals/` and `data/private/research/`; only the signal definitions (`data/dictionary/private_signals.yaml`, no values) are tracked. It is not required for the public V1, the public build never reads it, and the Wind skill itself is never copied into this repository. The rules below are the boundary it respects. Capability baseline: [`wind-capability-note.md`](wind-capability-note.md).

## Two modes

| | Private Research Mode | Public Demo Mode |
|---|---|---|
| Purpose | Conduct the real research | Build the portfolio website |
| Inputs allowed | Wind (the official locally installed skill), user CSV/XLSX, broker reports, other licensed inputs | Redistributable public sources only (NBS, PBOC, GACC/Customs, SAFE, MOF, FRED) |
| Where inputs live | `data/private/`, `research/private/` (gitignored) | `data/demo/` (tracked, each file listed in `data/demo/SOURCES.md`) |
| Who runs it | The researcher, on their own machine with Wind | Anyone; `site/` builds from tracked artifacts only |
| Credentials | The Wind skill's own local configuration (its CLI resolves the key; this project never reads or stores it), or a local `.env`; never in git | None |

## Rules

1. **No credential, raw Wind export, or copyrighted report ever enters git history.** `scripts/check_secrets.py` enforces this in two places:
   - **Pre-commit hook** on staged files. It is active only in a clone where `git config core.hooksPath .githooks` has been run, so run it once per clone.
   - **GitHub Actions** (`.github/workflows/checks.yml`) on every push and pull request, over all tracked files. A red check is a stop sign. CI cannot un-push a leaked file, so the hook is the first line of defence.
2. **Wind-derived values are private by default.** Transformation (YoY, 3M average, percentile) does not make them redistributable. A Wind-sourced observation reaches the public build only if redistribution rights are confirmed in writing and recorded in `data/demo/SOURCES.md`.
3. **Public-first for Core Metrics.** Where an official public source publishes a Core Metric, the public build uses that source. Wind is used privately to fill gaps and cross-check.
4. **Public/private boundary (what is enforced today).** Every observation carries a `source_class` (`public` or `private`).
   - The public refresh and the site build read **tracked public artifacts only** (`data/demo/`).
   - Private observations live under **gitignored** paths (`data/private/`; `research/private/` for research files), and `scripts/check_secrets.py` blocks any of them from being committed.
   - A command run in public mode (`check --public`, `evaluate --public`, `refresh-public`, the site build) **never loads private observations**. Only an explicit private-mode command (`check`, `evaluate`, `refresh-private`, `diagnose-private`) reads `data/private/observations/`. Derived private diagnostics are read by no public command, site build or CI job.
   - There is no demo exporter. If an explicit export or sanitization layer is ever added, it must drop `private` observations and replace any claim that cites them with a disclosed placeholder ("based on licensed data, value withheld in public build"), and it needs its own tests.
   - The website never shows an unattributed number.
5. **Broker research** is `EXTERNAL_VIEW` only. Files stay in `research/private/`. The public build may cite institution, date and a one-line paraphrase of the view; never substantial text.
6. **Private observations are available only from their own `retrieved_at`.** The store ignores any `release_date` on a `source_class=private` row when it decides availability, so a licensed history pulled today can never appear in an earlier as-of information set. Wind provides no vintages, so its append-only snapshots start the record from the first retrieval.
7. **No fabricated provenance.** Unknown release dates, vintages, consensus figures or source codes are recorded as `null` with a `limitation` note, never guessed.
8. **If a secret is found in history:** stop using that credential, report it in the project thread, rotate it, and rewrite history before any further push.

## Repository status (Security / Repo Gate, 2026-10-03)

- GitHub visibility: **private** (verified via GitHub API, 2026-10-03).
- History audit: 1 commit, 2 markdown files, no credential patterns, no data files.
- Branches: `main` is the base branch and `claude/project-brief-v0-2-kdulnu` is the feature branch. Work reaches `main` by pull request, as a working convention.
- **Not yet active:** branch protection on `main`. GitHub only enforces branch protection and rulesets on private repositories under a paid plan (Pro/Team), and none is configured. Until then, "PR into main, CI green" is a convention, not a technical control.
- **Automatic commits (exception to the PR convention):** the scheduled public refresh (`.github/workflows/refresh.yml`) commits directly to `main` as `cnmacro-refresh[bot]`. It can stage only public observations, refresh records, automatic terminal updates and the eval report; it runs the secrets / data-boundary check and the full eval gate first, and commits nothing if either fails. It never handles credentials, Wind data or private inputs, and needs no secret beyond the workflow's own `GITHUB_TOKEN`.
- Pre-commit hook: enabled and tested in the cloud clone (2026-10-03). Each new clone must enable it with `git config core.hooksPath .githooks`.
- Pre-commit hook: enabled and tested in the researcher's local Windows clone (2026-10-04). It blocked a staged `data/private/` file and a staged credential string (a real `git commit` was refused) and passed a clean staged file. The hook now falls back from `python3` to `python` / `py -3`, because Windows Python installs often have no `python3` command; if it finds no Python, it blocks the commit.
