"""The desk reports public facts, keeps revisions, and never invents releases."""
import json

from daily import build_calendar, build_desk, desk_context
from cnmacro.claims import validate_claim
from cnmacro.store import as_of
from views import View


def test_kpis_equal_the_point_in_time_observation_store(model):
    desk = build_desk(model)
    held = as_of(model["observations"], model["evidence_as_of"])
    for kpi in desk["kpis"]:
        if kpi["metric_id"].startswith("drv:") or kpi["value"] is None:
            continue
        rows = held[held.metric_id == kpi["metric_id"]]
        row = rows[rows.reference_period == kpi["period"]].iloc[-1]
        assert kpi["value"] == row.value
        assert kpi["retrieved_at"] == row.retrieved_at
        assert kpi["release_date"] == (row.release_date or None)


def test_calendar_uses_beijing_day_and_requires_every_metric(model):
    item = {"name": "CPI", "period": "2099-10", "release": "2099-11-09T09:30:00+08:00",
            "metrics": ["cn_cpi_yoy", "cn_core_cpi_yoy"], "url": "https://www.stats.gov.cn/"}
    fixture = {**model, "release_calendar": [item]}
    assert build_calendar(fixture, "2099-11-09T01:00:00Z")[0]["status"] == "today"
    assert build_calendar(fixture, "2099-11-09T01:31:00Z")[0]["status"] == "pending"
    assert build_calendar(fixture, "2099-11-08T12:00:00Z")[0]["status"] == "scheduled"
    item["period"] = "2026-09"
    assert build_calendar(fixture, "2099-11-09T01:31:00Z")[0]["status"] == "released"


def test_brief_is_bound_to_observations_in_both_languages(model):
    desk = build_desk(model)
    assert 3 <= len(desk["claims"]) <= 5
    for claim in desk["claims"]:
        assert not validate_claim(claim)
        assert claim.values["value"].ref.startswith("obs:")
        assert claim.values["value"].recorded is not None
        assert "{value}" in claim.text_en and "{value}" in claim.text_zh
    for loc in ("en", "zh"):
        ctx = desk_context(desk, View(model, loc))
        assert all("{value}" not in sentence for sentence in ctx["brief"])


def test_revisions_with_unknown_publication_time_are_not_given_calendar_dates(model):
    desk = build_desk(model)
    unknown = [r for r in desk["releases"] if not r["published_at"]]
    assert unknown
    assert all(r["retrieved_at"] for r in unknown)
    assert any(r["is_revision"] for r in unknown)
    assert all(r["tier"] == "FACT" for r in desk["releases"])


def test_briefing_json_is_public_and_source_linked(built):
    data = json.loads((built / "data/briefing.json").read_text(encoding="utf-8"))
    assert data["releases"]
    for release in data["releases"]:
        assert release["canonical_url"].startswith("https://")
        assert release["retrieved_at"]
        assert all(value["ref"].startswith("obs:") for value in release["values"])
    assert "private_only" not in json.dumps(data)
