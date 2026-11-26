import json

from macro_benchmark import CONFIGURATIONS, PPI, REPLAY, build_report, candidate, score
from cnmacro.copilot.records import load_run
from conftest import ROOT


def test_replay_distinguishes_parsing_guardrails_and_evidence_alignment():
    report = build_report()
    assert report["model_performance_runs"] == 0
    assert report["fallback"]["status"] == "model_unavailable"
    assert not report["fallback"]["model_ran"]
    assert tuple(report["summary"]) == CONFIGURATIONS
    for row in report["cases"]:
        assert row["decisions"]["aligned"] == row["expected"]
        if row["expected_gate"]:
            assert row["expected_gate"] in {violation["gate"] for violation in row["violations"]}
    assert [row["block"]["correct"] for row in report["summary"].values()] == [0, 5, 6]
    assert all(row["allow"] == {"correct": 1, "total": 1} for row in report["summary"].values())
    focal = report["cases"][-1]
    assert focal["decisions"]["contract"] == "allow"
    assert "0.9%" in focal["contract_rendered"]


def test_adding_the_correct_reference_later_does_not_fix_the_first_binding():
    record, ctx = load_run(ROOT / REPLAY)
    draft, challenge = (item["parsed"] for item in record["passes"])
    wrong = candidate(draft, "wrong-metric", {})
    first = wrong["executive_delta"][0]
    first["template"] += " An additional observation is {" + PPI + "}."
    first["evidence_refs"].append(PPI)
    result = score(wrong, challenge, ctx)
    assert result["decisions"]["contract"] == "allow"
    assert result["decisions"]["aligned"] == "block"


def test_bilingual_demo_uses_the_exported_report_and_has_a_method_link(built):
    report = json.loads((built / "benchmark-results.json").read_text())
    for loc in ("en", "zh"):
        page = (built / loc / "benchmark.html").read_text()
        assert report["context_sha256"] in page
        assert page.count('class="benchmark-case"') == len(report["cases"])
        assert 'href="../benchmark-results.json"' in page
        assert 'href="#wrong-metric"' in page
        assert 'href="benchmark.html"' in (built / loc / "method.html").read_text()
