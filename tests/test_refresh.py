"""Public refresh pipeline: due detection, append-only dedupe, and an end-to-end historical replay."""
import json
from pathlib import Path

import pandas as pd

from cnmacro.refresh import Paths, due_metrics, new_rows, suggested_direction
from cnmacro.replay import BANNER, replay
from cnmacro.store import load_dictionary, load_observations

ROOT = Path(__file__).resolve().parents[1]
FX = Path(__file__).parent / "fixtures"


def _row(mid, period, value):
    return {"metric_id": mid, "reference_period": period, "value": value, "release_date": "2026-10-14",
            "release_date_basis": "official_calendar", "retrieved_at": "2026-10-14T02:00:00+00:00",
            "source": "TEST", "source_code": "", "source_class": "public", "consensus": "",
            "quality_flag": "ok", "limitation": ""}


def test_new_rows_keeps_only_new_periods_and_revisions():
    obs = load_observations(FX / "observations")
    held = obs[obs.metric_id == "fx_ppi_yoy"].iloc[0]
    rows = [_row("fx_ppi_yoy", held.reference_period, held.value),           # unchanged: dropped
            _row("fx_ppi_yoy", held.reference_period, held.value),           # duplicate in batch: dropped
            _row("fx_ppi_yoy", "2027-01", 1.0)]                              # new period: kept
    revised = _row("fx_ppi_yoy", held.reference_period, held.value + 0.3)    # revised value: kept as vintage
    out = new_rows(rows, obs)
    assert [(r["reference_period"]) for r in out] == ["2027-01"]
    rev = new_rows([revised], obs)[0]
    assert rev["quality_flag"] == "revised" and rev["release_date"] == "" and "earlier vintage" in rev["limitation"]


def test_due_metrics_follow_the_official_calendar():
    metrics = load_dictionary(ROOT / "data/dictionary/metrics.yaml")
    obs = load_observations(ROOT / "data/demo/observations")
    # the information set before the release (the store is append-only, so this stays true after it lands)
    obs = obs[pd.to_datetime(obs.retrieved_at, utc=True) < pd.Timestamp("2026-10-14 01:00", tz="UTC")]
    cal = {("cn_cpi_yoy", "2026-09"): ("2026-10-14T09:30:00+08:00", "")}
    before = due_metrics(metrics, obs, cal, pd.Timestamp("2026-10-14 01:00"))   # 09:00 Beijing
    after = due_metrics(metrics, obs, cal, pd.Timestamp("2026-10-14 02:00"))    # 10:00 Beijing
    assert "cn_cpi_yoy" not in before
    assert after["cn_cpi_yoy"] == {"route": "nbs", "held": "2026-08", "expected": "2026-09"}
    assert "cn_cgb10y" not in after  # licensed series are never fetched by the public refresh


def test_suggested_direction_is_mechanical():
    flips = [{"hypothesis": "H2", "effect_from": "challenges", "effect_to": "supports"},
             {"hypothesis": "H0", "effect_from": "challenges", "effect_to": "supports"}]
    assert suggested_direction(flips)["direction"] == "neutral"
    assert suggested_direction(flips[:1])["direction"] == "toward_thesis"


def test_replay_of_a_published_release_runs_the_whole_update_path(tmp_path):
    live = Paths.default(ROOT)
    live_refreshes = sorted((live.case_dir / "refreshes").glob("*.json"))
    rep = replay("2026-08-09", tmp_path / "replay", root=ROOT, log=lambda *_: None)

    assert rep["arrived"] and all(a.endswith("@2026-07") for a in rep["arrived"])
    assert rep["refresh"]["status"] == "refreshed" and rep["refresh"]["new_rows"] == len(rep["arrived"])
    assert {"T-H1-01", "T-H2-01"} <= set(rep["refresh"]["flipped"])
    assert "fail" not in rep["refresh"]["eval"].values()
    record = json.loads(Path(rep["refresh"]["record"]).read_text(encoding="utf-8"))
    assert record["analyst_judgment"]["changed_by_this_refresh"] is False
    assert rep["rerun"] == {"status": "no_new_data", "new_rows": 0, "record": None}
    # the same six pages in each language, plus the root selector and the legacy redirects
    pages = {loc: {p.split("/", 1)[1] for p in rep["site_pages"] if p.startswith(loc + "/")} for loc in ("en", "zh")}
    assert pages["en"] == pages["zh"] and len(pages["en"]) == 6 and "index.html" in rep["site_pages"]
    for loc in ("en", "zh"):
        page = (tmp_path / f"replay/site/{loc}/updates.html").read_text(encoding="utf-8")
        assert BANNER.split(":")[0] in page and "T-H1-01" in page
    # the live case is untouched
    assert sorted((live.case_dir / "refreshes").glob("*.json")) == live_refreshes


# ---------------------------------------------------------------- NBS press-release route
def _release_page(rows, copies=2, stamp="2026/10/14 09:30"):
    """Minimal NBS release page: the 主要数据 table as NBS lays it out (header with <br />, labels
    with '其中：' / '一、' prefixes and spaced characters), repeated for the desktop and mobile copies."""
    head = ("<tr><td><p> </p></td><td><p>环比涨跌幅</p><p>（%）</p></td><td><p>同比涨跌幅<br />（%）</p></td>"
            "<td><p>1—9月</p><p>同比涨跌幅</p><p>（%）</p></td></tr>")
    body = "".join(f"<tr><td><p><span>{lab}</span></p></td>" + "".join(f"<td><p>{v}</p></td>" for v in vals) + "</tr>"
                   for lab, vals in rows)
    table = f"<table><tbody>{head}{body}</tbody></table>"
    return f"<html><body><div>{stamp}</div>{table * copies}</body></html>"


CPI_ROWS = [("居民消费价格", ("0.2", "0.9", "0.9")), ("其中：食品", ("0.4", "-1.7", "-0.9")),
            ("其中：不包括食品和能源", ("0.0", "1.0", "1.1")), ("粮 食", ("-0.1", "-0.6", "-0.4"))]
PPI_ROWS = [("一、工业生产者出厂价格", ("1.2", "5.0", "2.3")), ("生产资料", ("1.4", "6.5", "3.3")),
            ("生活资料", ("0.1", "-0.1", "-1.0")), ("食品", ("0.2", "-1.8", "-1.9")),
            ("二、工业生产者购进价格", ("1.2", "6.9", "3.6"))]
LISTING = ("<a class='x' href=\"./202610/t20261014_1965477.html\" target=\"_blank\" title='2026年9月份居民消费价格同比上涨0.9%'>x</a>"
           "<a href=\"./202610/t20261014_1965476.html\" target=\"_blank\" title='2026年9月份工业生产者出厂价格同比上涨5.0% 环比上涨1.2%'>x</a>"
           "<a href=\"./202609/t20260909_1965263.html\" target=\"_blank\" title='2026年8月份居民消费价格同比上涨0.8%'>x</a>"
           "<a href=\"./202610/t20261013_1.html\" target=\"_blank\" title='2026年9月份能源生产情况'>x</a>")


def test_nbs_release_table_is_read_by_row_label_and_column_header():
    from cnmacro.ingest import parse_nbs_release
    cpi, released = parse_nbs_release(_release_page(CPI_ROWS), "居民消费价格")
    assert cpi == {"cn_cpi_yoy": 0.9, "cn_core_cpi_yoy": 1.0} and released == "2026-10-14T09:30:00+08:00"
    ppi, _ = parse_nbs_release(_release_page(PPI_ROWS, copies=1), "工业生产者出厂价格")
    assert ppi == {"cn_ppi_yoy": 5.0, "cn_ppi_mom": 1.2, "cn_ppi_producer_yoy": 6.5, "cn_ppi_consumer_yoy": -0.1}


def test_nbs_release_layout_change_fails_loudly_instead_of_guessing():
    import pytest
    from cnmacro.ingest import parse_nbs_release
    with pytest.raises(ValueError, match="cannot locate cn_core_cpi_yoy"):
        parse_nbs_release(_release_page(CPI_ROWS[:2]), "居民消费价格")
    copies = _release_page(CPI_ROWS, copies=1) + _release_page([("居民消费价格", ("0.2", "0.7", "0.9"))] + CPI_ROWS[1:], copies=1)
    with pytest.raises(ValueError, match="disagree"):
        parse_nbs_release(copies, "居民消费价格")
    with pytest.raises(ValueError, match="no 环比/同比 table header"):
        parse_nbs_release("<table><tr><td>居民消费价格</td><td>0.9</td></tr></table>", "居民消费价格")


def test_nbs_release_rows_fill_only_periods_the_store_lacks(monkeypatch):
    from cnmacro import ingest
    pages = {ingest.NBS_RELEASES: LISTING,
             ingest.NBS_RELEASES + "202610/t20261014_1965477.html": _release_page(CPI_ROWS),
             ingest.NBS_RELEASES + "202610/t20261014_1965476.html": _release_page(PPI_ROWS)}
    fetched = []
    monkeypatch.setattr(ingest, "_get", lambda url, **_: fetched.append(url) or pages[url].encode("utf-8"))
    metrics = load_dictionary(ROOT / "data/dictionary/metrics.yaml")
    ms = [metrics[m] for m in ("cn_cpi_yoy", "cn_ppi_yoy", "cn_m1_yoy")]
    rows = ingest.nbs_release_rows(ms, {"cn_cpi_yoy": "2026-08", "cn_ppi_yoy": "2026-09", "cn_m1_yoy": "2026-08"},
                                   {}, got="2026-10-14T03:00:00+00:00")
    assert [(r["metric_id"], r["reference_period"], r["value"]) for r in rows] == [("cn_cpi_yoy", "2026-09", 0.9)]
    r = rows[0]
    assert r["source"] == "NBS" and r["source_class"] == "public" and r["source_code"].endswith("t20261014_1965477.html")
    assert r["release_date"] == "2026-10-14T09:30:00+08:00" and r["release_date_basis"] == "source_field"
    assert "press release" in r["limitation"]
    # the PPI page is not fetched (2026-09 already held); the August CPI page is older than what is held
    assert not any(u.endswith(("1965476.html", "1965263.html")) for u in fetched)
    # a listing whose markup is no longer recognised fails loudly instead of returning nothing
    import pytest
    pages[ingest.NBS_RELEASES] = LISTING.replace("title='", 'title="').replace("%'", '%"')
    with pytest.raises(ValueError, match="no CPI/PPI release link"):
        ingest.nbs_release_rows(ms, {"cn_cpi_yoy": "2026-08"}, {}, got="2026-10-14T03:00:00+00:00")


def test_press_release_rows_join_the_nbs_route_and_each_half_fails_on_its_own(monkeypatch):
    from cnmacro import ingest
    metrics = load_dictionary(ROOT / "data/dictionary/metrics.yaml")
    cpi, m1 = metrics["cn_cpi_yoy"], metrics["cn_m1_yoy"]
    first = _row("cn_cpi_yoy", "2026-09", 0.9)
    monkeypatch.setattr(ingest, "nbs_release_rows", lambda ms, *_: [first])
    portal = {"nbs_cn_cpi_yoy.csv": []}
    seen, logs = [], []

    def base(route, ms, *_):
        seen.append(route)
        return portal

    fetch = ingest.with_nbs_release(base, log=logs.append)
    assert fetch("nbs", [cpi], {}, metrics, {}, "t") == {**portal, "nbs_release.csv": [first]}
    assert fetch("nbs", [m1], {}, metrics, {}, "t") == portal          # not a CPI/PPI metric: portal only
    assert fetch("fred", [cpi], {}, metrics, {}, "t") == portal        # other routes pass through
    assert seen == ["nbs", "nbs", "fred"]

    def broken(*_):
        raise RuntimeError("down")

    # portal down on release day: the first print is kept, and the failure is logged
    assert ingest.with_nbs_release(broken, log=logs.append)("nbs", [cpi], {}, metrics, {}, "t") == {"nbs_release.csv": [first]}
    assert any("data portal): FAILED" in x for x in logs)
    # press release down: the portal rows are kept
    monkeypatch.setattr(ingest, "nbs_release_rows", broken)
    assert ingest.with_nbs_release(base, log=logs.append)("nbs", [cpi], {}, metrics, {}, "t") == portal
    assert any("press release): FAILED" in x for x in logs)
    # both down: the route fails, as before
    import pytest
    with pytest.raises(RuntimeError):
        ingest.with_nbs_release(broken, log=logs.append)("nbs", [cpi], {}, metrics, {}, "t")


def test_a_new_refresh_record_is_not_credited_with_the_previous_records_commit(tmp_path, monkeypatch):
    """git log --follow reports a new file that resembles an existing one as its copy. Every refresh record resembles
    the previous one, so E4 counted the second record as edited after its first commit and failed the next refresh."""
    import subprocess
    from cnmacro import checks

    def git(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    body = "".join(f'  "line_{i}": {i},\n' for i in range(60))
    (tmp_path / "2026-10-09T1036Z.json").write_text("{\n" + body + '  "as_of": "2026-10-09"\n}\n', encoding="utf-8")
    git("add", "."), git("commit", "-qm", "first refresh")
    (tmp_path / "2026-10-14T0457Z.json").write_text("{\n" + body + '  "as_of": "2026-10-14"\n}\n', encoding="utf-8")
    git("add", "."), git("commit", "-qm", "second refresh")
    monkeypatch.chdir(tmp_path)
    assert len(checks.git_history(Path("2026-10-14T0457Z.json"))) == 1
    assert len(checks.git_history(Path("2026-10-09T1036Z.json"))) == 1
    (tmp_path / "2026-10-14T0457Z.json").write_text("{}\n", encoding="utf-8")       # a real edit is still caught
    git("commit", "-qam", "edit")
    assert len(checks.git_history(Path("2026-10-14T0457Z.json"))) == 2
