"""Static policy inbox view; current events are never injected into replay builds."""
from pathlib import Path

from cnmacro.events.store import load_items, load_source_status, stamp

ROOT = Path(__file__).resolve().parents[1]


def policy_inbox(model: dict, loc: str) -> dict:
    canonical = ROOT / "research/cases/cn-nominal"
    enabled = not model["preview"] and not model.get("banner") and Path(model["case_dir"]).resolve() == canonical.resolve()
    cutoff = model["built_at"]
    items = load_items(ROOT / "data/events", as_of=cutoff) if enabled else []
    sources = load_source_status(ROOT / "data/events", as_of=cutoff) if enabled else []
    visible = []
    for raw in items:
        if not raw.get("published_at") or stamp(raw["published_at"]) > stamp(cutoff) or raw["status"] == "rejected":
            continue
        title = raw.get("title_" + loc) or raw["title_zh"]
        summary = raw.get("summary_" + loc) or raw.get("summary_zh") or ""
        visible.append({**raw, "title": title, "summary": summary,
                        "original_language": loc == "en" and not raw.get("title_en")})
    return {"items": [r for r in visible if not r["archived"]][:30],
            "archive": [r for r in visible if r["archived"]][:30],
            "total": len(visible), "archived_count": sum(r["archived"] for r in visible),
            "quarantined": sum(not r.get("published_at") for r in items), "sources": sources, "as_of": cutoff}
