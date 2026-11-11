"""The Wind contract inside the one metric dictionary: tiers, evidence use, and the public/thesis boundary."""
import dataclasses
import re
from pathlib import Path

import pytest
import yaml

from cnmacro import wind
from cnmacro.expanded_data import NEW_METRICS
from cnmacro.price_releases import NEW_PRICE_METRICS
from cnmacro.derive import parse_drv
from cnmacro.evidence import load_tests
from cnmacro.refresh import route
from cnmacro.store import load_dictionary
from cnmacro.thesis import effective_case

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "research/cases/cn-nominal"
DICT = ROOT / "data/dictionary/metrics.yaml"


@pytest.fixture(scope="module")
def metrics():
    return load_dictionary(DICT)


def _entries(text: str) -> list[dict]:
    return yaml.safe_load(text)["metrics"]


def test_supplemental_is_a_third_tier_outside_the_public_budget(metrics):
    by_tier = {t: [m for m in metrics.values() if m.tier == t] for t in ("core", "diagnostic", "supplemental")}
    # The Owner-authorized public headline PMI (#10) does not expand the Wind diagnostic budget.
    budgeted = [m for m in by_tier["diagnostic"] if m.metric_id != "cn_pmi_mfg" and m.metric_id not in NEW_METRICS | NEW_PRICE_METRICS]
    assert len(by_tier["core"]) <= 24 and len(budgeted) <= 6
    assert len(by_tier["supplemental"]) == 13                                       # 12 P0 series + the daily 10Y view (cn_cgb10y stays core)
    for m in by_tier["supplemental"]:
        assert m.redistribution == "private_only" and m.wind is not None and m.hypotheses and m.role, m.metric_id


def test_the_dictionary_is_the_single_metric_universe(metrics):
    p0 = wind.p0_metrics(metrics)
    assert len(p0) == 14 and len({m.wind.code for m in p0}) == 13 and all(m.wind.priority == "P0" for m in p0)
    assert {m.wind.priority for m in metrics.values() if m.wind} == {"P0"}          # no P1 or P2 added in Phase 1
    cgb = [m for m in metrics.values() if "cgb" in m.metric_id]
    assert [m.metric_id for m in cgb] == ["cn_cgb10y", "cn_cgb10y_daily"]           # one series, two declared views
    d = metrics["cn_cgb10y_daily"]
    assert (d.tier, d.frequency, d.redistribution, d.wind.code, d.wind.aggregate, d.wind.same_series_as) == (
        "supplemental", "D", "private_only", "M0325687", None, "cn_cgb10y")
    c = metrics["cn_cgb10y"]
    assert (c.tier, c.frequency, c.redistribution, c.wind.code, c.wind.aggregate) == ("core", "M", "private_only", "M0325687", "month_end")
    assert c.source_primary == "Wind" and any("CCDC" in n and "permission-blocked" in n for n in c.caliber_notes)


def test_evidence_use_follows_the_review(metrics):
    use = {m.metric_id: m.wind.evidence_use for m in wind.p0_metrics(metrics)}
    active = {"cn_dr007", "cn_cgb10y", "cn_cgb10y_daily", "cn_loans_hh_short_flow", "cn_loans_corp_short_flow", "cn_hf_prop_bj",
              "cn_hf_prop_sz", "cn_hf_prop_sh", "cn_hf_prop_gz", "mkt_csi300"}
    mirror = {"cn_loans_hh_mlt_flow", "cn_loans_corp_mlt_flow"}
    snapshot = {"cn_cpi_consensus_wind", "cn_ppi_consensus_wind"}
    assert {k for k, v in use.items() if v == "active_diagnostic"} == active
    assert {k for k, v in use.items() if v == "mirror"} == mirror
    assert {k for k, v in use.items() if v == "snapshot_only"} == snapshot
    assert metrics["cn_loans_hh_mlt_flow"].wind.mirrors == "cn_loans_hh_mlt_ytd" and metrics["cn_loans_corp_mlt_flow"].wind.mirrors == "cn_loans_corp_mlt_ytd"
    assert {m.metric_id for m in wind.p0_metrics(metrics) if m.wind.experimental} == snapshot


def test_no_evidence_test_or_terminal_rule_can_use_a_wind_metric(metrics):
    """Supplemental diagnostics and consensus snapshots must never feed a preregistered rule automatically."""
    wind_ids = {m.metric_id for m in wind.p0_metrics(metrics) if m.tier == "supplemental"}
    sources = [yaml.safe_load((CASE / "case.yaml").read_text(encoding="utf-8")), effective_case(CASE)[0]]
    for case in sources:
        for t in load_tests(case["evidence_tests"]):
            used = {t.indicator} if "(" not in t.indicator else set(parse_drv(t.indicator)[1])
            assert not used & wind_ids, f"{t.id} uses a supplemental Wind metric: {used & wind_ids}"
        assert "cn_cgb10y" not in str(case["evidence_tests"]) and "consensus" not in str(case["terminal_rules"]).lower()


def test_the_dictionary_loader_rejects_a_bad_tier_or_contract(tmp_path):
    entries = _entries(DICT.read_text(encoding="utf-8"))
    dr007 = next(e for e in entries if e["metric_id"] == "cn_dr007")

    def load_with(**changes):
        e = {**dr007, **changes}
        p = tmp_path / "m.yaml"
        p.write_text(yaml.safe_dump({"metrics": [e]}, allow_unicode=True), encoding="utf-8")
        return load_dictionary(p)

    assert load_with()["cn_dr007"].wind.code == "M1006337"
    with pytest.raises(ValueError, match="tier"):
        load_with(tier="shadow")
    with pytest.raises(ValueError, match="evidence_use"):
        load_with(wind={**dr007["wind"], "evidence_use": "thesis_input"})
    with pytest.raises(ValueError, match="known_gaps"):
        load_with(wind={**dr007["wind"], "known_gaps": [{"field": "name"}]})
    with pytest.raises(TypeError):
        load_with(wind={**dr007["wind"], "api_key": "never here"})                 # unknown contract fields are not allowed


def test_the_public_site_model_lists_no_supplemental_metric(model):
    tiers = {m.tier for m in model["metrics"].values()}
    assert tiers == {"core", "diagnostic"} and "cn_cgb10y" in model["metrics"]


def test_the_public_refresh_never_routes_a_wind_metric(metrics):
    for m in metrics.values():
        if m.wind is not None:
            assert route(m) is None, m.metric_id


def test_the_wind_contract_holds_no_credential_and_no_observation():
    text = (ROOT / "data/dictionary/wind_runtime.yaml").read_text(encoding="utf-8")
    assert not re.search(r"(?i)api[_-]?key|token|secret|password|bearer", text)
    contract = yaml.safe_load(text)
    assert set(contract) == {"skill", "operations", "groups"} and contract["skill"]["name"] == "wind-mcp-skill"
    dict_text = DICT.read_text(encoding="utf-8")
    assert not re.search(r"(?i)api[_-]?key|bearer", dict_text)


# ---------------------------------------------------------------- the documents say what the code does
def test_the_wind_skill_is_never_vendored_into_the_public_repository():
    """The private Wind capability note stays in the private origin repository; the public repository must still
    say the skill is never copied in, pin the runtime instead, and track no copy of the skill."""
    import subprocess
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "the skill is never copied into this repository" in readme
    assert (ROOT / "data/dictionary/wind_runtime.yaml").exists()
    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    assert not [p for p in tracked if re.search(r"(^|/)wind[-_]?skill", p, re.I)], "a Wind skill copy is tracked"
    note = ROOT / "docs/wind-capability-note.md"
    if note.exists():   # where the private note is present (origin repo), it must not ask for a vendored copy
        text = note.read_text(encoding="utf-8")
        assert "Vendor and **pin** a copy" not in text and "Vendor a pinned copy of the skill" not in text


def test_the_data_policy_describes_the_boundary_that_is_enforced():
    policy = (ROOT / "docs/data-policy.md").read_text(encoding="utf-8")
    assert "src/export_demo.py" not in policy and not (ROOT / "src/export_demo.py").exists()
    for must in ("tracked public artifacts only", "gitignored", "never loads private observations", "must drop `private` observations",
                 "available only from their own `retrieved_at`"):
        assert must in policy, must


def test_the_public_eval_never_names_a_supplemental_metric(metrics):
    """The public refresh regenerates the eval report; it must not start listing private diagnostics."""
    from cnmacro.checks import data_quality
    from cnmacro.store import load_observations
    obs = load_observations(ROOT / "data/demo/observations")
    supplemental = {m.metric_id for m in metrics.values() if m.tier == "supplemental"}
    public = data_quality(obs, metrics, public_only=True)
    assert not [d for d in public.details if d.split(":")[0] in supplemental]
    assert "cn_cgb10y: not in public build (private_only); private mode only" in public.details   # the existing behaviour, unchanged
    private = data_quality(obs, metrics, public_only=False)
    assert {d.split(":")[0] for d in private.details if d.endswith("no observations")} >= supplemental   # private mode asks for them
    assert private.status in ("warn", "fail")
