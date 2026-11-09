# China macro public-source matrix

Issue #3, V2 Stage 1. This is a bounded reachability/shape probe, not a new provider layer. Only NBS RSS, PBOC news and gov.cn policy intake are authorized new product sources in strategy §0; MOF/NDRC below remain diagnostic candidates. FinLens and broker reports are deferred.

## Runner evidence

The existing `source reachability probe` workflow records HTTP status, latency, parsed item count, response hash and up to three source examples. Transport success is distinct from usable content: a WAF/empty/malformed response is not an empty successful intake. Complete official responses are attached as `official-source-probe` diagnostic fixtures; they are not observations or analyst-reviewed events.

[Dispatched runner evidence](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public/actions/runs/42507127955), probed **2026-11-08T17:52:40Z**, completed successfully. Artifact `official-source-probe` contains `probe.json` plus raw responses named by URL hash. Defaults in `refresh.yml` are unchanged because the event probes require `--events`.

| Probe | HTTP | Seconds | Parsed items | Content |
|---|---:|---:|---:|---|
| NBS RSS | 200 | 17.3 | 500 | RSS, 4,509,166 bytes; latest sampled publication 2026-11-04 09:30 Beijing |
| PBOC news | 200 | 0.6 | 15 | Article URLs contain valid Beijing timestamps |
| gov.cn monetary query | 200 | 1.6 | 80 | Four `catMap` categories; counts reflect returned rows, not unique events |
| gov.cn fiscal query | 200 | 1.2 | 80 | Four `catMap` categories; overlapping republications need grouping |
| MOF fiscal list | 200 | 1.8 | 21 | Dated document links go to `gks.mof.gov.cn` |
| NDRC press releases | 200 | 0.7 | 25 | Dated document links, latest sampled date 2026-11-06 |
| NBS November agenda | 200 | 0.8 | 11 | Confirms Nov 9 CPI/PPI 09:30, Nov 16 activity 10:00, Nov 27 profits 09:30, Nov 30 PMI 09:30 Beijing |
| NBS PMI metadata | 200 | 0.8 | 14 | Headline indicator `_id=a09aa989bdcf4cffa2021795722eb916` in catalog `93ffbb1aa85740d3aa2618371508b606` |

The first dispatched run ([42506786975](https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public/actions/runs/42506786975)) exposed three probe assumptions: the RSS exceeded a 4 MB read cap; gov.cn uses category lists rather than `result` for the short query; MOF links cross to its fiscal subdomain. After adapting these measured shapes, the table above reports usable content for all eight diagnostics. This proves reachability/parsing at that instant, not future availability or analyst approval. gov.cn's `totalCount=0` is not a reliable empty-result signal for the observed categorized response.

November agenda response SHA-256: `ba9e896b9ac978f7b898087ffe00b57ee6de8d6b2662daf37fd93d1973628a91`; PMI metadata: `d56a279a859fe9e43647859ad8bbdd881326745d88c0b8954992457116fc0e87`. Complete source hashes and sample title/date/URL tuples are in `probe.json`.

| Source | Format and stable item identity | Publication/time rule | Revision and cadence | Research relevance / tier | Scope |
|---|---|---|---|---|---|
| [NBS latest releases](https://www.stats.gov.cn/sj/zxfb/rss.xml) | RSS `channel/item`, `guid` plus canonical link | `pubDate`; preserve explicit offset, otherwise Asia/Shanghai; missing date quarantined | Repeated URL/hash is idempotent; changed body at same URL is a new revision, never replace original; release-driven | H1 prices, H2 activity, H4 trade when present; EVENT, linked `obs:` remain FACT | MVP |
| [PBOC news](https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html) | HTML article link; canonical detail URL | Valid 14-digit `YYYYMMDDHHMMSS` prefix in detail URL is Beijing time; date-only list remains date precision if prefix absent | Scan retained list/backfill rather than last-24h cutoff; source content hash versions revisions; irregular | H2 credit and demand; H3 monetary impulse; EVENT | MVP |
| [gov.cn monetary policy search](https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary&q=%E8%B4%A7%E5%B8%81%E6%94%BF%E7%AD%96) / [fiscal search](https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary&q=%E8%B4%A2%E6%94%BF) | JSON `searchVO.catMap.<category>.listVO[]` observed, `result[]` on alternate queries; canonical `url`, document number if explicitly printed; `puborg` identifies publisher | Observed `pubtime` epoch milliseconds plus `pubtimeStr` display date; preserve both and date precision, do not invent exact midnight | Query results overlap; identity is document URL/hash, not result position; irregular, indexed with delay | H3 fiscal/credit, H2 demand; EVENT | MVP if usable; explicit source failure otherwise |
| [MOF fiscal revenue/spending](https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/quanguocaizhengshouzhiqingkuang/) | HTML dated article URLs | Document/list date, Asia/Shanghai, date precision until detail verifies time | Monthly fiscal release; same URL revisions retained separately | H3 fiscal transmission; EVENT; existing official fiscal observations remain FACT | Probe only; no new route here |
| [NDRC press releases](https://www.ndrc.gov.cn/xwdt/xwfb/) | HTML dated article URLs | Detail/list date, Asia/Shanghai; no trustworthy date means quarantine | Irregular; duplicate links and reposts common | H0 supply discipline, H2 demand, H3 investment impulse; EVENT | Probe only; no new route here |
| [NBS November agenda](https://data.stats.gov.cn/dg/website/publicrelease/web/external/queryAgendas?startDate=2026/11/01%2000:00:00&endDate=2026/11/30%2023:59:59) | Existing JSON agenda route, date-keyed lists | `fb_time`, Asia/Shanghai; schedule is not proof of a published observation | Re-probe before changing `verified_on`; retain exact response hash | Release timing, not evidence or judgment | Existing route; Stage 0 verification |
| [NBS PMI catalog](https://data.stats.gov.cn/dg/website/publicrelease/web/external/new/queryIndicatorsByCid?cid=93ffbb1aa85740d3aa2618371508b606&dt=&name=) | Existing JSON `data.list`; catalog and indicator IDs | Indicator metadata, no publication-time assertion | Lookup identity before adding headline PMI; never guess ID | Diagnostic PMI for Daily Desk; FACT only after official observation ingestion | Existing route; #10 lookup |

## Common ingestion rules

- Keep original publication, first seen and retrieval times separately. Date-only records explicitly declare precision; no host-local timezone interpretation.
- More than 48 hours between publication and first seen means archived history, never today's news. Backfill is allowed; synthetic history is not.
- An official document is source-verifiable EVENT content, not an analyst-approved JUDGMENT. A verified item can still be irrelevant to the thesis.
- Cross-site republication is one occurrence with both links; an implementation follow-up is a separate event connected to the same story.
- Read failures retain an error and do not advance a cursor beyond unprocessed items.

No Tushare permission expansion, media API, broker scraping, server or database is required.
