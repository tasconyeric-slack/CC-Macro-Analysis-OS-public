"""Issue #52, one end-to-end path on a genuine release: the 2026-11-09 CPI/PPI refresh record -> deterministic draft ->
explicit analyst decision -> immutable signed update -> public pages. The approval here is a FIXTURE signer in a
temporary copy of the case; the repository's own review stays `awaiting_analyst` and has no update."""
import json
import shutil
import subprocess
import sys

import pytest
import yaml

from conftest import CASE, ROOT
from htmlutil import parse

from cnmacro import review
from cnmacro.refresh import Paths
from cnmacro.thesis import fold

REFRESH = "2026-11-09T0223Z.json"          # genuine: the October 2026 CPI/PPI release, committed by the refresh bot
RID = "2026-11-09T0223Z"
FIXTURE_SIGNER = "Fixture Analyst (test only)"


@pytest.fixture()
def case(tmp_path):
    c = tmp_path / "case"
    shutil.copytree(CASE, c, ignore=shutil.ignore_patterns("__pycache__", "reviews", "updates"))
    return c


def paths(case_dir):
    return Paths(ROOT, case_dir, ROOT / "data/demo/observations", ROOT / "data/dictionary/metrics.yaml",
                 ROOT / "data/dictionary/release_calendar.yaml", None)


def drafted(case_dir):
    d = review.build_draft(paths(case_dir), REFRESH, created_at="2026-11-11T04:00:00Z")
    review.write_draft(case_dir, d)
    return d


def build(case_dir, out):
    done = subprocess.run([sys.executable, str(ROOT / "site/build.py"), "--case-dir", str(case_dir), "--out", str(out)],
                          cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return out


def test_release_to_draft_to_signed_update_to_public_page(case, tmp_path):
    d = drafted(case)
    # the draft is bound to the real record and states the judgment really in force (the preregistered baseline)
    rec = (case / "refreshes" / REFRESH).read_bytes()
    assert d["refresh_record"]["sha256"] == review._sha(rec) and d["status"] == "awaiting_analyst"
    assert d["previous_state"]["file"] == "2026-10-04-baseline.yaml" and d["previous_state"]["probability"] == 0.3
    ppi = next(f for f in d["new_facts"] if f["metric_id"] == "cn_ppi_yoy")
    raw = json.loads(rec)
    assert ppi["value"] == next(o["value"] for o in raw["new_observations"] if o["metric_id"] == "cn_ppi_yoy")
    assert ppi["previous_period"] == "2026-09" and ppi["previous_value"] is not None
    assert {f["test"] for f in d["flips_since_judgment"]} >= {"T-H2-03", "T-H2-04"}   # changes versus the previous reading
    assert d["supporting_evidence"] and d["contradicting_evidence"] and d["competing_explanation"]["hypothesis"] == "H0"
    assert d["proposal"]["thesis_change"] == "none_proposed" and "no change to the thesis" in d["text"]["en"]

    # nobody but a named person can sign; nothing is written by a refused decision
    for bad in ("github-actions[bot]", "claude-agent", ""):
        with pytest.raises(review.ReviewError):
            review.decide(case, RID, "approve", bad, at="2026-11-11T05:00:00Z")
    with pytest.raises(review.ReviewError, match="back-dating"):
        review.decide(case, RID, "approve", FIXTURE_SIGNER, at="2026-11-09T02:00:00Z")
    with pytest.raises(review.ReviewError, match="reason"):
        review.decide(case, RID, "reject", FIXTURE_SIGNER, at="2026-11-11T05:00:00Z")
    assert not (case / "reviews" / RID / "decision.json").exists() and not (case / "updates").exists()

    # before a decision the site shows the draft as a draft and the previous judgment as the judgment
    before = build(case, tmp_path / "before")
    up = parse(before / "en/updates.html").text()
    assert "Draft · awaiting analyst" in up and "still the last signed one" in up
    assert "Latest release drafted for review" in parse(before / "en/index.html").text()

    # explicit approval (fixture signer) -> decision + signed update, dated at the decision
    dec_path, upd_path = review.decide(case, RID, "approve", FIXTURE_SIGNER, at="2026-11-11T05:00:00Z", via="test")
    upd = yaml.safe_load(upd_path.read_text(encoding="utf-8"))
    assert upd_path.name == "2026-11-11-2026-10-cpi.yaml" and upd["as_of"] == "2026-11-11T05:00:00Z"
    assert upd["author"] == FIXTURE_SIGNER and upd["signature"]["review_id"] == RID
    assert upd["evidence_as_of"] == raw["as_of"] and upd["probability"] == 0.3 and upd["probability_change"] is None
    state, _, errs = fold(case)
    assert not errs and state["as_of"] == "2026-11-11T05:00:00Z"
    assert review.verify(case, RID) == []
    with pytest.raises(review.ReviewError, match="final"):
        review.decide(case, RID, "reject", FIXTURE_SIGNER, reason="changed my mind", at="2026-11-11T06:00:00Z")

    after = build(case, tmp_path / "after")
    up = parse(after / "en/updates.html").text()
    assert "Signed · approved as drafted" in up and FIXTURE_SIGNER in up
    assert "2026-11-11-2026-10-cpi.yaml" in up
    assert "reviewed and signed by" in parse(after / "en/index.html").text()
    assert "已签署" in parse(after / "zh/updates.html").text()

    # an edit to the draft after the decision is detected
    p = case / "reviews" / RID / "draft.json"
    p.write_text(p.read_text(encoding="utf-8").replace("none_proposed", "raise"), encoding="utf-8")
    assert any("not chained" in e for e in review.verify(case, RID))


def test_edit_with_a_probability_change_must_be_explained_and_reject_publishes_nothing(case):
    drafted(case)
    with pytest.raises(review.ReviewError, match="reasoning"):
        review.decide(case, RID, "edit", FIXTURE_SIGNER, reason="demand leg", at="2026-11-11T05:00:00Z",
                      edits={"text_en": "My own read.", "probability": 0.35})
    _, upd = review.decide(case, RID, "edit", FIXTURE_SIGNER, reason="demand leg", at="2026-11-11T05:00:00Z",
                           edits={"text_en": "My own read.", "text_zh": "我的判断。", "probability": 0.35,
                                  "reasoning": "New orders recovered.", "evidence": ["T-H2-04"]})
    doc = yaml.safe_load(upd.read_text(encoding="utf-8"))
    assert doc["probability_change"]["previous"] == 0.3 and doc["last_update_direction"] == "STRENGTHENED"
    assert not fold(case)[2]


def test_reject_records_the_decision_and_keeps_the_judgment(case):
    drafted(case)
    dec, upd = review.decide(case, RID, "reject", FIXTURE_SIGNER, reason="needs the activity data", at="2026-11-11T05:00:00Z")
    assert upd is None and not (case / "updates").exists()
    assert json.loads(dec.read_text(encoding="utf-8"))["published_update"] is None
    assert review.reviews(case)[-1]["status"] == "rejected"


def test_the_repository_has_no_signed_update_without_a_real_decision():
    """The missing updates/ entry is not created until the analyst actually decides (issue #52 acceptance)."""
    for r in review.reviews(CASE):
        if r["decision"] is None:
            assert r["status"] in ("awaiting_analyst", "superseded")
        else:
            assert not review.NOT_A_PERSON.search(r["decision"]["signed_by"])
            assert review.verify(CASE, r["review_id"]) == []
    if not any(r["decision"] for r in review.reviews(CASE)):
        assert not list((CASE / "updates").glob("*.yaml"))


def test_a_release_ingested_after_a_later_refresh_still_maps_to_its_calendar_entry():
    """The October PMI (released 2026-10-31) reached the store only in the 2026-11-02 refresh, whose window starts
    after the release: it is matched by metric and period, not by the release falling inside the window."""
    rec = json.loads((CASE / "refreshes/2026-11-02T0938Z.json").read_text(encoding="utf-8"))
    spec, entries = review.release_group(ROOT / "data/dictionary/release_calendar.yaml", rec)
    assert spec is not None and "PMI" in spec.name and [e["period"] for e in entries] == ["2026-10"]


def test_a_terminal_status_keeps_its_preregistered_rule_in_the_signed_update(case):
    (case / "updates").mkdir()
    (case / "updates" / "2026-11-10-terminal-confirmed.yaml").write_text(yaml.safe_dump({
        "kind": "update", "baseline": "2026-10-04-baseline.yaml", "as_of": "2026-11-10T00:00:00Z",
        "release": "2026-10 CPI (居民消费价格指数月度报告)", "author": "automation (preregistered terminal rule)",
        "previous_state": {"probability": 0.3, "conviction": "LOW", "status": "ACTIVE", "last_update_direction": "UNCHANGED"},
        "test_results": {}, "flipped_tests": [], "terminal_check": "CONFIRMED", "new_claims": [],
        "does_this_change_the_thesis": "Terminal rule fired (fixture).", "probability": 0.3, "conviction": "LOW",
        "status": "CONFIRMED", "last_update_direction": "UNCHANGED", "probability_change": None,
        "terminal_rule_fired": "R-FIXTURE"}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    drafted(case)
    _, upd = review.decide(case, RID, "approve", FIXTURE_SIGNER, at="2026-11-11T05:00:00Z")
    doc = yaml.safe_load(upd.read_text(encoding="utf-8"))
    assert doc["status"] == "CONFIRMED" and doc["terminal_rule_fired"] == "R-FIXTURE"
    assert not fold(case)[2]


def test_the_signed_update_names_every_release_entry_and_the_card_reads_in_both_languages(case):
    drafted(case)
    card = review.decision_card(case, RID)
    assert "CPI" in card.splitlines()[1] and "PPI" in card.splitlines()[1]          # CPI and PPI share one release
    assert "竞争性解释" in card and "供给端" in card                                   # H0 in the frozen Chinese wording
    row = review.summary(review.reviews(case)[-1], now="2026-11-13T04:00:00Z")
    assert row["status"] == "awaiting_analyst" and row["awaiting_hours"] == 48.0
    _, upd = review.decide(case, RID, "approve", FIXTURE_SIGNER, at="2026-11-11T05:00:00Z")
    doc = yaml.safe_load(upd.read_text(encoding="utf-8"))
    assert doc["release"].startswith("2026-10 CPI")                                    # the key the site already uses
    assert [e["period"] for e in doc["release_entries"]] == ["2026-10", "2026-10"]
    assert any("PPI" in e["name"] for e in doc["release_entries"]) and not fold(case)[2]
    assert review.summary(review.reviews(case)[-1])["awaiting_hours"] is None


def test_a_newer_draft_supersedes_the_older_one_which_can_no_longer_be_signed(case):
    older = review.build_draft(paths(case), "2026-11-02T0938Z.json", created_at="2026-11-11T03:00:00Z")
    review.write_draft(case, older)
    drafted(case)
    states = {r["review_id"]: r["status"] for r in review.reviews(case)}
    assert states == {"2026-11-02T0938Z": "superseded", RID: "awaiting_analyst"}
    with pytest.raises(review.ReviewError, match="superseded"):
        review.decide(case, "2026-11-02T0938Z", "approve", FIXTURE_SIGNER, at="2026-11-11T05:00:00Z")
    assert not (case / "reviews" / "2026-11-02T0938Z" / "decision.json").exists()
