# Public macro news sources (#27)

Owner-authorized V2.1 public reporting slice. Actual fetches on 2026-11-09 are stored with per-source retrieval time, response hash, source URL and item publication dates in `data/news/latest.json`.

| Family | Actual endpoint | Successful macro items | Limitation |
|---|---|---:|---|
| NDRC | https://www.ndrc.gov.cn/xwdt/xwfb/ | 11 | Official dated list; headlines are retained as source excerpts. Latest captured item is November 6. |
| MOF | https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/quanguocaizhengshouzhiqingkuang/ | 21 | Monthly fiscal releases; latest is the October 23 release for the first three quarters. List date wins over the date embedded in a document URL. |
| Wallstreetcn | https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=100 | 6 | Public short reporting flashes, filtered for China macro relevance; market-price tickers and undated/future items are excluded. Reporting is not an official observation. |

The exact counts and timestamps are snapshot evidence, not a promise of future availability. BBC/FT Chinese feeds timed out, China Daily's old RSS URL returned HTML and SAFE's tested listing returned a block page; these are excluded rather than called successful sources. The feed retains last valid items on upstream failures and records failure in maintenance output.

AIHOT reuse: MIT-licensed [source normalization](https://github.com/KKKKhazix/AIHOT/blob/main/packages/backend/src/sources/json-list.ts) (blob `c64cea84ba6ecfabf562bf5975b5cf680c668591`) and [relation definitions](https://github.com/KKKKhazix/AIHOT/blob/main/industry/prompts/group-definitions.md) (blob `b978478e8fb8d92913e6a7f08e2da7d8f44565b5`) informed the narrow adapters: dated item first, canonical URL identity, same occurrence distinct from follow-up and roundup. No upstream application code, name or logo is copied; existing #4/#5 official collectors/grouped-public reader are reused.

A live repeated-report sample is the November 9 October CPI release: NBS's official headline and Wallstreetcn's core-CPI report share a single release occurrence. A combined CPI/PPI roundup stays separate; an announcement and implementation follow-up stay separate. Source-backed excerpts carry the reporting content. “What to watch” is a deterministic topic question linked to existing indicators, not an invented causal conclusion or an analyst-approved thesis change.

Integration API: `from news_feed import news_context`; set `ctx['macro_news']=news_context(model,loc)` for home/daily; include `news-feed.html`; load `news-feed.css` and `news-feed.js`. The partial serves five developments on home, forty sortable/filterable headlines on Daily and an eight-item reading digest. Native page content works without JavaScript. The new hourly `news.yml` writes only the single public-news snapshot through the existing verified GitHub publisher. It does not touch observations, thesis, preregistration or FinLens.
