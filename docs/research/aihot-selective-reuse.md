# Selective reuse for official macro events

Issue #3, V2 Stage 1. Reviewed upstream source on 2026-11-08. Reuse concepts and small compatible functions inside the existing Python/static architecture; do not host AIHOT or port its application.

| Concept | Primary upstream reference | CC Macro target | Decision |
|---|---|---|---|
| RSS, HTML listing and JSON listing shapes | [AIHOT sources](https://github.com/KKKKhazix/AIHOT/blob/main/docs/sources.md), `packages/backend/src/sources/{rss,web-list,json-list,listing-fetch}.ts` | `events/intake.py` (#4) | Adapt narrow readers; explicit shape errors and source allowlists. No configurable provider framework. |
| Source timezone and time precision | [AIHOT dates](https://github.com/KKKKhazix/AIHOT/blob/main/packages/backend/src/sources/dates.ts), [macro-news PBOC timestamp example](https://github.com/qweeqw231/macro-news/blob/main/src/pbc-time.mjs) | `events/intake.py` (#4) | Implement in Python from official fields/URL format. A calendar day is not an exact timestamp. Validate dates, not regex alone. |
| Retry/backfill and identity | macro-news `src/collect.mjs`, [dedupe](https://github.com/qweeqw231/macro-news/blob/main/src/news-dedupe.mjs) | Inbox/cursors (#4), grouping (#5) | Adapt behavior independently: URL, content hash, first seen; preserve meaningful query parameters. No copied macro-news code (no license file). |
| Four relation classes | [AIHOT grouping](https://github.com/KKKKhazix/AIHOT/blob/main/docs/grouping.md), `industry/prompts/{group-definitions,group-pair,group-method}.md` | `events/grouping.py` (#5), relation gold | Adapt SAME_OCCURRENCE / SAME_STORY / UNRELATED / ROUNDUP to macro announcements and implementation. Deterministic first; ambiguous pairs remain flagged without a model. |
| Separating relation from attention | AIHOT `packages/backend/src/events/{group,merge,relate}.ts`, `industry/selection.ts` | Grouping/triage (#5) | Retain distinction, skip embeddings, heat scoring, multi-vendor confirmation and story graph engine. Relevance maps to H0–H4 and next confirmation. |
| Evidence-bound summaries | [AIHOT anti-hallucination rules](https://github.com/KKKKhazix/AIHOT/blob/main/industry/prompts/rules-anti-hallucination.md) | Copilot policy context (#6) | Adapt with MIT attribution; existing CC Macro placeholder and closed-book rules take precedence. No invented facts or stronger causal language. |
| Relation eval format | AIHOT `industry/relation-gold.example.jsonl`, `scripts/eval-relations.ts`, `tests/grouping-reliability.test.ts` | Real labelled sample (#7) | Adapt schema and count-based reporting; human labels must be committed before model runs. Upstream fictional examples are not real evaluation data. |
| gov.cn search endpoint, Referer and field names | [policy-search-china-skill](https://github.com/dongwei6688/policy-search-china-skill/blob/main/scripts/gov_library_search.py) | Probe and optional gov.cn reader (#4) | Adapt public HTTP request/JSON shape; report empty/malformed response explicitly. Skip Playwright dependency inside production intake. |
| Full platform | AIHOT Docker/PostgreSQL/API/worker/web | None | Skip: incompatible with authorized static architecture. |

AIHOT is MIT, copyright 2026 数字生命卡内克; the project name/logo are not part of the code license. policy-search-china-skill is MIT, copyright 2026 dongwei6688. Any later copied/substantially adapted source must retain the respective MIT notice. This PR's probe is an independent standard-library implementation and copies no upstream function or prompt.

Useful inspected blob identities: AIHOT grouping doc `7168a03d101e80b60cbfdffec5e22f2f6bc9076c`; anti-hallucination rules `b56a5fc897078c4b20a6f49a6a12061e659ecf74`; event group `0528092fec84b7d649dc3ee552d7a689fb8054f8`; macro-news timestamp `495f2f27e28a8f5a45b6528cc33889162de77e13`, dedupe `39baedc5edf52578e3937bb9e852eb3c997f24ea`. Pin the actual upstream revision when copying code in a later issue.

Deferred: external media, social heat, FinLens, brokerage research, full content search, embeddings and any server/database.
