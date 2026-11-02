"""Engine tests on a synthetic fixture (tests/fixtures). Numbers are fake by design."""
from pathlib import Path

import pandas as pd
import pytest

from cnmacro.checks import asof_leakage, citation_integrity, data_quality, derived_lineage
from cnmacro.claims import Binding, Claim, bare_numbers, validate_claim
from cnmacro.derive import Deriver
from cnmacro.evidence import EvidenceTest, evaluate_condition, evaluate_test, terminal_decision
from cnmacro.store import as_of, load_dictionary, load_observations
from cnmacro.thesis import on_grid, validate_update

FX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def metrics():
    return load_dictionary(FX / "dictionary.yaml")


@pytest.fixture(scope="module")
def obs():
    return load_observations(FX / "observations")


def test_as_of_excludes_future_release(obs):
    before = as_of(obs, "2026-10-13")
    after = as_of(obs, "2026-10-15")
    assert "2026-09" not in set(before[before.metric_id == "fx_ppi_yoy"].reference_period)
    assert "2026-09" in set(after[after.metric_id == "fx_ppi_yoy"].reference_period)


def test_single_from_cumulative_handles_jan_feb(obs, metrics):
    d = Deriver(as_of(obs, "2026-10-13"), metrics)
    s = d.single("fx_profit_cum")
    feb, mar, apr = (pd.Period(p, "M") for p in ("2026-02", "2026-03", "2026-04"))
    assert s[feb].value == 100 and s[mar].value == 60 and s[apr].value == 70
    assert s[mar].inputs == ["obs:fx_profit_cum@2026-03", "obs:fx_profit_cum@2026-02"]


def test_deflator_and_resolve(obs, metrics):
    d = Deriver(as_of(obs, "2026-10-13"), metrics)
    pt = d.resolve("drv:deflator_yoy(fx_ngdp_yoy,fx_rgdp_yoy)@2026Q2")
    assert pt.value == pytest.approx((1.046 / 1.05 - 1) * 100)
    assert d.resolve("obs:fx_ppi_yoy@2026-08").value == -1.2
    assert d.resolve("drv:ma(fx_ppi_yoy,3)@2026-08").value == pytest.approx(-1.5)


def test_evidence_test_rules(obs, metrics):
    d = Deriver(as_of(obs, "2026-10-13"), metrics)
    up = EvidenceTest("T1", "H1", "fx_ppi_yoy", "change", ">", 0, n=3, if_true="supports")
    r = evaluate_test(up, d)
    assert r.outcome == "true" and r.effect == "supports" and r.latest_period == "2026-08"
    neg = EvidenceTest("T2", "H1", "fx_ppi_yoy", "streak", ">=", 0, n=2)
    assert evaluate_test(neg, d).effect == "challenges"
    long = EvidenceTest("T3", "H1", "fx_ppi_yoy", "streak", ">", -9, n=99)
    assert evaluate_test(long, d).outcome == "insufficient_data"


def test_terminal_rules_need_combination_and_window(obs, metrics):
    d = Deriver(as_of(obs, "2026-10-13"), metrics)
    tests = [EvidenceTest("P", "H1", "fx_ppi_yoy", "latest", ">", -2, n=1),
             EvidenceTest("D", "H2", "single(fx_profit_cum)", "latest", ">", 0, n=1)]
    res = {t.id: evaluate_test(t, d) for t in tests}
    rules = {"CONFIRMED": {"when": {"all": [{"test": "P"}, {"test": "D"}]}}}
    assert terminal_decision(rules, res, decision_window_open=False) == "ACTIVE"
    assert terminal_decision(rules, res, decision_window_open=True) == "CONFIRMED"
    never = {"CONFIRMED": {"when": {"test": "P", "is": False}}}
    assert terminal_decision(never, res, decision_window_open=True) == "RETIRED"
    assert evaluate_condition({"at_least": 2, "of": [{"test": "P"}, {"test": "missing"}]}, res) is None


def test_bare_number_lint():
    assert bare_numbers("PPI rose to {ppi} in 2026-08, a 3-month high") == []
    assert bare_numbers("PPI rose to -1.0% in 2026-08") != []
    assert bare_numbers("Deflator in 2026Q2 and H1 test over 10Y") == []
    # the same discipline holds in Chinese, where a figure is glued to the characters around it
    assert bare_numbers("2026年8月PPI同比为{p}，较2025年12月回落", "zh") == []
    assert bare_numbers("PPI同比上涨3.8%", "zh") != []
    assert bare_numbers("PPI同比为-1.9%", "zh") != []


def _claim(as_of_, ref, recorded, ctype="FACT"):
    return Claim(id="C1", type=ctype, text_en="PPI was {v}", text_zh="PPI为{v}", as_of=as_of_, hypotheses=["H1"],
                 values={"v": Binding(ref=ref, recorded=recorded)})


def test_citation_integrity_pass_and_fail(obs, metrics):
    ok = _claim("2026-10-13", "obs:fx_ppi_yoy@2026-08", -1.2)
    bad = _claim("2026-10-13", "obs:fx_ppi_yoy@2026-08", -0.4)
    assert citation_integrity([ok], obs, metrics).status == "pass"
    assert citation_integrity([bad], obs, metrics).status == "fail"
    assert validate_claim(_claim("2026-10-13", "drv:ma(fx_ppi_yoy,3)@2026-08", 0)) != []  # FACT needs obs


def test_leakage_detected(obs, metrics):
    leak = _claim("2026-10-13", "obs:fx_ppi_yoy@2026-09", -0.5)
    assert asof_leakage([leak], obs, metrics).status == "fail"
    fine = _claim("2026-10-15", "obs:fx_ppi_yoy@2026-09", -0.5)
    assert asof_leakage([fine], obs, metrics).status == "pass"


def test_derived_lineage(obs, metrics):
    c = _claim("2026-10-13", "drv:single(fx_profit_cum)@2026-03", 60, ctype="DERIVED")
    assert derived_lineage([c], obs, metrics).status == "pass"


def test_data_quality_flags_missing_provenance(obs, metrics):
    bad = obs.copy()
    bad.loc[0, "limitation"] = ""
    bad.loc[0, "release_date"] = ""
    assert data_quality(bad, metrics).status == "fail"


def test_probability_discipline():
    assert on_grid(0.35) and not on_grid(0.37)
    prev = {"probability": 0.35, "_baseline_file": "b.yaml"}
    silent = {"probability": 0.40, "conviction": "LOW", "status": "ACTIVE",
              "last_update_direction": "STRENGTHENED", "baseline": "b.yaml"}
    assert any("without probability_change" in e for e in validate_update(silent, prev, "u"))
    explained = {**silent, "probability_change": {"previous": 0.35, "new": 0.40, "evidence": ["C1"],
                                                  "hypotheses": ["H1"], "reasoning": "x"}}
    assert validate_update(explained, prev, "u") == []
    early_terminal = {**explained, "status": "FALSIFIED"}
    assert any("terminal_rule_fired" in e for e in validate_update(early_terminal, prev, "u"))


def test_change_window_is_calendar_based(obs, metrics):
    d = Deriver(as_of(obs, "2026-10-13"), metrics)
    t = EvidenceTest("G", "H2", "fx_profit_cum", "change", ">", 0, n=3)  # Apr vs Jan; Jan absent
    assert evaluate_test(t, d).outcome == "insufficient_data"


def test_availability_is_compared_in_utc():
    from cnmacro.store import available_at, release_time
    # 09:30 Beijing is 01:30 UTC: available from then, not from 09:30 UTC
    assert release_time("2026-10-14T09:30:00+08:00") == pd.Timestamp("2026-10-14 01:30")
    # a date-only release date counts from the end of that Beijing day
    assert release_time("2026-10-14") == pd.Timestamp("2026-10-14 15:59:59")
    row = {"release_date": "", "retrieved_at": "2026-10-04T08:00:00+08:00"}
    assert available_at(row) == pd.Timestamp("2026-10-04 00:00")
