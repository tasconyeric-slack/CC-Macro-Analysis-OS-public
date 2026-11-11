# News AI enrichment: the two Owner switches

Optional layer on top of the hourly News run (`.github/workflows/news.yml`). DeepSeek writes an English headline and a one-sentence
"Why it matters" (Chinese and English) for the selected events and the open daily edition. It reads only the item's own title,
summary (up to 220 characters), publisher, release time and URL. It never browses, never touches fact ingestion, ranking, the
research case, the preregistration or any analyst judgment. **It is off until you turn it on, and you can turn it off at any time
without a code change.**

## Where to click

Repository **Settings → Secrets and variables → Actions**.

| What | Tab | Name | Value |
|---|---|---|---|
| Key | **Secrets** → New repository secret | `DEEPSEEK_API_KEY` | your DeepSeek API key (only the News collect step can read it) |
| Switch 1 | **Variables** → New repository variable | `NEWS_AI_ENABLED` | `true` to allow model calls. **Anything else, or unset, means zero calls.** |
| Switch 2 | **Variables** → New repository variable | `NEWS_AI_DISPLAY_ENABLED` | `true` to show model text on the site, `false` to hide it. Unset means "same as `NEWS_AI_ENABLED`". |
| Optional | **Variables** | `NEWS_AI_MODEL` | defaults to `deepseek-flash`; the other accepted value is `deepseek-v4-pro` |
| Optional | **Variables** | `NEWS_AI_MAX_ITEMS` | most items sent per run, default `12` (hard ceiling 60) |

The comparison is exact and case-sensitive: `true` turns a switch on; `True`, `TRUE`, `1`, `yes` and ` true` (with a space) do not.
That is deliberate, so a typo can never turn spending on.

## What each switch does

| `NEWS_AI_ENABLED` | `NEWS_AI_DISPLAY_ENABLED` | New API calls | Model text on the site |
|---|---|---|---|
| unset / not `true` | unset | none | hidden (the default) |
| `true` | unset | yes | shown |
| `true` | `false` | yes (cache keeps filling) | **hidden** |
| `false` | `true` | none | shown from what is already cached |
| `false` | `false` | none | hidden |

- **Stop all spending:** set `NEWS_AI_ENABLED` to `false` (or delete it, or delete the secret). No HTTP request is made.
- **Stop showing model text, keep or stop spending:** set `NEWS_AI_DISPLAY_ENABLED` to `false`. The next run writes
  `"ai_display": false` into `data/news/latest.json`, the site renders nothing from the model, and new model text is no longer
  copied into `latest.json` or the open edition. Pages fall back to the original Chinese headline.
- Both switches need no code change and no new deploy of your own.

## How fast it takes effect

1. The switches are read at the start of each News run. Runs happen **every hour at :15**. For an immediate effect open
   **Actions → public macro news → Run workflow** (leave "dry_run" unticked).
2. The run commits the refreshed `data/news/*.json` (including `ai_display`); the normal site deploy then publishes it. Budget the
   deploy time (a few minutes) on top of the run. So: **worst case about one hour plus a deploy, or a few minutes if you run the workflow by hand.**
3. Closed daily editions are never rewritten. If an edition closed while display was on, its JSON keeps the model text it was
   closed with, but the site still hides it while `ai_display` is `false`, because the page checks the switch, not the edition.
4. The cache file `data/news/ai_cache.json` is public like the rest of `data/news/`. It holds model text for later display; the
   display switch controls what pages render, not what the cache file contains.

## Safety properties (what the code guarantees)

- Zero HTTP calls unless `NEWS_AI_ENABLED` is exactly `true` **and** `DEEPSEEK_API_KEY` is set. With either missing, the run is the same
  deterministic pipeline as before and the Copilot client is not even imported.
- The key is only read from the environment by the shared client (`cnmacro.copilot.llm`). It is never logged, written to a file, put in
  `latest.json`, or sent to a browser. Provider errors are redacted by that client before they are recorded.
- **Fail open.** Network error, HTTP error, quota, refusal, truncated or unparseable reply: the first failure stops further calls
  that run, the run still collects, ranks, publishes editions and builds the site, with the original Chinese headlines.
- **Validated output only.** The model must return JSON `{title_en, why_zh, why_en}`. Each field is checked separately and dropped
  (never "fixed") if it contains a number, date or name that is not in the item, converts a unit wrongly (`100亿` is 10 billion, not 100 billion),
  uses investment-advice or probability wording, is in the wrong language, or is too long. A missing field is simply not shown.
  The official `title_zh` is never replaced or edited.
- **Cached.** Key = item id + hash of the exact input + prompt version + model. Unchanged content never triggers a new call, including
  content whose reply was fully rejected. Changing `NEWS_AI_MODEL` or the prompt version re-enriches once.
- **Bounded.** At most `NEWS_AI_MAX_ITEMS` items per run, sent in batches of 4; only selected events active in the last 72 hours; the open
  edition's events first.
- Not checked by code: causal claims or tone in the generated sentence. The readers see an **AI** label with a note on every explanation
  and the original Chinese headline in the headline's tooltip. Treat the validator as a guard rail, not a fact-checker.

## What a run reports

Every run writes a usage record into `data/news/latest.json` under `"ai"` and prints a `news_ai ...` line (plus up to three samples)
in the **Collect public macro reporting** step log (example shape, not a measurement):

```
news_ai enabled=True display=True model=deepseek-flash status=ok candidates=14 cache_hits=9 calls=2 items_enriched=5 items_rejected=0 input_tokens=1480 output_tokens=610 estimated_cost_usd=0.001176 errors=none
```

`estimated_cost_usd` is an **upper bound** from DeepSeek's published peak-hour, cache-miss list price
(`deepseek-flash`: $0.30 per 1M input, $1.20 per 1M output; checked 2026-11-09 at
<https://api-docs.deepseek.com/quick_start/pricing/>). Real billing is usually lower (off-peak is half, cache hits are cheaper).
Rough ceiling at defaults: 12 items per run, 3 requests of about 700 input and 400 output tokens, about $0.002 per run, a few cents a day even if every
run found 12 new items; with the cache it is normally far less. Check the DeepSeek console for actual spend.

`rejections` counts why fields were dropped (`number`, `date`, `name`, `advice`, `language`, `length`, `markup`, `type`, `missing`).
A steady stream of `name` rejections usually means the glossary in `src/cnmacro/news_ai.py` needs another entity.

## Testing without spending

- `python -m pytest tests/test_news_ai.py` uses a fake transport; no network, no key.
- **Dry run in Actions:** *Actions → public macro news → Run workflow → tick `dry_run`*. It collects and runs the AI step with whatever
  switches and key are configured, prints the usage line and samples in the log, and **publishes nothing**. With the key absent it must finish green
  with `calls=0`.
