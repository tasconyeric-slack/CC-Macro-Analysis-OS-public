"""The cn-nominal case definition must be internally consistent with the dictionary."""
from pathlib import Path

import yaml

from cnmacro.derive import parse_drv
from cnmacro.expanded_data import NEW_METRICS
from cnmacro.price_releases import NEW_PRICE_METRICS
from cnmacro.evidence import load_tests
from cnmacro.store import load_dictionary

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "research/cases/cn-nominal/case.yaml"


def _leaf_tests(node):
    if "test" in node:
        yield node["test"]
    for k in ("all", "any", "of"):
        for child in node.get(k, []):
            yield from _leaf_tests(child)


def test_case_tests_reference_dictionary_metrics():
    metrics = load_dictionary(ROOT / "data/dictionary/metrics.yaml")
    case = yaml.safe_load(CASE.read_text(encoding="utf-8"))
    tests = load_tests(case["evidence_tests"])
    for t in tests:
        if t.indicator in metrics:
            continue
        fn, args = parse_drv(t.indicator)
        assert any(a in metrics for a in args), f"{t.id}: {t.indicator} uses no known metric"
    ids = {t.id for t in tests}
    for name, rule in case["terminal_rules"].items():
        if isinstance(rule, dict) and "when" in rule:
            missing = set(_leaf_tests(rule["when"])) - ids
            assert not missing, f"{name} references unknown tests {missing}"


def test_metric_budget():
    metrics = load_dictionary(ROOT / "data/dictionary/metrics.yaml")
    # Owner-authorized Issues #10/#28 add named public views; the prior research budget remains bounded.
    tiers = [m.tier for m in metrics.values() if m.metric_id != "cn_pmi_mfg" and m.metric_id not in NEW_METRICS | NEW_PRICE_METRICS
             and m.category != "markets"]      # daily Tushare market views (T4) are Owner-authorized, not thesis evidence
    assert tiers.count("core") <= 24 and tiers.count("diagnostic") <= 6
    headline = metrics["cn_pmi_mfg"]
    assert (headline.tier, headline.source_primary, headline.redistribution) == ("diagnostic", "NBS", "public")
    for m in metrics.values():
        assert m.hypotheses and m.role, f"{m.metric_id} needs hypotheses and a role"
