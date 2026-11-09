# T3 prices depth execution plan

Phase/Gate: §0 V2 Product Build — Public News & Official Data, supporting the public product deliverable alongside G-B/G-C; this deterministic feature does not itself claim either research gate. §15.2: (1) Yes, show upstream/downstream price changes together; (2) No, not a new live research/evaluation result; (3) No, deterministic parsing/calculation is appropriate; (4) Yes, owner-reported sparse prices coverage in #28; (5) Yes, depth is an explicit current deliverable. Three yes answers. Blocked behavior: readers cannot trace prices through the production chain or compare components on the existing sparse topic page.

## Design and constraints

Implement the owner's specified vertical slice on `codex/prices-depth`, based on fetched `origin/main`. Reuse NBS archived monthly release tables, observation append/vintage rules, Python/Jinja, SVG chart and range controls. No new dependency or hosting. Use exact published labels and headers; missing cells remain missing. Fuel means the published transport-fuel component, explicitly labelled, not a fabricated broad energy aggregate. Do not modify strategy, preregistration, amendments, existing updates/refreshes or mechanical_delta. Shared build/i18n changes stay minimal; base template stays unchanged.

Chosen approach: dedicated release parser/collector plus dedicated prices view/template, with small existing-build hooks. A generic data framework or replacement frontend would broaden scope and conflicts without improving this slice. Owner supplied the page design and execution instructions; implementation details remain agent decisions.

## Steps

1. Runner probe: enumerate NBS releases and archive pages for at least 36 available months; push diagnostic results to a temporary branch. Inspect actual tables and compare reference dashboard features. Delete temporary branch after use.
2. Parse CPI/PPI YoY and MoM and PMI purchase/output indices with dated URL lineage, explicit missing values, strict column/label validation and idempotent append-only vintages. Add dictionary entries and a maintained scheduled refresh route. Backfill available official releases, recording gaps without interpolation.
3. Add a common-period producer PPI / consumer PPI / core CPI chart with labelled gaps, this-month table (latest, immediately prior month, percentage-point change and trailing 36-calendar-month percentile), small multiples, metric anchors and CSVs. Generate an all-price-series XLSX with lineage using standard-library OOXML.
4. Verify parser failures, missing-month handling, vintage idempotence, table statistics, exports and public boundary. Run full tests/eval/build and 1440/390 px browser checks/screenshots in both languages.
5. Review changed files against frozen paths, synchronize remote head/main without force push, open one PR into main with reference feature checklist, evidence links/screenshots, limitations and Deferred list. Verify CI and signed Vercel preview. Do not merge; in particular no site/pipeline merge 2026-11-16 08:00–16:00 Beijing.

## Review focus

Column reversal (NBS tables publish MoM before YoY); food vs food/tobacco/alcohol; transport fuel vs broad energy; missing core MoM; duplicate/conflicting rows; PMI tables contain multiple months; gaps must break chart lines; prior means previous calendar month; same-period composite; stable archived vintage availability; no manufactured history.

## Execution evidence

- Small-batch runner archive capture: 42662050695. Imported 144 releases / 1,008 new observations / 21 new metrics with 48 published months each; no interpolation or parser errors. Existing longer histories retained. Six temporary result branches and diagnostic workflows/scripts removed after use.
- Current NBS CPI table revealed the 2026 transport fuel-to-energy classification change. Exact labels, observation limitations, chart breaks and comparable percentile segments record it.
- Independent review found and verified fixes for same-source legacy revision capture and a missing-January classification-break path. A real combined-store build additionally caught timestamp precision incompatibility; new captures now use the existing second-precision ISO convention, with a regression test.
- Real-data browser acceptance: both locales, 1440/390 px, no page overflow or browser errors; range switches, metric details and CSV/XLSX routes verified. Screenshots and reports live in `docs/design/prices/`.
- Public evaluation: E1–E5 pass; only pre-existing E0 warnings remain. Full-suite results are recorded in the PR checks.
