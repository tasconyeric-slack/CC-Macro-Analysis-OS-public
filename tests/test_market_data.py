"""Market data ingest: skip-not-guess behaviour, vintages, derived slope, token hygiene, cross-checks."""
import json
import shutil
from datetime import date, timedelta

import pytest
import yaml

from cnmacro import market_crosscheck as xc
from cnmacro import market_data as md
from cnmacro import tushare_client as tc
from cnmacro.store import OBS_COLUMNS, load_dictionary, load_observations
from conftest import ROOT

TODAY = date(2026, 11, 9)


def weekdays(params):
    a = date.fromisoformat(md.iso(params["start_date"]))
    b = date.fromisoformat(md.iso(params["end_date"]))
    d = a
    while d <= b:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def level(d, base):
    return round(base + (d - date(2026, 1, 1)).days * 0.001, 4)


class FakeTushare:
    """Deterministic stand-in for tc.call: every endpoint answers for weekdays only."""

    def __init__(self, deny=(), tweak=None):
        self.calls, self.deny, self.tweak = [], set(deny), tweak or {}

    def __call__(self, api, params, fields=None):
        self.calls.append((api, dict(params)))
        if api in self.deny:
            raise tc.TushareError(tc.NOT_PERMITTED, "抱歉，您没有接口访问权限")
        rows = []
        for d in weekdays(params):
            s = d.strftime("%Y%m%d")
            bump = self.tweak.get((api, s), 0.0)
            if api == "yc_cb":
                base = 1.1 if str(params["curve_term"]) == "1" else 1.6
                rows.append({"trade_date": s, "yield": level(d, base) + bump})
            elif api == "shibor":
                rows.append({"date": md.iso(s), "on": level(d, 1.3), "1w": level(d, 1.35), "3m": level(d, 1.5), "1y": level(d, 1.6)})
            elif api == "hibor":
                rows.append({"date": md.iso(s), "on": level(d, 2.4), "3m": level(d, 3.1)})
            elif api == "us_tycr":
                rows.append({"date": md.iso(s), "y1": level(d, 3.5), "y10": level(d, 4.0) + bump})
            elif api == "us_trycr":
                rows.append({"date": md.iso(s), "y10": level(d, 2.6)})
            elif api == "fx_daily":
                rows.append({"trade_date": s, "bid_close": level(d, 7.0), "ask_close": level(d, 7.0) + 0.0004})
            elif api in ("index_daily", "sw_daily"):
                rows.append({"trade_date": s, "close": level(d, 4000)})
            elif api == "fut_mapping":
                rows.append({"trade_date": s, "ts_code": params["ts_code"], "mapping_ts_code": "CU2701.SHF"})
            elif api == "fut_daily":
                rows.append({"trade_date": s, "ts_code": params["ts_code"], "close": level(d, 80000)})
        return rows


def make_root(path, with_parked=False):
    (path / "data/dictionary").mkdir(parents=True)
    shutil.copy(ROOT / "data/dictionary/metrics.yaml", path / "data/dictionary/metrics.yaml")
    spec_text = (ROOT / "data/dictionary/market_series.yaml").read_text(encoding="utf-8")
    if with_parked:     # what enabling the parked series after a points upgrade would look like
        spec = yaml.safe_load(spec_text)
        metrics = yaml.safe_load((path / "data/dictionary/metrics.yaml").read_text(encoding="utf-8"))
        for item in spec.pop("parked"):
            spec["series"].append(item["series"])
            metrics["metrics"].append(item["metric"])
        spec_text = yaml.safe_dump(spec, allow_unicode=True)
        (path / "data/dictionary/metrics.yaml").write_text(yaml.safe_dump(metrics, allow_unicode=True), encoding="utf-8")
    (path / "data/dictionary/market_series.yaml").write_text(spec_text, encoding="utf-8")
    (path / "data/demo/observations").mkdir(parents=True)
    return path


@pytest.fixture()
def root(tmp_path):
    return make_root(tmp_path)


@pytest.fixture()
def root_all(tmp_path):
    return make_root(tmp_path, with_parked=True)


def run(root, call, **kw):
    return md.refresh_market(root, call=call, today=TODAY, log=lambda *_: None, now="2026-11-09T12:30:00+00:00", **kw)


def stored(root):
    return load_observations(root / "data/demo/observations")


def test_every_configured_series_has_a_public_metric_with_the_markets_category():
    spec = md.load_spec(ROOT)
    metrics = load_dictionary(ROOT / "data/dictionary/metrics.yaml")
    assert len(spec["series"]) >= 8
    for s in spec["series"]:
        m = metrics[s["metric_id"]]
        assert (m.category, m.frequency, m.redistribution, m.source_primary) == ("markets", "D", "public", "Tushare")
        assert m.name_zh and m.role_zh


def test_first_run_backfills_and_writes_schema_valid_rows(root):
    summary = run(root, FakeTushare())
    obs = stored(root)
    assert summary["new_rows"] == len(obs) > 0
    assert set(OBS_COLUMNS) <= set(obs.columns)
    assert {s["status"] for s in summary["series"].values()} == {"ok"}
    row = obs[obs.metric_id == "mk_ust10y"].sort_values("reference_period").iloc[-1]
    assert (row.source, row.source_class, row.release_date_basis, row.quality_flag) == ("Tushare", "public", "unknown", "ok")
    assert row.limitation and row.retrieved_at == "2026-11-09T12:30:00+00:00"
    assert obs.reference_period.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()
    # history starts at the configured date, not at the first lookback window
    assert obs[obs.metric_id == "mk_ust10y"].reference_period.min() >= md.load_spec(root)["history_start"]


def test_slope_is_the_stored_difference_of_the_two_yields(root):
    run(root, FakeTushare())
    obs = stored(root)
    ten = obs[obs.metric_id == "mk_ust10y"].set_index("reference_period").value
    one = obs[obs.metric_id == "mk_ust1y"].set_index("reference_period").value
    slope = obs[obs.metric_id == "mk_ust_slope_10y_1y"].set_index("reference_period").value
    assert len(slope) == len(ten) and (slope - (ten - one).round(4)).abs().max() < 1e-9


def test_parked_futures_and_yield_curve_series_work_once_enabled(root_all):
    """The account cannot call these interfaces today; the fetchers stay tested so a points upgrade is a spec edit."""
    call = FakeTushare()
    run(root_all, call)
    root = root_all
    assert any(api == "fut_daily" and p["ts_code"] == "CU2701.SHF" for api, p in call.calls)
    assert not stored(root)[lambda d: d.metric_id == "mk_copper_main"].empty
    assert not stored(root)[lambda d: d.metric_id == "mk_cn_gov_10y"].empty


def test_second_run_is_a_no_op_and_a_revision_becomes_a_new_vintage(root):
    run(root, FakeTushare())
    before = len(stored(root))
    again = run(root, FakeTushare())
    assert again["new_rows"] == 0 and len(stored(root)) == before        # idempotent, lookback only
    revised = run(root, FakeTushare(tweak={("us_tycr", "20261106"): 0.05}))
    obs = stored(root)
    assert revised["new_rows"] >= 1
    rows = obs[(obs.metric_id == "mk_ust10y") & (obs.reference_period == "2026-11-06")]
    assert (rows.quality_flag == "revised").any() and (rows.quality_flag == "ok").any()   # old vintage kept


def test_dry_run_writes_nothing(root):
    summary = run(root, FakeTushare(), dry_run=True)
    assert summary["new_rows"] > 0 and not list((root / "data/demo/observations").glob("*.csv"))


def test_not_permitted_endpoint_skips_only_its_series(root_all):
    root = root_all
    summary = run(root, FakeTushare(deny={"sw_daily"}))
    states = {mid: s["status"] for mid, s in summary["series"].items()}
    assert states["mk_sw_coal"] == "skipped" and states["mk_ust10y"] == "ok"
    assert summary["series"]["mk_sw_coal"]["reason"] == tc.NOT_PERMITTED
    assert stored(root)[lambda d: d.metric_id.str.startswith("mk_sw_")].empty     # never substituted


def test_missing_token_skips_everything_and_stays_green(root, monkeypatch):
    monkeypatch.delenv(tc.TOKEN_ENV, raising=False)
    summary = md.refresh_market(root, today=TODAY, log=lambda *_: None)
    assert summary["token_present"] is False and summary["new_rows"] == 0
    assert {s["reason"] for s in summary["series"].values()} == {tc.MISSING_TOKEN}
    assert not list((root / "data/demo/observations").glob("*.csv"))


def test_client_without_token_raises_a_classified_error(monkeypatch):
    monkeypatch.delenv(tc.TOKEN_ENV, raising=False)
    with pytest.raises(tc.TushareError) as err:
        tc.call("shibor", {})
    assert err.value.kind == tc.MISSING_TOKEN


def test_client_never_leaks_the_token_and_classifies_errors():
    secret = "t0ken-" + "x" * 30

    class Reply:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def opener(payload):
        return lambda req, timeout: Reply(payload)

    with pytest.raises(tc.TushareError) as err:
        tc.call("yc_cb", {}, token=secret, opener=opener({"code": 2002, "msg": f"抱歉，您没有接口访问权限 {secret}"}))
    assert err.value.kind == tc.NOT_PERMITTED and secret not in str(err.value)
    with pytest.raises(tc.TushareError) as err:
        tc.call("yc_cb", {}, token=secret, retries=0, opener=opener({"code": 40203, "msg": "抱歉，您访问接口(yc_cb)频率超限(2次/分钟)"}))
    assert err.value.kind == tc.RATE_LIMITED
    rows = tc.call("shibor", {}, token=secret, opener=opener({"code": 0, "data": {"fields": ["date", "on"], "items": [["20261109", 1.3]]}}))
    assert rows == [{"date": "20261109", "on": 1.3}]


def test_no_written_artifact_contains_the_token(root, monkeypatch):
    secret = "t0ken-" + "y" * 30
    monkeypatch.setenv(tc.TOKEN_ENV, secret)
    summary = md.run_market(root, call=FakeTushare(), today=TODAY, log=lambda *_: None,
                            now="2026-11-09T12:30:00+00:00", crosscheck=lambda stored, log, active: [])
    blob = json.dumps(summary) + "".join(p.read_text(encoding="utf-8") for p in root.rglob("*") if p.is_file() and p.suffix in (".csv", ".json"))
    assert secret not in blob


# ---------------------------------------------------------------- cross-checks (fixtures are real captured pages)
FIX = ROOT / "tests/fixtures/market"


def test_chinabond_page_parses_the_treasury_row():
    date_, curve = xc.parse_chinabond((FIX / "chinabond_pbc_more.html").read_text(encoding="utf-8"))
    assert date_ == "2026-11-09" and curve[1] == 1.1667 and curve[10] == 1.5874


def test_chinabond_parser_refuses_a_page_with_another_first_row():
    page = (FIX / "chinabond_pbc_more.html").read_text(encoding="utf-8").replace("中债国债收益率曲线", "中债商业银行普通债收益率曲线(AAA)", 1)
    with pytest.raises(ValueError, match="not the treasury curve"):
        xc.parse_chinabond(page)


def test_cfets_history_parses_dated_central_parity():
    parity = xc.parse_cfets((FIX / "cfets_ccpr_history.json").read_text(encoding="utf-8"))
    assert parity["2026-11-09"] == 6.7188 and len(parity) == 10


def test_compare_flags_a_gap_without_touching_anything():
    ok = xc.compare("mk_cn_gov_10y", "2026-11-09", 1.5874, {"2026-11-09": 1.5874})
    gap = xc.compare("mk_cn_gov_10y", "2026-11-09", 1.5874, {"2026-11-09": 1.62})
    pending = xc.compare("mk_cn_gov_10y", "2026-11-09", 1.5874, {"2026-11-06": 1.58})
    fx = xc.compare("mk_usdcnh", "2026-11-09", 6.7188, {"2026-11-09": 6.74})
    fx_gap = xc.compare("mk_usdcnh", "2026-11-09", 6.7188, {"2026-11-09": 6.80})
    assert (ok["status"], gap["status"], pending["status"], fx["status"], fx_gap["status"]) == ("ok", "gap", "pending", "ok", "gap")
    assert gap["difference"] == pytest.approx(0.0326) and pending["tushare_value"] is None


def test_run_crosschecks_reports_unreachable_pages_without_raising():
    def offline(url, timeout=40):
        raise OSError("blocked")
    logs = []
    results = xc.run_crosschecks({}, fetch=offline, log=logs.append)
    pages = [r for r in results if r["official_source"] in ("ChinaBond", "CFETS")]
    assert pages and {r["status"] for r in pages} == {"unavailable"} and any("unavailable" in line for line in logs)


def test_run_crosschecks_end_to_end_with_fixtures():
    pages = {xc.CHINABOND_URL: (FIX / "chinabond_pbc_more.html").read_bytes()}

    def fetch(url, timeout=40):
        return pages.get(url, (FIX / "cfets_ccpr_history.json").read_bytes())
    stored_ = {"mk_cn_gov_10y": {"2026-11-09": 1.5874}, "mk_cn_gov_1y": {"2026-11-09": 1.1667}, "mk_usdcnh": {"2026-11-09": 6.7211}}
    results = {r["metric_id"]: r for r in xc.run_crosschecks(stored_, fetch=fetch, today=date(2026, 11, 10), log=lambda *_: None)}
    assert [results[m]["status"] for m in ("mk_cn_gov_10y", "mk_cn_gov_1y", "mk_usdcnh")] == ["ok", "ok", "ok"]


def test_hourly_rate_limit_is_not_waited_out_but_per_minute_limit_is(monkeypatch):
    waits = []
    monkeypatch.setattr(tc.time, "sleep", lambda s: waits.append(s))

    class Reply:
        def __init__(self, msg):
            self.msg = msg

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"code": 40203, "msg": self.msg}).encode()

    with pytest.raises(tc.TushareError) as err:
        tc.call("shibor", {}, token="t", opener=lambda req, timeout: Reply("抱歉，您访问接口(shibor)频率超限(1次/小时)"))
    assert err.value.kind == tc.RATE_LIMITED and waits == []
    with pytest.raises(tc.TushareError):
        tc.call("shibor", {}, token="t", opener=lambda req, timeout: Reply("抱歉，您访问接口(shibor)频率超限(2次/分钟)"))
    assert waits == [62.0, 62.0]


def test_each_interface_is_read_in_one_call_for_the_default_history(root):
    call = FakeTushare()
    run(root, call)
    per_api = {}
    for api, p in call.calls:
        if api in ("shibor", "us_tycr", "index_daily", "hibor", "us_trycr"):
            per_api.setdefault((api, p.get("ts_code")), []).append(p)
    assert all(len(v) == 1 for v in per_api.values()), per_api


# ---------------------------------------------------------------- FRED monthly cross-check (no web page involved)
def month_of(value, month, days=20):
    return {f"{month}-{d:02d}": value for d in range(1, days + 1)}


def test_monthly_mean_matches_fred_within_tolerance_or_reports_a_gap():
    daily = {**month_of(4.60, "2026-09"), **month_of(5.10, "2026-10")}
    ok = xc.compare_monthly("mk_ust10y", daily, {"2026-09": 4.60, "2026-10": 5.12})
    gap = xc.compare_monthly("mk_ust10y", daily, {"2026-09": 4.60, "2026-10": 5.30})
    assert (ok["status"], ok["date"], ok["tushare_value"], ok["official_value"]) == ("ok", "2026-10", 5.1, 5.12)
    assert gap["status"] == "gap" and gap["difference"] == pytest.approx(-0.2)


def test_monthly_check_is_pending_without_enough_days_or_an_official_month():
    short = xc.compare_monthly("mk_ust10y", month_of(5.1, "2026-10", days=5), {"2026-10": 5.1})
    none = xc.compare_monthly("mk_ust10y", month_of(5.1, "2026-11"), {"2026-10": 5.1})
    assert short["status"] == none["status"] == "pending" and short["tushare_value"] is None


def test_crosschecks_cover_only_ingested_series_and_need_no_network_for_fred():
    def offline(url, timeout=40):
        raise AssertionError("no page may be fetched: the ChinaBond and CFETS series are not ingested")
    stored_ = {"mk_ust10y": month_of(5.1, "2026-10"), "gl_ust10y": {"2026-10": 5.13}}
    results = xc.run_crosschecks(stored_, fetch=offline, log=lambda *_: None, active={"mk_ust10y", "mk_csi300"})
    assert [(r["metric_id"], r["status"]) for r in results] == [("mk_ust10y", "ok")]


def test_run_market_writes_a_crosscheck_record_when_rows_were_added(root):
    header = ",".join(OBS_COLUMNS)
    row = "gl_ust10y,2026-10,5.13,,unknown,2026-11-08T15:26:30+00:00,FRED,GS10,public,,ok,x"
    (root / "data/demo/observations/fred_gl_ust10y.csv").write_text(header + "\n" + row + "\n", encoding="utf-8")
    summary = md.run_market(root, call=FakeTushare(), today=TODAY, log=lambda *_: None, now="2026-11-09T12:30:00+00:00")
    files = list((root / "data/market/crosschecks").glob("*.json"))
    assert len(files) == 1 and summary["crosschecks"][0]["metric_id"] == "mk_ust10y"
    again = md.run_market(root, call=FakeTushare(), today=TODAY, log=lambda *_: None, now="2026-11-09T13:30:00+00:00")
    assert again["new_rows"] == 0 and len(list((root / "data/market/crosschecks").glob("*.json"))) == 1


# ---------------------------------------------------------------- quota safety (one call per interface per hour)
class Refusing(FakeTushare):
    """Answers like the Owner's account after its allowance is used: a refusal per interface."""

    def __init__(self, refuse: dict[str, tuple[str, str]], **kw):
        super().__init__(**kw)
        self.refuse = refuse

    def __call__(self, api, params, fields=None):
        if api in self.refuse:
            self.calls.append((api, dict(params)))
            kind, msg = self.refuse[api]
            raise tc.TushareError(kind, msg)
        return super().__call__(api, params, fields)


def test_a_rate_limited_interface_is_requested_once_per_run_and_other_interfaces_still_run(root):
    call = Refusing({"shibor": (tc.RATE_LIMITED, "抱歉，您访问接口(shibor)频率超限(1次/小时)")})
    summary = run(root, call, dry_run=True)
    assert [api for api, _ in call.calls].count("shibor") == 1          # four SHIBOR series, one request
    shibor = {m: v for m, v in summary["series"].items() if m.startswith("mk_shibor")}
    assert len(shibor) == 4 and all(v["reason"] == tc.RATE_LIMITED and v["interface"] == "shibor" for v in shibor.values())
    assert summary["series"]["mk_ust10y"]["status"] == "ok" and summary["series"]["mk_csi300"]["status"] == "ok"
    assert summary["requests"].count("shibor") == 1
    assert sorted(md.incomplete(summary)) == ["mk_shibor_1w", "mk_shibor_1y", "mk_shibor_3m", "mk_shibor_on"]


def test_an_invalid_token_stops_every_interface_after_one_request(root):
    call = Refusing({api: (tc.INVALID_TOKEN, "您的token不对，请确认。")
                     for api in ("shibor", "hibor", "us_tycr", "us_trycr", "index_daily")})
    summary = run(root, call, dry_run=True)
    assert len(call.calls) == 1 and summary["requests"] == [call.calls[0][0]]
    assert len(md.incomplete(summary)) == len(md.load_spec(root)["series"])


def test_series_sharing_an_interface_stay_one_request_when_only_some_have_history(root):
    run(root, FakeTushare())
    obs_dir = root / "data/demo/observations"
    (obs_dir / "tushare_mk_shibor_1w.csv").unlink()       # e.g. a tenor added later: no stored rows yet
    call = FakeTushare()
    summary = run(root, call, dry_run=True)
    shibor = [p for api, p in call.calls if api == "shibor"]
    assert len(shibor) == 1 and shibor[0]["start_date"] == "20200101"
    assert summary["series"]["mk_shibor_1w"]["new"] > 0 and summary["series"]["mk_shibor_on"]["new"] == 0
    hibor = [p for api, p in call.calls if api == "hibor"]
    assert len(hibor) == 1 and hibor[0]["start_date"] != "20200101"   # untouched groups keep the short lookback


def test_a_backfill_cut_short_by_a_row_cap_is_reported(root):
    class Capped(FakeTushare):
        def __call__(self, api, params, fields=None):
            rows = super().__call__(api, params, fields)
            return [r for r in rows if str(r.get("date") or r.get("trade_date")).replace("-", "") >= "20230101"] \
                if api == "shibor" else rows
    summary = run(root, Capped(), dry_run=True)
    assert any(w.startswith("mk_shibor_on: history begins 2023-01-02") for w in summary["warnings"])
    assert summary["series"]["mk_shibor_on"]["status"] == "ok"           # reported, not dropped


def test_require_all_turns_a_partial_live_run_into_a_failed_check(monkeypatch, tmp_path, capsys):
    from cnmacro import cli
    import cnmacro.market_data as m
    partial = {"series": {"mk_ust10y": {"status": "ok"}, "mk_shibor_on": {"status": "error", "reason": tc.RATE_LIMITED}},
               "failed": ["mk_shibor_on"], "new_rows": 0}
    monkeypatch.setattr(m, "run_market", lambda *a, **k: partial)
    monkeypatch.setattr(cli.ingest, "sync_clock", lambda **k: None)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["market-refresh", "--dry-run", "--require-all"]) == 3
    assert "mk_shibor_on" in capsys.readouterr().out
    assert cli.main(["market-refresh", "--dry-run"]) == 0                 # scheduled runs report and stay green
