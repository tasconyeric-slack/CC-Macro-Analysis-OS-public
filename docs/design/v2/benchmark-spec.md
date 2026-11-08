# V2 reference benchmark

Captured 2026-11-08 with Playwright Chromium (desktop 1440×900; mobile 390×844, DPR 2). Full-page, hover and focus states accompany the viewport captures in `reference/guojin` and `reference/cmm`. Computed styles are in `measurements.json`; request status/MIME/latency in `har-summary.json`. REA CDP inspection exports retain evidence IDs, script/resource inventory, accessibility coverage and limitations. No FinLens reference was accessed.

| Token / geometry | Guojin observed | CMM observed | CC Macro choice |
|---|---|---|---|
| Container at 1440 | 1354px columns, 1313px hero inner | 1088px | 1232px usable (1280 incl. 24px insets) |
| Header | 61px, navy | 34px live strip + 88px masthead + 50px nav | Single sticky 68px navy header |
| Hero | 534px; navy, gold emphasis | Navy briefing band below research card | Research question + existing current view; no promotional section |
| H1 | 54px, 800, 1.2 line-height | Newsreader editorial serif | 40px desktop / 29px mobile sans for Chinese |
| Section heading | 30px, 800 | 21px serif with navy rule | 26px, 750 |
| Card heading | 21px, 800 | 20px editorial serif | 22px sans |
| Body | 16px, 1.6 | 16px, 1.55 | 15px; 14px inside cards |
| Palette | #0b2545 navy, blue and gold | #14233a ink, #fbfaf7 background | #0b2545, #235da4, #e7c46a, #f4f7fb, white |
| Columns | Four cards on desktop, one on phone | Briefing + sidebar | Three cards; two below 800px; one below 520px |
| Card anatomy | Column no., frequency, English kicker, title, description, chips, CTA | Research card and KPI strip | Adopt complete Guojin anatomy; computed series count and release date |

## Inventory and interactions

**Adopt:** the three grouped entry points, source legend, clear typography hierarchy, navy brand/navigation, frequency chips and clickable card surface. Header active state, keyboard focus and card hover are captured. CC Macro's mobile menu works with an accessible expanded-state button and Escape; all links remain visible without JavaScript.

**Adapt:** Current View remains before the portal; the probability retains its discretionary-judgment label. What Changed uses real refresh records and an explicit absence of post-baseline analyst review. Seven data categories replace the reference's eighteen columns. Hypotheses, evidence and audit remain accessible below. Existing language switch keeps fragments.

**Skip:** broker reports, forecasts/consensus, decorative KPI counts, the references' branding, generated market narrative and downloadable research that CC Macro does not actually have. CMM loads Chart.js 4.4.3, SheetJS and ExcelJS as observed in the HAR; CC Macro retains its existing deterministic SVG charts rather than adding these runtime dependencies. Reference network captures are a finite observation, not proof of a complete endpoint inventory.

## Focused visual check

`portal-desktop.png`, `portal-mobile.png`, `portal-mobile-menu.png` and `portal-en.png` show the implemented shell. At 1440 and 390px there is no horizontal overflow; the five primary targets resolve; mobile menu expansion works. The shared hero preserves the source-bound analyst text rather than copying promotional copy. Final combined page comparison and the program's one material correction pass belong to #13 after Daily/Data/Policy integration. Own captures are a review baseline, never a competitor pixel-match target.

The `portal-comparison-desktop.png` and `portal-comparison-mobile.png` pairs put the Guojin capture beside the portal. Guojin has no mobile menu button; CMM uses in-page tabs and had horizontal overflow at this viewport. REA bundle analysis retained one captured CMM source as unavailable, so its endpoint inventory is explicitly incomplete; the HAR's observed Chart.js/SheetJS/ExcelJS resources are the usable vendor evidence. Do not infer absent routes from the zero static candidates.

Only trimmed HAR summaries are retained. REA summary exports omit generated script/resource identity fields; their historical `script_key`/`resource_key` values are prefix plus SHA256, independently verified as content identities, not credentials. Six exact historical Gitleaks fingerprints are documented in `.gitleaksignore`; the general history scan remains enabled.

## Shared implementation contract

`site/portal.py` defines the seven category IDs and returns localized `portal.categories` with title, kicker, description, actual public metric count, latest release and destination. `build_model` exposes public point-in-time `observations` and `release_calendar` for the downstream Daily/Data modules. `base.html` provides `head` and `scripts` extension blocks. `_macros.html` provides section_header, column_card, kpi_tile, source_line, tier_badge, empty_state and chart_frame. All original research URLs and fragments remain intact.
