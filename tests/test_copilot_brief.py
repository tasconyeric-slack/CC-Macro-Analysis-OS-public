"""Research Brief (Issue #69 W6): the real 2026-10 CPI/PPI release plus the source-linked items collected around it,
Explain + Challenge under the Release Copilot's hard gates, a Run Record, a person's review and the public export.
Model answers here are hand-written fixtures; nothing in this file is, or is presented as, a genuine model run."""
import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from conftest import ROOT

from cnmacro.copilot import brief, contract, records
from cnmacro.copilot.context import ContextError, build_context, resolve_release
from cnmacro.copilot.llm import FixtureClient, ModelUnavailable
from cnmacro.refresh import Paths

FX = Path(__file__).parent / "fixtures/copilot_brief"
BUNDLE = ROOT / "research/cases/cn-nominal/inputs/2026-11-10.json"
AS_OF = "2026-11-09T03:00:00Z"            # just after the 2026-11-09 refresh ingested the October CPI/PPI first print


class GenuineLike(FixtureClient):
    """Stands in for a working provider so the reviewed path can be exercised; it is still hand-written text."""
    genuine = True
    provider = "test-double"


@pytest.fixture(scope="module")
def base_ctx():
    paths = Paths.default(ROOT)
    return brief.build_brief_context(paths, resolve_release(paths.calendar, "2026-10 PPI"), AS_OF, None, bundle_path=BUNDLE)


@pytest.fixture
def ctx(base_ctx):
    return copy.deepcopy(base_ctx)


def load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def gates(errs):
    return {e.gate for e in errs}


def run(ctx, tmp_path, client):
    return brief.run_brief(client, ctx, tmp_path / "briefs", log=lambda *_: None)


# ================================================================ context
def test_brief_context_is_the_release_context_plus_point_in_time_sources(ctx):
    paths = Paths.default(ROOT)
    plain = build_context(paths, resolve_release(paths.calendar, "2026-10 PPI"), AS_OF, None)
    assert [e for e in ctx["allowlist"] if e["kind"] != "source"] == plain["allowlist"]          # facts unchanged
    assert [o["ref"] for o in ctx["new_observations"]] == [o["ref"] for o in plain["new_observations"]]
    src = [e for e in ctx["allowlist"] if e["kind"] == "source"]
    assert src and len(src) <= brief.MAX_SOURCES
    assert src[0]["evidence_kind"] == "official_release" and src[0]["url"].startswith("https://www.stats.gov.cn/")
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    by_id = {i["event_id"]: i for i in bundle["items"]}
    for e in src:
        item = by_id[e["ref"][4:]]
        assert item["available_at"] <= AS_OF and item["triage"] in ("research_needed", "monitor") and not item["repetition_of"]
    # the 2026-11-10 customs headlines were not knowable at as_of
    assert not any("货物贸易" in e["display"] for e in src)
    assert ctx["version"] == brief.BRIEF_CONTEXT_VERSION and ctx["sha256"] == brief.context_hash(ctx)


def test_brief_context_is_deterministic_and_masks_figures_the_model_could_echo(ctx, base_ctx):
    paths = Paths.default(ROOT)
    again = brief.build_brief_context(paths, resolve_release(paths.calendar, "2026-10 PPI"), AS_OF, None, bundle_path=BUNDLE)
    assert again["sha256"] == base_ctx["sha256"]
    for e in ctx["allowlist"]:
        if e["kind"] == "source":
            assert contract.digits_left(e["title"] + " " + e["excerpt"]) == [], e["title"]


def test_without_a_bundle_the_brief_has_facts_only(ctx):
    paths = Paths.default(ROOT)
    bare = brief.build_brief_context(paths, resolve_release(paths.calendar, "2026-10 PPI"), AS_OF, None, bundle_path=None)
    assert bare["sources"]["count"] == 0 and not any(e["kind"] == "source" for e in bare["allowlist"])


def test_a_file_that_is_not_a_bundle_is_refused(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text('{"kind": "news"}', encoding="utf-8")
    with pytest.raises(ContextError):
        brief.load_bundle(bad)


# ================================================================ gates
def test_the_fixture_passes_every_gate_and_renders_code_values(ctx, tmp_path):
    rec, d = run(ctx, tmp_path, FixtureClient([FX / "draft.json", FX / "challenge.json"]))
    assert rec["status"] == "validated" and d.parent.name == "samples"          # a fixture never lands in runs/
    md = brief.render_markdown(rec["rendered"], ctx, rec["sources"])
    by_ref = {e["ref"]: e for e in ctx["allowlist"]}
    assert by_ref["obs:cn_ppi_yoy@2026-10"]["display"] in md and "{" not in md
    assert {s["ref"] for s in rec["sources"]} >= {"src:event_7c0e35a3eee519ffe8ae", "src:event_aaa6cf65550e45187700"}
    assert all(s["url"] in md for s in rec["sources"])
    assert rec["result"]["whats_next"][0]["scheduled_metrics"]                  # the date maps onto the calendar entry
    assert rec["signed_thesis_update"] is False and "direction_hint" not in json.dumps(rec["result"])


def test_a_claim_resting_on_media_reports_alone_is_refused(ctx):
    media = {"ref": "src:evt-media", "kind": "source", "evidence_kind": "media_report", "display": "x", "label": "media",
             "publisher": "x", "published_at": AS_OF, "url": "https://example.com", "title": "x", "excerpt": "",
             "hypotheses": ["H4"], "triage": "monitor", "observation_refs": []}
    ctx["allowlist"].append(media)
    draft = load("draft.json")
    draft["executive_delta"][0]["evidence_refs"] = ["src:evt-media"]
    draft["executive_delta"][0]["template"] = "Trade looks strong according to {src:evt-media}."
    assert "missing_evidence" in gates(brief.validate_explain(draft, ctx))
    draft["executive_delta"][0]["evidence_refs"] = ["src:evt-media", "obs:cn_ppi_yoy@2026-10"]
    assert brief.validate_explain(draft, ctx) == []


@pytest.mark.parametrize("text", ["PPI rose to 5.7 in October.", "PPI rose by 0.7 percentage points.", "Core CPI hit 0.8%."])
def test_typed_numbers_fail_in_every_brief_field(ctx, text):
    ch = load("challenge.json")
    ch["counter_evidence"][0]["claim"] = text
    assert "numeric_grounding" in gates(brief.validate_brief_challenge(ch, ctx, load("draft.json")))


def test_a_competing_explanation_resting_on_media_alone_is_refused(ctx):
    ctx["allowlist"].append({"ref": "src:evt-media", "kind": "source", "evidence_kind": "media_report", "display": "x"})
    ch = load("challenge.json")
    ch["competing_explanation"]["evidence_refs"] = ["src:evt-media"]
    ch["competing_explanation"]["why_plausible"] = "Reported in {src:evt-media}."
    ch["competing_explanation"]["claim"] = "Trade is the driver."
    assert "missing_evidence" in gates(brief.validate_brief_challenge(ch, ctx, load("draft.json")))


def test_non_string_targets_and_dates_are_schema_failures_not_crashes(ctx):
    ch = load("challenge.json")
    ch["counter_evidence"][0]["against"] = ["X1"]
    ch["whats_next"][0]["release_at"] = {"at": "2026-11-16T02:00:00Z"}
    assert "schema" in gates(brief.validate_brief_challenge(ch, ctx, load("draft.json")))


def test_whats_next_dates_are_code_owned(ctx):
    ch = load("challenge.json")
    ch["whats_next"][0]["release_at"] = "2026-11-15T02:00:00Z"
    assert "as_of_violation" in gates(brief.validate_brief_challenge(ch, ctx, load("draft.json")))
    ch["whats_next"][0]["release_at"] = "unscheduled"
    assert brief.validate_brief_challenge(ch, ctx, load("draft.json")) == []
    ch["whats_next"][0]["watch"] = "The 2027-06 data will settle it."
    assert "as_of_violation" in gates(brief.validate_brief_challenge(ch, ctx, load("draft.json")))


def test_counter_evidence_must_target_the_draft_and_cite_the_allowlist(ctx):
    ch = load("challenge.json")
    ch["counter_evidence"][0]["against"] = "X9"
    assert "schema" in gates(brief.validate_brief_challenge(ch, ctx, load("draft.json")))
    ch = load("challenge.json")
    ch["counter_evidence"][0]["evidence_refs"] = ["obs:cn_gdp_yoy@2026-10"]
    assert "invalid_evidence_ref" in gates(brief.validate_brief_challenge(ch, ctx, load("draft.json")))
    ch = load("challenge.json")
    ch["counter_evidence"] = []
    assert "schema" in gates(brief.validate_brief_challenge(ch, ctx, load("draft.json")))


def test_the_brief_cannot_carry_thesis_state(ctx):
    ch = load("challenge.json")
    ch["probability"] = 0.5
    assert "thesis_state_write" in gates(brief.validate_brief_challenge(ch, ctx, load("draft.json")))
    dr = load("draft.json")
    dr["hypothesis_impact"][0]["mechanical_delta"] = "unchanged"
    assert "mechanical_delta_overwrite" in gates(brief.validate_explain(dr, ctx))


def test_a_failed_explain_stops_before_the_challenge(ctx, tmp_path):
    bad = tmp_path / "bad.json"
    d = load("draft.json")
    d["executive_delta"][0]["template"] = "PPI rose to 5.7."
    bad.write_text(json.dumps(d), encoding="utf-8")
    rec, _ = run(ctx, tmp_path, FixtureClient([bad, FX / "challenge.json"]))
    assert rec["status"] == "validation_failed" and len(rec["passes"]) == 1 and rec["rendered"] is None
    assert rec["validation"]["hard_gate_failures"]["numeric_grounding"] >= 1


# ================================================================ fail-soft, review, export
def test_no_credential_is_a_recorded_outcome_with_the_evidence_pack(ctx, tmp_path):
    rec, d = run(ctx, tmp_path, None)
    assert rec["status"] == "model_unavailable" and d.parent.name == "runs"
    pack = rec["evidence_pack"]
    assert {f["ref"] for f in pack["facts"]} == {o["ref"] for o in ctx["new_observations"]}
    ppi = next(f for f in pack["facts"] if f["metric_id"] == "cn_ppi_yoy")
    assert (ppi["value"], ppi["previous"], ppi["change"]) == ("5.7%", "5.0%", "+0.7 pp")
    out = brief.export_public(d)
    assert out["status"] == "evidence_only" and out["brief"] is None and out["reason"] == "no model ran"
    assert "AI" not in json.dumps(out["evidence_pack"])


def test_a_model_outage_is_recorded_not_raised(ctx, tmp_path):
    class Down(GenuineLike):
        def call(self, system, user):
            raise ModelUnavailable("network", "TimeoutError")
    rec, _ = run(ctx, tmp_path, Down([]))
    assert rec["status"] == "model_error" and rec["copilot"] == "unavailable"


def test_only_a_person_can_review_and_only_reviewed_text_is_exported(ctx, tmp_path):
    rec, d = run(ctx, tmp_path, GenuineLike([FX / "draft.json", FX / "challenge.json"]))
    assert d.parent.name == "runs"
    assert brief.export_public(d)["status"] == "evidence_only"                      # awaiting review: no AI text
    for bot in ("github-actions[bot]", "Claude", "deepseek-flash", "codex"):
        with pytest.raises(records.RecordError):
            brief.review(d, "accept", reviewer=bot)
    with pytest.raises(records.RecordError):
        brief.review(d, "edit", reviewer="Yeric", reason="")
    brief.review(d, "edit", reviewer="Yeric", reason="tighten X1", final_markdown="# edited\n")
    out = brief.export_public(d)
    assert out["status"] == "reviewed_ai_interpretation" and out["signed_thesis_update"] is False
    assert out["brief_markdown"] == "# edited\n" and out["reviewer"] == "Yeric" and "Not a signed thesis update" in out["label"]["en"]
    ev = records.events(d)
    assert [e["kind"] for e in ev] == ["revealed", "decision"] and ev[1]["edit_diff"]
    with pytest.raises(records.RecordError):                                         # append-only: one decision per run
        brief.review(d, "accept", reviewer="Yeric")
    assert records.verify_chain(d) == []


def test_a_rejected_or_synthetic_brief_never_exports_model_text(ctx, tmp_path):
    rec, d = run(ctx, tmp_path, GenuineLike([FX / "draft.json", FX / "challenge.json"]))
    brief.review(d, "reject", reviewer="Yeric", reason="overstates H0")
    assert brief.export_public(d)["brief"] is None
    rec2, d2 = run(ctx, tmp_path, FixtureClient([FX / "draft.json", FX / "challenge.json"]))
    brief.review(d2, "accept", reviewer="Yeric")
    out = brief.export_public(d2)
    assert out["status"] == "evidence_only" and out["reason"] == "a fixture is synthetic and is never published"


def test_the_brief_writes_only_its_own_records(tmp_path, monkeypatch):
    """CLI end to end without a credential: exit 3, a Run Record under copilot/briefs/, nothing else touched."""
    for rel in ("data/dictionary", "data/demo", "research/cases/cn-nominal"):
        shutil.copytree(ROOT / rel, tmp_path / rel, ignore=shutil.ignore_patterns("latest-private.json"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    def digest():
        return {p.relative_to(tmp_path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(tmp_path.rglob("*")) if p.is_file()}
    from cnmacro import cli
    before = digest()
    assert cli.main(["copilot", "brief", "run", "--release", "2026-10 PPI", "--as-of", AS_OF]) == 3
    changed = {k for k, v in digest().items() if before.get(k) != v}
    assert changed and all(k.startswith("research/cases/cn-nominal/copilot/briefs/runs/") for k in changed), changed
    assert cli.main(["copilot", "brief", "pack", "--release", "2026-10 PPI", "--as-of", AS_OF, "--markdown"]) == 0
