"""Private research diagnostics (V1.2 Phase 2): the deterministic signal layer. Synthetic inputs only."""
import copy
import dataclasses
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml
from signal_support import (CITIES, CORP_BROADENING, CORP_WEAKENING, HH_BROADENING, HH_WEAKENING, PRICE_DOWN,
                            PRICE_UP, PROP_DOWN, PROP_UP, ROOT, WHEN, Scenario, frame, public_results)

from cnmacro import signals
from cnmacro.signals import INSUFFICIENT, compute_signals, load_signal_contract
from cnmacro.store import load_dictionary

CONTRACT = ROOT / "data/dictionary/private_signals.yaml"


@pytest.fixture(scope="module")
def metrics():
    return load_dictionary(ROOT / "data/dictionary/metrics.yaml")


@pytest.fixture(scope="module")
def contract(metrics):
    return load_signal_contract(CONTRACT, metrics)


def run(contract, metrics, *scenarios, public=None, when=WHEN):
    return {s.signal_id: s for s in compute_signals(frame(*scenarios), metrics, contract, when, public)}


def contract_with(tmp_path, mutate) -> Path:
    raw = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    mutate({s["signal_id"]: s for s in raw["signals"]}, raw)
    p = tmp_path / "private_signals.yaml"
    p.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return p


# ---------------------------------------------------------------- the contract file itself
def test_the_contract_loads_and_carries_no_values(contract):
    ids = [s.signal_id for s in contract.signals]
    assert ids == ["A1_dr007_liquidity_trend", "A2_cgb10y_pricing", "B1_household_credit_pulse",
                   "B2_corporate_credit_pulse", "C1_property_city_momentum", "C2_property_breadth", "D1_market_regime",
                   "X1_consensus_snapshot", "R1_domestic_demand_confirmation", "R2_policy_transmission",
                   "R3_market_confirmation", "R4_h0_competing_explanation"]
    for s in contract.signals:
        assert s.version >= 1 and s.formula and s.research_role != "PRIMARY_EVIDENCE"
        assert s.research_role in signals.ROLES and s.hypothesis_mapping
    roles = {s.signal_id: s.research_role for s in contract.signals}
    assert roles["A2_cgb10y_pricing"] == roles["D1_market_regime"] == roles["R3_market_confirmation"] == "CONTEXT_ONLY"
    assert roles["X1_consensus_snapshot"] == "EXPERIMENTAL" and roles["R4_h0_competing_explanation"] == "COMPETING_EXPLANATION"


def test_the_frozen_thresholds_are_the_contracted_ones(contract):
    t = {s.signal_id: s.thresholds for s in contract.signals}
    assert t["A1_dr007_liquidity_trend"] == {"easing_at_or_below_bp": -10, "tightening_at_or_above_bp": 10}
    assert t["C1_property_city_momentum"] == {"positive_at_or_above_pct": 5, "negative_at_or_below_pct": -5}
    assert t["C2_property_breadth"] == {"broad_min_positive": 3, "broad_improvement_median_above_pct": 5,
                                        "weak_max_positive": 1, "broad_weakness_median_below_pct": -5}
    w = {s.signal_id: s.window for s in contract.signals}
    assert (w["A1_dr007_liquidity_trend"]["recent"], w["A1_dr007_liquidity_trend"]["previous"]) == (20, 20)
    assert w["A2_cgb10y_pricing"]["changes"] == [20, 60] and w["B1_household_credit_pulse"]["months"] == 3
    assert (w["C1_property_city_momentum"]["recent"], w["C1_property_city_momentum"]["previous"]) == (28, 28)


@pytest.mark.parametrize("mutate, match", [
    (lambda s, r: s["D1_market_regime"]["hypothesis_mapping"].update(H2="CONFIRMATORY"), "CONTEXT_ONLY signal cannot be CONFIRMATORY"),
    (lambda s, r: s["A2_cgb10y_pricing"]["hypothesis_mapping"].update(H1="STRONG_CONFIRMATORY"), "cannot be STRONG_CONFIRMATORY"),
    (lambda s, r: s["R1_domestic_demand_confirmation"]["inputs"]["signals"].append("D1_market_regime"), "cannot take the CONTEXT_ONLY signal"),
    (lambda s, r: s["X1_consensus_snapshot"].update(research_role="CONFIRMATORY"), "consensus stays EXPERIMENTAL"),
    (lambda s, r: s["R3_market_confirmation"]["inputs"]["signals"].append("X1_consensus_snapshot"), "experimental signals feed nothing"),
    (lambda s, r: s["B1_household_credit_pulse"].update(research_role="PRIMARY_EVIDENCE"), "PRIMARY_EVIDENCE"),
    (lambda s, r: s["A1_dr007_liquidity_trend"]["thresholds"].pop("easing_at_or_below_bp"), "thresholds missing"),
    (lambda s, r: s["C1_property_city_momentum"]["inputs"]["metrics"].update(bj="cn_ppi_yoy"), "not a private routed metric"),
    (lambda s, r: r.update(private_only=False), "private_only"),
])
def test_the_loader_rejects_contracts_that_break_the_research_rules(tmp_path, metrics, mutate, match):
    with pytest.raises(ValueError, match=match):
        load_signal_contract(contract_with(tmp_path, mutate), metrics)


def test_a_definition_hash_ignores_wording_but_not_semantics(contract):
    a1 = contract.get("A1_dr007_liquidity_trend")
    assert dataclasses.replace(a1, caveats=["reworded"], title="renamed").sha256 == a1.sha256
    assert dataclasses.replace(a1, thresholds={**a1.thresholds, "easing_at_or_below_bp": -15}).sha256 != a1.sha256
    assert dataclasses.replace(a1, version=2).sha256 != a1.sha256


# ---------------------------------------------------------------- determinism and provenance
def test_same_inputs_give_identical_results_whatever_the_row_order(contract, metrics):
    s = Scenario(dr007=(1.9, 1.7), hh=HH_BROADENING, corp=CORP_WEAKENING, cities=PROP_UP, csi_return_pct=4.0)
    df = frame(s)
    a = [asdict(x) for x in compute_signals(df, metrics, contract, WHEN, public_results(PRICE_UP))]
    b = [asdict(x) for x in compute_signals(df.sample(frac=1, random_state=7), metrics, contract, WHEN, public_results(PRICE_UP))]
    c = [asdict(x) for x in compute_signals(df.copy(), metrics, contract, WHEN, public_results(PRICE_UP))]
    assert a == b == c


def test_every_result_carries_its_exact_input_provenance(contract, metrics):
    r = run(contract, metrics, Scenario(dr007=(1.9, 1.7)))
    a1 = r["A1_dr007_liquidity_trend"]
    assert len(a1.input_observation_ids) == 40 and len(set(a1.input_observation_ids)) == 40
    assert all(i.startswith("obs:cn_dr007@2026-") and i.endswith("#wind_SYNTHETIC1") for i in a1.input_observation_ids)
    assert a1.signal_version == 1 and a1.definition_sha256 == contract.get("A1_dr007_liquidity_trend").sha256
    assert a1.thresholds == {"easing_at_or_below_bp": -10, "tightening_at_or_above_bp": 10}
    assert "median" in a1.calculation_method and a1.private_only is True
    b1 = r["B1_household_credit_pulse"]
    assert len(b1.input_observation_ids) == 12                        # 2 components x (3 recent + 3 year-ago) months
    assert b1.components["recent_months"] == ["2026-06", "2026-07", "2026-08"]
    assert b1.components["year_ago_months"] == ["2025-06", "2025-07", "2025-08"]
    r1 = r["R1_domestic_demand_confirmation"]
    assert r1.input_signals == [f"B1_household_credit_pulse@v1={r['B1_household_credit_pulse'].status}",
                                f"B2_corporate_credit_pulse@v1={r['B2_corporate_credit_pulse'].status}",
                                f"C2_property_breadth@v1={r['C2_property_breadth'].status}"]
    assert set(b1.input_observation_ids) <= set(r1.input_observation_ids)


# ---------------------------------------------------------------- as-of: a later snapshot never leaks backwards
def test_a_later_private_snapshot_cannot_enter_an_earlier_diagnosis(contract, metrics):
    first = Scenario(dr007=(1.8, 1.8), retrieved_at="2026-10-10T07:59:00+00:00", file="wind_FIRST")
    # retrieved a week later, with a different (current-vintage) history for the same reference dates and more
    later = Scenario(dr007=(2.2, 1.6), dr007_n=60, hh=HH_WEAKENING, cities=PROP_DOWN,
                     retrieved_at="2026-10-17T07:59:00+00:00", file="wind_LATER")
    alone = run(contract, metrics, first)
    both = run(contract, metrics, first, later)
    assert [asdict(alone[k]) for k in alone] == [asdict(both[k]) for k in both]
    assert both["A1_dr007_liquidity_trend"].status == "STABLE"
    assert not any("wind_LATER" in i for s in both.values() for i in s.input_observation_ids)
    # one second before the first retrieval nothing private exists at all
    before = run(contract, metrics, first, later, when="2026-10-10T07:58:59Z")
    assert all(s.status == INSUFFICIENT for k, s in before.items() if not k.startswith(("R", "C1")))
    # and once the later snapshot exists, it is the one used
    after = run(contract, metrics, first, later, when="2026-10-17T08:00:00Z")
    assert after["A1_dr007_liquidity_trend"].status == "EASING"
    assert all(i.endswith("#wind_LATER") for i in after["A1_dr007_liquidity_trend"].input_observation_ids)


# ---------------------------------------------------------------- insufficient data is explicit, never neutral
def test_too_few_observations_are_insufficient_not_neutral(contract, metrics):
    r = run(contract, metrics, Scenario(dr007_n=39, cgb_n=20, csi_n=20))
    assert r["A1_dr007_liquidity_trend"].status == INSUFFICIENT
    assert "39 observations" in r["A1_dr007_liquidity_trend"].coverage_detail[0]
    assert r["A2_cgb10y_pricing"].status == INSUFFICIENT and r["D1_market_regime"].status == INSUFFICIENT
    assert r["R3_market_confirmation"].status == INSUFFICIENT


def test_the_60_day_change_needs_61_observations_and_says_so(contract, metrics):
    a2 = run(contract, metrics, Scenario(cgb_n=40, cgb_change_bp=8))["A2_cgb10y_pricing"]
    assert a2.status == "RISING" and a2.coverage_status == "PARTIAL"
    assert a2.numeric_components["change_20d_bp"] == 8 and a2.numeric_components["change_60d_bp"] is None


def test_stale_inputs_are_insufficient(contract, metrics):
    r = run(contract, metrics, Scenario(last_day="2026-09-20", last_month="2026-05"))
    assert r["A1_dr007_liquidity_trend"].status == INSUFFICIENT and "days old" in r["A1_dr007_liquidity_trend"].coverage_detail[0]
    assert r["B1_household_credit_pulse"].status == INSUFFICIENT
    assert all(r[f"C1_property_city_momentum.{c}"].status == INSUFFICIENT for c in CITIES)


def test_a_missing_year_ago_month_makes_credit_insufficient(contract, metrics):
    df = frame(Scenario())
    df = df[~((df.metric_id == "cn_loans_hh_short_flow") & (df.reference_period == "2025-07"))]
    r = {s.signal_id: s for s in compute_signals(df, metrics, contract, WHEN, None)}
    b1 = r["B1_household_credit_pulse"]
    assert b1.status == INSUFFICIENT and "cn_loans_hh_short_flow@2025-07" in b1.coverage_detail[0]
    assert r["B2_corporate_credit_pulse"].status != INSUFFICIENT


def test_a_city_with_too_few_observed_days_is_insufficient_and_breadth_needs_all_four(contract, metrics):
    r = run(contract, metrics, Scenario(cities=PROP_UP, city_days={"gz": 19}))
    assert r["C1_property_city_momentum.gz"].status == INSUFFICIENT
    assert r["C1_property_city_momentum.bj"].status == "POSITIVE"
    assert r["C2_property_breadth"].status == INSUFFICIENT
    r = run(contract, metrics, Scenario(cities={c: v for c, v in PROP_UP.items() if c != "sh"}))
    assert r["C1_property_city_momentum.sh"].status == INSUFFICIENT and r["C2_property_breadth"].status == INSUFFICIENT


def test_missing_inputs_never_become_neutral_in_assessments(contract, metrics):
    # property missing; household and corporate both broadening -> could be POSITIVE or MIXED -> undetermined
    r = run(contract, metrics, Scenario(hh=HH_BROADENING, corp=CORP_BROADENING, cities={}))
    assert r["R1_domestic_demand_confirmation"].status == INSUFFICIENT
    # property missing, but two channels already negative -> NEGATIVE whatever property says
    r = run(contract, metrics, Scenario(hh=HH_WEAKENING, corp=CORP_WEAKENING, cities={}))
    assert r["R1_domestic_demand_confirmation"].status == "NEGATIVE"
    assert r["R1_domestic_demand_confirmation"].coverage_status == "PARTIAL"
    # DR007 missing with every channel responding: easing would mean VISIBLE, stable NO_CLEAR_EASING
    r = run(contract, metrics, Scenario(dr007=None, hh=HH_BROADENING, corp=CORP_BROADENING, cities=PROP_UP))
    assert r["R2_policy_transmission"].status == INSUFFICIENT
    # no public evidence state: the supply-led flag cannot be decided from silence
    r = run(contract, metrics, Scenario(hh=HH_WEAKENING, corp=CORP_WEAKENING, cities=PROP_DOWN))
    assert r["R4_h0_competing_explanation"].components["flags"]["H0_SUPPLY_LED_RISK"] == INSUFFICIENT


def test_decide_only_concludes_what_every_completion_agrees_on():
    rule = lambda a, b: "X" if a == 1 or b == 1 else "Y"
    assert signals.decide(rule, {"a": 1, "b": None}, {"a": (0, 1), "b": (0, 1)}) == "X"
    assert signals.decide(rule, {"a": 0, "b": None}, {"a": (0, 1), "b": (0, 1)}) == INSUFFICIENT
    assert signals.decide(rule, {"a": 0, "b": 0}, {"a": (0, 1), "b": (0, 1)}) == "Y"


# ---------------------------------------------------------------- property: cities are never summed
def test_city_areas_are_never_combined_across_cities(contract, metrics):
    base = Scenario(cities={"bj": (100.0, 110.0), "sh": (100.0, 90.0), "sz": (100.0, 106.0), "gz": (100.0, 120.0)})
    huge = copy.deepcopy(base)
    huge.cities["sh"] = (100000.0, 90000.0)                       # Shanghai in different units: same momentum
    a, b = run(contract, metrics, base), run(contract, metrics, huge)
    for c in ("bj", "sz", "gz"):
        assert asdict(a[f"C1_property_city_momentum.{c}"]) == asdict(b[f"C1_property_city_momentum.{c}"])
    assert a["C1_property_city_momentum.sh"].status == b["C1_property_city_momentum.sh"].status == "NEGATIVE"
    assert a["C2_property_breadth"].numeric_components == b["C2_property_breadth"].numeric_components
    assert a["C2_property_breadth"].status == b["C2_property_breadth"].status
    # each city's result is built from that city's observations alone
    for c, mid in CITIES.items():
        assert all(i.startswith(f"obs:{mid}@") for i in a[f"C1_property_city_momentum.{c}"].input_observation_ids)
    # and a city's result does not depend on whether the other cities exist
    alone = run(contract, metrics, Scenario(cities={"bj": (100.0, 110.0)}))
    assert asdict(alone["C1_property_city_momentum.bj"]) == asdict(a["C1_property_city_momentum.bj"])


def test_holiday_windows_are_caveated_not_adjusted(contract, metrics):
    r = run(contract, metrics, Scenario(cities=PROP_UP))
    bj = r["C1_property_city_momentum.bj"]
    assert any("Golden Week 2026" in c for c in bj.caveats) and bj.status == "POSITIVE"
    assert bj.numeric_components["momentum_pct"] == 20


# ---------------------------------------------------------------- threshold boundaries (frozen, deterministic)
@pytest.mark.parametrize("prev, recent, expected", [
    (1.80, 1.70, "EASING"),        # (1.70 - 1.80) * 100 = -10.000000000000009 in floating point: still exactly -10 bp
    (1.80, 1.7001, "STABLE"),      # -9.99 bp
    (1.80, 1.90, "TIGHTENING"),    # +10 bp
    (1.80, 1.8999, "STABLE"),
    (1.80, 1.60, "EASING"),
])
def test_dr007_band_boundaries(contract, metrics, prev, recent, expected):
    a1 = run(contract, metrics, Scenario(dr007=(prev, recent)))["A1_dr007_liquidity_trend"]
    assert a1.status == expected


@pytest.mark.parametrize("recent, expected", [(105.0, "POSITIVE"), (104.99, "FLAT"), (95.0, "NEGATIVE"), (95.01, "FLAT")])
def test_city_momentum_boundaries(contract, metrics, recent, expected):
    r = run(contract, metrics, Scenario(cities={"bj": (100.0, recent)}))
    assert r["C1_property_city_momentum.bj"].status == expected


@pytest.mark.parametrize("cities, expected", [
    ({"bj": 106, "sh": 106, "sz": 106, "gz": 90}, "BROAD_IMPROVEMENT"),    # 3 positive, median +6
    ({"bj": 105, "sh": 105, "sz": 105, "gz": 105}, "MIXED"),               # median exactly +5 is not > +5
    ({"bj": 106, "sh": 106, "sz": 100, "gz": 100}, "MIXED"),               # only 2 positive
    ({"bj": 94, "sh": 94, "sz": 106, "gz": 94}, "BROAD_WEAKNESS"),         # 1 positive, median -6
    ({"bj": 95, "sh": 95, "sz": 95, "gz": 95}, "MIXED"),                   # median exactly -5 is not < -5
    ({"bj": 106, "sh": 106, "sz": 80, "gz": 80}, "MIXED"),                 # 2 positive, median below -5
])
def test_property_breadth_boundaries(contract, metrics, cities, expected):
    r = run(contract, metrics, Scenario(cities={c: (100.0, float(v)) for c, v in cities.items()}))
    assert r["C2_property_breadth"].status == expected


@pytest.mark.parametrize("ret, chg, dr, expected", [
    (3.0, 5.0, (1.8, 1.8), "REFLATION_CONFIRMATION"),        # exactly on both bands; liquidity stable
    (3.0, 5.0, (1.8, 1.9), "MIXED"),                          # ...but liquidity tightening
    (5.0, -10.0, (1.9, 1.7), "LIQUIDITY_DRIVEN_RALLY"),
    (5.0, 0.0, (1.8, 1.8), "MIXED"),                          # rally, flat yields, no easing
    (-3.0, -5.0, (1.8, 1.8), "WEAK_GROWTH_PRICING"),
    (-4.0, 6.0, (1.8, 1.8), "RISK_OFF_OR_MIXED"),
    (2.99, 6.0, (1.8, 1.8), "MIXED"),
])
def test_market_regime_rules_and_bands(contract, metrics, ret, chg, dr, expected):
    r = run(contract, metrics, Scenario(csi_return_pct=ret, cgb_change_bp=chg, dr007=dr))
    assert r["D1_market_regime"].status == expected


def test_thresholds_come_from_the_contract_not_the_code(tmp_path, metrics):
    def widen(s, r):
        s["A1_dr007_liquidity_trend"]["thresholds"] = {"easing_at_or_below_bp": -25, "tightening_at_or_above_bp": 25}
        s["A1_dr007_liquidity_trend"]["version"] = 2
    c2 = load_signal_contract(contract_with(tmp_path, widen), metrics)
    a1 = run(c2, metrics, Scenario(dr007=(1.80, 1.60)))["A1_dr007_liquidity_trend"]
    assert a1.status == "STABLE" and a1.numeric_components["delta_bp"] == -20 and a1.signal_version == 2


# ---------------------------------------------------------------- credit composition
def test_credit_pulse_uses_level_deltas_and_valid_shares_only(contract, metrics):
    r = run(contract, metrics, Scenario(hh=((100.0, 150.0), (100.0, 50.0)), corp=((-40.0, 30.0), (100.0, 120.0))))
    b1, b2 = r["B1_household_credit_pulse"], r["B2_corporate_credit_pulse"]
    assert b1.status == "MIXED" and b1.numeric_components["breadth"] == 1
    assert b1.numeric_components["short_term_yoy_delta"] == 150 and b1.numeric_components["medium_long_term_yoy_delta"] == -150
    assert b1.numeric_components["ml_share_recent"] == 0.25 and b1.numeric_components["ml_share_year_ago"] == 0.5
    assert b1.numeric_components["ml_share_change_pp"] == -25
    # a negative component in the year-ago window: the share is undefined there, never forced
    assert b2.status == "BROADENING" and b2.numeric_components["ml_share_year_ago"] is None
    assert b2.numeric_components["ml_share_change_pp"] is None and b2.coverage_status == "PARTIAL"
    assert not any("consumption" in c.lower() and "not labelled" not in c.lower() for c in b1.caveats)


# ---------------------------------------------------------------- the contracted economic scenarios
def test_scenario_a_policy_led_credit_without_broad_demand(contract, metrics):
    """Easier DR007 + stronger corporate credit, but weak household credit and weak property."""
    r = run(contract, metrics, Scenario(dr007=(1.9, 1.7), corp=CORP_BROADENING, hh=HH_WEAKENING, cities=PROP_DOWN),
            public=public_results(PRICE_DOWN))
    assert r["A1_dr007_liquidity_trend"].status == "EASING"                  # liquidity support exists
    assert r["B2_corporate_credit_pulse"].status == "BROADENING"
    assert r["R1_domestic_demand_confirmation"].status == "NEGATIVE"         # no broad domestic-demand confirmation
    assert r["R2_policy_transmission"].status == "MIXED"                     # one channel responds, not transmission
    r4 = r["R4_h0_competing_explanation"]
    assert r4.components["flags"]["POLICY_SUPPLY_LED_CREDIT_RISK"] == "ELEVATED"
    assert r4.status == "ELEVATED"


def test_scenario_b_price_improvement_without_domestic_demand(contract, metrics):
    """Public inflation evidence stronger, private domestic demand negative."""
    r = run(contract, metrics, Scenario(hh=HH_WEAKENING, corp=CORP_WEAKENING, cities=PROP_DOWN),
            public=public_results(PRICE_UP))
    r4 = r["R4_h0_competing_explanation"]
    assert r4.components["price_improving"] is True and r4.components["nominal_improving"] is True
    assert r["R1_domestic_demand_confirmation"].status == "NEGATIVE"
    assert r4.components["flags"]["H0_SUPPLY_LED_RISK"] == "ELEVATED" and r4.status == "ELEVATED"
    assert r4.input_public_tests["T-H1-01"] == "true"
    # the same price evidence with confirmed private demand does not elevate the supply-led flag
    ok = run(contract, metrics, Scenario(hh=HH_BROADENING, corp=CORP_BROADENING, cities=PROP_UP), public=public_results(PRICE_UP))
    assert ok["R1_domestic_demand_confirmation"].status == "POSITIVE"
    assert ok["R4_h0_competing_explanation"].components["flags"]["H0_SUPPLY_LED_RISK"] == "NOT_ELEVATED"


def test_scenario_c_liquidity_driven_rally_is_not_thesis_confirmation(contract, metrics):
    """CSI 300 up, 10Y down, DR007 easing."""
    r = run(contract, metrics, Scenario(csi_return_pct=6.0, cgb_change_bp=-12.0, dr007=(1.9, 1.7),
                                        hh=HH_WEAKENING, cities=PROP_DOWN), public=public_results(PRICE_DOWN))
    assert r["D1_market_regime"].status == "LIQUIDITY_DRIVEN_RALLY"
    assert r["R3_market_confirmation"].status == "DOES_NOT_CONFIRM"
    assert r["R3_market_confirmation"].research_role == "CONTEXT_ONLY"
    assert r["R4_h0_competing_explanation"].components["flags"]["FINANCIAL_MARKET_CONFIRMATION_WITHOUT_REAL_DEMAND"] == "ELEVATED"
    assert r["R1_domestic_demand_confirmation"].status != "POSITIVE"


def test_a_market_rally_cannot_lift_domestic_demand(contract, metrics):
    calm = run(contract, metrics, Scenario(hh=HH_WEAKENING, cities=PROP_DOWN))
    boom = run(contract, metrics, Scenario(hh=HH_WEAKENING, cities=PROP_DOWN, csi_return_pct=20.0, cgb_change_bp=30.0))
    assert boom["R3_market_confirmation"].status == "CONFIRMS"
    for sid in ("R1_domestic_demand_confirmation", "R2_policy_transmission", "B1_household_credit_pulse", "C2_property_breadth"):
        assert boom[sid].status == calm[sid].status


# ---------------------------------------------------------------- consensus stays experimental
def test_consensus_is_a_snapshot_record_with_no_value_and_no_surprise(contract, metrics):
    r = run(contract, metrics, Scenario())
    x1 = r["X1_consensus_snapshot"]
    assert x1.status == "EXPERIMENTAL_SNAPSHOT_ONLY" and x1.research_role == "EXPERIMENTAL"
    assert x1.numeric_components == {} and x1.components["validation"]["status"] == "NOT_VALIDATED"
    assert x1.mapped_hypotheses == {"H1": "EXPERIMENTAL"}
    snaps = x1.components["snapshots"]["cn_cpi_consensus_wind"]
    assert snaps == [{"target_period": "2026-09", "retrieved_at": "2026-10-10T07:59:00+00:00", "snapshot": "wind_SYNTHETIC1"}]
    for s in r.values():
        assert not any("surprise" in k.lower() for k in s.numeric_components)
        assert "X1_consensus_snapshot" not in " ".join(s.input_signals)
    assert "0.5" not in str(asdict(x1)) and "-2.0" not in str(asdict(x1))     # the consensus values are never read


# ---------------------------------------------------------------- R4 v2: the nominal premise is the price evidence alone
EXTERNAL_ONLY = {"T-H1-01": "false", "T-H1-02": "false", "T-H1-03": "true", "T-H4-01": "true", "T-H4-02": "true"}


def test_external_evidence_alone_never_triggers_the_supply_led_flag(contract, metrics):
    """External evidence improving + price evidence NOT improving + weak domestic demand."""
    r = run(contract, metrics, Scenario(hh=HH_WEAKENING, corp=CORP_WEAKENING, cities=PROP_DOWN),
            public=public_results(EXTERNAL_ONLY))
    r4 = r["R4_h0_competing_explanation"]
    assert r["R1_domestic_demand_confirmation"].status == "NEGATIVE"
    assert r4.components["external_improving"] is True                       # still reported, as context
    assert r4.components["price_improving"] is False and r4.components["nominal_improving"] is False
    assert r4.components["flags"]["H0_SUPPLY_LED_RISK"] == "NOT_ELEVATED"
    assert r4.signal_version == 2


@pytest.mark.parametrize("hh, corp, cities, r1", [
    (HH_WEAKENING, CORP_WEAKENING, PROP_DOWN, "NEGATIVE"),
    (HH_BROADENING, CORP_WEAKENING, {c: (100.0, 100.0) for c in CITIES}, "MIXED"),   # property flat -> MIXED
])
def test_price_evidence_with_unconfirmed_demand_elevates_the_supply_led_flag(contract, metrics, hh, corp, cities, r1):
    r = run(contract, metrics, Scenario(hh=hh, corp=corp, cities=cities),
            public=public_results({**PRICE_DOWN, "T-H1-01": "true", "T-H1-02": "true"}))   # 2 of 3 price tests, no external
    r4 = r["R4_h0_competing_explanation"]
    assert r["R1_domestic_demand_confirmation"].status == r1
    assert r4.components["price_improving"] is True and r4.components["external_improving"] is False
    assert r4.components["flags"]["H0_SUPPLY_LED_RISK"] == "ELEVATED" and r4.status == "ELEVATED"


def test_external_strength_cannot_stand_in_for_missing_price_evidence(contract, metrics):
    public = public_results({"T-H1-01": "true", "T-H1-02": "insufficient_data", "T-H1-03": "false",
                             "T-H4-01": "true", "T-H4-02": "true"})
    r4 = run(contract, metrics, Scenario(hh=HH_WEAKENING, corp=CORP_WEAKENING, cities=PROP_DOWN),
             public=public)["R4_h0_competing_explanation"]
    assert r4.components["price_improving"] is None and r4.components["external_improving"] is True
    assert r4.components["flags"]["H0_SUPPLY_LED_RISK"] == INSUFFICIENT


def test_r4_v2_is_a_new_version_with_a_new_definition_hash(contract):
    r4 = contract.get("R4_h0_competing_explanation")
    assert r4.version == 2 and signals.METHOD_VERSIONS["h0_competing_explanation"] == 2
    v1 = dataclasses.replace(r4, version=1)
    assert v1.sha256 != r4.sha256
