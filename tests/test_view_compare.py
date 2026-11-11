"""Research view comparison: signed view vs. evidence since, and the EXTERNAL_VIEW boundary."""
import json
import shutil

import pytest
import yaml

from cnmacro.refresh import suggested_direction
from cnmacro.views import build_comparison, render_markdown, validate_external_view
from cnmacro.views.__main__ import main as views_main
from cnmacro.views.external import forecast_summary, load_external_views

from conftest import CASE, ROOT

ACCESS = ROOT / "data/external/access.yaml"


def refreshes():
    return sorted(CASE.glob("refreshes/*.json"))


def test_real_case_compares_the_signed_baseline_with_the_latest_refresh():
    c = build_comparison(CASE, access_file=ACCESS, external_dir=ROOT / "data/external/views")
    base = yaml.safe_load(next(CASE.glob("preregistered/*-baseline.yaml")).read_text(encoding="utf-8"))
    latest = json.loads(refreshes()[-1].read_text(encoding="utf-8"))
    # the signed view is read, never changed
    assert {k: c["signed_view"][k] for k in ("probability", "conviction", "status")} == \
        {k: base[k] for k in ("probability", "conviction", "status")}
    assert c["evidence_at_signing"]["source"].endswith("-baseline.yaml")
    assert c["evidence_now"]["source"] == refreshes()[-1].name
    # every reported flip is a real outcome difference between the two committed records
    flips = [f for h in c["hypotheses"] for f in h["flips"]]
    expected = {k for k, v in latest["test_results"].items() if base["test_results"][k]["outcome"] != v["outcome"]}
    assert {f["test"] for f in flips} == expected and expected
    for f in flips:
        assert f["to"] == latest["test_results"][f["test"]]["outcome"]
        assert f["refs_to"] == latest["test_results"][f["test"]]["refs"]
    # same direction rule as the refresh record
    assert c["summary"]["score"] == suggested_direction(flips)["score"]
    assert sum(h["score"] for h in c["hypotheses"]) == c["summary"]["score"]
    # tallies cover every test of each hypothesis, at signing and now
    for h in c["hypotheses"]:
        assert sum(h["at_signing"].values()) == sum(h["now"].values()) == h["tests"]
        assert h["signed_assessment"]["en"] and h["signed_assessment"]["zh"]
    assert len(c["timeline"]) == c["refreshes_since_signing"] == len(refreshes())
    # no institutional source is connected: nothing shown, and the reason is dated and sourced
    assert c["external"]["status"] == "not_connected"
    assert all(not h["external_views"] for h in c["hypotheses"])
    assert {"FinLens", "Tushare"} <= {a["source"].split()[0] for a in c["external"]["access_checks"]}
    json.dumps(c, allow_nan=False)
    for lang in ("en", "zh"):
        md = render_markdown(c, lang)
        assert "None" not in md and c["signed_view"]["file"] in md
        assert all(f["test"] in md for f in flips)


def test_an_earlier_cutoff_never_reads_a_later_refresh():
    first_flip = next(p for p in refreshes() if json.loads(p.read_text())["flipped_tests"])
    c = build_comparison(CASE, to_refresh=first_flip.name)
    assert c["evidence_now"]["source"] == first_flip.name
    later = {p.name for p in refreshes() if p.name > first_flip.name}
    assert not later & {t["refresh"] for t in c["timeline"]}
    with pytest.raises(ValueError):
        build_comparison(CASE, to_refresh="1999-01-01T0000Z.json")


def test_a_later_update_without_results_is_compared_from_the_refresh_it_was_signed_on(tmp_path):
    case = tmp_path / "case"
    shutil.copytree(CASE, case)
    recs = refreshes()
    signed_on = json.loads(recs[4].read_text(encoding="utf-8"))
    (case / "updates").mkdir()
    base = yaml.safe_load(next(CASE.glob("preregistered/*-baseline.yaml")).read_text(encoding="utf-8"))
    (case / "updates" / "2026-10-24-update.yaml").write_text(yaml.safe_dump({
        "kind": "update", "as_of": signed_on["as_of"], "release": "test", "baseline": next(CASE.glob("preregistered/*-baseline.yaml")).name,
        "probability": base["probability"], "conviction": "MEDIUM", "status": "ACTIVE", "last_update_direction": "UNCHANGED",
        "hypothesis_assessment": {"H1": "Price turn holds."}}), encoding="utf-8")
    c = build_comparison(case)
    assert c["signed_view"]["file"] == "2026-10-24-update.yaml" and c["signed_view"]["conviction"] == "MEDIUM"
    assert c["evidence_at_signing"]["source"] == recs[4].name          # at or before signing, never later
    assert c["refreshes_since_signing"] == len(recs) - 5
    assert [d["file"] for d in c["signed_history"]][-1] == "2026-10-24-update.yaml"
    # no zh rendering for the new update: the English text is shown rather than nothing
    assert next(h for h in c["hypotheses"] if h["id"] == "H1")["signed_assessment"]["zh"] == "Price turn holds."
    # an earlier cutoff uses the view in force then, never the later update or its results
    early = build_comparison(case, to_refresh=recs[2].name)
    assert early["signed_view"]["file"].endswith("-baseline.yaml")
    assert early["evidence_now"]["source"] == recs[2].name
    assert [d["file"] for d in early["signed_history"]][-1].endswith("-baseline.yaml")


def view(i, **kw):
    rec = {"view_id": f"v{i}", "institution": f"Inst {i}", "institution_type": "domestic_broker",
           "title": "Macro monthly", "published_at": "2026-11-01", "retrieved_at": "2026-11-02T00:00:00Z",
           "source_url": f"https://example.org/report/{i}", "via": "publisher", "hypothesis": "H1",
           "stance": "supports", "quote": "PPI is bottoming.", "redistribution": "public_link"}
    rec.update(kw)
    return rec


def write_views(d, recs):
    d.mkdir(parents=True, exist_ok=True)
    (d / "2026-11-02.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")


def test_external_views_fail_closed_and_respect_time_and_redistribution(tmp_path):
    assert validate_external_view(view(1)) == []
    assert any("source_url" in e for e in validate_external_view(view(1, source_url="http://x")))
    assert any("full text" in e for e in validate_external_view(view(1, quote="x" * 500)))
    assert any("forecast" in e for e in validate_external_view(view(1, forecast={"metric_id": "cn_cpi_yoy", "value": 1})))
    assert any("forecast" in e for e in validate_external_view(view(1, forecast=[])))
    assert validate_external_view(None) and validate_external_view([])
    recs = [view(1), view(2, source_url=""), view(3, redistribution="private"),
            view(4, published_at="2026-12-01", retrieved_at="2026-12-02T00:00:00Z"), view(1),
            None, [], view(5, forecast=[])]
    write_views(tmp_path / "v", recs)
    views, errors = load_external_views(tmp_path / "v", "2026-11-09T00:00:00Z")
    assert [v["view_id"] for v in views] == ["v1"]                       # private and future-dated left out
    assert any("v2" in e for e in errors) and any("duplicate" in e for e in errors)
    assert sum("JSON object" in e for e in errors) == 2 and any("v5" in e for e in errors)
    private, _ = load_external_views(tmp_path / "v", "2026-11-09T00:00:00Z", public=False)
    assert {v["view_id"] for v in private} == {"v1", "v3"}
    assert load_external_views(tmp_path / "missing") == ([], [])


def test_forecast_median_only_with_five_institutions():
    fc = lambda v: {"metric_id": "cn_cpi_yoy", "period": "2026-11", "value": v, "unit": "%"}
    four = forecast_summary([view(i, forecast=fc(0.5 + i / 10)) for i in range(4)])[0]
    assert four["n"] == 4 and four["median"] is None and not four["consensus"]
    # the same institution twice counts once, with its latest value
    five = forecast_summary([view(i, forecast=fc(i)) for i in range(5)]
                            + [view(9, institution="Inst 0", published_at="2026-11-03", forecast=fc(9))])[0]
    assert five["n"] == 5 and five["consensus"] and five["median"] == 3 and five["range"] == [1, 9]


def test_external_views_sit_beside_the_signed_view_without_moving_the_evidence(tmp_path):
    bare = build_comparison(CASE)
    write_views(tmp_path / "v", [view(1, stance="challenges"), view(2, hypothesis="H2"), view(3, hypothesis="H9")])
    c = build_comparison(CASE, external_dir=tmp_path / "v")
    assert c["external"]["status"] == "connected" and c["external"]["institutions"] == 2
    assert c["external"]["errors"] and "H9" in c["external"]["errors"][0]
    assert [(h["id"], h["score"], h["at_signing"], h["now"]) for h in c["hypotheses"]] == \
        [(h["id"], h["score"], h["at_signing"], h["now"]) for h in bare["hypotheses"]]
    assert c["summary"] == bare["summary"]
    h1 = next(h for h in c["hypotheses"] if h["id"] == "H1")
    assert h1["external_stances"]["challenges"] == 1 and h1["external_views"][0]["source_url"].startswith("https://")
    assert "Inst 1" in render_markdown(c, "en")


def test_cli_writes_json_and_markdown_and_rejects_bad_external_rows(tmp_path, capsys):
    out_json, out_md = tmp_path / "c.json", tmp_path / "c.md"
    assert views_main(["compare", "--json", str(out_json), "--md", str(out_md), "--lang", "zh",
                       "--external", str(tmp_path / "none")]) == 0
    assert json.loads(out_json.read_text(encoding="utf-8"))["kind"] == "view_comparison"
    assert "已签署观点" in out_md.read_text(encoding="utf-8")
    write_views(tmp_path / "bad", [view(1, source_url="")])
    assert views_main(["compare", "--external", str(tmp_path / "bad")]) == 1
