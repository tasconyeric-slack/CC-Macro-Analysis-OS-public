# CC Macro V2 — Codex execution handoff (public sources only)

Owner-approved scope: [PRODUCT_STRATEGY.md §0](../PRODUCT_STRATEGY.md), updated 2026-11-08. Canonical repo: https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public. Production: https://ccmacro.byliyz.com/.

## Mission
Execute the already-written [Epic #8](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public/issues/8) and [Epic #1](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public/issues/1) as one program. Build a useful bilingual China macro website using **real public official data, NBS/PBOC announcements, gov.cn policy text, trustworthy source links and existing deterministic evidence/thesis infrastructure**. Prioritize user journeys and production functionality over new plans, simulated news or large infrastructure.

## Binding scope adjustment
**Issue #11 (FinLens/Consensus Radar/broker research) is DEFERRED.** Do not pursue credentials, install FinLens, create `FINLENS_TOKEN`, build radar UI/navigation/sync, scrape broker reports, or invent institutional forecasts. Remove #11 as a dependency for all V2 acceptance gates. All remaining official-source work continues.

## Start facts, verify once
- PR #14 (E4 origin-history recovery) is merged; do not re-implement it.
- PR #15 (verified public-refresh GitHub commits) is merged. Its verified merge `a76cf072` reached Vercel READY. Verify the **next actual refresh-bot commit** is VERIFIED and reaches READY; do not disable Vercel Require Verified Commits, force-push or replay history.
- Retired private repo `Stopped-CC-Macro-Analysis-OS` has no scheduled refresh triggers; do not repeat that task.
- Current Focus was updated by Owner commit `a7c9f138`. Agents must not edit `docs/PRODUCT_STRATEGY.md`. Start with latest main, not an older snapshot or worktree.
- On 2026-11-09 09:30 BJT the October CPI/PPI release requires real refresh evidence; protect the research cadence.

## Work order (all details live in GitHub issues)
- Stage 0: remaining #2 tasks only (validate real refresh, release calendar, live baseline), no duplicate E4 fix.
- Stage 1: #9 shared design/portal first; #3 small official-source + open-source reuse probe in parallel.
- Stage 2 after #9 merges: #10 Daily Desk v1, #12 seven-category data portal, #4 official news/policy inbox. Use separate non-overlapping branches/worktrees where helpful.
- Stage 3: #5 event grouping/triage, #10 v2 event integration, #6 policy text delta.
- Stage 4: #7 research-delta wiring, #13 integration, side-by-side desktop/mobile visual QA, production.
- Never schedule or implement #11 until the Owner expressly reauthorizes it.

## Acceptance emphasis
Home → latest official release → Daily Desk → sourced observation/chart → evidence/hypothesis → **What Changed**. Official news/policy must have publisher, source URL, original publication time, first-seen/retrieval time, verified/candidate status and dedupe behavior. Separate FACT/EVENT/CANDIDATE from analyst-approved JUDGMENT; do not infer a changed probability or publish a fake analyst update. Missing data should be explained honestly, never invented. Preserve current Python/Jinja2 static-build, static JSON, public/private separation, immutable research trail, E0–E5 and source provenance.

Follow §20, the specific issue acceptance criteria (except superseded #11 requirements), and the #8 stage gates. Prefer Playwright/REA to inspect Guojin and China Macro Monitor, with one targeted visual correction pass, not endless review. One PR per issue, targeted tests once and production smoke check. No site/pipeline merges in the release T−2h to T+6h window. Normal technical work may proceed autonomously; escalate only real permission/security, irreversible, material data integrity or product-direction decisions.

## Delivery
Continue across stages without asking the Owner to approve routine technical choices. Do not stop after just planning. At the end report merged PRs, real production URL + commit, visual captures, working data sources, latest actual refresh, public news/policy examples, thesis-update status, and bounded remaining gaps.