"""Terminal decisions of the preregistered case, as amended by A-01.

The preregistered definition: sustainable iff the deflator is >= 0 in both 2026Q4 and
2027Q1 (T-H1-05 at the terminal release) AND at least 3 of 6 demand tests (H2) pass.
At the window the outcome must be CONFIRMED when that holds, FALSIFIED when it fails,
and RETIRED only when required terminal data are insufficient.
"""
from pathlib import Path

import pytest
import yaml

from cnmacro.evidence import TestResult as Result, terminal_decision, window_is_open
from cnmacro.thesis import apply_amendments, effective_case

ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "research/cases/cn-nominal"
BASELINE = CASE_DIR / "preregistered/2026-10-04-baseline.yaml"
H2 = [f"T-H2-0{i}" for i in range(1, 7)]


def results(h1_04="true", h1_05="true", h2=("true",) * 6, early_ok=True):
    out = {"T-H1-04": h1_04, "T-H1-05": h1_05, **dict(zip(H2, h2))}
    # early-falsification inputs: price momentum alive unless the scenario says otherwise
    for t in ("T-H1-01", "T-H1-02"):
        out[t] = "true" if early_ok else "false"
    return {k: Result(k, k[2:4], v, "none", None, None) for k, v in out.items()}


@pytest.fixture(scope="module")
def frozen():
    return yaml.safe_load(BASELINE.read_text(encoding="utf-8"))["case"]["terminal_rules"]


@pytest.fixture(scope="module")
def amended():
    case, _, errs = effective_case(CASE_DIR)
    assert errs == []
    return case["terminal_rules"]


def decide(rules, res, window=True):
    return terminal_decision(rules, res, decision_window_open=window)


def test_q4_negative_q1_positive_is_falsified(frozen, amended):
    res = results(h1_04="true", h1_05="false")  # latest quarter >= 0, but not both quarters
    assert decide(frozen, res) == "RETIRED"     # the inconsistency A-01 corrects
    assert decide(amended, res) == "FALSIFIED"


def test_only_two_demand_tests_pass_is_falsified(frozen, amended):
    res = results(h2=("true", "true", "false", "false", "false", "false"))
    assert decide(frozen, res) == "RETIRED"     # the inconsistency A-01 corrects
    assert decide(amended, res) == "FALSIFIED"


def test_latest_deflator_negative_is_falsified(amended):
    assert decide(amended, results(h1_04="false", h1_05="false")) == "FALSIFIED"


def test_definition_met_is_confirmed(amended):
    res = results(h2=("true", "true", "true", "false", "false", "false"))
    assert decide(amended, res) == "CONFIRMED"


def test_insufficient_demand_data_is_retired(amended):
    # 2 pass, 2 fail, 2 missing: 3 of 6 can be neither reached nor ruled out
    res = results(h2=("true", "true", "false", "false", "insufficient_data", "insufficient_data"))
    assert decide(amended, res) == "RETIRED"


def test_missing_deflator_streak_is_retired(amended):
    res = results(h1_05="insufficient_data", h2=("true", "true", "true", "false", "false", "false"))
    assert decide(amended, res) == "RETIRED"


def test_before_the_window_only_early_rules_apply(amended):
    assert decide(amended, results(h1_05="false"), window=False) == "ACTIVE"
    weak = results(h2=("false",) * 6, early_ok=False)  # price momentum and demand fail together
    assert decide(amended, weak, window=False) == "FALSIFIED"


def test_outcomes_are_exhaustive_with_complete_data(amended):
    import itertools
    for h1_05 in ("true", "false"):
        for h2 in itertools.product(("true", "false"), repeat=6):
            want = "CONFIRMED" if h1_05 == "true" and h2.count("true") >= 3 else "FALSIFIED"
            assert decide(amended, results(h1_05=h1_05, h2=h2)) == want


class _D:
    def __init__(self, held):
        self.held = held

    def resolve(self, ref):
        return object() if ref in self.held else None


def test_window_opens_when_first_2027q1_gdp_print_is_available():
    case, _, _ = effective_case(CASE_DIR)
    h = case["horizon"]
    assert not window_is_open(h, _D(set()), "2027-04-01")
    assert not window_is_open(h, _D({"obs:cn_ngdp_q@2027Q1"}), "2027-04-16")
    assert window_is_open(h, _D({"obs:cn_ngdp_q@2027Q1", "obs:cn_rgdp_yoy@2027Q1"}), "2027-04-16")


def test_amendment_cannot_change_evidence_or_mismatched_values():
    case = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))["case"]
    base = {"kind": "amendment", "id": "X", "reason": "r", "baseline": "b.yaml", "baseline_commit": "abc",
            "effective_before": {"at": "2026-10-14T09:30:00+08:00"}, "informed_by_tested_data": False}
    bad_path = {**base, "changes": [{"path": "evidence_tests", "before": case["evidence_tests"], "after": []}]}
    bad_before = {**base, "changes": [{"path": "terminal_rules.otherwise", "before": "not the frozen text",
                                       "after": "x"}]}
    _, errs = apply_amendments(case, [("a.yaml", bad_path), ("b.yaml", bad_before)], "b.yaml")
    assert any("may not change 'evidence_tests'" in e for e in errs)
    assert any("before-value does not match" in e for e in errs)
