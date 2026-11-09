"""Public deterministic policy comparison; only explicitly accepted model output is rendered."""
from pathlib import Path

from cnmacro import policy_delta as delta
from cnmacro.copilot import records
from cnmacro.store import utc_naive

ROOT = Path(__file__).resolve().parents[1]


def comparison_view(model: dict, loc: str) -> list[dict]:
    canonical = ROOT / "research/cases/cn-nominal"
    if model["preview"] or model.get("banner") or Path(model["case_dir"]).resolve() != canonical.resolve(): return []
    cutoff = model["built_at"]
    root = ROOT / "data/events"
    comparisons = delta.load_comparisons(root, ROOT / "data/dictionary/policy_lexicon.yaml", as_of=cutoff)
    out = []
    for pair in comparisons:
        ctx = delta.interpretation_context(pair)
        accepted = delta.accepted_interpretation(root / "policy_copilot", ctx, as_of=cutoff)
        status = "not_run"
        latest = None
        for p in (root / "policy_copilot/runs").glob("*/record.json"):
            try:
                rec, saved = records.load_run(p.parent)
            except (records.RecordError, ValueError, KeyError, OSError):
                continue
            if saved.get("sha256") == ctx["sha256"] and utc_naive(rec["run_at"]) <= utc_naive(cutoff):
                if latest is None or utc_naive(rec["run_at"]) > utc_naive(latest["run_at"]): latest = rec
        if latest: status = latest["status"]
        out.append({**pair, "title": pair["title_" + loc], "before_title": pair["before"]["title_" + loc],
                    "after_title": pair["after"]["title_" + loc],
                    "changed": [r for r in pair["rows"] if r["tag"] != "unchanged"],
                    "unchanged": [r for r in pair["rows"] if r["tag"] == "unchanged"],
                    "accepted": accepted, "model_status": status})
    return out
