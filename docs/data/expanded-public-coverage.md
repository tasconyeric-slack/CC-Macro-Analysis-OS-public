# Expanded public macro coverage (Issue #28)

Fetched 2026-11-09 08:13:28 UTC. Nine new series contain 785 actual monthly observations, plus 94 observations backfilling the existing manufacturing PMI headline. Source metadata identifiers were discovered from the live NBS indicator tree, not guessed; `data/dictionary/expanded_series.json` retains the actual indicator labels and units.

| New view | Public origin / route | History | Latest period |
|---|---|---|---|
| Nonmanufacturing activity PMI | NBS JSON | 94 months | October 2026 |
| Services activity PMI | NBS JSON | 70 months | October 2026 |
| Construction activity PMI | NBS JSON | 70 months | October 2026 |
| Composite output PMI | NBS JSON | 94 months | October 2026 |
| Urban surveyed unemployment | NBS JSON | 93 months | September 2026 |
| USD imports YoY | GACC via NBS JSON | 93 months | September 2026 |
| USD trade balance | GACC via NBS JSON | 93 months | September 2026 |
| General public budget revenue YTD YoY | MOF via NBS JSON | 85 months | September 2026 |
| M2 YoY | PBOC originals + NBS JSON history | 93 months | September 2026 |

Two actual retrieval paths succeeded: the NBS `stream/esData` JSON API and the original PBOC financial-statistics documents ([August](https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/2026091414593871200/index.html), [September](https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/2026101415422529740/index.html)). The M2 parser reads the literal M2 paragraph, never the TSF growth rate elsewhere on the same page. Publication metadata supplies a date only; no clock time is invented. Historical first-publication dates unavailable in NBS metadata remain unknown, with availability recorded at actual retrieval time.

The complete October PMI group now includes manufacturing, nonmanufacturing, services, construction and composite output. September→October readings are respectively 50.1→49.3, 50.2→49.7, 50.2→50.0, 50.3→48.0 and 50.7→49.7. Existing category charts and CSV exports consume these rows directly. These are official index points, not percentage growth rates; the trade-balance unit is USD thousand.

Maintenance: `python scripts/fetch_expanded_data.py --summary expanded-summary.json` appends only genuinely changed rows and exits nonzero on source errors while keeping previous files. Normal `refresh-public` also recognizes every new metric's existing `nbs:` code. The existing NBS PMI agenda mapping now includes the four new PMI fields. On Windows, the transport honors the server's ordinary Set-Cookie redirect using a temporary cookie jar; without that cookie engine the server returned a 307 loop. No browser automation, account, token or backend is required. Temporary response cookies are deleted and never committed.
