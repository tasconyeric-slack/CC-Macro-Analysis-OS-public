"""`diagnose-private` over several providers, end to end in an isolated copy of the repo: anchors, candidates, the
route filter at the anchor's time, `routes` in every run, the genesis rule for legacy runs, and the retroactivity guard.
Synthetic publications only; `altprov` is a stand-in provider (tests/provider_support.py) and nothing is fetched."""
import json
import shutil

import pytest
from provider_support import ALT, DICT_REL, ROUTED, append_activation, commit_dictionary, edited, init_repo, route_cn_dr007
from signal_support import ROOT, Scenario, write_publication, write_snapshot

from cnmacro import cli

C1, S1, P1, A4, C2 = "20261008T075900Z", "20261010T075900Z", "20261011T075900Z", "20261017T075900Z", "20261020T075900Z"
E = "2026-10-12T00:00:00Z"                  # T3: the activation that makes `altprov` authoritative
NO_OTHER_INPUTS = dict(cgb_change_bp=None, csi_return_pct=None, hh=None, corp=None, cities={}, consensus=False)


def wind_t2() -> Scenario:                  # T2: the Wind anchor; DR007 eases
    return Scenario(dr007=(1.8137, 1.6911), retrieved_at="2026-10-10T07:59:00+00:00")


def alt(retrieved_at: str, last_day: str, dr007=(1.80, 1.95), n=40) -> Scenario:
    return Scenario(provider=ALT, dr007=dr007, dr007_n=n, retrieved_at=retrieved_at, last_day=last_day, **NO_OTHER_INPUTS)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for rel in ("data/dictionary", "data/demo", "research/cases/cn-nominal"):
        shutil.copytree(ROOT / rel, tmp_path / rel, ignore=shutil.ignore_patterns("latest-private.json"))
    route_cn_dr007(tmp_path / DICT_REL)                      # cn_dr007: Wind from genesis, `altprov` declared and collected
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return tmp_path


def invoke(capsys, *argv):
    code = cli.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def doc_of(repo, out):
    return json.loads((repo / out["output"]).read_text(encoding="utf-8"))


def a1(doc):
    return next(s for s in doc["signals"] if s["signal_id"] == "A1_dr007_liquidity_trend")


def private_tree(repo):
    return sorted(p.relative_to(repo).as_posix() for p in (repo / "data/private").rglob("*") if p.is_file())


# ---------------------------------------------------------------- T1..T4: point-in-time routing end to end
def test_the_temporal_activation_sequence(repo, capsys):
    # T1: a second provider publishes DR007, but its route is not authoritative: a candidate publication
    c1 = write_publication(repo, alt("2026-10-08T07:59:00+00:00", "2026-10-07"), C1, "candidates")
    candidate_bytes = c1.read_bytes()

    # T2: Wind publishes and is the anchor; the candidate (retrieved earlier, same periods) is not in the information set
    write_snapshot(repo, wind_t2(), S1)
    code, out2 = invoke(capsys, "diagnose-private")
    assert code == 0 and out2["status"] == "diagnosed" and out2["anchor"] == f"wind_{S1}" and out2["snapshot"] == S1
    doc2 = doc_of(repo, out2)
    assert doc2["routes"][ROUTED] == {"provider": "wind", "series_key": doc2["routes"][ROUTED]["series_key"],
                                      "equivalence": "EXACT", "effective_at": "genesis"}
    assert set(out2["routes"].values()) == {"wind"} and doc2["anchor"]["provider"] == "wind" and doc2["anchor"]["stem"] == f"wind_{S1}"
    assert doc2["information_set"]["private_files"] == [f"wind_{S1}.csv"]
    assert a1(doc2)["status"] == "EASING"                                           # Wind's DR007, not the candidate's
    assert all(i.endswith(f"#wind_{S1}") for i in a1(doc2)["input_observation_ids"])
    stored_r2 = (repo / out2["output"]).read_bytes()

    # T3: a reviewed record is appended; it changes nothing that already exists
    append_activation(repo / DICT_REL, E)

    # the replay of T2 still resolves Wind, byte for byte (the `--snapshot` alias is the same anchor)
    for args in (("--anchor", f"wind_{S1}"), ("--snapshot", S1)):
        code, again = invoke(capsys, "diagnose-private", *args)
        assert code == 0 and again["status"] == "reproduced" and again["run_id"] == out2["run_id"]
        assert set(again["routes"].values()) == {"wind"}
    assert (repo / out2["output"]).read_bytes() == stored_r2

    # T4: the newly activated provider publishes an active publication and becomes the anchor
    write_publication(repo, alt("2026-10-17T07:59:00+00:00", "2026-10-16", n=10), A4, "observations")
    code, out4 = invoke(capsys, "diagnose-private")
    assert code == 0 and out4["anchor"] == f"{ALT}_{A4}" and out4["snapshot"] == f"{ALT}_{A4}" and out4["previous_snapshot"] == S1
    assert out4["run_id"].startswith(f"{ALT}_{A4}-") and out4["routes"][ROUTED] == ALT
    doc4 = doc_of(repo, out4)
    assert doc4["routes"][ROUTED]["provider"] == ALT and doc4["routes"][ROUTED]["effective_at"] == E
    assert set(doc4["information_set"]["private_files"]) == {f"{ALT}_{A4}.csv", f"{ALT}_{C1}.csv", f"wind_{S1}.csv"}   # the T1 rows are history now
    ids = a1(doc4)["input_observation_ids"]
    assert ids and all(i.endswith((f"#{ALT}_{A4}", f"#{ALT}_{C1}")) for i in ids)       # no Wind row enters DR007's window
    assert a1(doc4)["status"] == "TIGHTENING"
    # the provider switch is annotated, and the signal means the same thing
    change = next(c for c in doc4["changes"] if c["signal_id"] == "A1_dr007_liquidity_trend")
    assert change["route_changes"] == [{"metric_id": ROUTED, "before": "wind", "after": ALT}] and "input route changed" in change["note"]
    assert a1(doc4)["definition_sha256"] == a1(doc2)["definition_sha256"]
    # nothing that existed was moved or rewritten
    assert (repo / out2["output"]).read_bytes() == stored_r2 and c1.read_bytes() == candidate_bytes and c1.parent.name == "candidates"
    assert "Provider history inside a publication" in (repo / out4["report"]).read_text(encoding="utf-8")


def test_a_later_retrieved_candidate_cannot_displace_the_active_provider_in_a_diagnosis(repo, capsys):
    """Wind publishes DR007 on 10-10; `altprov` publishes it LATER (10-11) as a candidate; a Wind anchor on 10-12 carries
    only other metrics. Without the filter store.as_of would pick the later altprov rows for DR007."""
    write_snapshot(repo, wind_t2(), S1)
    write_publication(repo, alt("2026-10-11T07:59:00+00:00", "2026-10-10"), "20261011T075900Z", "candidates")
    later_wind = Scenario(retrieved_at="2026-10-12T07:59:00+00:00", last_day="2026-10-11", dr007=None)      # no DR007 in this file
    write_snapshot(repo, later_wind, "20261012T075900Z")
    code, out = invoke(capsys, "diagnose-private")
    assert code == 0 and out["anchor"] == "wind_20261012T075900Z" and out["previous_snapshot"] == S1
    doc = doc_of(repo, out)
    assert a1(doc)["status"] == "EASING" and all(i.endswith(f"#wind_{S1}") for i in a1(doc)["input_observation_ids"])
    assert not any(f.startswith(ALT) for f in doc["information_set"]["private_files"])


# ---------------------------------------------------------------- candidates are never anchors, never evidence
def test_a_candidate_publication_is_never_an_anchor(repo, capsys):
    write_snapshot(repo, wind_t2(), S1)
    write_publication(repo, alt("2026-10-20T07:59:00+00:00", "2026-10-19"), C2, "candidates")   # the NEWEST file of all
    code, out = invoke(capsys, "diagnose-private")
    assert code == 0 and out["anchor"] == f"wind_{S1}"
    code, err = invoke(capsys, "diagnose-private", "--anchor", f"{ALT}_{C2}")
    assert code == 1 and err["error"] == "ANCHOR_NOT_ELIGIBLE" and "candidate" in err["message"]
    append_activation(repo / DICT_REL, "2026-10-13T00:00:00Z")                          # even once its route is active
    code, err = invoke(capsys, "diagnose-private", "--anchor", f"{ALT}_{C2}")
    assert code == 1 and err["error"] == "ANCHOR_NOT_ELIGIBLE" and "candidate" in err["message"]
    code, out = invoke(capsys, "diagnose-private")
    assert code == 0 and out["anchor"] == f"wind_{S1}"


def test_a_candidate_copied_into_observations_is_not_verified_and_not_an_anchor(repo, capsys):
    write_snapshot(repo, wind_t2(), S1)
    c2 = write_publication(repo, alt("2026-10-20T07:59:00+00:00", "2026-10-19"), C2, "candidates")
    shutil.copy(c2, repo / "data/private/observations" / c2.name)                       # the manifest records it as a candidate
    code, out = invoke(capsys, "diagnose-private")
    assert code == 0 and out["anchor"] == f"wind_{S1}"
    assert any(f"{ALT}_{C2}.csv" in p and "does not record this file under data/private/observations" in p
               for p in doc_of(repo, out)["unverified_snapshots_ignored"])
    code, err = invoke(capsys, "diagnose-private", "--anchor", f"{ALT}_{C2}")
    assert code == 1 and err["error"] == "ANCHOR_NOT_ELIGIBLE"


def test_a_publication_made_before_its_route_was_active_never_becomes_an_anchor_later(repo, capsys):
    """Eligibility is judged at the file's own time T, not at the time of the question: a file written to observations/
    while Wind was authoritative has no row on a route that was active then, and activation later does not change that."""
    write_snapshot(repo, wind_t2(), S1)
    write_publication(repo, alt("2026-10-11T07:59:00+00:00", "2026-10-10"), P1, "observations")     # after S1, before E
    append_activation(repo / DICT_REL, E)
    code, out = invoke(capsys, "diagnose-private")
    assert code == 0 and out["anchor"] == f"wind_{S1}"                                   # not the newer, pre-activation altprov file
    code, err = invoke(capsys, "diagnose-private", "--anchor", f"{ALT}_{P1}")
    assert code == 1 and err["error"] == "ANCHOR_NOT_ELIGIBLE" and "active at its own time" in err["message"]


def test_unverified_publications_are_never_loaded(repo, capsys):
    write_snapshot(repo, wind_t2(), S1)
    write_publication(repo, alt("2026-10-12T07:59:00+00:00", "2026-10-11"), P1, "observations", manifest_sha="0" * 64)
    (repo / "data/private/observations/altprov_nomanifest.csv").write_text(
        (repo / f"data/private/observations/{ALT}_{P1}.csv").read_text(encoding="utf-8"), encoding="utf-8")
    append_activation(repo / DICT_REL, "2026-10-09T00:00:00Z")                          # altprov authoritative: its rows WOULD count
    code, out = invoke(capsys, "diagnose-private")
    assert code == 0 and out["anchor"] == f"wind_{S1}"
    doc = doc_of(repo, out)
    assert doc["information_set"]["private_files"] == [f"wind_{S1}.csv"]
    problems = " ".join(doc["unverified_snapshots_ignored"])
    assert "SHA256 differs" in problems and "no run manifest" in problems


# ---------------------------------------------------------------- legacy runs and the retroactivity guard
def _strip_to_legacy(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    for key in ("routes", "anchor"):
        doc.pop(key)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def test_a_run_stored_before_routes_existed_replays_as_reproduced_under_the_genesis_state(repo, capsys):
    write_snapshot(repo, wind_t2(), S1)
    code, out = invoke(capsys, "diagnose-private")
    # every field a rerun must reproduce is byte-for-byte what Phase 2 stored (the real-data check caught a reworded reason)
    assert doc_of(repo, out)["previous_snapshot"] == {
        "status": "NOT_EVALUABLE", "reason": "Only one genuine snapshot exists; no earlier snapshot was retrieved before this one. "
                                             "Nothing is compared with reconstructed pseudo-vintages."}
    _strip_to_legacy(repo / out["output"])                                              # exactly what a Phase 2 run looked like
    assert "routes" not in json.loads((repo / out["output"]).read_text(encoding="utf-8"))
    code, again = invoke(capsys, "diagnose-private")
    assert code == 0 and again["status"] == "reproduced" and again["run_id"] == out["run_id"]
    append_activation(repo / DICT_REL, E)                                               # a later activation does not disturb it
    code, again = invoke(capsys, "diagnose-private", "--snapshot", S1)
    assert code == 0 and again["status"] == "reproduced"


def test_a_legacy_run_must_still_be_the_genesis_state(repo, capsys):
    write_snapshot(repo, wind_t2(), S1)
    code, out = invoke(capsys, "diagnose-private")
    _strip_to_legacy(repo / out["output"])
    before = private_tree(repo)
    append_activation(repo / DICT_REL, "2026-10-09T00:00:00Z")                          # before the run's as_of: it was never on altprov
    code, err = invoke(capsys, "diagnose-private")
    assert code == 1 and err["error"] == "ROUTE_HISTORY_RETROACTIVE" and ROUTED in err["message"]
    assert private_tree(repo) == before                                                 # and nothing was written


def test_a_record_before_a_stored_runs_as_of_is_refused_and_writes_nothing(repo, capsys):
    write_snapshot(repo, wind_t2(), S1)
    code, out = invoke(capsys, "diagnose-private")
    stored = (repo / out["output"]).read_bytes()
    before = private_tree(repo)
    append_activation(repo / DICT_REL, "2026-10-09T12:00:00Z")                          # T2 is 10-10: this would rewrite R2's meaning
    for args in ((), ("--anchor", f"wind_{S1}")):
        code, err = invoke(capsys, "diagnose-private", *args)
        assert code == 1 and err["error"] == "ROUTE_HISTORY_RETROACTIVE" and "may only be appended" in err["message"]
    assert private_tree(repo) == before and (repo / out["output"]).read_bytes() == stored


def test_a_record_after_a_stored_run_is_fine_for_the_retroactivity_guard(repo, capsys):
    write_snapshot(repo, wind_t2(), S1)
    code, out = invoke(capsys, "diagnose-private")
    append_activation(repo / DICT_REL, "2026-10-10T08:00:00Z")                          # one minute after T2's as_of
    code, again = invoke(capsys, "diagnose-private")
    assert code == 0 and again["status"] == "reproduced"


@pytest.mark.parametrize("legacy", [False, True], ids=["run with routes", "legacy run (genesis rule)"])
def test_a_changed_equivalence_of_the_route_a_run_used_is_retroactive(repo, capsys, legacy):
    """EXACT -> FUNCTIONALLY_EQUIVALENT is a change between two activatable states, so the loader accepts it. A stored run
    recorded the route it was built from, equivalence included: the guard must compare that, not provider and time alone."""
    write_snapshot(repo, wind_t2(), S1)
    code, out = invoke(capsys, "diagnose-private")
    assert doc_of(repo, out)["routes"][ROUTED]["equivalence"] == "EXACT"
    if legacy:
        _strip_to_legacy(repo / out["output"])
    stored, before = (repo / out["output"]).read_bytes(), private_tree(repo)
    edited(repo / DICT_REL, lambda e: e["sources"][0].update(equivalence="FUNCTIONALLY_EQUIVALENT"))
    for args in ((), ("--anchor", f"wind_{S1}")):
        code, err = invoke(capsys, "diagnose-private", *args)
        assert code == 1 and err["error"] == "ROUTE_HISTORY_RETROACTIVE", err
        assert ROUTED in err["message"] and "differs: equivalence" in err["message"] and "may only be appended" in err["message"]
    assert private_tree(repo) == before and (repo / out["output"]).read_bytes() == stored          # nothing was written


def test_a_changed_equivalence_of_an_activated_route_is_retroactive_for_the_run_built_on_it(repo, capsys):
    append_activation(repo / DICT_REL, E)
    write_publication(repo, alt("2026-10-17T07:59:00+00:00", "2026-10-16", n=10), A4, "observations")
    write_snapshot(repo, wind_t2(), S1)
    code, out = invoke(capsys, "diagnose-private")
    assert code == 0 and out["anchor"] == f"{ALT}_{A4}" and doc_of(repo, out)["routes"][ROUTED]["equivalence"] == "EXACT"
    stored, before = (repo / out["output"]).read_bytes(), private_tree(repo)
    edited(repo / DICT_REL, lambda e: e["sources"][1].update(equivalence="FUNCTIONALLY_EQUIVALENT"))   # the provider's own route, after activation
    code, err = invoke(capsys, "diagnose-private")
    assert code == 1 and err["error"] == "ROUTE_HISTORY_RETROACTIVE" and "differs: equivalence" in err["message"], err
    assert private_tree(repo) == before and (repo / out["output"]).read_bytes() == stored


def test_a_changed_series_key_of_the_route_a_run_used_is_retroactive_too(repo, capsys):
    write_snapshot(repo, wind_t2(), S1)
    invoke(capsys, "diagnose-private")
    before = private_tree(repo)
    edited(repo / DICT_REL, lambda e: (e["sources"][0].update(series_key="M0000000"), e["wind"].update(code="M0000000")))
    code, err = invoke(capsys, "diagnose-private")
    assert code == 1 and err["error"] == "ROUTE_HISTORY_RETROACTIVE" and "differs: series_key" in err["message"] and private_tree(repo) == before


def test_inside_git_an_identity_rewrite_is_caught_by_the_audit_before_the_retroactivity_guard(repo, capsys):
    """Both layers protect the same fact; the audit is first because it also sees a rewrite that no stored run recorded."""
    init_repo(repo)
    commit_dictionary(repo, "v1")
    write_snapshot(repo, wind_t2(), S1)
    invoke(capsys, "diagnose-private")
    edited(repo / DICT_REL, lambda e: e["sources"][0].update(equivalence="FUNCTIONALLY_EQUIVALENT"))
    code, err = invoke(capsys, "diagnose-private")
    assert code == 1 and err["error"] == "ROUTE_HISTORY_REWRITTEN" and "equivalence" in err["message"]


# ---------------------------------------------------------------- the cross-version audit stops a diagnosis too
def test_a_diagnosis_refuses_to_run_on_a_rewritten_route_history(repo, capsys):
    """No stored run exists, so the retroactivity guard has nothing to contradict: only the cross-version audit sees it."""
    init_repo(repo)
    append_activation(repo / DICT_REL, E)
    commit_dictionary(repo, "v1: altprov active from E")
    edited(repo / DICT_REL, lambda e: e["route_history"][1].update(decision="a different story"))
    commit_dictionary(repo, "v2: rewrite")
    write_snapshot(repo, wind_t2(), S1)
    before = private_tree(repo)
    code, err = invoke(capsys, "diagnose-private")
    assert code == 1 and err["error"] == "ROUTE_HISTORY_REWRITTEN" and "not append-only" in err["message"]
    assert private_tree(repo) == before


def test_an_honest_append_only_history_diagnoses_normally_inside_git(repo, capsys):
    init_repo(repo)
    commit_dictionary(repo, "v1: genesis")
    append_activation(repo / DICT_REL, E)
    commit_dictionary(repo, "v2: append")
    write_snapshot(repo, wind_t2(), S1)
    code, out = invoke(capsys, "diagnose-private")
    assert code == 0 and out["status"] == "diagnosed"
