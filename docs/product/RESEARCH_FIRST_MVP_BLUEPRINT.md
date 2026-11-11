# CC Macro — Research-First MVP Product Blueprint

**Date:** 2026-11-10  
**Status:** Owner-directed product proposal; implement after the related strategy amendment is merged.  
**Repository:** `tasconyeric-slack/CC-Macro-Analysis-OS-public`  
**Design authority:** `docs/design/README.md` + `docs/design/masonry-red/tokens.json`  
**Research authority:** existing preregistration, evidence, `as_of`, analyst-signature and public/private contracts. This blueprint does not rewrite those contracts.

## 1. Product promise and audience

**Promise:** China macro research that continuously absorbs data, news, policy and events; explains **what changed, why it matters, whether it changes the research view, and what to watch next**. Not a news leaderboard or a generic AI-written market commentary site.

**Primary user:** macro/strategy and China-facing equity researchers, plus rigorous independent investors. In 30 seconds the user should know the current view; in five minutes they should understand its leading evidence and counter-evidence; in deeper reading they can inspect chart history, sources and revisions.

**User journey:** Open homepage → see the latest dated research conclusion → open Weekly/Monthly → inspect 3–5 consequential charts and arguments → follow evidence to official observations or cited policy/event records → see what can overturn the view.

**Core research question remains unchanged for the MVP:** whether China's nominal growth is entering a sustainable inflection. Reuse H0–H4 and current research artifacts. Do not create new theses or change preregistered judgments to populate a page.

## 2. Information hierarchy and routes

Primary navigation: **Overview · Research · Data**. Research is the center of the experience, not News.

- **Overview** (`/zh/`, `/en/`): current *signed* research stance, "what has materially changed", latest published Weekly/Monthly, 3–5 annotated research charts, upcoming confirmation/falsification markers, and evidence links.
- **Research** (existing `memo.html` and/or a lightweight new index if it clearly improves the journey): Weekly, Monthly, deep dives (only if real), and the signed thesis-update chronology. Do not duplicate whole reports across pages.
- **Data** (existing data portal + detail pages): first-class chart exploration, exact metric definitions/periods/releases, and paths back to the research question.
- **Evidence & events** (secondary links within Research/Data and footer): official publications, curated policy/event timeline, underlying news feed/archive, full source citations, updates, and method. Keep existing URLs operational; remove nothing from collection/storage. Existing News/Daily pages can remain accessible as a secondary research library but **must not** dominate the homepage or primary navigation.
- Institutional Views / FinLens / broker consensus is **deferred** until the Owner explicitly approves a reliable and permitted provider.

Use current bilingual architecture, Masonry Red tokens and static-site routing. No blank “coming soon” feature tiles or synthetic previews in production.

## 3. Publication policy — continuous intake, low-frequency public research

| Workflow | Cadence | User-visible output | Authority |
| --- | --- | --- | --- |
| Public data, news, event, policy intake | Existing scheduled frequencies, including hourly news as already configured | Source library, topical evidence, dated metadata; only selective highlighted events on homepage | Machine may ingest and classify, never sign a thesis |
| **Macro Weekly** | Once per completed China-time calendar week, subject to meaningful real evidence | Short research synthesis: thesis in one paragraph, 3 material changes, 3–5 explanatory charts, one counterargument, watch next | Draft generated automatically; research judgments require analyst approval |
| **Macro Monthly** | Once per completed calendar month | Deeper synthesis of activity, prices, credit, property, policy transmission and markets where data actually exists; scenario/watchlist and thesis comparison | Draft generated automatically; research judgments require analyst approval |
| **Thesis Update** | Event-driven, when new evidence materially affects an existing hypothesis; “unchanged” is valid | Signed dated decision record and before/after state | Explicit analyst Approve/Edit/Reject; no backdated signature |
| **Deep Dive** | Only when a real research question justifies it | Focused thematic memo | Explicit analyst review |

Do not mandate a daily public research report or auto-publish LLM's views. A major release enters the evidence store promptly even if the next user-facing synthesis is weekly. Critical thesis changes may be published as separately signed updates rather than waiting for the next report.

Weekly and monthly periods are Beijing time. A scheduled run may generate a **draft**, but no cron task can impersonate a human sign-off. If there is no new material evidence, explicitly state that rather than force three changes.

## 4. Research report contract (reuse before extending)

An edition needs at minimum:
- `edition_id`, `edition_type` (weekly/monthly), `period_start`, `period_end`, `as_of`, `generated_at`, `review_status` (draft/approved/rejected), `approved_at` and actual signer **only when approved**.
- A concise thesis takeaway; signed state when available; **do not conflate automated evidence with analyst judgment**.
- **What changed:** factual releases, policy/events, measured comparison with prior point/date, why each matters to H0–H4; link each to observation/source/event IDs and availability timestamps.
- **Key charts:** 3–5 (fewer if credible charts unavailable), each with a question-style title, exact unit/period, real data and a conclusion; never decorative chart cards.
- **Drivers and cross-checks**, **supporting evidence**, **counter-evidence/competing explanation**, **thesis delta or no-change**, **what to watch next**, with release calendar when reliable.
- **Asset implications** only when grounded in available market evidence; otherwise mark the inference and omit unsupported numerical claims.
- Linkable bibliography with primary-source URLs and `as_of`/retrieval provenance; bilingual rendering from the same research state.

MVP output may reuse existing YAML/JSON/Markdown and Jinja2 pages. Avoid a generic CMS or new database. Numeric values are computed by deterministic code and rendered via existing grounded placeholders/claim contracts, never fabricated by a language model. LLM summaries remain drafts until approved.

## 5. Data/news/policy → research evidence chain

```text
official data / releases + credible media + first-party policy text
  → normalize metadata (source, URL, published_at, retrieved_at, release period)
  → dedupe/group by real occurrence (NOT popularity)
  → tag growth/inflation/credit/property/policy/markets and hypothesis/economic mechanism
  → triage: irrelevant | monitor | research_needed with evidence and reason
  → identify actual observation change / policy-stage change / contradicting explanation
  → build candidate evidence bundle for Weekly/Monthly or Thesis Update
  → deterministic chart/data validation + bounded AI narrative draft
  → analyst Approve/Edit/Reject for judgment
  → publish one source-grounded research artifact + links back to evidence
```

Reuse `news.yml`, `data/news`, the existing official event intake, `data/events`, event dedup and H0–H4 linkage, and refresh records. News heat/coverage may help discovery but **never** substitute for economic importance or evidence quality. Headlines do not automatically become facts or thesis changes. An unsupported source is a lead for research, not verified evidence.

No portal, commercial consensus feed, Wind/private values or new paid API dependency is necessary to deliver this MVP. PR #37 market data is optional enrichment and must be integrated only after it passes its own gates; it is not a prerequisite.

## 6. Reader-first presentation (Masonry Red)

Overview above-the-fold: **current research conclusion with signed/as-of label**, latest report CTA, and 2–3 materially important developments. A follow-on section shows 3–5 key charts with interpretation, followed by Weekly/Monthly cards, watch-next items and evidence paths. Source/audit/method belongs in deeper reading, never a screenful of compliance banners.

Research page: compact edition index (Weekly/Monthly), readable article typography, meaningful subheads, side/inline evidence links, charts near the argument, concise document metadata. Do not reintroduce a visual news hot list.

Data page: preserve genuine time series and categories, prioritize question-led captions. No color/spacing inventions; the canonical Masonry Red file defines tokens.

Keep existing deep links (`news.html`, `daily.html`, `policy.html`, `evidence.html`, `updates.html`) resolvable. A navigation change is not a crawler deletion.

## 7. MVP vertical slice and DoD

One end-to-end *real-data* Weekly draft and one Monthly draft from already available historical/current artifacts; source grounded and clearly draft until the analyst actually approves. At least one signed real Thesis Update can appear **only after** authentic approval (#52); never backfill a fictitious historic approval.

Definition of done:
1. Ingested real data/events/policy information is traceable to source and at least one useful, hypothesis-linked research input is demonstrated.
2. Weekly/Monthly render meaningful factual summaries, key charts, a nontrivial explanation/counter-evidence and watch-next. If no signed conclusion exists, show the real latest signed prior view and a factual draft/pending state.
3. Homepage is research-first; bilingual desktop/mobile preview works and existing data, News and Policy URLs remain usable.
4. One focused research chain test + build + live Vercel preview check; existing safety and E0–E5/verified-commit gates are preserved.
5. Report the actual live outputs, what was not yet approved, and remaining genuine blockers. No vanity audit, new workflow platform or excessive verification loop.

## 8. Work packages and ownership (one issue = one worker)

- **Claude Code / existing #52**: `release → evidence → analyst draft → explicit approve/edit/reject → signed thesis update`. Owner owns the approval, never Agent. Work in `claude/*` branch; leave existing `mechanical_delta` intact.
- **Claude Code / research input issue**: map and prioritize already-ingested news/policy/event records into research-ready evidence bundles; reuse #4/#5/#27 outputs, not a new crawler. Separate branch and PR.
- **Codex / report issue**: Weekly/Monthly structured report builder and bilingual research article templates; coordinate the signed-state contract with #52 but do not implement signing yourself.
- **Codex / presentation issue**: research-first homepage/navigation, edition index and evidence deep links; start integration after report contract exists; do not edit ingestion and thesis code.

No two workers may change the same shared file concurrently; coordinate `site/build.py`, `site/templates/base.html`, `site/i18n/*` in the integration wave. Maintain `codex/*`/`claude/*` branches with separate PRs into `main`. Verified GitHub commits and Vercel PREVIEW READY follow `AGENTS.md`.

## 9. Explicitly deferred

Institutional research / FinLens and forecasts; high-frequency homepage news leaderboard; independent daily editorial production; general-purpose RAG/vector DB; server-side CMS; account/login; multi-agent orchestration; big redesign beyond research navigation; new paid sources; auto-signed reports; automatic probability/conviction changes.

**Operating principle:** identify the user question → agree an editorial/product blueprint → deliver the thinnest real end-to-end research slice → validate one critical path → iterate from evidence. Product quality is measured by decision usefulness, not number of features/PRs.
