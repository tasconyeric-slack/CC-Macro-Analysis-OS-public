"""News and policy intake -> China macro occurrences -> calendar and research inputs (deterministic, no model)."""
import json

from cnmacro.events.store import stamp
from cnmacro.macro_events import build_occurrences, extract_action, extract_figures, material
from cnmacro.research_inputs import _news
from daily import build_calendar, calendar_view
from views import View

AT = "2026-11-10T10:30:00+08:00"


def test_figures_keep_sign_basis_currency_and_period_as_written():
    text = ("海关总署11月10日发布数据，今年前10个月，我国货物贸易进出口44.81万亿元，同比增长20%。"
            "其中，出口25.99万亿元，同比增长17.6%。10月份，我国货物贸易进出口总值4.87万亿元，增长31.2%。"
            "其中，出口2.79万亿元，增长28.7%；进口2.08万亿元，增长34.7%。")
    got = {(f["indicator"], f["basis"], f["currency"], f["period"]): f["value"] for f in extract_figures(text, AT)}
    assert got[("exports", "ytd", "CNY", "2026-10")] == 17.6           # 前10个月 is year to date
    assert ("exports", "yoy", "CNY", "2026-10") not in got              # 10月份 sentence has no 同比 and no 同比(下同)
    usd = extract_figures("中国10月出口同比(按美元计) 35.2%，前值 36.3%", AT)[0]
    assert (usd["metric_id"], usd["value"], usd["previous"], usd["currency"]) == ("cn_exports_usd_yoy", 35.2, 36.3, "USD")
    down = extract_figures("1—9月份，全国固定资产投资（不含农户）334115亿元，同比下降7.2%", "2026-10-19T10:00:00+08:00")[0]
    assert (down["indicator"], down["value"], down["basis"], down["period"]) == ("fai", -7.2, "ytd", "2026-09")
    cpi = extract_figures("2026年10月份，全国居民消费价格同比上涨0.7%。10月份，全国居民消费价格环比持平。", AT)
    assert [(f["metric_id"], f["value"]) for f in cpi] == [("cn_cpi_yoy", 0.7)]
    jan = extract_figures("12月份CPI同比上涨0.5%", "2027-01-09T09:30:00+08:00")[0]
    assert jan["period"] == "2026-12"                                    # December is reported in January


def test_foreign_regional_and_product_figures_are_not_china_aggregates():
    assert not extract_figures("美国10月核心CPI环比上涨0.3%超预期", AT)
    assert not extract_figures("中国10月原油进口4,193.8万吨，同比下降13.3%", AT)
    assert not extract_figures("10月乘用车出口量同比增长68.5%", AT)
    assert not extract_figures("截至2026年9月末，西藏本外币各项贷款余额7975.8亿元，同比增长17.5%", AT)


def test_policy_action_names_issuer_action_and_size():
    rrr = extract_action("中国人民银行决定下调金融机构存款准备金率0.5个百分点，自2026年11月15日起执行")
    assert (rrr["issuer"], rrr["kind"], rrr["rate"], rrr["effective"]) == ("PBOC", "rrr_cut", "0.5个百分点", "11月15日")
    tariff = extract_action("国务院关税税则委员会：在2个月内继续暂停实施24%的对美加征关税税率")
    assert (tariff["issuer"], tariff["kind"]) == ("TARIFF", "tariff")
    assert extract_action("美联储理事沃勒：12月应加息50基点") is None
    assert extract_action("一份通知印发") is None                         # a document needs a named issuer


def _news_dir(tmp_path):
    """Four real-shaped reports: a media figure, the official first print plus media coverage of it, a policy action."""
    def item(i, publisher, tier, url, at, title, summary="", event="evt-x"):
        return {"item_id": i, "publisher": publisher, "source_tier": tier, "canonical_url": url, "published_at": at,
                "first_seen_at": "2026-11-10T03:00:00+00:00", "title_zh": title, "summary_zh": summary,
                "metric_ids": [], "event_id": event}
    items = [
        item("n1", "华尔街见闻", "T2", "https://wallstreetcn.com/livenews/1", "2026-11-10T10:30:00+08:00",
             "中国10月出口同比(按美元计) 35.2%，前值 36.3%", "", "evt-trade"),
        item("n2", "国家统计局", "T1", "https://www.stats.gov.cn/sj/zxfb/202611/t20261109_1.html", "2026-11-09T09:30:00+08:00",
             "2026年10月份居民消费价格同比上涨0.7%", "2026年10月份，全国居民消费价格同比上涨0.7%。", "evt-cpi"),
        item("n3", "东方财富", "T2", "https://finance.eastmoney.com/a/1.html", "2026-11-09T09:40:00+08:00",
             "国家统计局：10月CPI同比上涨0.7%", "10月份居民消费价格指数（CPI）同比上涨0.7%。", "evt-cpi"),
        item("n4", "中国人民银行", "T1", "https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/1/index.html",
             "2026-11-03T17:00:00+08:00", "中国人民银行决定上调金融机构外汇存款准备金率",
             "为加强金融机构外汇流动性管理，中国人民银行决定，自2026年11月15日起，上调金融机构外汇存款准备金率2个百分点。", "evt-pboc"),
    ]
    events = [{"event_id": e, "title_zh": t, "summary_zh": "", "url": u, "publisher": p, "official": o,
               "topic": tp, "items": ids, "publishers": []}
              for e, t, u, p, o, tp, ids in [
                  ("evt-trade", items[0]["title_zh"], items[0]["canonical_url"], "华尔街见闻", False, "trade", ["n1"]),
                  ("evt-cpi", items[1]["title_zh"], items[1]["canonical_url"], "国家统计局", True, "prices", ["n2", "n3"]),
                  ("evt-pboc", items[3]["title_zh"], items[3]["canonical_url"], "中国人民银行", True, "credit", ["n4"])]]
    (tmp_path / "archive").mkdir()
    (tmp_path / "latest.json").write_text(json.dumps({"events": events, "items": items}, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_news_to_occurrence_to_calendar_to_research_inputs(model, tmp_path):
    news = _news_dir(tmp_path)
    occ = {o["occurrence_id"]: o for o in build_occurrences(news, None, "2026-11-11T06:00:00Z")}
    assert set(occ) == {"evt-trade", "evt-cpi", "evt-pboc"} and all(material(o) for o in occ.values())
    assert occ["evt-cpi"]["publishers"] == ["东方财富", "国家统计局"]       # one occurrence, two outlets
    assert [f["publisher"] for f in occ["evt-cpi"]["figures"]] == ["国家统计局"]  # first party leads, copy dropped
    assert occ["evt-pboc"]["action"]["kind"] == "rrr_hike" and occ["evt-pboc"]["kind"] == "policy"
    assert occ["evt-trade"]["figures"][0]["publisher"] == "华尔街见闻"      # media alone is enough to show a report

    releases = [{"name": "2026-10 CPI (居民消费价格指数月度报告)", "period": "2026-10", "release": "2026-11-09T09:30:00+08:00",
                 "metrics": ["cn_cpi_yoy"], "url": "https://www.stats.gov.cn/sj/fbrc/"}]
    gacc = [{"source": "GACC", "kind": "gacc_flash", "period": "2026-10", "published": "2026-11-10",
             "url": "http://english.customs.gov.cn/Statics/oct.html"}]
    cal = build_calendar({**model, "release_calendar": releases, "official_publications": gacc},
                         "2026-11-11T06:00:00Z", occurrences=list(occ.values()))
    assert len(cal) == 3                                                  # CPI and trade coverage folded into releases
    cpi = next(e for e in cal if e["kinds"] == ["cpi"])
    assert set(cpi["occurrence_ids"]) == {"evt-cpi"} and {c["publisher"] for c in cpi["coverage"]} == {"国家统计局", "东方财富"}
    trade = next(e for e in cal if e["kinds"] == ["gacc_flash"])
    assert [(f["metric_id"], f["value"], f["publisher"]) for f in trade["reported"]] == [("cn_exports_usd_yoy", 35.2, "华尔街见闻")]
    policy = next(e for e in cal if e["kind"] == "policy")
    assert (policy["date"], policy["time"], policy["action"]["rate"]) == ("2026-11-03", "17:00", "2个百分点")
    for loc in ("zh", "en"):
        short = calendar_view(policy, View(model, loc))["short"]
        assert short == ("人民银行上调准备金率" if loc == "zh" else "PBoC Reserve ratio raised")

    start, end = stamp("2026-11-04T00:00:00Z"), stamp("2026-11-11T06:00:00Z")
    rows = {x["event_id"]: x for x in _news(news, start, end, end, {"cn_exports_usd_yoy", "cn_cpi_yoy"}, {})}
    assert rows["evt-trade"]["triage"] == "monitor" and rows["evt-trade"]["hypotheses"] == ["H4"]
    assert rows["evt-trade"]["reported_figures"][0]["span"] == "出口同比(按美元计) 35.2%，前值 36.3%"
    assert "cn_exports_usd_yoy" in rows["evt-trade"]["linked_metrics"]
    assert rows["evt-cpi"]["reported_figures"][0]["metric_id"] == "cn_cpi_yoy"
