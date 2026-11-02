"""`refresh-private`, `wind-runtime` and the public/private boundary, end to end in an isolated copy of the repo.

The copy gets the tracked dictionary, public data and research case; the Wind skill and transport are the
synthetic ones from tests/wind_support.py. Nothing here touches the real Wind skill, key or private data."""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from provider_support import alt_route, append_activation, route_cn_dr007
from wind_support import FAKE, ROOT, Clock, FakeWind, error_envelope, make_skill, pinned_runtime

from cnmacro import cli, ingest, normalize, wind
from cnmacro.store import load_dictionary, load_observations


def tree_digest(root: Path, skip=("data/private",)) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and not any(rel == s or rel.startswith(s + "/") for s in skip):
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """An isolated working copy with a synthetic skill, a runtime pinned to it, and a scripted transport."""
    for rel in ("data/dictionary", "data/demo", "research/cases/cn-nominal"):
        shutil.copytree(ROOT / rel, tmp_path / rel, ignore=shutil.ignore_patterns("latest-private.json"))
    skill = make_skill(tmp_path)
    monkeypatch.chdir(tmp_path)
    runtime_file = tmp_path / "data/dictionary/wind_runtime.yaml"
    real = wind.load_runtime(runtime_file)
    wind.pin_runtime(runtime_file, wind.read_runtime(skill, pinned_runtime(real)))
    metrics = load_dictionary(tmp_path / "data/dictionary/metrics.yaml")
    fake = FakeWind(wind.plan_groups(metrics, wind.load_runtime(runtime_file)), metrics)
    monkeypatch.setattr(wind, "locate_skill_dir", lambda *a, **k: skill)
    monkeypatch.setattr(wind, "cli_transport", lambda *a, **k: fake)
    monkeypatch.setattr(ingest, "sync_clock", lambda *a, **k: 0.0)
    monkeypatch.setattr(ingest, "now_iso", Clock("2026-10-10T08:00:00+00:00"))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    # the real eval re-runs every claim against the whole store (tens of seconds); most tests stub it
    real_eval = cli.private_eval
    monkeypatch.setattr(cli, "private_eval", lambda metrics, now: {
        "overall": "pass", "checks": {c: "pass" for c in ("E0", "E1", "E2", "E3", "E4", "E5")}, "details": {},
        "terminal": "ACTIVE", "tests": {}})
    return type("Repo", (), {"root": tmp_path, "skill": skill, "fake": fake, "runtime_file": runtime_file,
                             "use_real_eval": staticmethod(lambda: monkeypatch.setattr(cli, "private_eval", real_eval))})


def invoke(capsys, *argv):
    code = cli.main(list(argv))
    return code, capsys.readouterr()


# ---------------------------------------------------------------- refresh-private
def test_refresh_private_runs_the_whole_local_path(repo, capsys):
    repo.use_real_eval()
    before = tree_digest(repo.root)
    code, io = invoke(capsys, "refresh-private", "--provider", "wind")
    assert code == 0, io.out
    summary = json.loads(io.out)
    assert summary["status"] == "refreshed" and summary["calls"] == 5 and summary["metrics"] == 14
    assert summary["runtime_version"] == "9.9.9" and summary["eval"] in ("pass", "warn")
    assert summary["private_rows"] > 0 and summary["raw_dir"].startswith("data/private/wind/runs/")
    assert summary["snapshot"] == f"data/private/observations/wind_{summary['run_id']}.csv"
    assert set(summary["checks"]) == {"E0", "E1", "E2", "E3", "E4", "E5"} and summary["checks"]["E3"] == "pass"
    assert (repo.root / summary["snapshot"]).exists()
    # a private summary is written next to the run's manifest and raw responses
    run_dir = repo.root / summary["raw_dir"]
    assert (run_dir / "manifest.json").exists() and (run_dir / "summary.json").exists() and any((run_dir / "raw").iterdir())
    detail = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))["eval_detail"]
    assert detail["terminal"] and detail["tests"] and set(detail["checks"]) == {"E0", "E1", "E2", "E3", "E4", "E5"}
    # and nothing tracked changed: no public data, refresh record, thesis file, eval report or site
    assert tree_digest(repo.root) == before
    assert sorted(p.name for p in (repo.root / "research/cases/cn-nominal/eval").iterdir()) == ["latest.json"]
    # (the tree digest above already proves no refresh record was written; the case directory may legitimately
    # hold earlier ones, written by the scheduled public refresh)
    assert not (repo.root / "site").exists()


def test_refresh_private_prints_no_wind_values(repo, capsys):
    code, io = invoke(capsys, "refresh-private", "--provider", "wind")
    assert code == 0
    text = io.out + io.err
    for v in (FAKE, FAKE + 1, FAKE + 2, FAKE + 7, FAKE + 8):
        assert str(v) not in text
    run_dir = repo.root / json.loads(io.out)["raw_dir"]
    assert str(FAKE + 1) not in (run_dir / "manifest.json").read_text(encoding="utf-8")


def test_private_mode_checks_public_plus_private_and_comes_back_clean(repo, capsys):
    invoke(capsys, "refresh-private", "--provider", "wind")
    code, io = invoke(capsys, "check")                                     # the real, unstubbed private check
    assert "[FAIL]" not in io.out and "cn_cgb10y: no observations" not in io.out        # Wind filled the core gap
    assert code == 0
    private = load_observations(*cli.obs_dirs(False))
    assert {"Wind", "NBS"} <= set(private["source"]) and "private" in set(private["source_class"])


def test_a_failed_refresh_reports_accurately_and_publishes_nothing(repo, capsys):
    repo.fake.script["credit"] = [error_envelope("AUTH_ERROR", "bad key")]
    code, io = invoke(capsys, "refresh-private", "--provider", "wind")
    out = json.loads(io.out)
    assert code == 1 and out["status"] == "failed" and out["error"] == "AUTH_ERROR" and out["group"] == "credit"
    assert out["published"] is False and out["calls"] == 2
    obs_dir = repo.root / "data/private/observations"
    assert not obs_dir.exists() or list(obs_dir.glob("*")) == []
    assert (repo.root / out["raw_dir"] / "manifest.json").exists()


def test_quota_exhaustion_is_reported_as_blocked_quota(repo, capsys):
    repo.fake.script["rates"] = [error_envelope("backend_error", "账户积分余额不足，请充值")]
    code, io = invoke(capsys, "refresh-private", "--provider", "wind")
    assert code == 1 and json.loads(io.out)["error"] == "BLOCKED_QUOTA" and json.loads(io.out)["calls"] == 1


def test_plan_makes_no_call_and_writes_nothing(repo, capsys):
    before = tree_digest(repo.root, skip=())
    code, io = invoke(capsys, "refresh-private", "--provider", "wind", "--plan")
    plan = json.loads(io.out)
    assert code == 0 and plan["status"] == "plan" and plan["calls"] == 5 and plan["runtime"] == "match"
    assert [g["group"] for g in plan["groups"]] == ["rates", "credit", "property", "consensus", "market"]
    assert repo.fake.calls == [] and tree_digest(repo.root, skip=()) == before and not (repo.root / "data/private").exists()


def test_plan_reports_runtime_drift_without_calling(repo, capsys):
    (repo.skill / "scripts/call-rules.json").write_bytes(b'{"changed": 1}')
    code, io = invoke(capsys, "refresh-private", "--provider", "wind", "--plan")
    assert code == 1 and json.loads(io.out)["error"] == "WIND_RUNTIME_DRIFT" and repo.fake.calls == []


# ---------------------------------------------------------------- --provider: Wind is an explicit opt-in
def test_wind_runs_only_when_it_is_named(repo, capsys):
    """Wind spends paid credits: no flag, no call. The refusal itself makes no call and writes nothing."""
    for argv in (("refresh-private",), ("refresh-private", "--plan")):
        code, io = invoke(capsys, *argv)
        out = json.loads(io.out)
        assert code == 1 and out["status"] == "failed" and out["error"] == "NO_PROVIDER_SELECTED", argv
        assert out["available"] == ["wind"] and "--provider wind" in out["message"]
    assert repo.fake.calls == [] and not (repo.root / "data/private").exists()


def test_an_unknown_provider_is_refused_before_anything_runs(repo, capsys):
    code, io = invoke(capsys, "refresh-private", "--provider", "nowhere")
    out = json.loads(io.out)
    assert code == 1 and out["error"] == "UNKNOWN_PROVIDER" and "nowhere" in out["message"] and out["available"] == ["wind"]
    code, io = invoke(capsys, "refresh-private", "--provider", "wind", "nowhere")          # one unknown spoils the whole request
    assert code == 1 and json.loads(io.out)["error"] == "UNKNOWN_PROVIDER"
    assert repo.fake.calls == [] and not (repo.root / "data/private").exists()


def test_the_summary_names_its_provider_and_the_manifest_carries_the_generic_runtime_block(repo, capsys):
    code, io = invoke(capsys, "refresh-private", "--provider", "wind")
    summary = json.loads(io.out)
    assert code == 0 and summary["provider"] == "wind" and summary["runtime_version"] == "9.9.9"
    manifest = json.loads((repo.root / summary["raw_dir"] / "manifest.json").read_text(encoding="utf-8"))
    rt = manifest["runtime"]
    assert rt["kind"] == wind.RUNTIME_KIND == "wind-mcp-skill" and rt["version"] == "9.9.9"
    assert rt["fingerprints"] == rt["pre"]["files"] == rt["expected"]["files"] and rt["unchanged"] is True
    assert "skill" not in manifest                                       # the Wind-specific block is gone from new manifests
    assert normalize.runtime_version(manifest) == "9.9.9"


def test_a_manifest_written_before_the_generic_block_is_still_read():
    legacy = {"skill": {"expected_version": "1.2.3", "version": "1.2.3", "dir": "x"}, "runtime": {"pre": {}, "post": {}}}
    assert normalize.runtime_version(legacy) == "1.2.3"                  # existing manifests are read as they are
    assert normalize.runtime_version({**legacy, "runtime": {"version": "2.0.0"}}) == "2.0.0"
    assert normalize.runtime_version({}) is None
    block = normalize.runtime_block("http-endpoint", {"version": "v1"})
    assert block == {"kind": "http-endpoint", "version": None, "fingerprints": {}, "expected": {"version": "v1"}}


def _stub(order, name, status="refreshed", default=False):
    def refresh(metrics):
        order.append(name)
        if status == "failed":
            return {"status": "failed", "error": "NETWORK_ERROR", "published": False, "raw_dir": f"data/private/{name}/runs/r"}
        raw = Path(f"data/private/{name}/runs/r")
        raw.mkdir(parents=True)
        return {"status": "refreshed", "run_id": "r", "calls": 1, "raw_dir": raw.as_posix()}
    return cli.Adapter(plan=lambda m: {"status": "plan", "calls": 1}, refresh=refresh, default=default)


@pytest.fixture
def evals(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "private_eval", lambda metrics, now: seen.append(now) or {
        "overall": "pass", "checks": {"E0": "pass"}, "details": {}, "terminal": "ACTIVE", "tests": {}})
    return seen


def test_several_providers_run_in_the_order_named_and_one_failure_leaves_the_others_alone(repo, capsys, monkeypatch, evals):
    order = []
    monkeypatch.setattr(cli, "ADAPTERS", {n: _stub(order, n, "failed" if n == "two" else "refreshed") for n in ("one", "two", "three")})
    code, io = invoke(capsys, "refresh-private", "--provider", "three", "one", "two", "one")
    out = json.loads(io.out)
    assert order == ["three", "one", "two"]                                              # in order, a duplicate once
    assert code == 1 and out["status"] == "partial"
    assert [(p["provider"], p["status"]) for p in out["providers"]] == [("three", "refreshed"), ("one", "refreshed"), ("two", "failed")]
    assert len(evals) == 1                                                               # the private eval runs once, after all of them
    assert all("eval" in p for p in out["providers"] if p["status"] == "refreshed")
    assert (repo.root / "data/private/three/runs/r/summary.json").exists() and not (repo.root / "data/private/two").exists()


def test_when_every_provider_fails_nothing_is_evaluated(repo, capsys, monkeypatch, evals):
    order = []
    monkeypatch.setattr(cli, "ADAPTERS", {n: _stub(order, n, "failed") for n in ("one", "two")})
    code, io = invoke(capsys, "refresh-private", "--provider", "one", "two")
    assert code == 1 and json.loads(io.out)["status"] == "failed" and order == ["one", "two"] and evals == []


def test_a_single_provider_prints_its_own_result_and_a_plan_runs_every_selected_plan(repo, capsys, monkeypatch, evals):
    order = []
    monkeypatch.setattr(cli, "ADAPTERS", {n: _stub(order, n) for n in ("one", "two")})
    code, io = invoke(capsys, "refresh-private", "--provider", "one")
    assert code == 0 and json.loads(io.out)["provider"] == "one" and "providers" not in json.loads(io.out)
    code, io = invoke(capsys, "refresh-private", "--provider", "one", "two", "--plan")
    out = json.loads(io.out)
    assert code == 0 and out["status"] == "plan" and [p["provider"] for p in out["providers"]] == ["one", "two"]
    assert order == ["one"]                                                              # a plan refreshes nothing


@pytest.mark.parametrize("change, runs", [
    ({}, True),                                                                          # collected candidate, retrieval permitted
    ({"collect": False}, False),                                                         # declared but neither active nor collected
    ({"access": {"automated_retrieval": "prohibited", "manual_import": "prohibited", "private_use": "permitted",
                 "redistribution": "prohibited", "basis": "synthetic"}}, False),         # retrieval is not permitted
    ({"access": {"automated_retrieval": "unknown", "manual_import": "permitted", "private_use": "permitted",
                 "redistribution": "prohibited", "basis": "synthetic"}}, False),         # `unknown` is prohibited
])
def test_with_no_provider_named_only_a_permitted_default_adapter_with_a_collected_route_runs(repo, capsys, monkeypatch, evals, change, runs):
    route_cn_dr007(repo.root / "data/dictionary/metrics.yaml", alt=alt_route(provider="free", series_key="FREE:cn_dr007", **change))
    order = []
    monkeypatch.setattr(cli, "ADAPTERS", {"free": _stub(order, "free", default=True), **cli.ADAPTERS})
    code, io = invoke(capsys, "refresh-private")
    out = json.loads(io.out)
    assert repo.fake.calls == []                                                         # Wind is never run unless it is named
    if runs:
        assert code == 0 and out["provider"] == "free" and order == ["free"]
    else:
        assert code == 1 and out["error"] == "NO_PROVIDER_SELECTED" and order == []


def test_an_adapter_whose_route_is_active_now_runs_by_default_even_if_it_is_not_collected_as_a_candidate(repo, capsys, monkeypatch, evals):
    path = repo.root / "data/dictionary/metrics.yaml"
    route_cn_dr007(path, alt=alt_route(provider="free", series_key="FREE:cn_dr007", collect=False))
    append_activation(path, "2026-10-12T00:00:00Z", active="free")
    order = []
    monkeypatch.setattr(cli, "ADAPTERS", {"free": _stub(order, "free", default=True), **cli.ADAPTERS})
    code, io = invoke(capsys, "refresh-private")
    assert code == 0 and order == ["free"] and repo.fake.calls == []


def test_refresh_private_refuses_to_run_in_github_actions(repo, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    code, io = invoke(capsys, "refresh-private", "--provider", "wind")
    assert code == 1 and json.loads(io.out)["error"] == "PRIVATE_REFRESH_IS_LOCAL_ONLY"
    assert repo.fake.calls == [] and not (repo.root / "data/private").exists()


def test_no_workflow_runs_the_private_refresh():
    for wf in (ROOT / ".github/workflows").glob("*.yml"):
        text = wf.read_text(encoding="utf-8")
        assert "refresh-private" not in text and "WIND_API_KEY" not in text and not re.search(r"wind", text, re.I), wf.name


# ---------------------------------------------------------------- wind-runtime
def test_wind_runtime_verifies_without_a_wind_call(repo, capsys):
    code, io = invoke(capsys, "wind-runtime")
    out = json.loads(io.out)
    assert code == 0 and out["status"] == "match" and out["installed_version"] == out["pinned_version"] == "9.9.9"
    assert repo.fake.calls == []


def test_wind_runtime_reports_drift_and_only_repins_on_request(repo, capsys):
    cli_js = repo.skill / "scripts/cli.mjs"
    cli_js.write_bytes(cli_js.read_bytes().replace(b"9.9.9", b"9.9.10"))
    code, io = invoke(capsys, "wind-runtime")
    out = json.loads(io.out)
    assert code == 1 and out["status"] == "drift" and any("version" in d for d in out["differences"])
    assert wind.load_runtime(repo.runtime_file).version == "9.9.9"                    # inspection never rewrites the pin
    code, io = invoke(capsys, "wind-runtime", "--pin")
    assert code == 0 and json.loads(io.out)["status"] == "pinned"
    assert wind.load_runtime(repo.runtime_file).version == "9.9.10"
    assert invoke(capsys, "wind-runtime")[0] == 0


def test_a_run_after_a_skill_update_fails_closed_until_it_is_repinned(repo, capsys):
    cli_js = repo.skill / "scripts/cli.mjs"
    cli_js.write_bytes(cli_js.read_bytes() + b"// a new release\n")
    code, io = invoke(capsys, "refresh-private", "--provider", "wind")
    out = json.loads(io.out)
    assert code == 1 and out["error"] == "WIND_RUNTIME_DRIFT" and out["calls"] == 0
    assert repo.fake.calls == []


# ---------------------------------------------------------------- the public/private boundary
def test_public_mode_never_loads_private_observations(repo, capsys, monkeypatch):
    invoke(capsys, "refresh-private", "--provider", "wind")
    (repo.root / "data/private/observations/poison.csv").write_text("metric_id\nnot a valid file\n", encoding="utf-8")
    seen = {}
    monkeypatch.setattr(cli.checks, "run_all", lambda obs, *a, **k: seen.setdefault("check", []).append(obs) or [])
    monkeypatch.setattr(cli.checks, "write_report", lambda *a, **k: {})
    monkeypatch.setattr(cli, "evaluate_case", lambda obs, *a, **k: seen.setdefault("evaluate", []).append(obs) or ({}, "ACTIVE", False))
    assert invoke(capsys, "check", "--public")[0] == 0 and invoke(capsys, "evaluate", "--public", "--as-of", "2026-10-13T20:00")[0] == 0
    for frame in (seen["check"][0], seen["evaluate"][0]):
        assert "Wind" not in set(frame["source"]) and "private" not in set(frame["source_class"])
        assert not frame["_file"].str.contains("private").any()
    # the same commands without --public do load it (the poisoned file is not a valid observation file, so skip it here)
    (repo.root / "data/private/observations/poison.csv").unlink()
    invoke(capsys, "check")
    assert "Wind" in set(seen["check"][1]["source"])
    assert cli.obs_dirs(True) == [cli.DEMO_OBS] and cli.PRIVATE_OBS in cli.obs_dirs(False)


def test_wind_data_cannot_leak_into_a_historical_evaluation(repo, capsys):
    invoke(capsys, "refresh-private", "--provider", "wind")                       # retrieved 2026-10-10
    private = load_observations(*cli.obs_dirs(False))
    from cnmacro.store import as_of
    assert as_of(private[private.source == "Wind"], "2026-10-05").empty             # a pre-retrieval as-of date sees none of it


def test_the_secrets_and_data_boundary_check_stays_green():
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    done = subprocess.run([sys.executable, str(ROOT / "scripts/check_secrets.py")], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout


def test_no_wind_skill_or_private_file_is_tracked():
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    assert not [f for f in tracked if f.startswith("data/private/") and f != "data/private/README.md"]
    assert not [f for f in tracked if f.endswith(("cli.mjs", "tool-manifest.json", "call-rules.json", "update-check.mjs"))]
    assert not [f for f in tracked if "wind-mcp-skill" in f]
    assert not [f for f in tracked if f.endswith("latest-private.json")]
