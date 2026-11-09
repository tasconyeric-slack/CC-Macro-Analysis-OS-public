# Official event grouping and triage (#5)

Phase/Gate: V2 Public News & Official Data, Epic #8 Stage 3 after the three real Stage2 previews. §15.2: (1) Yes, repeated reports should not look like repeated changes; (2) Yes, real inbox relation fixtures and grouping outcomes provide a usable signal layer; (3) No for exact identities/keyword triage; a model is optional only for ambiguous relation pairs; (4) Yes, the real corpus contains repeated URLs, republications and composite reports; (5) Yes, this is required for the authorized Daily/Policy research chain. Without grouping, the reader sees duplicate signals and cannot distinguish an announcement from its follow-up. No merge before 2026-11-09 07:30UTC or out of the approved dependency order.

Implement deterministic identity, explicit follow-up/composite relations, excerpt-backed H-links, append-only event revisions and a public grouped reader. Missing model configuration leaves ambiguous pairs ungrouped and flagged; no automatic analyst decision. Technical fixture labels here are agent-authored parser/relation regression examples, not the analyst-labelled evaluation requested in #7.

## Real corpus result

The673 dated source revisions form655 occurrences. Seventeen groups have multiple source members;17 ambiguous pairs remain separate and flagged. The next unchanged grouping run appended zero event revisions. The missing-date item remains quarantined. The two source-verified November CPI/PPI releases remain distinct public occurrences; all rule-based hypothesis links include a literal source excerpt, rule version and item identity. No event is an analyst judgment.

Current candidate triage counts are328 monitor,269 outside the current rules and58 research-needed. These are deterministic rule outputs, not labelled evaluation accuracy. One real policy example is the PBOC item “中国人民银行加力实施股票回购增持再贷款政策”: implementation-stage wording, H3/H2 source excerpts and a need to confirm financing/transmission. It remains archived context and has no fabricated impact or analyst approval.

The real four-class regression fixture contains a repeated document, the July economic release and its explicit Q&A follow-up, an unrelated meeting/price pair, and a broad economic release versus its retail item. Records are copied unchanged from the inbox. A detected failure—treating background “落实” wording as proof of a follow-up—was corrected by requiring the follow-up marker in the title. The uncertain document pairs now remain flagged. A synthetic stage-boundary unit test separately proves that an announcement and implementation stay separate; it is not published as real news.

## Optional model path and validation

The default workflow makes **zero model calls**. `events group --model ...` is an explicit bounded opt-in, using the existing DeepSeek transport only for unresolved pairs (maximum ten per invocation). A missing key leaves the deterministic result intact. Each actual call writes a write-once Run Record/context with model identity, prompt/schema version, input hash, evidence IDs, raw response, token/latency metadata and validation. Invalid schema or a numeric claim in the reason leaves the pair unresolved.

`tests/fixtures/events/model-call-samples/` contains one labelled synthetic success and one numeric-reason failure created through that record path; neither is an actual provider call or AI-quality evidence. Hard gates on these fixture calls pass/fail as expected. Genuine tie-break precision/recall and analyst acceptance: **not measured**. #7 remains dependent on real analyst labels.

Validation:27 grouping/intake/i18n tests passed; the public build completed48 routes; source-boundary and diff checks passed. MIT attribution and the exact upstream prompt blob hashes are in `docs/third-party/AIHOT-MIT.txt`. Full CI and a real preview are required before merge.
