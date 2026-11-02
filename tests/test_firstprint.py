"""Regression tests for actual 2026-10-19 NBS first-print figures and freshness."""
import pandas as pd
import pytest

from cnmacro import firstprint, ingest
from cnmacro.firstprint import official_release_freshness
from cnmacro.store import load_dictionary

METRICS = load_dictionary("data/dictionary/metrics.yaml")
IDS = ["cn_ngdp_q", "cn_rgdp_yoy", "cn_ip_yoy",
       "cn_retail_sales_yoy", "cn_property_sales_area_ytd_yoy"]


def summary(ip="5.5", gdp="375367（三季度）"):
    rows = [
        ["一、国内生产总值（亿元）", gdp, "4.5（三季度）", "1071071", "4.6"],
        ["三、规模以上工业增加值", "…", ip, "…", "5.3"],
        ["新建商品房销售面积（万平方米）", "…", "…", "56483", "-13.2"],
        ["七、社会消费品零售总额（亿元）", "42433", "1.1", "370001", "1.1"],
    ]
    body = "".join("<tr>" + "".join(f"<td><p>{v}</p></td>" for v in row) + "</tr>" for row in rows)
    return "<html><body><table><tr><td>指标</td><td>9月绝对量</td><td>同比增长（%）</td><td>1—9月绝对量</td><td>同比增长（%）</td></tr>" + body + "</table></body></html>"


def test_read_all_five_official_20261019_observations_and_duplicate_tables():
    vals = firstprint.parse_activity_table(summary() + summary())
    assert vals == {"cn_ngdp_q": 375367.0, "cn_rgdp_yoy": 4.5,
                    "cn_ip_yoy": 5.5, "cn_retail_sales_yoy": 1.1,
                    "cn_property_sales_area_ytd_yoy": -13.2}


def test_contradictions_and_invalid_gdp_cells_rejected():
    with pytest.raises(ValueError, match="contradictory"):
        firstprint.parse_activity_table(summary(ip="5.5") + summary(ip="5.2"))
    with pytest.raises(ValueError, match="single-quarter GDP"):
        firstprint.parse_activity_table(summary(gdp="1071071亿元"))


def test_date_scoped_official_url_discovery():
    listing = ('<a href="../zxfbhjd/202610/t20261019_1965618.html">'
               '前三季度经济运行总体平稳　高质量发展取得新成效</a>'
               '<a href="./202610/t20261019_1965617.html" title="2026年9月份规模以上工业增加值增长5.5%">x</a>'
               '<a href="./202609/t20260915_1965308.html">8月份经济运行</a>')
    urls = firstprint.release_links(firstprint.LISTINGS[0], listing, "2026-10-19")
    assert len(urls) == 2
    assert urls[0].endswith("t20261019_1965618.html")


def test_calendar_gate_and_source_url(monkeypatch):
    url = "https://www.stats.gov.cn/sj/zxfbhjd/202610/t20261019_1965618.html"
    listing = f'<a href="{url}" title="前三季度经济运行总体平稳">summary</a>'
    def get(page, **kw):
        return (listing if page in firstprint.LISTINGS else summary()).encode("utf-8")
    monkeypatch.setattr(ingest, "_get", get)
    cal = {(mid, "2026Q3" if "gdp" in mid else "2026-09"):
           ("2026-10-19T10:00:00+08:00", "") for mid in IDS}
    held = {mid: ("2026Q2" if "gdp" in mid else "2026-08") for mid in IDS}
    metrics = [METRICS[mid] for mid in IDS]
    assert not firstprint.activity_release_rows(metrics, held, cal, "2026-10-19T01:59:00+00:00")
    got = firstprint.activity_release_rows(metrics, held, cal, "2026-10-19T02:52:00+00:00")
    assert {(r["metric_id"], r["reference_period"], r["value"]) for r in got} == {
        ("cn_ngdp_q", "2026Q3", 375367.0),
        ("cn_rgdp_yoy", "2026Q3", 4.5),
        ("cn_ip_yoy", "2026-09", 5.5),
        ("cn_retail_sales_yoy", "2026-09", 1.1),
        ("cn_property_sales_area_ytd_yoy", "2026-09", -13.2)}
    assert all(r["source"] == "NBS" and r["source_code"] == url and
               r["release_date_basis"] == "official_calendar" for r in got)
    current = {mid: ("2026Q3" if "gdp" in mid else "2026-09") for mid in IDS}
    assert not firstprint.activity_release_rows(metrics, current, cal, "2026-10-19T03:00:00+00:00")


def test_freshness_only_alerts_missing_calendar_confirmed_periods():
    due = {"cn_ip_yoy": {"expected": "2026-09"},
           "cn_m1_yoy": {"expected": "2026-09"}}
    cal = {("cn_ip_yoy", "2026-09"): ("2026-10-19T10:00:00+08:00", "")}
    obs = pd.DataFrame([{"metric_id": "cn_ip_yoy", "reference_period": "2026-08"}])
    pending = official_release_freshness(due, obs, cal, pd.Timestamp("2026-10-19T02:20:00"))
    assert pending["status"] == "RELEASE_PENDING_INGEST"
    assert len(pending["missing"]) == 1
    stale = official_release_freshness(due, obs, cal, pd.Timestamp("2026-10-19T04:20:00"))
    assert stale["status"] == "SOURCE_STALE"
    obs.loc[len(obs)] = {"metric_id": "cn_ip_yoy", "reference_period": "2026-09"}
    assert official_release_freshness(due, obs, cal, pd.Timestamp("2026-10-19T04:20:00"))["status"] == "CURRENT"


def test_press_release_route_keeps_portal_on_independent_error(monkeypatch):
    from cnmacro import ingest
    ms = [METRICS["cn_ip_yoy"]]
    def base(*args):
        return {"nbs_cn_ip_yoy.csv": []}
    monkeypatch.setattr(firstprint, "activity_release_rows", lambda *a: (_ for _ in ()).throw(ValueError("schema drift")))
    log = []
    got = ingest.with_nbs_release(base, log=log.append)(
        "nbs", ms, {"cn_ip_yoy": "2026-08"}, METRICS, {}, "2026-10-19T02:52:00Z")
    assert got == {"nbs_cn_ip_yoy.csv": []}
    assert any("FAILED" in s for s in log)
