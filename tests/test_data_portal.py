"""The portal must preserve actual observations, vintage history and public boundaries."""
import csv
import json
from dataclasses import replace

import pandas as pd
import pytest

from cnmacro.derive import Deriver
from cnmacro.store import as_of, load_observations
from data_portal import CATEGORIES, DEFLATOR, changes, public_metrics
from conftest import ROOT


def test_every_emitted_raw_series_equals_the_public_store(built, model):
    raw = load_observations(ROOT / "data/demo/observations")
    expected = as_of(raw, model["evidence_as_of"])
    daily = raw[raw.metric_id.isin([m for m, x in model["metrics"].items() if x.frequency == "D"])]
    if not daily.empty:     # daily market series are not tied to the evidence state (market.yml)
        expected = pd.concat([expected[~expected.metric_id.isin(daily.metric_id)], as_of(daily, daily.retrieved_at.max())])
    allowed = public_metrics(model["metrics"])
    emitted = {p.stem for p in (built / "data/series").glob("*.json")}
    assert emitted == set(allowed) | {DEFLATOR}
    for mid, metric in allowed.items():
        doc = json.loads((built / f"data/series/{mid}.json").read_text(encoding="utf-8"))
        rows = expected[(expected.metric_id == mid) & (expected.source_class == "public")].sort_values("reference_period")
        assert [(p["period"], p["value"], p["release_date"] or "", p["retrieved_at"]) for p in doc["points"]] == [
            (r.reference_period, float(r.value), r.release_date, r.retrieved_at) for _, r in rows.iterrows()]
        assert doc["category"] == metric.category
        history = raw[(raw.metric_id == mid) & (raw.source_class == "public")]
        with (built / f"data/series/{mid}.csv").open(encoding="utf-8-sig", newline="") as f:
            csv_rows = list(csv.DictReader(f))
        assert len(csv_rows) == len(history) == len(doc["vintages"])
        assert sorted((r["reference_period"], float(r["value"]), r["retrieved_at"]) for r in csv_rows) == sorted(
            (r.reference_period, float(r.value), r.retrieved_at) for _, r in history.iterrows())


def test_derived_deflator_uses_existing_formula_and_lineage(built, model):
    doc = json.loads((built / f"data/series/{DEFLATOR}.json").read_text(encoding="utf-8"))
    pts = Deriver(model["observations"], model["metrics"]).deflator_yoy("cn_ngdp_q", "cn_rgdp_yoy")
    assert [(p["period"], p["value"], p["inputs"]) for p in doc["points"]] == [(str(period), pt.value, pt.inputs) for period, pt in pts.items()]


def test_public_category_required_and_private_metrics_excluded(model, built):
    metrics = dict(model["metrics"])
    public = next(mid for mid, m in metrics.items() if m.redistribution == "public")
    metrics[public] = replace(metrics[public], category=None)
    with pytest.raises(ValueError, match="requires a valid category"):
        public_metrics(metrics)
    for mid, m in model["metrics"].items():
        if m.redistribution != "public" or m.tier == "supplemental":
            assert not (built / f"data/series/{mid}.json").exists()


def test_all_categories_have_charts_details_and_honest_gap(built):
    for loc in ("en", "zh"):
        for category in [c for c in CATEGORIES if c != "markets"]:     # markets: tests/test_market_site.py
            page = (built / loc / f"data-{category}.html").read_text(encoding="utf-8")
            assert 'class="chart"' in page
            assert 'class="data-detail"' in page
            assert 'data-range="2y"' in page and 'data-range="5y"' in page
            assert '.csv" download' in page and '.json"' in page
        fiscal = (built / loc / "data-fiscal.html").read_text(encoding="utf-8")
        assert 'id="metric-cn_gov_fund_rev_ytd_yoy"' in fiscal
    gap = json.loads((built / "data/series/cn_gov_fund_rev_ytd_yoy.json").read_text(encoding="utf-8"))
    assert not gap["points"]


def test_differences_require_exact_comparable_periods():
    points = [{"period": "2025-10", "value": 1}, {"period": "2026-08", "value": 2}, {"period": "2026-10", "value": 3}]
    assert changes(points, "M") == (None, 2)


def test_raw_history_preserves_revisions_and_unknown_dates(model):
    history = model["observation_history"]
    rows = history[(history.metric_id == "cn_ngdp_q") & (history.reference_period == "2026Q3")]
    assert len(rows) > len(model["observations"][(model["observations"].metric_id == "cn_ngdp_q") & (model["observations"].reference_period == "2026Q3")])
    point = next(p for p in model["data_portal"]["series"]["cn_ngdp_q"]["points"] if p["period"] == "2026Q3")
    original = rows.sort_values("retrieved_at").iloc[-1]
    assert point["release_date"] == (original.release_date or None)
    assert point["quality_flag"] == original.quality_flag
