# ExecPlan — P0 DeepSeek Copilot for October 14

**Phase A → G-A (§14).** §15.2: (1) Yes: a working model can explain What Changed and Why. (2) Yes: a genuine replay and Shadow Live create proof. (3) Yes: Draft and Challenge require interpretation; facts stay deterministic. (4) Partly: PR #13 exposed the observed gap of zero genuine model runs, although no live failure exists yet. (5) Yes: without a working API call, the October 14 Shadow run and its Run Record cannot happen. This infrastructure change unblocks the concrete behavior `replay → Draft → Challenge → hard gates → Run Record`, using the existing Copilot.

1. Confirm the latest `main`, Issue #11, merged PR #13, DeepSeek's official Anthropic compatibility guide, the model transport, record accounting, CLI, tests and October 14 runbook.
2. Replace only the model transport and credential/configuration wiring. Keep two separate bounded calls, no new dependency, and fail closed on malformed or incomplete responses. Attribute the DeepSeek model and actual usage; record cost as unknown without a sound billing calculation.
3. Update targeted offline tests and the minimum runbook/README guidance. Run the full suite and public eval gate.
4. If the runtime has a key, execute one genuine August 9 replay, inspect its economic reasoning and verify its Run Record. Otherwise provide the Owner exact PowerShell commands and report that G-A's real-model proof remains open.
5. Push a dedicated branch from latest `main` and open a PR. Keep the frozen Baseline, data plane, mechanical deltas, research history and hosting untouched.

**Deferred:** New data providers, provider framework, new SDK, Phase B/C, cloud secrets and automation. Every failed genuine call or validation failure remains a separate Run Record.
