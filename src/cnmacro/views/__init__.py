"""Research view comparison: the latest signed CC Macro view against the evidence since.

Read-only and deterministic. It reads committed artifacts only (the signed baseline/updates,
the append-only refresh records, the frozen Chinese renderings) and never writes a judgment,
probability or test outcome. External (institutional) views are an optional, separately
validated input that never feeds the evidence tests; see `external.py`.
"""
from .compare import build_comparison, render_markdown  # noqa: F401
from .external import load_external_views, validate_external_view  # noqa: F401
