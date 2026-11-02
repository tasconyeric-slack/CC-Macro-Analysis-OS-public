"""Release Copilot v0 (docs/PRODUCT_STRATEGY.md §8, docs/execplans/phase-a-release-copilot-v0.md).

    existing store -> deterministic delta -> Context Builder -> Draft -> Challenge
        -> hard validation -> Run Record -> analyst (blind take, decision)

Deterministic code owns every number, the as-of clock, test outcomes and `mechanical_delta`. The model
interprets. The analyst decides. Nothing in this package writes to the preregistered case, the claims
ledger, an analyst update or any public artifact, and `refresh.py` / `replay.py` never import it: a
model failure cannot reach the deterministic pipeline.
"""

PROMPT_VERSION = "release-copilot-prompt/1"
SCHEMA_VERSION = "release-copilot-schema/1"
CONTEXT_VERSION = "release-copilot-context/1"
RECORD_VERSION = "release-copilot-run-record/1"
