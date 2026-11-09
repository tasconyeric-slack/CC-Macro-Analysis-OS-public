# Official intake acceptance (#4)

Phase/Gate: V2 Public News & Official Data, Epic #8 Stage 2. §15.2 answers: (1) Yes, real official announcements make What Changed source-verifiable; (2) Yes, real intake and repeat-run evidence establish live functionality; (3) No, fetching/parsing/time handling need deterministic code; (4) Yes, runner probes exposed RSS size, timezone and response-shape failures; (5) Yes, Policy/Daily source-linked journeys are part of the authorized V2 deliverable. Without this slice, the Policy page cannot collect and distinguish real candidates from reviewed research. Owner authorized implementation from the CI-green portal branch while its merge waits for the release blackout to end; this PR must remain unmerged until 2026-11-09 07:30 UTC and after #9/#3.

Implement one append-only official inbox, explicit source outcomes, conservative time/archive rules, review logs, a static bilingual Policy inbox, and an events-only verified bot writer. No model, evidence-test or analyst-judgment automation. Validate using real NBS/PBOC responses, idempotent repeat ingestion, failure/backfill, review/as-of boundaries, writer allowlists and one build smoke check.

## Real collection evidence

At 2026-11-09T02:37:40Z the first local curl-backed collection captured PBOC15 and gov.cn159 distinct candidate revisions. The full NBS feed exposed one older title containing `R&D`: HTMLParser required `close()` to flush the text; the source failed explicitly rather than reporting an empty success. After that fix, the real 2026-11-09T02:41:41Z retry backfilled all500 NBS items without losing the already-collected PBOC/gov.cn records. A second independent network fetch at02:41:50Z added **zero** items from all four source queries. Raw inbox history contains674 source revisions, folded to663 document URLs; these counts are collection coverage, not research/evaluation success.

The current NBS [October CPI release](https://www.stats.gov.cn/sj/zxfb/202611/t20261109_1965795.html) and [PPI release](https://www.stats.gov.cn/sj/zxfb/202611/t20261109_1965794.html) carry RSS Beijing times09:30:02 and09:30:01 respectively (calendar09:30). The two technical source-verification reviews are appended separately; no item is analyst-approved and no probability/thesis/evidence judgment is changed. Earlier PBOC/gov.cn materials remain archived because they were first seen more than48hours after publication.

`tests/fixtures/events/provenance.json` records URLs, retrieval times, hashes and exact fixture trimming. The NBS fixture contains five unedited real item nodes including the current CPI/PPI pair; PBOC is the complete real listing; gov.cn retains two actual result rows per category from runner42507127955.

Validation:19 targeted intake/i18n tests pass; the immutable-file comparison passes after merging the current main refresh; the public static build completes48 routes. Tests cover source time, large/oversized RSS, explicit error/backfill, repeat-run idempotency, date quarantine, review/as-of separation, replay isolation and events-only append-only writer boundaries. Full engine/eval gates and the preview are checked by PR CI. The production events workflow can be exercised only after the new workflow is merged outside the release blackout.

No FinLens work, history rewrite or changes to Owner-only strategy.
