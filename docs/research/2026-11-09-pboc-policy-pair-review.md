# PBOC Q2 → Q3 2026: factual review material for #6

Phase: V2 Public News & Official Data, preparation for Epic #8 Stage 3 / Issue #6. This note does not pass a stage gate or G-A/G-B/G-C. §15.2: (1) Yes — document the exact wording changes a reader should be able to inspect; (2) No — this historical document pair is not new live proof; (3) No AI is needed to identify textual differences; (4) Yes — actual source inspection exposed a timestamp-basis ambiguity; (5) Yes — a real sourced policy comparison is part of the approved V2 deliverable. This is agent-prepared source material, not analyst judgment, gold labels, an accepted interpretation or a research update.

Prepared during the 2026-11-09 CPI/PPI release merge blackout (01:30 UTC release; no site/pipeline merges before 07:30 UTC). No product code, deployment, event review, thesis state or immutable research history is changed.

## Source identity

The two official pages were retrieved on 2026-11-08 in the program's source probe. Existing raw captures were re-read for this note; no second retrieval is claimed. Their local capture mtimes are 17:53:09 UTC, which is filesystem metadata rather than an independently recorded retrieval timestamp.

| Item | Q2 | Q3 |
|---|---|---|
| Official title | 中国人民银行货币政策委员会召开2026年第二季度例会 | 中国人民银行货币政策委员会召开2026年第三季度例会 |
| Source | [PBOC Q2 communiqué](https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/2026070818273311767/index.html) | [PBOC Q3 communiqué](https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/2026092416074632670/index.html) |
| Page `createDate` metadata (Beijing) | 2026-07-08 18:51:03 | 2026-09-24 17:19:32 |
| Timestamp embedded in URL (Beijing) | 2026-07-08 18:27:33 | 2026-09-24 16:07:46 |
| Meeting date stated in body | 2026-07-04 | 2026-09-19 |
| Raw HTML bytes | 27,663 | 27,807 |
| Raw HTML SHA256 | `c943dc6cea2e87e597dd51efb1dfbf3df4e8fdac3c3f04bcbe392ea9cfcd76f4` | `7586562927f4fe7bf421838fc96dbfbe20b107f9de446f3811b9fca86ada1490` |

The page metadata and URL stamps disagree about the clock time while agreeing on the publication date. Preserve the basis explicitly; do not silently treat an encoded URL time as an independently confirmed publication time. A meeting date is a different field. Paragraph references below count the seven `<p>` elements inside the official page's `div#zoom`, starting at one.

## Exact changes to inspect

| Location | Q2 wording | Q3 wording | Deterministic observation |
|---|---|---|---|
| P3, domestic conditions | 运行总体平稳、结构向优 | 运行总体平稳、动能向新、结构向优 | A description of growth drivers is inserted. |
| P3, adjustment | 加大逆周期和跨周期调节力度 | 加大逆周期调节力度 | “和跨周期” is removed **from this sentence**. P2 still contains both kinds of adjustment in both documents. |
| P4, instruments | No matching clause | 综合运用并适时调整货币政策工具 | A clause about use and adjustment of tools is added before the liquidity sentence. It does not announce a specific cut or quantify an operation. |
| P4, operating framework | 强化央行政策利率引导; text on market-based rate formation, self-regulation, implementation and supervision | 推动货币政策操作框架改革完善 | The wording is rewritten. Text replacement alone does not establish stronger or weaker policy action. |
| P4, exchange rate | Existing resilience and expectation clauses | Adds 坚持市场在汇率形成中的决定性作用 and 防范市场“羊群效应”和非理性预期的自我强化 | New clauses are inserted; the closing commitment to basic exchange-rate stability remains. |
| P5, structural tools | 优化工具管理 | 不断完善工具设计和管理 | Wording about tool design is added. |
| P5, support areas | 内需、科技创新、中小微企业等 | Adds “六张网”建设 | The named set of support areas expands. This is not evidence of funding already paid or observed economic impact. |
| P6, allocation / growth drivers | 做优增量、盘活存量 | 加快推动新旧动能转换 | Wording is replaced within the closing policy paragraph. |

The meeting identity, attendance and regional participant changes in P1/P7 should remain visible as document facts but should not be elevated automatically into economic policy signals.

## Useful controls and review boundaries

- **Exact unchanged control:** P2 is byte-for-byte identical after HTML text extraction. It includes the unchanged phrase 货币政策保持适度宽松. The same paragraph also retains 强化逆周期和跨周期调节. A diff that calls this paragraph a policy change is wrong.
- **Formatting control:** P4 changes the comma following 增强政策前瞻性灵活性针对性 from ASCII to full-width punctuation. Ignore this formatting difference when aligning clauses; retain the original source text for display.
- **No change of thesis is implied.** The documents are EVENT-tier text. They are neither numeric observations nor analyst-approved JUDGMENT. No probability, evidence test or `mechanical_delta` changes follow from this note.
- **No model has run on this pair in this preparation.** There is no AI run record, acceptance decision, analyst label set or policy-delta evaluation result to report. Numeric figures in any future interpretation must use the existing deterministic binding discipline.
- **Review questions, not conclusions:** which wording changes matter to credit transmission; which next official observation would distinguish a tool-design change from realized demand support; whether apparent omissions are restatements elsewhere in the same document. H-links and strength tags require the stated deterministic rule basis or analyst review.

## Integration state

PR #22's green shared shell (`e7380ff0c3f6932ef7db6989e139bc2e2a01e65d`) is a technically usable isolated base: it provides the Policy route, `head`/`scripts` extension blocks and common source/tier macros. An isolated branch or preview is not a merged stage gate. Follow the Owner's temporary permission to develop Stage 2 from that green shell, retain the Stage 2 real-data preview gate before #6 product code, and preserve merge order once the blackout ends. #6 should then layer the comparison above #4's inbox, keep candidate interpretations private until accepted, and reuse the existing Copilot transport and append-only record primitives. No new server, provider or framework is needed.
