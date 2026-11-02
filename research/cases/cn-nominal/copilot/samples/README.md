# Sample Run Records — synthetic, NOT evidence

These two records were produced by the Copilot's real code path (replay of the 2026-08-09 release on the production
`as_of` path, Context Builder, two passes, hard validation, rendering, Run Record) with **hand-written fixture
responses** instead of a model (`kind: fixture`, `genuine_model_run: false`, `model.requested_id:
fixture:hand-written`). No model produced them. They exist to show the record format and the gates working, and
`records.write_run` makes it structurally impossible for a fixture run to be written anywhere except `samples/`.

**They must never be counted in any evaluation, quoted as model output, or used as a Copilot result.** Real runs
live in `../runs/` (none exists yet) and carry `kind: model_run`.

| Run | What it is | Outcome |
|---|---|---|
| `20261010T043513Z-81249026-138f` | a well-formed Draft and Challenge (`tests/fixtures/copilot/ok/`) | `validated`; two divergences (H0, H2) found and consistent with the code-owned `mechanical_delta` |
| `20261010T043526Z-81249026-ae68` | a deliberately bad Draft (`tests/fixtures/copilot/fabricated/`): a typed figure and unit word, a period after the information set, an evidence id outside the allowlist, a supplied `mechanical_delta`, a supplied `probability`, a hidden divergence | `validation_failed`; no Challenge call, no result, nothing rendered or showable |

Reproduce and check (the check rebuilds the sandbox and the context from the store and compares hashes):

```bash
python -m cnmacro copilot replay --release-at 2026-08-09 --fixture tests/fixtures/copilot/ok
python -m cnmacro copilot replay --release-at 2026-08-09 --fixture tests/fixtures/copilot/fabricated
python -m cnmacro copilot verify --run-id 20261010T043513Z-81249026-138f
```

The replay context labels itself: the 2026-10-04 judgment post-dates the replayed release and the hypotheses were
designed after seeing 2026 data (strategy §10.2), so a replay is never live evidence. Analyst events (blind take,
reveal, decision) are deliberately absent: they are the Owner's, and none is invented here.
