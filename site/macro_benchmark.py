"""Build the public Release Copilot benchmark report from a frozen replay."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))

from cnmacro.copilot import contract, records
from cnmacro.copilot.context import context_hash

CASE_DIR = Path("research/cases/cn-nominal/copilot")
REPLAY = CASE_DIR / "samples/20261010T043513Z-81249026-138f"
FALLBACK = CASE_DIR / "briefs/runs/20261111T130813Z-564de122-1283"
REPOSITORY = "https://github.com/tasconyeric-slack/CC-Macro-Analysis-OS-public/blob/170fea9baf2a5f0251088aacd07f3e7468af2247/"
PPI = "obs:cn_ppi_yoy@2026-07"
CORE_CPI = "obs:cn_core_cpi_yoy@2026-07"
FUTURE_REF = "obs:cn_ppi_yoy@2026-09"
FIELD = "$.executive_delta[0]"
CONFIGURATIONS = ("json", "contract", "aligned")

# The expected verdicts belong to this dev suite, not to a population of model answers.
SCENARIOS = {
    "aligned": ("allow", None),
    "bare-number": ("block", "numeric_grounding"),
    "unknown-ref": ("block", "invalid_evidence_ref"),
    "future-period": ("block", "as_of_violation"),
    "rule-overwrite": ("block", "mechanical_delta_overwrite"),
    "undeclared-ref": ("block", "missing_evidence"),
    "wrong-metric": ("block", "claim_evidence_mismatch"),
}


def candidate(original: dict, scenario: str, evidence: dict) -> dict:
    draft = copy.deepcopy(original)
    item = draft["executive_delta"][0]
    if scenario == "bare-number":
        item["template"] = item["template"].replace("{" + PPI + "}", evidence[PPI]["display"])
    elif scenario == "unknown-ref":
        item["evidence_refs"].append(FUTURE_REF)
    elif scenario == "future-period":
        item["template"] += " The 2026-09 outcome confirms this reading."
    elif scenario == "rule-overwrite":
        draft["hypothesis_impact"][0]["mechanical_delta"] = "supports"
    elif scenario == "undeclared-ref":
        item["evidence_refs"].remove(PPI)
    elif scenario == "wrong-metric":
        item["template"] = item["template"].replace(PPI, CORE_CPI)
        item["evidence_refs"] = [CORE_CPI if ref == PPI else ref for ref in item["evidence_refs"]]
    return draft


def score(draft: dict, challenge: dict, ctx: dict) -> dict:
    # All candidates start as valid JSON objects. Compare the same output at every stage.
    draft = contract.parse_json(json.dumps(draft))
    violations = contract.validate_draft(draft, ctx)
    if not violations:
        violations = contract.validate_challenge(challenge, ctx)
    rendered = None
    alignment = []
    if not violations:
        result = contract.assemble(ctx, draft, challenge)
        rendered = contract.render(result, ctx)["executive_delta"][0]["template"]
        item = draft["executive_delta"][0]
        first_binding = contract.PLACEHOLDER.search(item["template"])
        if first_binding is None or first_binding.group(1) != PPI or PPI not in item["evidence_refs"]:
            alignment.append(contract.Violation("claim_evidence_mismatch", FIELD, f"Expected the PPI YoY binding {PPI}"))
    return {
        "decisions": {
            "json": "allow",
            "contract": "block" if violations else "allow",
            "aligned": "block" if violations or alignment else "allow",
        },
        "violations": [error.as_dict() for error in violations + alignment],
        "contract_rendered": rendered,
    }


def build_report(root: Path = ROOT) -> dict:
    archive, ctx = records.load_run(root / REPLAY)
    if (archive["kind"] != "fixture" or archive["genuine_model_run"] or
            archive["context"]["sha256"] != ctx["sha256"] or context_hash(ctx) != ctx["sha256"]):
        raise ValueError("Benchmark replay does not match its archived fixture context")
    draft, challenge = (item["parsed"] for item in archive["passes"])
    allowed = {entry["ref"]: entry for entry in ctx["allowlist"]}
    cases = []
    for scenario, (expected, gate) in SCENARIOS.items():
        answer = candidate(draft, scenario, allowed)
        snippet = ({"mechanical_delta": answer["hypothesis_impact"][0]["mechanical_delta"]}
                   if scenario == "rule-overwrite" else answer["executive_delta"][0])
        cases.append({"id": scenario, "split": "demo-dev", "expected": expected, "expected_gate": gate,
                      "candidate_excerpt": snippet, **score(answer, challenge, ctx)})

    summary = {}
    for key in CONFIGURATIONS:
        summary[key] = {}
        for verdict in ("block", "allow"):
            subset = [row for row in cases if row["expected"] == verdict]
            summary[key][verdict] = {"correct": sum(row["decisions"][key] == verdict for row in subset),
                                     "total": len(subset)}

    fallback, _ = records.load_run(root / FALLBACK)
    source_base = "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202608/t20260809_"
    evidence = [{**allowed[ref], "source": source_base + ("1965008.html" if ref == CORE_CPI else "1965007.html")}
                for ref in (PPI, "obs:cn_ppi_mom@2026-07", CORE_CPI)]
    return {
        "schema": 1, "evidence_class": "archived public release snapshot with hand-written replay candidates",
        "model_performance_runs": 0, "context_sha256": ctx["sha256"], "release": ctx["release"],
        "clock": "replay calendar availability convention; prior is not an intraday first-publication timestamp",
        "as_of": ctx["as_of"], "prior_as_of": ctx["prior_as_of"], "evidence": evidence,
        "archive_url": REPOSITORY + (REPLAY / "record.json").as_posix(),
        "cases": cases, "summary": summary,
        "fallback": {"status": fallback["status"], "model_ran": fallback["genuine_model_run"],
                     "run_at": fallback["run_at"], "as_of": fallback["as_of"],
                     "facts": len(fallback["evidence_pack"]["facts"]),
                     "record_url": REPOSITORY + (FALLBACK / "record.json").as_posix()},
    }


if __name__ == "__main__":
    print(json.dumps(build_report(), ensure_ascii=False, indent=2))
