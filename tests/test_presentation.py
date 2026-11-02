"""The current explanatory layer: explicit key-evidence selection, qualitative states, Chinese for frozen text."""
import copy
import re

import pytest
import yaml

import views
from cnmacro.thesis import load_yaml
from conftest import CASE, ROOT

PRES = yaml.safe_load((CASE / "presentation.yaml").read_text(encoding="utf-8"))


def test_the_view_was_written_for_the_judgment_now_in_force(model):
    """When an analyst update is appended, this layer must be re-confirmed (it is out of date until then)."""
    assert PRES["applies_to"] == model["judgment_file"]
    assert model["view_current"] is True


def test_key_evidence_is_chosen_explicitly_not_by_file_order(model):
    ids = lambda key, m=model: [x["claim"]["id"] for x in views.View(m, "en").curated(key)]
    chosen_for = [x["claim"] for x in PRES["top_evidence_for"]]
    chosen_against = [x["claim"] for x in PRES["top_evidence_against"]]
    assert ids("top_evidence_for") == chosen_for and ids("top_evidence_against") == chosen_against
    # reverse and shuffle the claims: the homepage selection must not move
    for order in (list(reversed(model["claims"])), sorted(model["claims"], key=lambda k: hash(k) % 97)):
        shuffled = {**model, "claims": {k: model["claims"][k] for k in order}}
        assert ids("top_evidence_for", shuffled) == chosen_for
        assert ids("top_evidence_against", shuffled) == chosen_against


def test_no_template_selects_evidence_by_position():
    for name in ("index.html",):
        src = (ROOT / "site/templates" / name).read_text(encoding="utf-8")
        assert "claims.values" not in src and not re.search(r"claims[^%}]*\[\s*:\s*\d", src)
        assert "Strongest evidence" not in src


def test_key_evidence_lists_are_valid(model):
    both = PRES["top_evidence_for"] + PRES["top_evidence_against"]
    ids = [x["claim"] for x in both]
    assert len(ids) == len(set(ids)), "a claim cannot be both for and against"
    assert 1 <= len(PRES["top_evidence_for"]) <= 5 and 1 <= len(PRES["top_evidence_against"]) <= 5
    for x in both:
        assert x["claim"] in model["claims"], x
        assert x["lens"] in views.LENSES, x
    assert {x["lens"] for x in both} >= {"level", "marginal", "breadth", "mechanism"}   # all four lenses are used


def test_every_hypothesis_has_a_qualitative_state_in_both_languages():
    states = PRES["hypothesis_states"]
    assert set(states) == {"H0", "H1", "H2", "H3", "H4"}
    for h, s in states.items():
        assert s["state"] in views.STATE_TONE, h
        assert s["note"]["en"].strip() and s["note"]["zh"].strip()


def test_states_do_not_come_from_test_counts(model):
    """Changing the support / challenge tallies must not change the state shown."""
    v = views.View(model, "en")
    before = {h["id"]: v.view_state(h["id"]) for h in model["hypotheses"]}
    tampered = copy.deepcopy(model["hypotheses"])
    for h in tampered:
        h["supports"], h["challenges"] = h["challenges"] + 3, h["supports"] + 3
    after = {h["id"]: views.View({**model, "hypotheses": tampered}, "en").view_state(h["id"]) for h in tampered}
    assert before == after


def test_homepage_shows_no_weighted_score_or_raw_counts(built):
    from htmlutil import parse
    for loc in ("en", "zh"):
        text = parse(built / loc / "index.html").text(include_details=True)
        assert not re.search(r"[▲▼○]\s*\d", text), f"{loc}: a raw support/challenge count on the homepage"
        assert "class=\"tally\"" not in (built / loc / "index.html").read_text(encoding="utf-8")
    ev = parse(built / "en/evidence.html").text()
    assert "Test counts are diagnostics, not a weighted score" in ev
    assert "检验计数只是诊断信息，并非加权得分" in parse(built / "zh/evidence.html").text()


def test_question_and_statement_in_english_are_the_frozen_text(model):
    assert PRES["question"]["en"] == model["case"]["question"]
    assert PRES["question"]["zh"] == model["case"]["question_zh"]
    en = views.View(model, "en").case()
    assert en["statement"] == model["case"]["statement"]
    assert en["sustainable"] == model["case"]["horizon"]["definition_of_sustainable"]


def test_scenario_matrix_covers_the_requested_rows_in_both_languages():
    sc = PRES["scenarios"]
    assert len(sc) >= 2
    for s in sc:
        assert set(s["rows"]) == set(views.SCENARIO_ROWS)
        for row in s["rows"].values():
            assert row["en"].strip() and row["zh"].strip()
        assert s["name"]["en"] and s["name"]["zh"]


def test_research_prose_has_no_typed_numbers():
    from cnmacro.checks import Check, lint_presentation
    c = Check("E1", "x")
    for f in ("presentation.yaml", "policy_events.yaml"):
        lint_presentation(CASE / f, c)
    assert c.details == [] and c.status == "pass"
    bad = {"x": {"en": "PPI rose 3.8% in August", "zh": "PPI同比上涨3.8%"}}
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "p.yaml"; p.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
        c2 = Check("E1", "x"); lint_presentation(p, c2)
        assert len(c2.details) == 2


# ---------------------------------------------------------------- Chinese for the immutable English artifacts
def test_every_frozen_english_text_has_a_chinese_rendering(model):
    """Building the Chinese pages must never fall back to English for research text of this repository."""
    v = views.View(model, "zh")
    from conftest import PAGES
    import argparse, build
    # exercise every localized accessor the pages use
    v.case(); [v.hypothesis_text(h["id"], h) for h in model["hypotheses"]]
    [v.assessment(h["id"], h["assessment"]) for h in model["hypotheses"] if h["assessment"]]
    [v.test_row(t) for t in model["tests"]]
    [v.metric_name(m) for m in model["metrics"]]; [v.metric_role(m) for m in model["metrics"]]
    v.policy(); v.rules(); v.scenarios(); v.limitations(); v.sources_status()
    for r in model["next_releases"]:
        v.release_label(r)
    for it in model["audit_items"]:
        d = it["doc"]
        if it["kind"] == "baseline":
            v.frozen(d["rationale"], "documents", d["_file"], "rationale"); v.release_name(d["committed_before"]["release"])
        if it["kind"] == "amendment":
            for k in ("title", "reason", "effect"):
                v.frozen(d[k], "documents", d["_file"], k)
            v.release_name(d["effective_before"]["release"])
    assert v.missing == [], f"English text that has no Chinese rendering: {sorted(set(v.missing))}"


def test_frozen_zh_keys_match_the_frozen_english_exactly(model):
    """The Chinese renderings are keyed by the frozen English (windows, checks) and ids: a changed or removed
    English source cannot leave a stale translation behind."""
    fz = yaml.safe_load((CASE / "frozen_zh.yaml").read_text(encoding="utf-8"))
    tests = {t["id"]: t for t in model["tests"]}
    assert set(fz["tests"]) == set(tests)
    assert set(fz["windows"]) == {t["window"] for t in tests.values()}
    assert set(fz["checks"]) == {t["check"] for t in tests.values()}
    assert set(fz["hypotheses"]) == {h["id"] for h in model["hypotheses"]}
    docs = {it["doc"]["_file"] for it in model["audit_items"] if it["kind"] in ("baseline", "amendment")}
    assert set(fz["documents"]) == docs
    assert set(fz["documents"]["2026-10-04-baseline.yaml"]["hypothesis_assessment"]) == set(model["baseline"]["hypothesis_assessment"])


def test_the_preregistered_files_were_not_touched():
    """V1.1 adds layers beside the frozen artifacts; it must not edit them (eval E4 checks history too)."""
    import subprocess
    out = subprocess.run(["git", "diff", "--name-only", "origin/main", "--", "research/cases/cn-nominal/preregistered",
                          "research/cases/cn-nominal/updates", "research/cases/cn-nominal/refreshes",
                          "research/cases/cn-nominal/eval"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("origin/main is not available")
    assert out.stdout.split() == [] or out.stdout.split() == ["research/cases/cn-nominal/eval/latest.json"], out.stdout
