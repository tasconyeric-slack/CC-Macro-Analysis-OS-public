# Research Journal — design specification (implemented in Phase B, not in Phase A)

Status: **design only.** Authority: `docs/PRODUCT_STRATEGY.md` §13.3, §8.6, §14 (Phase B), D-03. Owner decision: the Release Updates navigation and presentation evolve into **Research Journal** (English) and **研究追踪** (Chinese). Phase B builds it from the real 2026-10-14 and 2026-10-19 records, not from placeholder content.

## 1. Purpose

Show how an analyst's judgment evolves as evidence arrives, so a reader sees *what changed, what the AI thought, what the analyst did, and what remains open*, without reading technical documents. It is not a changelog and not a feed of automatic refreshes.

Non-goals: no new data store, no homepage redesign in Phase A, no AI text presented as the accepted view, no edit to the frozen baseline.

## 2. What counts as an entry

| Kind | Source of truth | Shown as |
|---|---|---|
| `baseline` | `preregistered/*-baseline.yaml` (frozen) | The first entry, read-only, labelled "Preregistered baseline". Its wording is never improved; better wording lives in the presentation layer. |
| `update` (thesis changed) | `updates/*.yaml` with a `probability_change` | A full entry with before/after. |
| `update` (explicitly unchanged) | `updates/*.yaml`, `probability_change: null`, `does_this_change_the_thesis` | A full entry. "No material change" is a first-class entry (strategy P7). |
| automatic refresh | `refreshes/*.json` | **Not an entry.** Counted in one collapsed line ("N automatic data refreshes since the last analyst entry") linking to Method → Automatic refresh. |

An entry exists only when the analyst published an update. Until then the page for that release shows the deterministic facts and the text "Analyst update pending", never the Copilot's conclusions.

## 3. Reader journey (the ten blocks, in order)

| # | Block | Built from | Rule |
|---|---|---|---|
| 1 | **Research event** | calendar entry (name, release time, period) | One line and a link to the source release. |
| 2 | **Pre-release expectation** | frozen Expectation Note | Shown only if it passed the "committed once, before the release" test; otherwise "No expectation was frozen" (never backfilled). Outcome shown as inside / above / below, computed by code. |
| 3 | **What changed** | refresh record: new observations, flipped tests, marginal changes | Validated facts only; every number is a bound reference (claims rules). |
| 4 | **AI interpretation** | Run Record `rendered`: executive delta, hypothesis impact | Only sections the analyst accepted or edited (edited text replaces the AI text). Rejected sections are not shown. Labelled "AI interpretation, reviewed by the analyst". |
| 5 | **Divergence** | hypothesis rows with `divergence: true` | Each shows mechanical direction, AI direction, reason, and the analyst's verdict (accept / reject / keep). Top of the entry when any exists. |
| 6 | **Strongest counter-case** | `competing_explanation`, `does_not_prove` | Subject to the same accept/edit filter. |
| 7 | **Analyst blind take** | `blind_take` event | Shown once the entry is published, with its commit time (proof it preceded the AI read). If waived: "Blind take waived". |
| 8 | **Analyst decision** | `decision` event + the published update | Accept / Edit / Reject / Keep unresolved per section, with reasons; the explicit statement "thesis unchanged" or "changed". |
| 9 | **Before / after thesis** | update `previous_state` vs new fields | Probability, conviction, status, direction. For the baseline entry: "initial". An unchanged thesis is stated, not omitted. |
| 10 | **Open research questions** | accepted / kept `research_needs` | The question, the hypothesis, what data would answer it. |

Second-level disclosure (collapsed `<details>`, like Technical lineage today): run id, model id and version, prompt / schema / context versions, context hash, evidence allowlist, validation summary (hard-gate counts), the git commit of each file, and `copilot: unavailable | blocked | ok`.

## 4. Rules that protect the record

1. **No unapproved AI text is ever the accepted view.** The builder joins a Run Record to an entry only through a `decision` event; no event, no AI text.
2. **Automatic refresh and analyst update stay visibly different** (strategy §5, README §5): refreshes are facts, entries are judgments.
3. **Bilingual consistency**: the model writes one canonical language (English). Chinese for accepted AI text comes from the constrained translation pass (a Phase B deliverable, deferred from Phase A): placeholders unchanged and the same period set, checked with `claims.PLACEHOLDER` / `claims.period_tokens` (eval E1). Analyst-edited text must be supplied in both languages, as `does_this_change_the_thesis_zh` is today; a missing Chinese text falls back to English, marked `lang="en"`, and the build says so (existing behaviour, `tests/test_update_flow.py`).
4. **Public / private boundary**: entries are built only from tracked public artifacts. A Run Record is read only after its decision event exists, and only the rendered text of accepted or edited sections is used; raw model output, prompts and contexts are never published.
5. **Compatibility**: `updates/*.yaml`, `preregistered/*`, `refreshes/*` and `claims.jsonl` keep their schemas; the journal reads them and adds nothing to them. Run Records live in `copilot/runs/` and are only read.

## 5. Navigation, URLs and redirects

* Label change only: `nav.updates` → "Research Journal" / "研究追踪" (`site/i18n/en.yaml`, `zh.yaml`; keys and parity tests unchanged).
* The index stays at `/<locale>/updates.html`, so no existing link, hreflang or `#fragment` breaks. Entry pages are added under `/<locale>/journal/<entry-id>.html` (entry id = update file stem, e.g. `2026-10-14-september-2026-cpi-and-ppi`; the baseline is `baseline`).
* If the index is later renamed to `journal.html`, keep `updates.html` as a redirect stub through the existing legacy-redirect mechanism (`site/templates/legacy.html`), preserving the fragment, and add a test that every old URL still resolves.
* Homepage (Phase B, strategy §13.2 item 2): a "What changed recently" card shows the **latest accepted entry** (headline, divergence if any, before/after, link). Until an entry exists it shows nothing rather than a placeholder.

## 6. Build and checks (Phase B)

* `site/views.py` gains a `journal` model assembled from the artifacts above; `site/build.py` renders `journal.html` templates in both locales.
* Tests: an entry exists only for a published update; a Run Record without a decision never appears; rejected sections are absent; every numeric token in journal prose is a bound reference (extend the E1 presentation lint to journal text); both locales have the same entries and the same placeholders; the baseline entry is byte-faithful to the frozen file; old URLs resolve.
* Implementation order: (1) the entry page for the real 2026-10-14 update, with every block it can fill from real records; (2) the index and the baseline entry; (3) the second real entry (2026-10-19) to expose what the first got wrong; (4) the homepage card; (5) the translation pass. Each step is shippable on its own.

## 7. Open questions for the Owner (none block Phase A)

1. Should the blind take be public with each entry, or only its timestamp? (This spec shows the text, because the strategy's marginal-insight claim is only credible if readers can see it.)
2. Should rejected AI sections be listed as "considered and rejected" in the technical disclosure? (Spec: not shown on the page; present in the Run Record.)
