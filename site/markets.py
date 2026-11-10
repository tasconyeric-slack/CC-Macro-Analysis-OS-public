"""Markets & financial conditions: daily series from the observation store, shown deterministically.

Everything here is arithmetic on stored observations: latest level, change vs the prior trading
day, change vs one month earlier (last observation on or before the same calendar day), and the
share of the trailing 365 days at or below the latest level. No estimate, no substitute series.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml
from markupsafe import Markup

from charts import line_chart

MARKETS = "markets"
ROOT = Path(__file__).resolve().parents[1]
CHART_RANGES = (("3m", 3), ("1y", 12), ("all", None))
MAX_CHART_POINTS = 300          # long ranges are thinned for the chart only; the CSV keeps every row
MIN_PERCENTILE_POINTS = 60      # a percentile from a handful of days would mislead


def load_specs(root: Path = ROOT) -> dict[str, dict]:
    """{metric_id: fetch spec} - `change` ('bp' | 'pct') and the upstream/downstream `group` come from here."""
    spec = yaml.safe_load((root / "data/dictionary/market_series.yaml").read_text(encoding="utf-8"))
    return {s["metric_id"]: s for s in spec["series"]}


def latest_crosschecks(root: Path = ROOT) -> dict[str, dict]:
    folder = root / "data/market/crosschecks"
    files = sorted(folder.glob("*.json")) if folder.exists() else []
    if not files:
        return {}
    doc = json.loads(files[-1].read_text(encoding="utf-8"))
    return {r["metric_id"]: {**r, "checked_at": doc.get("checked_at")} for r in doc.get("results", [])}


def thin(points: list, limit: int = MAX_CHART_POINTS) -> list:
    if len(points) <= limit:
        return points
    step = -(-len(points) // limit)
    kept = points[::step]
    return kept if kept[-1] is points[-1] else kept + [points[-1]]


def percentile_1y(points: list[dict]) -> int | None:
    last = pd.Timestamp(points[-1]["period"])
    window = [p["value"] for p in points if pd.Timestamp(p["period"]) > last - pd.Timedelta(days=365)]
    if len(window) < MIN_PERCENTILE_POINTS:
        return None
    return round(100 * sum(1 for x in window if x <= points[-1]["value"]) / len(window))


def one_month_ago(points: list[dict]) -> dict | None:
    cutoff = pd.Timestamp(points[-1]["period"]) - pd.DateOffset(months=1)
    older = [p for p in points if pd.Timestamp(p["period"]) <= cutoff]
    return older[-1] if older else None


def move(latest: float, old: float | None, kind: str) -> float | None:
    if old is None:
        return None
    return (latest - old) * 100 if kind == "bp" else ((latest / old - 1) * 100 if old else None)


def decimals(unit: str) -> int:
    return 4 if unit in ("%", "CNY per USD") else 2


def market_card(mid: str, item: dict, metric, v, spec: dict, check: dict | None, source_url) -> dict:
    kind = spec["change"]
    pts = item["points"]
    name = v.metric_name(mid)
    unit = v.unit(item["unit"])
    latest = pts[-1] if pts else None
    prev = pts[-2] if len(pts) > 1 else None
    month = one_month_ago(pts) if pts else None

    def text(x):
        if x is None:
            return v.t("data_explorer.not_available")
        return f"{x:+,.1f} {v.t('markets.bp')}" if kind == "bp" else f"{x:+,.2f}%"

    pct = percentile_1y(pts) if pts else None
    ranges = []
    if pts:
        last = pd.Timestamp(pts[-1]["period"])
        for key, months in CHART_RANGES:
            chosen = [p for p in pts if months is None or pd.Timestamp(p["period"]) > last - pd.DateOffset(months=months)]
            plots = [{"size": size, "svg": Markup(line_chart(
                [(p["period"], p["value"]) for p in thin(chosen)], item["unit"], chart_id=f"data-{mid}-{key}-{size}",
                width=width, label=name, empty=v.t("chart.not_enough")))} for size, width in (("wide", 640), ("compact", 360))]
            ranges.append({"key": key, "plots": plots})
    crosscheck = None
    if check:
        crosscheck = {**check, "source_name": v.source_name(check["official_source"]),
                      "state": check["status"],
                      "tolerance": f"{check['tolerance'] * 100:g}%" if check.get("tolerance_mode") == "rel"
                      else f"{check['tolerance'] * 100:g} {v.t('markets.bp')}" if check.get("tolerance") is not None else ""}
        date = str(check.get("date") or "")
        crosscheck["date_text"] = v.period(date) if len(date) == 7 else v.date(date) if date else ""
        if check.get("difference") is not None:
            crosscheck["difference_text"] = (f"{check['difference'] * 100:+.1f} {v.t('markets.bp')}"
                                             if check.get("tolerance_mode") == "abs" else f"{check['difference']:+.4f}")
    digits = decimals(item["unit"])
    return {"id": mid, "category": item["category"], "name": name, "role": v.metric_role(mid), "unit": unit,
            "frequency": "D", "latest": latest, "value": f"{latest['value']:,.{digits}f}" if latest else "–",
            "previous_change": text(move(latest["value"], prev["value"], kind)) if prev else text(None),
            "previous_date": prev["period"] if prev else None,
            "month_change": text(move(latest["value"], month["value"], kind) if month else None),
            "month_date": month["period"] if month else None,
            "percentile": pct, "year_change": text(None),
            "publisher": v.source_name("Tushare"), "source_url": source_url, "source_code": metric.source_code if metric else "",
            "notes": [], "ranges": ranges, "points": pts, "vintages": [], "tests": [], "derived": False, "market": True,
            "thumbnail": Markup(line_chart([(p["period"], p["value"]) for p in thin(pts[-120:], 90)], item["unit"],
                                           chart_id=f"thumb-{mid}", width=320, height=110, label=name)) if len(pts) > 1 else None,
            "json_url": f"../data/series/{mid}.json", "csv_url": f"../data/series/{mid}.csv", "crosscheck": crosscheck,
            "group": spec.get("group")}
