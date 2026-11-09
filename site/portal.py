"""Portal navigation from the public chart inventory; no new observations or judgment."""

from data_portal import CATEGORIES, public_metrics

# Category order only: metric membership is defined once in metrics.yaml.
CATEGORY_METRICS = CATEGORIES


def portal_context(model, v):
    charts = {ch["m"].metric_id: ch for ch in model["charts"]}
    categories = []
    for cid in CATEGORIES:
        mids = [mid for mid, m in public_metrics(model["metrics"]).items() if m.category == cid]
        available = [charts[mid] for mid in mids if mid in charts and charts[mid]["pts"]]
        releases = [str(ch["latest_release"]) for ch in available if ch["latest_release"]]
        categories.append({
            "id": cid, "title": v.t(f"portal.category.{cid}.title"),
            "kicker": v.t(f"portal.category.{cid}.kicker"),
            "description": v.t(f"portal.category.{cid}.description"),
            "metric_count": len(available), "latest_release": max(releases, default=None),
            "url": f"data-{cid}.html", "metric_ids": [ch["m"].metric_id for ch in available],
        })
    return {"categories": categories, "latest_refresh": model["refreshes"][-1] if model["refreshes"] else None,
            "metric_count": len({mid for c in categories for mid in c["metric_ids"]})}
