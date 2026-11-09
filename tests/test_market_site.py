"""Markets & financial conditions page: deterministic numbers, range switch, CSV export, source labels."""
import argparse
import csv
import json
import shutil
from datetime import date

import pytest

import markets
from conftest import CASE, ROOT
from test_market_data import TODAY, FakeTushare


def pt(day, value):
    return {"period": day, "value": value}


def test_one_day_and_one_month_changes_use_trading_days_and_calendar_months():
    pts = [pt("2026-10-08", 100.0), pt("2026-10-09", 101.0), pt("2026-11-06", 110.0), pt("2026-11-09", 111.1)]
    assert markets.one_month_ago(pts) == pt("2026-10-09", 101.0)      # 2026-10-09 is the last day on or before 9 Oct
    assert markets.move(111.1, 110.0, "pct") == pytest.approx(1.0)
    assert markets.move(1.5874, 1.5674, "bp") == pytest.approx(2.0)
    assert markets.move(5.0, None, "pct") is None
    assert markets.one_month_ago([pt("2026-11-09", 1.0)]) is None


def test_percentile_is_the_share_of_the_trailing_year_at_or_below_the_latest():
    days = [date.fromordinal(date(2026, 11, 9).toordinal() - i).isoformat() for i in range(120)][::-1]
    pts = [pt(d, float(i)) for i, d in enumerate(days)]                  # rising: the latest is the maximum
    assert markets.percentile_1y(pts) == 100
    pts[-1] = pt(days[-1], 59.5)                                          # a mid-window level
    assert markets.percentile_1y(pts) == 51                               # values 0..59 plus itself: 61 of 120
    assert markets.percentile_1y(pts[:30]) is None                        # too little history to claim a percentile


def test_thinning_keeps_the_last_point_and_the_bound():
    pts = [pt(str(i), float(i)) for i in range(1000)]
    out = markets.thin(pts)
    assert len(out) <= markets.MAX_CHART_POINTS + 1 and out[-1] is pts[-1] and out[0] is pts[0]
    assert markets.thin(pts[:50]) == pts[:50]


@pytest.fixture(scope="module")
def market_site(tmp_path_factory):
    import build
    from cnmacro import market_data as md
    work = tmp_path_factory.mktemp("market-site")
    root = work / "repo"
    (root / "data/dictionary").mkdir(parents=True)
    for name in ("metrics.yaml", "market_series.yaml"):
        shutil.copy(ROOT / "data/dictionary" / name, root / "data/dictionary" / name)
    shutil.copytree(ROOT / "data/demo/observations", root / "data/demo/observations")
    md.refresh_market(root, call=FakeTushare(), today=TODAY, log=lambda *_: None, now="2026-11-09T12:30:00+00:00")
    checks = {"mk_cn_gov_10y": {"metric_id": "mk_cn_gov_10y", "official_source": "ChinaBond", "date": "2026-11-09", "status": "ok",
                             "official_value": 1.5874, "difference": 0.0, "tolerance": 0.01, "tolerance_mode": "abs"},
              "mk_usdcnh": {"metric_id": "mk_usdcnh", "official_source": "CFETS", "date": "2026-11-09", "status": "gap",
                            "official_value": 6.7188, "difference": 0.09, "tolerance": 0.005, "tolerance_mode": "rel"}}
    original = markets.latest_crosschecks
    markets.latest_crosschecks = lambda root=ROOT: checks
    try:
        ns = argparse.Namespace(preview=False, banner=None, case_dir=str(CASE), obs_dir=str(root / "data/demo/observations"),
                                calendar=str(ROOT / "data/dictionary/release_calendar.yaml"),
                                dictionary=str(ROOT / "data/dictionary/metrics.yaml"))
        out = work / "dist"
        build.render_site(build.build_model(ns), out)
    finally:
        markets.latest_crosschecks = original
    return out, root


def test_markets_page_shows_every_series_with_levels_changes_percentile_and_ranges(market_site):
    out, _ = market_site
    spec = markets.load_specs()
    for loc in ("en", "zh"):
        page = (out / loc / "data-markets.html").read_text(encoding="utf-8")
        for mid in spec:
            assert f'id="metric-{mid}"' in page, (loc, mid)
        assert page.count('data-range="3m"') == len(spec) and page.count('data-range="1y"') == len(spec)
        assert 'data-range="all"' in page and page.count("data-range-plot=") == 3 * len(spec)
        assert page.count('.csv" download') == len(spec) and "Tushare" in page
        assert 'id="upstream-downstream"' in page and page.count('class="chart"') >= 3 * 2 * len(spec) - 6
        assert "%" in page and "data-portal.js" in page
    en = (out / "en/data-markets.html").read_text(encoding="utf-8")
    assert "Markets &amp; financial conditions" in en and "1-year percentile" in en
    zh = (out / "zh/data-markets.html").read_text(encoding="utf-8")
    assert "市场与金融条件" in zh and "近一年分位" in zh


def test_crosscheck_lines_report_passes_and_gaps_without_hiding_either(market_site):
    out, _ = market_site
    en = (out / "en/data-markets.html").read_text(encoding="utf-8")
    assert 'data-state="ok"' in en and "Cross-check passed: China Central Depository" in en
    assert 'data-state="gap"' in en and "Cross-check gap: China Foreign Exchange" in en and "nothing was overwritten" in en


def test_series_csv_exports_every_vintage_and_matches_the_store(market_site):
    out, root = market_site
    for mid in ("mk_cn_gov_10y", "mk_csi300", "mk_cn_gov_slope_10y_1y"):
        with (root / f"data/demo/observations/tushare_{mid}.csv").open(encoding="utf-8", newline="") as f:
            stored = list(csv.DictReader(f))
        with (out / f"data/series/{mid}.csv").open(encoding="utf-8-sig", newline="") as f:
            exported = list(csv.DictReader(f))
        assert [(r["reference_period"], r["value"]) for r in exported] == [(r["reference_period"], r["value"]) for r in stored]
        doc = json.loads((out / f"data/series/{mid}.json").read_text(encoding="utf-8"))
        assert doc["category"] == "markets" and doc["points"][-1]["period"] == "2026-11-09"
        assert {p["source"] for p in doc["points"]} == {"Tushare"}


def test_data_hub_lists_the_markets_column_and_page_size_stays_reasonable(market_site):
    out, _ = market_site
    hub = (out / "en/data.html").read_text(encoding="utf-8")
    assert 'href="data-markets.html"' in hub
    assert (out / "en/data-markets.html").stat().st_size < 4_000_000


def test_markets_series_are_not_evidence_explorer_inputs(market_site):
    out, _ = market_site
    charts = (out / "en/charts.html").read_text(encoding="utf-8")
    assert "mk_cn_gov_10y" not in charts


def test_markets_page_without_observations_shows_an_honest_gap_not_numbers(built):
    """Before the first market run (or if the token is absent) the page must show gaps, never guessed values."""
    if list((ROOT / "data/demo/observations").glob("tushare_*.csv")):
        pytest.skip("market observations exist; the populated page is covered by the fixture-built site")
    for loc in ("en", "zh"):
        page = (built / loc / "data-markets.html").read_text(encoding="utf-8")
        assert page.count('class="data-metric chartcard"') == len(markets.load_specs())
        assert 'class="chart"' not in page and "data-range=" not in page
