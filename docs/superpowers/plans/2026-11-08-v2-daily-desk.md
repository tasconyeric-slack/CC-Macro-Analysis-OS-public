# V2 Daily Macro Desk implementation

Phase: Owner-authorized V2 Public News & Official Data; Epic #8 Stage 2/3, preserving Phase B/C live cadence. Gate: Daily Desk real-release acceptance in #10, then integrated production acceptance #13.

Prioritization (§15.2): (1) Yes, connects changes to sources and research. (2) Yes, exposes real refresh records and pending releases. (3) No AI is needed for factual briefing; deterministic claims are appropriate. (4) Yes, the current site lacks a usable daily view and analyst-update status. (5) Yes, the authorized V2 deliverable needs this reader journey. Blocked behavior: readers cannot go from the latest release to its sourced values and evidence in one daily page.

Spec: Issue #10 and docs/implementation/v2-public-sources-kickoff.md. Architecture: existing Python/Jinja static build, one locale-neutral model, bilingual UI. No runtime requests, no new data provider, no judgment writes.

- [x] Stage 0 green. Owner explicitly authorized development from green #22 during the release blackout; merge order and blackout remain binding.
- [x] Add site/daily.py to derive KPIs, refresh release groups, deterministic placeholder-bound brief and Beijing-time calendar from existing artifacts.
- [x] Render daily.html with shared source/tier/KPI macros, honest pending and no-analyst-update states; emit static briefing JSON.
- [x] Verify headline PMI metadata and add its existing NBS route; actual history ingestion awaits the post-merge main refresh, without hand-entering observations.
- [x] Test KPI/store equality, future-release pending behavior, timezone handling and source metadata; run build and public E0-E5.
- [ ] After #4/#5, integrate verified official events, keeping candidates and analyst judgment distinct.
- [ ] One Issue #10 PR, targeted checks, signed preview, merge outside release blackout, production journey proof in #13.

Verification focus: vintages are resolved as of evidence time; scheduled dates do not manufacture releases; old first-seen news is not today; absent model keys do not block facts; absent analyst updates are visible. FinLens and LPR deferred. §0 and immutable research history untouched.
