"""Cross-version append-only integrity of route history.

One YAML file can show only that its own history is well formed. These tests show the audit that catches a history that
was REWRITTEN between Git versions, including a rewrite that contradicts no stored ResearchRun (so the retroactivity
guard, which protects only what a stored run recorded, would not notice). It extends the repository's existing git-history
audit trail (eval check E4), and `diagnose-private` refuses to run on a rewritten history.
"""
import re
import shutil

import pytest
from provider_support import (ALT, DICT_REL, ROUTED, append_activation, commit_dictionary, edited, entry, git, init_repo,
                              read, route_cn_dr007, write)
from signal_support import ROOT

from cnmacro import checks

E = "2026-10-12T00:00:00Z"
GENESIS_REC = {"effective_at": "genesis", "active": "wind", "decision": "genesis: the incumbent route"}
ACTIVATION = {"effective_at": E, "active": ALT, "decision": "reviewed change 1"}


@pytest.fixture
def repo(tmp_path):
    """A git repository whose only tracked file is the dictionary, with cn_dr007 on Wind (commit 1) and then on
    `altprov` from E (commit 2): an honest append."""
    init_repo(tmp_path)
    (tmp_path / "data/dictionary").mkdir(parents=True)
    dest = tmp_path / DICT_REL
    shutil.copy(ROOT / DICT_REL, dest)
    route_cn_dr007(dest)
    commit_dictionary(tmp_path, "v1: cn_dr007 on wind")
    append_activation(dest, E, decision="reviewed change 1")
    commit_dictionary(tmp_path, "v2: activate altprov from E")
    return tmp_path


def audit(repo):
    return checks.route_history_audit(repo / DICT_REL)


def rewrite(repo, fn, commit=True):
    edited(repo / DICT_REL, fn)
    if commit:
        commit_dictionary(repo, "rewrite")


def test_an_honest_append_only_history_passes(repo):
    assert audit(repo) == ([], [])


def test_appending_another_record_passes(repo):
    edited(repo / DICT_REL, lambda e: e["route_history"].append({"effective_at": "2026-11-01T00:00:00Z", "active": "wind",
                                                                 "decision": "reviewed change 2: back to wind"}))
    assert audit(repo)[0] == []                                            # uncommitted append: still an extension
    commit_dictionary(repo, "v3")
    assert audit(repo) == ([], [])


@pytest.mark.parametrize("name, fn, why", [
    ("edit an earlier decision", lambda e: e["route_history"][1].update(decision="a different story"), "decision reference was edited"),
    ("move an activation time", lambda e: e["route_history"][1].update(effective_at="2026-10-20T00:00:00Z"), "record 1 changed"),
    ("backdate an activation", lambda e: e["route_history"][1].update(effective_at="2026-10-01T00:00:00Z"), "record 1 changed"),
    ("change which route was active", lambda e: e["route_history"][1].update(active="wind"), "record 1 changed"),
    ("remove the activation", lambda e: e["route_history"].pop(), "removed"),
    ("remove the genesis record", lambda e: e["route_history"].pop(0), "changed|removed"),
    ("reorder the records", lambda e: e["route_history"].reverse(), "record 0 changed"),
    ("edit the genesis decision", lambda e: e["route_history"][0].update(decision="rewritten"), "decision reference was edited"),
    ("delete the whole history", lambda e: (e.pop("route_history"), e.pop("sources")), "removed"),
])
def test_a_rewritten_history_is_detected_even_when_no_stored_run_exists(repo, name, fn, why):
    """No ResearchRun exists in this repository at all, so the retroactivity guard has nothing to contradict."""
    assert not list(repo.rglob("signals/*.json"))
    rewrite(repo, fn)
    violations, _ = audit(repo)
    assert violations and ROUTED in violations[0] and "not append-only" in violations[0], name
    assert re.search(why, violations[0]), (name, violations)


def test_an_uncommitted_rewrite_is_detected_too(repo):
    rewrite(repo, lambda e: e["route_history"][1].update(decision="edited in the working copy"), commit=False)
    assert audit(repo)[0] and "working copy" in audit(repo)[0][0]


def test_a_rewrite_that_was_later_reverted_is_still_on_record(repo):
    """The audit walks every committed version, so putting the file back does not erase that it was changed."""
    original = (repo / DICT_REL).read_text(encoding="utf-8")
    rewrite(repo, lambda e: e["route_history"][1].update(decision="a different story"))
    (repo / DICT_REL).write_text(original, encoding="utf-8")
    commit_dictionary(repo, "revert")
    assert audit(repo)[0]


def test_unrelated_dictionary_edits_are_not_route_history_rewrites(repo):
    edited(repo / DICT_REL, lambda e: e.update(role="reworded role text"))
    edited(repo / DICT_REL, lambda e: e["sources"][1].update(validation_basis="a fuller comparison, recorded later"))
    commit_dictionary(repo, "docs")
    assert audit(repo) == ([], [])


# ---------------------------------------------------------------- what a record MEANS: the identity of the route it names
# A history record names only a provider. Editing that provider's route later (its series, its equivalence, its aggregation)
# would change what the old record means while the record itself stayed put, so the identity is frozen from the version
# that first named it. Documentation, evidence texts and present-tense policy stay editable.
@pytest.mark.parametrize("name, fn, field", [
    ("the activated route's series_key", lambda e: e["sources"][1].update(series_key="ALTPROV:a-different-series"), "series_key"),
    ("the activated route's equivalence (both are activatable)", lambda e: e["sources"][1].update(equivalence="FUNCTIONALLY_EQUIVALENT"), "equivalence"),
    ("the activated route's aggregation", lambda e: e["sources"][1].update(aggregate="month_end"), "aggregate"),
    ("the incumbent route's series_key", lambda e: e["sources"][0].update(series_key="M0000000"), "series_key"),
    ("the incumbent route's equivalence", lambda e: e["sources"][0].update(equivalence="FUNCTIONALLY_EQUIVALENT"), "equivalence"),
])
def test_rewriting_the_identity_of_a_route_a_record_names_is_detected(repo, name, fn, field):
    assert not list(repo.rglob("signals/*.json"))                        # no stored run: the retroactivity guard sees nothing
    rewrite(repo, fn)
    violations, _ = audit(repo)
    assert len(violations) == 1 and ROUTED in violations[0] and "its identity changed" in violations[0], (name, violations)
    assert field in violations[0] and "a new route with its own activation record" in violations[0]


def test_an_uncommitted_identity_rewrite_is_detected_too(repo):
    rewrite(repo, lambda e: e["sources"][1].update(series_key="ALTPROV:a-different-series"), commit=False)
    violations, _ = audit(repo)
    assert len(violations) == 1 and "working copy" in violations[0]


def test_removing_the_declaration_of_a_named_route_is_an_identity_change(repo):
    rewrite(repo, lambda e: e["sources"].pop(0))                         # the history still names wind; its route is gone
    violations, _ = audit(repo)
    assert any("route wind" in v and "no longer declared" in v for v in violations)


def test_an_identity_change_is_reported_once_and_later_versions_compare_with_it(repo):
    rewrite(repo, lambda e: e["sources"][1].update(series_key="ALTPROV:a-different-series"))
    edited(repo / DICT_REL, lambda e: e.update(role="reworded role text"))
    commit_dictionary(repo, "unrelated edit after the rewrite")
    assert len(audit(repo)[0]) == 1


def test_documentation_and_present_tense_policy_stay_editable_after_activation(repo):
    """Only identity is frozen: evidence texts, expected metadata, collection, and what we may do TODAY with a route."""
    def enrich(e):
        e["role"] = "reworded role text"
        for r in e["sources"]:
            r["equivalence_basis"] = r["equivalence_basis"] + " (reviewed again, with a longer overlap)"
            r["validation_basis"] = "a fuller comparison, recorded later"
            r["access"]["basis"] = "terms page re-read on a later date"
            r["params"] = {"endpoint": "v2"}
        e["sources"][1]["expected"] = {"name": "n", "freq": "D", "unit": "a provider label"}
        e["sources"][1]["known_gaps"] = []
        e["sources"][1]["collect"] = False
        e["sources"][0]["access"]["automated_retrieval"] = "prohibited"      # the terms changed; wind is no longer the active route
    rewrite(repo, enrich)
    assert audit(repo) == ([], [])


def test_a_route_no_record_names_may_still_change_identity_until_it_is_activated(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "data/dictionary").mkdir(parents=True)
    dest = tmp_path / DICT_REL
    shutil.copy(ROOT / DICT_REL, dest)
    route_cn_dr007(dest)                                                 # `altprov` is declared and collected: a candidate
    commit_dictionary(tmp_path, "v1: candidate")
    edited(dest, lambda e: e["sources"][1].update(series_key="ALTPROV:found-the-right-series", equivalence="FUNCTIONALLY_EQUIVALENT"))
    commit_dictionary(tmp_path, "v2: the candidate is corrected before any activation")
    assert audit(tmp_path) == ([], [])
    append_activation(dest, E, decision="reviewed change 1")
    commit_dictionary(tmp_path, "v3: activation freezes what the record means")
    assert audit(tmp_path) == ([], [])
    edited(dest, lambda e: e["sources"][1].update(series_key="ALTPROV:and-changed-again"))
    commit_dictionary(tmp_path, "v4: too late")
    violations, _ = audit(tmp_path)
    assert len(violations) == 1 and "named by the route history in" in violations[0] and "series_key" in violations[0]


def test_the_incumbent_wind_routes_identity_is_frozen_in_the_compatibility_shim_too(repo):
    """A metric with only a `wind:` block has an implicit genesis record naming wind: its code and aggregation are its identity."""
    mid = "cn_cgb10y"                                                     # monthly, month_end
    edited(repo / DICT_REL, lambda e: e["wind"].update(code="M0000000"), mid)
    violations, _ = audit(repo)
    assert any(mid in v and "series_key" in v and "M0325687" in v for v in violations)
    commit_dictionary(repo, "rewrite the code")
    edited(repo / DICT_REL, lambda e: e["wind"].update(code="M0325687", aggregate=None), mid)
    assert any(mid in v and "aggregate" in v for v in audit(repo)[0])


def test_an_implicit_genesis_may_become_an_explicit_one_but_not_a_different_one(repo):
    raw = read(repo / DICT_REL)
    other = entry(raw, "cn_loans_hh_short_flow")
    other["route_history"] = [{"effective_at": "genesis", "active": "wind", "decision": "now written down"}]
    write(repo / DICT_REL, raw)
    assert audit(repo)[0] == []                                          # making the implicit record explicit adds a decision text only
    commit_dictionary(repo, "explicit genesis")
    raw = read(repo / DICT_REL)
    entry(raw, "cn_loans_hh_short_flow")["route_history"][0]["decision"] = "rewritten"
    write(repo / DICT_REL, raw)
    assert audit(repo)[0]                                                # but once written, it cannot be edited


def test_without_git_history_the_audit_says_so_instead_of_passing_silently(tmp_path):
    p = tmp_path / "metrics.yaml"
    shutil.copy(ROOT / DICT_REL, p)
    violations, notes = checks.route_history_audit(p)
    assert violations == [] and notes and "no git history" in notes[0]


def test_the_real_repository_history_is_append_only():
    violations, _ = checks.route_history_audit(ROOT / DICT_REL)
    assert violations == []


# ---------------------------------------------------------------- where the audit is enforced
def test_the_eval_gate_fails_e4_on_a_rewritten_history(repo):
    rewrite(repo, lambda e: e["route_history"][1].update(decision="a different story"))
    c = checks.Check("E4", "Preregistration immutability")
    checks.route_history_integrity(c, repo / DICT_REL)
    assert c.status == "fail" and "not append-only" in c.details[0]
    ok = checks.Check("E4", "Preregistration immutability")
    checks.route_history_integrity(ok, ROOT / DICT_REL)
    assert ok.status != "fail"


def test_a_shallow_clone_audits_only_what_it_can_see_and_says_so(repo, tmp_path):
    clone = tmp_path / "shallow"
    git(tmp_path, "clone", "-q", "--depth", "1", repo.as_uri(), str(clone))
    violations, notes = checks.route_history_audit(clone / DICT_REL)
    assert violations == [] and any("shallow clone" in n for n in notes)
