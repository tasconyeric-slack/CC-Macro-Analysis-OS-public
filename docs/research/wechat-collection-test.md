# Zero-cost WeChat collection test (2026-11-09)

Question: can broker macro-team WeChat articles be collected for free, without a paid API or a persistent crawler, to feed Radar (#11)?

Method: `scripts/probe_news_sources.py` on a GitHub-hosted runner (runs 42606946896 onward), five teams: 华泰宏观, 中金宏观, 招商宏观, 广发宏观, 申万宏源宏观.

| Route | Result |
|---|---|
| Sogou WeChat article search (`type=2`) | Reachable, no captcha on the first request; 8–10 results per team with title, account and timestamp |
| Same, with the recency filter (`tsn=1`/`tsn=3`) | 0 results |
| Recency of unfiltered results | Ranked by relevance: mostly 2017–2023; only 申万宏源宏观 returned posts from the last two weeks (2026-10-27, 2026-11-07) |
| Resolving a result link to the article | Redirected to Sogou's anti-spider page; no article URL or body |
| wechat2rss public list | Reachable; no broker macro accounts listed |
| RSSHub public instance (WeChat routes) | HTTP 403 from the runner |

Conclusion: no reliable free route provides recent broker macro articles daily. Radar stays deferred; nothing institutional is shown. Revisit if the Owner supplies a working method (the "bainianAI method" mentioned in the brief was not included with it) or a permitted feed.
