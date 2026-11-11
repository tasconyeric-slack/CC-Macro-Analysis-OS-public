# ExecPlan: optional DeepSeek enrichment for News (issue #34)

**Phase / Gate.** V2 Product Build, Public News and Official Data (`docs/PRODUCT_STRATEGY.md` section 0, "News 可选模型增强", authorised by the Owner on 2026-11-09). It does not advance a Proof Gate (G-A/G-B/G-C) and does not touch Phase A copilot work.

**Prioritization Rule (section 15.2).**
1. Does it materially help users understand What Changed and Why? **Yes**: English readers get a readable headline and a one-line reason for each selected China-macro event; today the English site shows Chinese-only headlines.
2. Does it produce a new live proof, user outcome or evaluation data point? **Yes**: every run records calls, cache hits, tokens, cost estimate and rejection reasons, so validator quality and spend become measurable.
3. Is AI genuinely necessary? **Yes for translation and explanation**, which deterministic code cannot do; **no for everything else**, so the layer is optional, bounded, validated by code, and the deterministic path never depends on it.
4. Does it come from an observed failure? **Partly**: the Owner observed the Chinese-only English News pages; no replay failure involved.
5. Would skipping it for two weeks weaken the current deliverable? **No**. Answers 1-3 are yes, so the rule is met (at least 2).

**Blocked product behaviour without it:** the English News, Overview and daily-edition pages can only show untranslated Chinese headlines.

**Scope.** `src/cnmacro/news_ai.py` (new), small hooks in `news_rank.py` and `site/news_feed.py` plus three templates, `news.yml` env and a `dry_run` input, `docs/runbooks/news-ai.md`, `tests/test_news_ai.py`. `DeepSeekClient` gains an optional `thinking="disabled"` argument; the Copilot's Run Record shape is unchanged.

**Frozen, untouched:** preregistration, amendments, update/refresh history, `mechanical_delta`, `docs/PRODUCT_STRATEGY.md`, closed daily editions.

**Verification.** Offline tests (fake transport) cover switch-off, switch-on, cache hit, API failure, display off, closed edition. One Actions dry run with the key absent must be green with zero calls. One live run is gated on the Owner setting the secret and `NEWS_AI_ENABLED=true`.

**Deferred (not done here).** Enriching the "All updates" feed rows; pruning `ai_cache.json` if it grows large; a Chinese-side glossary beyond the starter entities; Chat Completions endpoint (the shared client uses DeepSeek's documented Anthropic-format endpoint, same models and prices); evaluating translation quality against a labelled sample.
