# V2 public data portal — Issue #12

Phase/Gate: Owner-authorized V2 Public News & Official Data, Stage 2 / #12, feeding the #13 production acceptance gate. §15.2: (1) yes, readers can see sourced changes rather than opaque test IDs; (2) yes, seven usable data journeys with actual observations; (3) no AI is necessary, all values and differences are deterministic; (4) yes, the existing charts lack the category/metric-detail journey identified in the V2 review; (5) yes, this is an explicit V2 deliverable. The blocked reader action is comparing a release with its history and inspecting its original source and revisions.

## Delivered slice

- Metric membership lives only in `metrics.yaml` (`category`); public metrics without a valid category fail the site build. Seven category routes remain shared with the portal.
- Public latest-vintage series are emitted as static JSON. Public CSV contains all captured vintages; the model retains raw public history separately from its point-in-time collapsed observations. Private, unclear and supplemental series are excluded from all exports.
- Category pages show latest facts, exact prior-period/prior-year differences, release/retrieval metadata, source links, evidence-test links and expandable definitions/vintage history. Missing periods produce no comparison, and missing release dates remain unknown.
- Existing SVG charts supply all/2Y/5Y ranges, tooltips and a narrow viewport variant. Charts work without JavaScript; JavaScript only switches pre-rendered ranges. No browser API fetch, new chart dependency or service.
- The implied GDP deflator uses the existing `Deriver` formula with input references. Fiscal revenue without observations remains an explicit gap. Original English caliber notes are identified as such.

## Live provenance

The development baseline includes the actual November 9 CPI/PPI refresh record `2026-11-09T0223Z.json`, added by verified bot commit `5ebff7a1615a1da4217d26ffd1341fe0b4e74cde`. Those six October facts are displayed from the store, not typed into templates. No analyst decision, probability, frozen research artifact or historical refresh record was changed.

## Acceptance and remaining work

Focused tests compare every emitted raw series and CSV with the public observation store, check derived lineage, require all seven chart/detail routes, enforce the public boundary, preserve revisions and exercise missing-period comparisons. Initial desktop/mobile captures accompany this change; #13 owns the single combined visual correction pass and production journeys. No site/pipeline merge occurs before the November 9 07:30 UTC blackout ends; #9 must merge before #12.

Deferred: no broker forecasts, licensed high-frequency/rate dashboard, or analyst-signed research update is created. The 28 dictionary metrics include one explicit no-data gap; headline manufacturing PMI is added by #10, independently of this portal implementation.
