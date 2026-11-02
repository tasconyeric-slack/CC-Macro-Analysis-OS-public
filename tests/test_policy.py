"""Policy Context: official events as context for H3, kept apart from the frozen baseline and the evidence tests."""
import copy
import re
from pathlib import Path

import pytest
import yaml

import views
from conftest import CASE, ROOT

DOC = yaml.safe_load((CASE / "policy_events.yaml").read_text(encoding="utf-8"))
EVENTS = {e["event_id"]: e for e in DOC["events"]}


def test_the_seeded_events_are_valid():
    assert views.validate_policy_events(DOC) == []
    assert set(EVENTS) == {"POL-2026-09-28-SC", "POL-2026-09-30-NDRC"}
    sc, ndrc = EVENTS["POL-2026-09-28-SC"], EVENTS["POL-2026-09-30-NDRC"]
    assert str(sc["published"]) == "2026-09-28" and str(ndrc["published"]) == "2026-09-30"
    assert sc["source"]["url"].startswith("https://www.gov.cn/") and sc["source"]["kind"] == "primary"
    assert sc["stage"] == "announced" and ndrc["stage"] == "funded"
    assert sc["hypothesis"] == ndrc["hypothesis"] == "H3"


def test_every_event_has_all_required_fields_in_both_languages():
    for e in DOC["events"]:
        for k in ("event_id", "published", "institution", "title", "source", "category", "measure", "stage",
                  "channel", "hypothesis", "interpretation", "next_confirmation"):
            assert e.get(k), (e["event_id"], k)
        for k in ("institution", "title", "measure", "channel", "interpretation", "next_confirmation"):
            assert e[k]["en"].strip() and e[k]["zh"].strip(), (e["event_id"], k)


def test_both_events_use_the_issuers_own_page():
    for e in DOC["events"]:
        assert e["source"]["kind"] == "primary" and "primary_listing" not in e["source"], e["event_id"]
    ndrc = EVENTS["POL-2026-09-30-NDRC"]
    assert ndrc["source"]["url"] == "https://www.ndrc.gov.cn/fggz/202609/t20260930_1407948.html"
    assert ndrc["source"]["publisher"] == {"en": "National Development and Reform Commission", "zh": "国家发展和改革委员会"}
    assert ndrc["official_headline_zh"] == "2026年2500亿元超长期特别国债支持消费品以旧换新资金已全部下达"
    assert ndrc["stage"] == "funded"
    assert "not disbursement and not demand" in ndrc["interpretation"]["en"]
    assert "不等于补贴兑付，更不等于需求形成" in ndrc["interpretation"]["zh"]
    assert "xinhua" not in yaml.safe_dump(DOC, allow_unicode=True).lower() and "新华" not in (CASE / "policy_events.yaml").read_text(encoding="utf-8")


def test_a_secondhand_source_is_only_valid_if_it_names_the_issuers_own_page():
    """The validator still supports media-carried announcements, but they must say so and link the issuer's page."""
    doc = copy.deepcopy(DOC)
    src = doc["events"][0]["source"]
    src.update(kind="official_media")
    assert any("primary_listing" in e for e in views.validate_policy_events(doc))
    src["primary_listing"] = "https://www.ndrc.gov.cn/xwdt/"
    assert views.validate_policy_events(doc) == []


def test_figures_are_stored_once_and_agree_with_the_chinese_source_wording():
    f = {x["id"]: x for x in EVENTS["POL-2026-09-30-NDRC"]["figures"]}
    assert views.fmt_cny(f["full_year"]["value_cny"], "en") == "RMB 250bn"
    assert views.fmt_cny(f["full_year"]["value_cny"], "zh") == "2500亿元" == f["full_year"]["quote_zh"]
    assert views.fmt_cny(f["fourth_batch"]["value_cny"], "en") == "RMB 62.5bn"
    assert views.fmt_cny(f["fourth_batch"]["value_cny"], "zh") == "625亿元" == f["fourth_batch"]["quote_zh"]


@pytest.mark.parametrize("mutate,needle", [
    (lambda e: e.update(stage="launched"), "stage"),
    (lambda e: e["source"].update(url="https://example.com/news"), "official https host"),
    (lambda e: e["source"].update(url="http://www.gov.cn/x"), "official https host"),
    (lambda e: e["source"].update(kind="blog"), "source.kind"),
    (lambda e: e.update(hypothesis="H9"), "hypothesis"),
    (lambda e: e["figures"][0].update(value_cny=25_000_000_000), "value"),          # 250亿 vs 2500亿: a unit slip
    (lambda e: e["title"].update(zh=""), "title missing in zh"),
    (lambda e: e.update(event_id=""), "event_id"),
])
def test_validator_rejects_bad_events(mutate, needle):
    doc = copy.deepcopy(DOC)
    mutate(next(e for e in doc["events"] if e["event_id"].endswith("NDRC") or not e["event_id"]))
    errs = views.validate_policy_events(doc)
    assert any(needle in e for e in errs), errs


def test_events_before_the_baseline_are_labelled_as_public_but_not_used(model):
    """Both seeded events predate the baseline date but are not part of the frozen judgment. The page says exactly that,
    in both languages, and never claims they were incorporated."""
    assert model["baseline"].get("policy_events") in (None, [])
    for loc in ("en", "zh"):
        events = views.View(model, loc).policy()["events"]
        assert {e["scope"] for e in events} == {"before_baseline"}
        label = events[0]["scope_label"]
        assert ("not used in the frozen baseline" in label) if loc == "en" else ("未用于冻结的基线判断" in label)


def test_scope_distinguishes_baseline_before_and_after(model):
    fake = copy.deepcopy(model)
    fake["policy"]["events"] = [dict(copy.deepcopy(DOC["events"][0]), event_id="X-IN", published="2026-09-01"),
                                dict(copy.deepcopy(DOC["events"][0]), event_id="X-BEFORE", published="2026-10-04"),
                                dict(copy.deepcopy(DOC["events"][0]), event_id="X-AFTER", published="2026-10-20")]
    fake["baseline"] = {**fake["baseline"], "policy_events": ["X-IN"]}
    got = {e["id"]: e["scope"] for e in views.View(fake, "en").policy()["events"]}
    assert got == {"X-IN": "in_baseline", "X-BEFORE": "before_baseline", "X-AFTER": "after_baseline"}


def test_policy_context_cannot_reach_the_engine():
    """The layer is presentation only. The one place under src/ that names the file is the typed-number lint in
    checks.py (it reads the prose, not the events as evidence); no test, rule, refresh or thesis code touches it."""
    readers = {f.name for f in (ROOT / "src").rglob("*.py") if "policy_events" in f.read_text(encoding="utf-8")}
    assert readers == {"checks.py"}, readers
    checks = (ROOT / "src/cnmacro/checks.py").read_text(encoding="utf-8")
    assert "lint_presentation" in checks and "evaluate_test" not in checks
    case = yaml.safe_load((CASE / "case.yaml").read_text(encoding="utf-8"))
    assert "policy_events" not in yaml.safe_dump(case)


def test_page_separates_realized_impulse_from_the_forward_stance(built):
    from htmlutil import parse
    en = parse(built / "en/evidence.html").text(include_details=True)
    for needle in ("Frozen baseline judgment", "Forward policy stance", "Realized quantitative impulse",
                   "Public before the baseline date, but not used in the frozen baseline judgment",
                   "Realized policy impulse remains weak in current quantitative data, while the forward policy stance has become more supportive",
                   "Announced", "Funded", "Next observable confirmation"):
        assert needle in en, needle
    zh = parse(built / "zh/evidence.html").text(include_details=True)
    for needle in ("冻结的基线判断", "前瞻性政策取向", "已实现的量化政策力度", "已公布", "资金已下达",
                   "下一个可观察的验证点", "国务院常务会议", "国家发展和改革委员会"):
        assert needle in zh, needle
    html = (built / "en/evidence.html").read_text(encoding="utf-8")
    assert 'href="https://www.gov.cn/yaowen/liebiao/202609/content_7082280.htm"' in html
    assert 'href="https://www.ndrc.gov.cn/fggz/202609/t20260930_1407948.html"' in html
    assert "Xinhua" not in html and "official media carrying" not in html


def test_the_frozen_h3_tests_are_unchanged_by_the_policy_layer(model):
    """Evidence outcomes at the baseline and now are the data's, regardless of policy events."""
    for t in model["tests"]:
        if t["hypothesis"] == "H3":
            assert t["result"]["outcome"] == t["at_baseline"]["outcome"]
