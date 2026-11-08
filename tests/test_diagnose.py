"""`diagnose-private` end to end in an isolated copy of the repo, and the public/private boundary around it.

Snapshots here are synthetic (tests/signal_support.py) with the run manifest refresh-private would write.
Nothing touches the real Wind skill, key or private data."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest
import yaml
from signal_support import (CORP_BROADENING, HH_BROADENING, HH_WEAKENING, PROP_DOWN, PROP_UP, ROOT, Scenario,
                            write_snapshot)

from cnmacro import cli, diagnose, signals
from cnmacro.store import load_dictionary, load_observations

S1, S2 = "20261010T075900Z", "20261017T075900Z"
MARK = 1.6911          # a distinctive synthetic value: it must never reach stdout


def tree_digest(root: Path, skip=("data/private",)) -> dict[str, str]:
    import hashlib
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()
            and not any(p.relative_to(root).as_posix().startswith(s) for s in skip)}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for rel in ("data/dictionary", "data/demo", "research/cases/cn-nominal"):
        shutil.copytree(ROOT / rel, tmp_path / rel, ignore=shutil.ignore_patterns("latest-private.json"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return tmp_path


def first(**kw) -> Scenario:
    return Scenario(dr007=(1.8137, MARK), retrieved_at="2026-10-10T07:59:00+00:00", **kw)


def second(**kw) -> Scenario:
    return Scenario(dr007=(1.8137, 1.95), retrieved_at="2026-10-17T07:59:00+00:00", last_day="2026-10-16", **kw)


def invoke(capsys, *argv):
    code = cli.main(list(argv))
    return code, capsys.readouterr()


SECTIONS = ["# Private Macro Diagnostic", "## Executive diagnostic", "## Liquidity / financial conditions",
            "## Credit demand", "## Property pulse", "## Market confirmation", "## H0 competing explanations",
            "## H1–H4 relevance", "## What changed since previous genuine snapshot", "## What remains unresolved",
            "## Data / as-of / coverage caveats"]


# ---------------------------------------------------------------- the local path
def test_diagnose_private_runs_end_to_end_and_writes_only_private_files(repo, capsys):
    write_snapshot(repo, first(hh=HH_WEAKENING, cities=PROP_DOWN), S1)
    before = tree_digest(repo)
    code, io = invoke(capsys, "diagnose-private")
    assert code == 0, io.out
    out = json.loads(io.out)
    assert out["status"] == "diagnosed" and out["snapshot"] == S1 and out["previous_snapshot"] is None
    assert out["run_id"].startswith(S1 + "-") and out["as_of"] == "2026-10-10T07:59:00Z"
    assert out["signals"]["A1_dr007_liquidity_trend"] == "EASING" and out["signals"]["R1_domestic_demand_confirmation"] == "NEGATIVE"
    assert out["output"] == f"data/private/signals/{out['run_id']}.json"
    assert out["report"] == f"data/private/research/{out['run_id']}/PRIVATE_DIAGNOSTIC_REPORT.md"
    assert str(MARK) not in io.out and str(MARK * 100) not in io.out              # classes only, never values
    assert tree_digest(repo) == before                                           # nothing outside data/private changed
    doc = json.loads((repo / out["output"]).read_text(encoding="utf-8"))
    assert doc["private_only"] is True and doc["snapshot"]["run_id"] == S1
    assert doc["previous_snapshot"]["status"] == "NOT_EVALUABLE" and doc["changes"] == []
    assert doc["information_set"]["private_files"] == [f"wind_{S1}.csv"]
    assert all(s["run_id"] == out["run_id"] and s["as_of"] == out["as_of"] and s["private_only"] for s in doc["signals"])
    report = (repo / out["report"]).read_text(encoding="utf-8")
    assert [h for h in SECTIONS if h in report] == SECTIONS
    assert [report.index(h) for h in SECTIONS] == sorted(report.index(h) for h in SECTIONS)
    assert "Cannot yet be evaluated: this is the first genuine anchor." in report
    assert "LOCAL ONLY" in report and "pseudo-vintages" in report


def test_a_rerun_reproduces_the_stored_result_and_never_overwrites_it(repo, capsys):
    write_snapshot(repo, first(), S1)
    out1 = json.loads(invoke(capsys, "diagnose-private")[1].out)
    stored = (repo / out1["output"]).read_bytes()
    code, io = invoke(capsys, "diagnose-private", "--snapshot", S1)
    out2 = json.loads(io.out)
    assert code == 0 and out2["status"] == "reproduced" and out2["run_id"] == out1["run_id"]
    assert (repo / out1["output"]).read_bytes() == stored


def test_a_result_that_changes_for_identical_inputs_is_refused(repo, capsys, monkeypatch):
    write_snapshot(repo, first(), S1)
    out1 = json.loads(invoke(capsys, "diagnose-private")[1].out)
    stored = (repo / out1["output"]).read_bytes()
    real = signals.METHODS["median_shift"]

    def drifted(d, ctx):                                  # a method whose arithmetic changed with no version bump
        res = real(d, ctx)
        res[0].numeric_components["delta_bp"] += 1
        return res
    monkeypatch.setitem(signals.METHODS, "median_shift", drifted)
    code, io = invoke(capsys, "diagnose-private")
    assert code == 1 and json.loads(io.out)["error"] == "NON_REPRODUCIBLE"
    assert (repo / out1["output"]).read_bytes() == stored


# ---------------------------------------------------------------- versions: old results are never rewritten
def _edit_contract(root: Path, fn):
    p = root / "data/dictionary/private_signals.yaml"
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    fn({s["signal_id"]: s for s in raw["signals"]})
    p.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")


def test_a_changed_definition_needs_a_new_version_and_leaves_old_results_alone(repo, capsys):
    write_snapshot(repo, first(), S1)
    out1 = json.loads(invoke(capsys, "diagnose-private")[1].out)
    old = (repo / out1["output"]).read_bytes()
    _edit_contract(repo, lambda s: s["A1_dr007_liquidity_trend"]["thresholds"].update(easing_at_or_below_bp=-25))
    code, io = invoke(capsys, "diagnose-private")
    assert code == 1 and json.loads(io.out)["error"] == "SIGNAL_DEFINITION_CHANGED_WITHOUT_VERSION_BUMP"
    _edit_contract(repo, lambda s: s["A1_dr007_liquidity_trend"].update(version=2))
    code, io = invoke(capsys, "diagnose-private")
    out2 = json.loads(io.out)
    assert code == 0 and out2["run_id"] != out1["run_id"] and out2["signals"]["A1_dr007_liquidity_trend"] == "STABLE"
    assert (repo / out1["output"]).read_bytes() == old                           # the v1 result is untouched
    v1 = json.loads(old)["signals"][0]
    v2 = json.loads((repo / out2["output"]).read_text(encoding="utf-8"))["signals"][0]
    assert (v1["signal_version"], v1["status"]) == (1, "EASING") and (v2["signal_version"], v2["status"]) == (2, "STABLE")
    # editing only the wording (title, caveats) needs no new version
    _edit_contract(repo, lambda s: s["A1_dr007_liquidity_trend"].update(title="Reworded title"))
    assert invoke(capsys, "diagnose-private")[0] == 0


# ---------------------------------------------------------------- genuine snapshots and what changed
def test_what_changed_compares_only_genuine_earlier_snapshots(repo, capsys):
    write_snapshot(repo, first(hh=HH_WEAKENING, cities=PROP_DOWN), S1)
    out1 = json.loads(invoke(capsys, "diagnose-private")[1].out)
    write_snapshot(repo, second(hh=HH_BROADENING, corp=CORP_BROADENING, cities=PROP_UP), S2)
    code, io = invoke(capsys, "diagnose-private")
    out2 = json.loads(io.out)
    assert code == 0 and out2["snapshot"] == S2 and out2["previous_snapshot"] == S1
    doc = json.loads((repo / out2["output"]).read_text(encoding="utf-8"))
    ch = {c["signal_id"]: c for c in doc["changes"]}
    assert ch["A1_dr007_liquidity_trend"]["before"] == "EASING" and ch["A1_dr007_liquidity_trend"]["after"] == "TIGHTENING"
    assert ch["R1_domestic_demand_confirmation"]["before"] == "NEGATIVE"
    assert ch["R1_domestic_demand_confirmation"]["after"] == "POSITIVE" and ch["R1_domestic_demand_confirmation"]["class_changed"]
    assert "delta_bp" in ch["A1_dr007_liquidity_trend"]["numeric_change"]
    report = (repo / out2["report"]).read_text(encoding="utf-8")
    assert f"Previous genuine snapshot: `data/private/observations/wind_{S1}.csv`" in report
    # the earlier snapshot, diagnosed again, is unaffected by the later one
    code, io = invoke(capsys, "diagnose-private", "--snapshot", S1)
    assert json.loads(io.out)["status"] == "reproduced" and json.loads(io.out)["run_id"] == out1["run_id"]


def test_a_snapshot_that_does_not_match_its_manifest_is_never_used(repo, capsys):
    write_snapshot(repo, first(), S1, manifest_sha="0" * 64)
    code, io = invoke(capsys, "diagnose-private", "--snapshot", S1)
    assert code == 1 and json.loads(io.out)["error"] == "SNAPSHOT_NOT_VERIFIED"
    write_snapshot(repo, second(), S2)
    out = json.loads(invoke(capsys, "diagnose-private")[1].out)
    assert out["previous_snapshot"] is None                    # a tampered file is not a genuine earlier snapshot
    doc = json.loads((repo / out["output"]).read_text(encoding="utf-8"))
    assert any("SHA256 differs" in p for p in doc["unverified_snapshots_ignored"])


def test_without_a_snapshot_it_fails_cleanly(repo, capsys):
    code, io = invoke(capsys, "diagnose-private")
    assert code == 1 and json.loads(io.out)["error"] == "NO_VERIFIED_SNAPSHOT"
    assert not (repo / "data/private/signals").exists()


def test_diagnose_private_never_runs_in_ci(repo, capsys, monkeypatch):
    write_snapshot(repo, first(), S1)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    code, io = invoke(capsys, "diagnose-private")
    assert code == 1 and json.loads(io.out)["error"] == "PRIVATE_DIAGNOSIS_IS_LOCAL_ONLY"
    assert not (repo / "data/private/signals").exists()


# ---------------------------------------------------------------- preregistration is untouched
def test_private_diagnostics_cannot_move_tests_or_terminal_rules(repo, capsys):
    metrics = load_dictionary("data/dictionary/metrics.yaml")
    case = cli.case_in_force()
    public_only = load_observations("data/demo/observations")
    when = "2026-10-10T08:00:00Z"
    res0, term0, _ = cli.evaluate_case(public_only, metrics, case, when)
    # the most thesis-friendly private picture possible: easing, broad credit, property boom, reflation pricing
    write_snapshot(repo, first(hh=HH_BROADENING, corp=CORP_BROADENING, cities=PROP_UP, csi_return_pct=15.0,
                               cgb_change_bp=25.0), S1)
    out = json.loads(invoke(capsys, "diagnose-private")[1].out)
    assert out["signals"]["R3_market_confirmation"] == "CONFIRMS" and out["signals"]["R1_domestic_demand_confirmation"] == "POSITIVE"
    res1, term1, _ = cli.evaluate_case(load_observations(*cli.obs_dirs(False)), metrics, cli.case_in_force(), when)
    assert term1 == term0 and {k: r.outcome for k, r in res1.items()} == {k: r.outcome for k, r in res0.items()}
    doc = json.loads((repo / out["output"]).read_text(encoding="utf-8"))
    assert doc["public_state"]["terminal_status"] == term0
    assert doc["public_state"]["tests"] == {k: {"hypothesis": r.hypothesis, "outcome": r.outcome, "effect": r.effect,
                                                "latest_period": r.latest_period} for k, r in res0.items()}
    # no signal id or supplemental metric is an evidence test or a terminal-rule input
    text = json.dumps({"tests": case["evidence_tests"], "rules": case["terminal_rules"]})
    contract = signals.load_signal_contract(signals.SIGNALS_CONTRACT, metrics)
    assert not any(s.signal_id in text for s in contract.signals)
    assert not any(mid in text for mid, m in metrics.items() if m.tier == "supplemental")
    assert not list((repo / "research/cases/cn-nominal").rglob("*private*"))


# ---------------------------------------------------------------- the public boundary
PUBLIC_CODE = ["site/build.py", "site/views.py", "site/charts.py", "site/localization.py", "src/cnmacro/refresh.py",
               "src/cnmacro/checks.py", "src/cnmacro/replay.py", "src/cnmacro/claims.py", "src/cnmacro/derive.py",
               "src/cnmacro/evidence.py", "src/cnmacro/thesis.py", "src/cnmacro/store.py", "src/cnmacro/ingest.py",
               "scripts/vercel_build.sh"]


def test_no_public_code_path_can_load_private_diagnostics():
    for rel in PUBLIC_CODE:
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"\b(import|from)\s+[.\w]*\b(signals|diagnose)\b", src), rel
        assert "data/private/signals" not in src and "data/private/research" not in src, rel
        assert "private_signals" not in src and "diagnose-private" not in src, rel


def test_ci_never_runs_private_refresh_or_diagnosis():
    for wf in (ROOT / ".github/workflows").glob("*.yml"):
        text = wf.read_text(encoding="utf-8")
        assert "diagnose-private" not in text and "refresh-private" not in text, wf.name
    for f in ("netlify.toml", "vercel.json", "scripts/vercel_build.sh"):
        text = (ROOT / f).read_text(encoding="utf-8")
        assert "diagnose" not in text and "data/private" not in text, f


def test_private_outputs_are_gitignored_and_blocked():
    paths = ["data/private/signals/x.json", "data/private/research/x/PRIVATE_DIAGNOSTIC_REPORT.md"]
    done = subprocess.run(["git", "check-ignore", "--no-index", *paths], cwd=ROOT, capture_output=True, text=True)
    assert done.stdout.split() == paths
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_secrets", ROOT / "scripts/check_secrets.py")
    cs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cs)
    assert all(any(re.search(pat, p) for pat, _ in cs.FORBIDDEN_PATHS) for p in paths)
    tracked = subprocess.check_output(["git", "ls-files", "data/private", "research/private"], cwd=ROOT, text=True).split()
    # nothing but an optional README may be tracked in the private folders (the public snapshot ships none)
    assert set(tracked) <= {"data/private/README.md", "research/private/README.md"}, tracked


def test_the_tracked_contract_holds_definitions_not_values():
    raw = yaml.safe_load((ROOT / "data/dictionary/private_signals.yaml").read_text(encoding="utf-8"))
    allowed = {"signal_id", "version", "layer", "block", "title", "method", "inputs", "window", "formula", "thresholds",
               "classification", "minimum_coverage", "research_role", "hypothesis_mapping", "caveats", "per_input",
               "validation"}
    for s in raw["signals"]:
        assert set(s) <= allowed, s["signal_id"]
    assert set(raw) == {"contract_version", "private_only", "precision", "holiday_caveat_windows", "signals"}


def test_the_public_site_names_no_private_signal(built):
    contract = signals.load_signal_contract(ROOT / "data/dictionary/private_signals.yaml")
    ids = [s.signal_id for s in contract.signals] + ["cn_cgb10y_daily", "PRIVATE_DIAGNOSTIC_REPORT"]
    for page in built.rglob("*.html"):
        html = page.read_text(encoding="utf-8")
        assert not any(i in html for i in ids), page.name
