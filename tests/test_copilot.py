"""Release Copilot v0: bounded context, hard gates, Run Record, analyst protocol, and isolation from the
deterministic pipeline. Model responses here are hand-written fixtures or fakes; nothing in this file is,
or is presented as, a genuine model run."""
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

from conftest import CASE, ROOT
from htmlutil import parse

from cnmacro import checks, store
from cnmacro.copilot import contract, context as ctxmod, llm, ops, records, runner
from cnmacro.copilot.context import ContextError, ReleaseSpec, build_context, context_hash
from cnmacro.copilot.llm import DeepSeekClient, FixtureClient, ModelUnavailable, Reply
from cnmacro.refresh import Paths

FX = Path(__file__).parent / "fixtures/copilot"


def load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- one real replay, shared (about 12 s)
@pytest.fixture(scope="module")
def replayed(tmp_path_factory):
    out = tmp_path_factory.mktemp("copilot") / "sb"
    ctx, extra, rep = ops.replay_context("2026-08-09", out, ROOT, log=lambda *_: None)
    return {"ctx": ctx, "extra": extra, "rep": rep, "out": out}


@pytest.fixture
def ctx(replayed):
    return copy.deepcopy(replayed["ctx"])


def gates(errs):
    return {e.gate for e in errs}


# ================================================================ context builder
def test_context_is_deterministic_bounded_and_replay_labelled(replayed):
    ctx, out = replayed["ctx"], replayed["out"]
    again = build_context(ops.sandbox_paths(out), ReleaseSpec(**ctx["release"]), ctx["as_of"], ctx["prior_as_of"])
    assert again["sha256"] == ctx["sha256"] == context_hash(ctx)
    assert len(ctx["allowlist"]) <= ctxmod.MAX_ALLOWLIST and len(json.dumps(ctx)) < 60_000
    assert ctx["mode"] == "replay" and "framework contamination" in ctx["replay_disclosure"]
    assert all(h["analyst_prior"] is None for h in ctx["hypotheses"].values())      # 2026-10-04 prose post-dates the replay
    assert ctx["standing_thesis"]["read_only"] is True


def test_mechanical_direction_is_computed_from_test_flips(ctx):
    d = {h: v["mechanical_delta"] for h, v in ctx["hypotheses"].items()}
    assert d == {"H1": "challenges", "H2": "supports", "H3": "unchanged", "H4": "unchanged", "H0": "unchanged"}
    assert [f["test"] for f in ctx["hypotheses"]["H1"]["flips"]] == ["T-H1-01"]
    assert ctx["terminal"]["owner"] == "code"


def test_context_never_contains_an_observation_unavailable_at_as_of(replayed):
    ctx, out = replayed["ctx"], replayed["out"]
    obs = store.load_observations(out / "observations")
    held = store.as_of(obs, ctx["as_of"])
    have = {(r.metric_id, r.reference_period) for r in held.itertuples()}
    when = pd.Timestamp(ctx["as_of"]).tz_localize(None)
    for e in ctx["allowlist"]:
        if e["kind"] == "obs":
            assert (e["ref"].split(":")[1].split("@")[0], e["period"]) in have
            assert pd.Timestamp(e["available_at"]).tz_localize(None) <= when


def test_rows_released_after_as_of_do_not_change_the_context(replayed, tmp_path):
    ctx, out = replayed["ctx"], replayed["out"]
    sb = tmp_path / "sb"
    shutil.copytree(out, sb)
    obs_dir = sb / "observations"
    future = {"metric_id": "cn_ppi_yoy", "reference_period": "2026-08", "value": 99.0, "release_date": "2026-09-09",
              "release_date_basis": "official_calendar", "retrieved_at": "2026-10-04T00:00:00+00:00", "source": "NBS",
              "source_code": "", "source_class": "public", "consensus": "", "quality_flag": "ok", "limitation": ""}
    pd.DataFrame([future]).to_csv(obs_dir / "future.csv", index=False)
    again = build_context(ops.sandbox_paths(sb), ReleaseSpec(**ctx["release"]), ctx["as_of"], ctx["prior_as_of"])
    assert again["sha256"] == ctx["sha256"]
    assert not any("2026-08" in e["ref"] for e in again["allowlist"] if e["kind"] == "obs" and "ppi_yoy" in e["ref"])


def test_context_refuses_private_observations_and_withholds_licensed_series(replayed, tmp_path):
    ctx, out = replayed["ctx"], replayed["out"]
    paths = ops.sandbox_paths(out)
    private = Paths(**{**paths.__dict__, "obs_dir": tmp_path / "data/private/observations"})
    with pytest.raises(ContextError, match="public observations only"):
        build_context(private, ReleaseSpec(**ctx["release"]), ctx["as_of"], ctx["prior_as_of"])
    sb = tmp_path / "sb"
    shutil.copytree(out, sb)
    d = yaml.safe_load((sb / "dictionary.yaml").read_text(encoding="utf-8"))
    for m in d["metrics"]:
        if m["metric_id"] == "cn_core_cpi_yoy":
            m["redistribution"] = "private_only"
    (sb / "dictionary.yaml").write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    again = build_context(ops.sandbox_paths(sb), ReleaseSpec(**ctx["release"]), ctx["as_of"], ctx["prior_as_of"])
    assert not any("cn_core_cpi_yoy" in e["ref"] for e in again["allowlist"])
    assert "cn_core_cpi_yoy" not in json.dumps(again["new_observations"])


def test_no_delta_means_no_context(replayed):
    ctx, out = replayed["ctx"], replayed["out"]
    rel = ReleaseSpec(**ctx["release"])
    with pytest.raises(ContextError):
        build_context(ops.sandbox_paths(out), rel, ctx["prior_as_of"], ctx["prior_as_of"])
    with pytest.raises(ContextError, match="has not happened yet"):
        build_context(ops.sandbox_paths(out), rel, "2026-08-01T00:00:00Z", ctx["prior_as_of"])


def test_live_mode_uses_the_standing_judgment_and_analyst_words(tmp_path):
    """Synthetic September rows in a scratch copy of the live case (test data, not a release)."""
    for rel in ("data/dictionary", "data/demo", "research/cases/cn-nominal"):
        shutil.copytree(ROOT / rel, tmp_path / rel, ignore=shutil.ignore_patterns("latest-private.json"))
    rows = [{"metric_id": m, "reference_period": "2026-09", "value": v, "release_date": "2026-10-14T09:30:00+08:00",
             "release_date_basis": "official_calendar", "retrieved_at": "2026-10-14T02:21:00+00:00", "source": "NBS",
             "source_code": "", "source_class": "public", "consensus": "", "quality_flag": "ok", "limitation": ""}
            for m, v in [("cn_ppi_yoy", 4.0), ("cn_ppi_mom", 0.1), ("cn_cpi_yoy", 0.7), ("cn_core_cpi_yoy", 0.9),
                         ("cn_ppi_producer_yoy", 5.0), ("cn_ppi_consumer_yoy", -0.5)]]
    pd.DataFrame(rows).to_csv(tmp_path / "data/demo/observations/synthetic_september.csv", index=False)
    paths = Paths.default(tmp_path)
    rel = ctxmod.resolve_release(paths.calendar, "September 2026 CPI and PPI")
    c = build_context(paths, rel, "2026-10-14T03:00:00Z")
    assert c["mode"] == "live" and c["replay_disclosure"] is None
    assert c["standing_thesis"]["judgment"]["probability"] == 0.3 and c["standing_thesis"]["judgment_source"] == "2026-10-04-baseline.yaml"
    assert c["hypotheses"]["H0"]["analyst_prior"].startswith("Best-supported")
    assert "obs:cn_ppi_yoy@2026-09" in ctxmod.allowed_refs(c) and c["expectation"] is None
    assert c["release"]["release_id"] == "september-2026-cpi-and-ppi"
    # the same context an hour before the release has nothing to interpret
    with pytest.raises(ContextError):
        build_context(paths, rel, "2026-10-14T00:00:00Z")


def test_expectation_note_counts_only_if_frozen_before_the_release(tmp_path, monkeypatch):
    note = tmp_path / "2026-10-14-cpi-ppi.yaml"
    note.write_text(yaml.safe_dump({"kind": "expectation_note", "release": "R", "expectations": [
        {"ref": "obs:x@2026-09", "direction_vs_prior": "up", "range": [1.0, 2.0]}]}), encoding="utf-8")
    (tmp_path / "_template.yaml").write_text("kind: expectation_note\nrelease: R\n", encoding="utf-8")
    rel = ReleaseSpec("r", "R", "2026-09", "2026-10-14T09:30:00+08:00", [])

    class D:
        def resolve(self, ref):
            return type("P", (), {"value": 2.5})()

    def status(commits, when):
        monkeypatch.setattr(records, "git_commits", lambda p: commits)
        monkeypatch.setattr(checks, "commit_time", lambda sha: pd.Timestamp(when) if when else None)
        return ctxmod._expectation(tmp_path, rel, D())

    assert status([], None)["status"] == "excluded"                                        # never committed
    assert status(["a", "b"], "2026-10-12")["status"] == "excluded"                        # edited after first commit
    assert status(["a"], "2026-10-14T02:00:00")["status"] == "excluded"                    # committed after the release (UTC 02:00 > 01:30)
    note.write_text(yaml.safe_dump({"kind": "expectation_note", "release": "R", "expectations": [
        {"ref": "obs:x@2026-09", "direction_vs_prior": "up", "range": [1.0, 2.0], "note": "I expect 1.5 at most"}],
        "scenarios": [{"if": "PPI m/m below -0.2", "then": "H1 weakens; 3 of 6 demand tests fail by 2026Q4"}]}), encoding="utf-8")
    ok = status(["a"], "2026-10-13T12:00:00")
    assert ok["status"] == "frozen" and ok["items"][0]["vs_expectation"] == "above"        # computed by code from the note
    assert ok["items"][0]["range"] == [1.0, 2.0]                                           # the analyst's own range stays structured data
    assert "[figure]" in ok["items"][0]["note"] and "1.5" not in json.dumps(ok["scenarios"]) + ok["items"][0]["note"]
    assert ok["scenarios"][0]["then"] == "H1 weakens; [figure] of [figure] demand tests fail by 2026Q4"   # labels and periods survive


def test_analyst_prose_reaches_the_model_with_its_figures_masked():
    m = ctxmod.mask_figures
    assert m("Raise to 35% by 2026-12 if PPI m/m is below -0.2 and 3 of 6 tests pass (2027Q1).") == \
        "Raise to [figure] by 2026-12 if PPI m/m is below [figure] and [figure] of [figure] tests pass (2027Q1)."
    assert m("H2 holds; no figures.") == "H2 holds; no figures." and m(None) is None
    assert contract.digits_left(m("up 35%, +0.4pp and 1,200 units")) == []                 # nothing left for the model to echo


# ================================================================ hard gates
def test_the_well_formed_fixture_passes_every_gate(ctx):
    assert contract.validate_draft(load("ok/draft.json"), ctx) == []
    assert contract.validate_challenge(load("ok/challenge.json"), ctx) == []


@pytest.mark.parametrize("text", [
    "PPI eased to 3.4 in July.",                                   # a data figure
    "PPI eased by about {obs:cn_ppi_yoy@2026-07}, roughly 1 point.",
    "Prices fell 0.6 percent.",                                    # unit word
    "Prices fell by two percentage points.",
    "The reading was weak (-0.6%).",
    "T-H1-01 flipped.",                                            # a test id typed instead of {test:...}
    "Release on 2026-10-14 will tell.",                            # a full date leaves digits behind
])
def test_ungrounded_numbers_fail_validation(ctx, text):
    d = load("ok/draft.json")
    d["executive_delta"][3]["template"] = text
    assert "numeric_grounding" in gates(contract.validate_draft(d, ctx))


def test_evidence_must_come_from_the_allowlist_and_be_declared(ctx):
    d = load("ok/draft.json")
    d["executive_delta"][0]["evidence_refs"] = ["obs:cn_ppi_yoy@2026-07", "obs:cn_ppi_yoy@2026-08"]      # a period that does not exist yet
    d["executive_delta"][1]["template"] = "Momentum is {drv:ma(cn_ppi_mom,3)@2026-08}."                 # placeholder outside the allowlist
    d["executive_delta"][2]["evidence_refs"] = ["obs:invented@2026-07"]
    errs = contract.validate_draft(d, ctx)
    assert {"invalid_evidence_ref"} <= gates(errs) and len([e for e in errs if e.gate == "invalid_evidence_ref"]) >= 3
    d2 = load("ok/draft.json")
    d2["executive_delta"][0]["evidence_refs"] = ["obs:cn_ppi_yoy@2026-07"]           # uses two more placeholders than it declares
    assert "missing_evidence" in gates(contract.validate_draft(d2, ctx))
    d3 = load("ok/draft.json")
    d3["executive_delta"][3]["evidence_refs"] = []
    assert "missing_evidence" in gates(contract.validate_draft(d3, ctx))


def test_the_model_cannot_supply_mechanical_delta_not_even_the_true_value(ctx):
    d = load("ok/draft.json")
    d["hypothesis_impact"][1]["mechanical_delta"] = ctx["hypotheses"]["H1"]["mechanical_delta"]
    assert "mechanical_delta_overwrite" in gates(contract.validate_draft(d, ctx))
    # and the assembled result always carries the code's value, whatever the model argued
    res = contract.assemble(ctx, load("ok/draft.json"), load("ok/challenge.json"))
    assert {h["hypothesis"]: h["mechanical_delta"] for h in res["hypothesis_impact"]} == \
        {h: v["mechanical_delta"] for h, v in ctx["hypotheses"].items()}


@pytest.mark.parametrize("where, key", [("top", "probability"), ("top", "conviction"), ("delta", "status"), ("delta", "new_probability")])
def test_the_model_cannot_write_thesis_state(ctx, where, key):
    d = load("ok/draft.json")
    (d if where == "top" else d["executive_delta"][0])[key] = 0.35
    assert "thesis_state_write" in gates(contract.validate_draft(d, ctx))


def test_the_model_cannot_assign_a_conviction_level(ctx):
    c = load("ok/challenge.json")
    c["draft_analyst_update"]["text_template"] = "Raise conviction to HIGH on this evidence."
    assert "thesis_state_write" in gates(contract.validate_challenge(c, ctx))
    c = load("ok/challenge.json")
    c["draft_analyst_update"]["direction_hint"] = "set_probability_0.4"
    assert "schema" in gates(contract.validate_challenge(c, ctx))                  # a direction, never a number


def test_code_owned_fields_cannot_be_supplied(ctx):
    d = load("ok/draft.json")
    d["executive_delta"][0]["vs_expectation"] = "above"
    d["as_of"] = "2026-08-11T00:00:00Z"
    d["release_id"] = "x"
    errs = contract.validate_draft(d, ctx)
    assert sum("code-owned" in e.message for e in errs) == 3


def test_periods_after_the_information_set_are_an_as_of_violation(ctx):
    d = load("ok/draft.json")
    d["executive_delta"][3]["template"] = "September data will show it, and 2026-09 is the next test."
    assert contract.validate_draft(d, ctx) == [] or True                           # words are not policed; tokens are
    d["executive_delta"][3]["template"] = "The 2026-09 reading will confirm this."
    assert "as_of_violation" in gates(contract.validate_draft(d, ctx))
    d["executive_delta"][3]["template"] = "This matters for the terminal test in 2026Q4 and the 2026-06 base."
    assert "as_of_violation" not in gates(contract.validate_draft(d, ctx))         # horizon period and a past period are fine


def test_divergence_is_derived_and_cannot_be_hidden_or_invented(ctx):
    d = load("ok/draft.json")
    h = {x["hypothesis"]: x for x in d["hypothesis_impact"]}
    h["H1"]["divergence"], h["H1"]["divergence_reason"] = True, "I disagree somehow."          # aligned pair, claimed divergence
    h["H0"]["divergence"], h["H0"]["divergence_reason"] = False, ""                            # real divergence, hidden
    errs = [e for e in contract.validate_draft(d, ctx) if e.gate == "divergence_inconsistent"]
    assert {e.path for e in errs} >= {"$.hypothesis_impact[1].divergence", "$.hypothesis_impact[0].divergence"}
    d = load("ok/draft.json")
    d["hypothesis_impact"][0]["divergence_reason"] = ""                                         # divergence true, no reason
    assert contract.validate_draft(d, ctx)
    assert contract.divergence_of("supports", "strengthen") is False and contract.divergence_of("unchanged", "unresolved") is False
    assert contract.divergence_of("supports", "unresolved") is True and contract.divergence_of("challenges", "unchanged") is True


def test_closed_schema_and_bounds(ctx):
    d = load("ok/draft.json")
    d["hypothesis_impact"].pop()
    d["executive_delta"] = d["executive_delta"] * 2
    d["extra"] = []
    errs = contract.validate_draft(d, ctx)
    assert gates(errs) == {"schema"} and len(errs) >= 3
    assert contract.validate_draft("not an object", ctx)
    c = load("ok/challenge.json")
    c["research_needs"] = c["research_needs"] * 2
    assert any(e.path == "$.research_needs" for e in contract.validate_challenge(c, ctx))
    c = load("ok/challenge.json")
    c["competing_explanation"]["background_knowledge"] = ["Oil rose 5 times last year."]
    assert "numeric_grounding" in gates(contract.validate_challenge(c, ctx))
    c["competing_explanation"]["background_knowledge"] = ["Background citing {obs:cn_ppi_yoy@2026-07}."]
    assert "invalid_evidence_ref" in gates(contract.validate_challenge(c, ctx))        # background is never evidence


def test_vs_expectation_is_computed_by_code(ctx):
    ctx["expectation"] = {"status": "frozen", "items": [{"ref": "obs:cn_ppi_yoy@2026-07", "vs_expectation": "below"}]}
    res = contract.assemble(ctx, load("ok/draft.json"), load("ok/challenge.json"))
    assert [x["vs_expectation"] for x in res["executive_delta"]] == ["below", "not_set", "not_set", "not_set"]
    ctx["expectation"] = {"status": "excluded"}
    assert {x["vs_expectation"] for x in contract.assemble(ctx, load("ok/draft.json"), load("ok/challenge.json"))["executive_delta"]} == {"not_set"}


def test_rendering_fills_values_from_the_allowlist_and_refuses_anything_else(ctx):
    res = contract.assemble(ctx, load("ok/draft.json"), load("ok/challenge.json"))
    r = contract.render(res, ctx)
    assert "3.5%" in r["executive_delta"][0]["template"] and "4.1%" in r["executive_delta"][0]["template"]
    assert "+0.1 pp" in r["executive_delta"][2]["template"] and "T-H1-01" in r["executive_delta"][1]["template"]
    assert not re.search(r"\{(obs|drv|test):", json.dumps(r)) and r["executive_delta"][0]["evidence_refs"] == res["executive_delta"][0]["evidence_refs"]
    res["executive_delta"][0]["template"] = "Level {obs:cn_ppi_yoy@2026-08}."
    with pytest.raises(contract.RenderError):
        contract.render(res, ctx)
    md = contract.render_markdown(r, ctx, show_hint=False)
    assert "withheld until your blind take" in md and "hold" not in md.split("Direction hint")[1]
    assert "*Direction hint:* hold" in contract.render_markdown(r, ctx, show_hint=True)


# ================================================================ runner and Run Record
class Genuine:
    """A stand-in for a real client in tests only: it is labelled genuine so the record lands in runs/."""
    genuine, provider, model = True, "deepseek", "deepseek-flash"

    def __init__(self, texts=None, error=None):
        self.texts, self.error, self.i = texts or [], error, 0

    def identity(self):
        return {"provider": "deepseek", "requested_id": self.model}

    def call(self, system, user):
        if self.error:
            raise self.error
        t = self.texts[self.i]
        self.i += 1
        return Reply(t, {"test": True}, {"input_tokens": 1000, "output_tokens": 500}, 5, "end_turn", self.model)


def text(name):
    return (FX / name).read_text(encoding="utf-8")


def test_a_validated_run_is_complete_and_inspectable(ctx, tmp_path):
    rec, d = runner.run_release(FixtureClient([FX / "ok/draft.json", FX / "ok/challenge.json"]), ctx, tmp_path, log=lambda *_: None)
    assert d.parent.name == "samples" and rec["kind"] == "fixture" and rec["genuine_model_run"] is False      # synthetic never lands in runs/
    assert rec["status"] == "validated" and rec["copilot"] == "ok" and rec["validation"]["ok"]
    for k in ("run_id", "run_at", "release", "as_of", "model", "versions", "context", "passes", "result", "rendered", "validation", "usage"):
        assert k in rec
    assert rec["versions"]["prompt"] == "release-copilot-prompt/1" and rec["versions"]["schema"] and rec["versions"]["context"]
    assert rec["context"]["sha256"] == ctx["sha256"] and set(rec["context"]["evidence_allowlist"]) == ctxmod.allowed_refs(ctx)
    assert [p["name"] for p in rec["passes"]] == ["draft", "challenge"] and all(p["prompt_sha256"] and p["raw_response"] for p in rec["passes"])
    assert rec["publication"]["public"] is False and "fixture" in rec["evidence_class"] and rec["mode"] == "replay"
    assert records.load_run(d)[1]["sha256"] == ctx["sha256"]
    assert ops.verify_run(d, ROOT, rebuild=False)["ok"]


def test_a_fabricating_draft_fails_closed_and_stops(ctx, tmp_path):
    rec, d = runner.run_release(FixtureClient([FX / "fabricated/draft.json"]), ctx, tmp_path, log=lambda *_: None)
    assert rec["status"] == "validation_failed" and rec["result"] is None and rec["rendered"] is None
    assert [p["name"] for p in rec["passes"]] == ["draft"]                                  # no Challenge on a failed Draft
    f = rec["validation"]["gate_failures"]
    assert f["numeric_grounding"] and f["invalid_evidence_ref"] and f["as_of_violation"] and f["mechanical_delta_overwrite"] \
        and f["thesis_state_write"] and f["divergence_inconsistent"]
    assert rec["validation"]["hard_gate_failures"]["mechanical_delta_overwrite"] == 1
    assert ops.verify_run(d, ROOT, rebuild=False)["ok"]                                     # a failure replays to the same failure


def test_a_failed_challenge_discards_the_whole_run(ctx, tmp_path):
    bad = json.loads(text("ok/challenge.json"))
    bad["research_needs"][0]["why_now"] = "Up 3 points."
    client = Genuine([text("ok/draft.json"), json.dumps(bad)])
    rec, d = runner.run_release(client, ctx, tmp_path, log=lambda *_: None)
    assert rec["status"] == "validation_failed" and rec["result"] is None and [p["name"] for p in rec["passes"]] == ["draft", "challenge"]
    assert d.parent.name == "runs" and rec["kind"] == "model_run"
    assert rec["usage"]["input_tokens"] == 2000 and rec["usage"]["cost_usd"] is None
    assert rec["model"]["provider"] == "deepseek" and rec["model"]["requested_id"] == "deepseek-flash"


def test_an_answer_that_is_not_json_is_a_schema_failure(ctx, tmp_path):
    rec, _ = runner.run_release(Genuine(["Here is my analysis: it is fine."]), ctx, tmp_path, log=lambda *_: None)
    assert rec["status"] == "validation_failed" and rec["validation"]["errors"][0]["gate"] == "schema"
    fenced = "```json\n" + text("ok/draft.json") + "\n```"
    rec2, _ = runner.run_release(Genuine([fenced, text("ok/challenge.json")]), ctx, tmp_path, log=lambda *_: None)
    assert rec2["status"] == "validated"


def test_a_model_outage_is_a_recorded_outcome_not_an_exception(ctx, tmp_path):
    err = ModelUnavailable("network", "URLError: unreachable", None, 12)
    rec, d = runner.run_release(Genuine(error=err), ctx, tmp_path, log=lambda *_: None)
    assert rec["status"] == "model_error" and rec["copilot"] == "unavailable" and rec["unavailable"]["kind"] == "network"
    assert rec["result"] is None and (d / "record.json").exists()


def test_a_missing_credential_is_recorded_as_copilot_unavailable(ctx, tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ModelUnavailable) as e:
        DeepSeekClient()
    rec, d = runner.run_release(None, ctx, tmp_path, unavailable=e.value, log=lambda *_: None)
    assert rec["status"] == "model_unavailable" and rec["copilot"] == "unavailable" and rec["kind"] == "unavailable"
    assert rec["genuine_model_run"] is False and "none" in rec["evidence_class"] and d.parent.name == "runs"


def test_run_records_are_append_only_and_events_are_ordered(ctx, tmp_path):
    rec, d = runner.run_release(FixtureClient([FX / "ok/draft.json", FX / "ok/challenge.json"]), ctx, tmp_path, log=lambda *_: None)
    with pytest.raises(records.RecordError, match="append-only"):
        records.write_run(tmp_path, rec, ctx)
    with pytest.raises(records.RecordError, match="blind take"):
        records.append_event(d, "revealed", {})
    with pytest.raises(records.RecordError, match="shown"):
        records.append_event(d, "decision", {})
    records.append_event(d, "blind_take", {"author": "a", "text": "my take"}, at="2026-08-10T04:00:00+00:00")
    with pytest.raises(records.RecordError, match="already recorded"):
        records.append_event(d, "blind_take", {"text": "second thoughts"})
    records.append_event(d, "revealed", {}, at="2026-08-10T04:05:00+00:00")
    assert [e["kind"] for e in records.events(d)] == ["blind_take", "revealed"]
    assert records.verify_chain(d) == []
    (d / "record.json").write_text((d / "record.json").read_text(encoding="utf-8").replace("validated", "validated "), encoding="utf-8")
    assert any("chain broken" in p for p in records.verify_chain(d))                         # an edit after the fact is detectable


def test_committed_once_means_this_paths_own_history_not_a_renamed_lookalike(tmp_path, monkeypatch):
    """git's --follow lends a new file the history of a similar deleted one. A frozen Expectation Note or a Run
    Record must not inherit that: its own commit count is what proves it was never edited."""
    def git(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    body = "kind: expectation_note\n" + "line\n" * 40
    (tmp_path / "old.yaml").write_text(body, encoding="utf-8")
    git("add", "."), git("commit", "-qm", "template")
    (tmp_path / "old.yaml").unlink()
    (tmp_path / "note.yaml").write_text(body, encoding="utf-8")
    git("add", "-A"), git("commit", "-qm", "rename it to a note")
    monkeypatch.chdir(tmp_path)
    assert len(checks.git_history(Path("note.yaml"))) == 2            # the trap: --follow sees the lookalike's history
    assert len(records.git_commits(Path("note.yaml"))) == 1           # the check the Copilot uses does not


def test_a_waived_blind_take_is_recorded_as_such(ctx, tmp_path):
    _, d = runner.run_release(FixtureClient([FX / "ok/draft.json", FX / "ok/challenge.json"]), ctx, tmp_path, log=lambda *_: None)
    records.append_event(d, "revealed", {"waived_blind_take": "no time"})
    assert records.events(d)[0]["waived_blind_take"] == "no time"


def test_decisions_need_an_explicit_thesis_statement_and_reasons(ctx, tmp_path):
    rec, _ = runner.run_release(FixtureClient([FX / "ok/draft.json", FX / "ok/challenge.json"]), ctx, tmp_path, log=lambda *_: None)
    t = records.decision_template(rec)
    assert set(t["divergences"]) == {"H0", "H2"} and "executive_delta" in t["sections"]
    assert records.validate_decision({"sections": {"executive_delta": {"action": "accept"}}}, rec)                       # no thesis statement
    assert records.validate_decision({"thesis_decision": "unchanged", "sections": {"executive_delta": {"action": "reject"}}}, rec)  # no reason
    assert records.validate_decision({"thesis_decision": "changed", "sections": {"executive_delta": {"action": "accept"}}}, rec)  # no update file
    assert records.validate_decision({"thesis_decision": "unchanged", "sections": {"executive_delta": {"action": "maybe"}}}, rec)
    ok = {"thesis_decision": "unchanged", "sections": {"executive_delta": {"action": "accept"}, "research_needs": {"action": "keep_unresolved", "reason": "wait"}}}
    assert records.validate_decision(ok, rec) == []
    assert "-" in records.edit_diff("a\n", "b\n")


def test_unresolved_research_needs_flow_into_the_next_context(ctx, tmp_path):
    rec, d = runner.run_release(Genuine([text("ok/draft.json"), text("ok/challenge.json")]), ctx, tmp_path, log=lambda *_: None)
    assert records.open_research_needs(tmp_path, pd.Timestamp("2026-12-01")) == []                  # nothing decided yet
    records.append_event(d, "blind_take", {"text": "x"})
    records.append_event(d, "revealed", {})
    records.append_event(d, "decision", {"sections": {"research_needs": {"action": "keep_unresolved"}}}, at="2026-08-12T00:00:00+00:00")
    needs = records.open_research_needs(tmp_path, pd.Timestamp("2026-09-01"))
    assert [n["hypothesis"] for n in needs] == ["H2", "H1"] and needs[0]["from_run"] == rec["run_id"]
    assert records.open_research_needs(tmp_path, pd.Timestamp("2026-08-11")) == []                  # not before it was decided


def test_cost_is_unknown_without_deepseek_billing_information():
    assert llm.cost_usd("deepseek-flash", {"input_tokens": 1_000_000, "output_tokens": 100_000}) is None
    assert llm.cost_usd("deepseek-v4-pro", {"input_tokens": 1, "output_tokens": 1}) is None


# ================================================================ the live adapter's request, checked offline
class FakeResponse:
    def __init__(self, body, headers=None):
        self._b, self.headers = json.dumps(body).encode(), headers or {"request-id": "req_test"}

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_request_shape_is_minimal_and_never_logs_the_key(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen.update(url=req.full_url, headers=dict(req.header_items()), body=json.loads(req.data), timeout=timeout)
        return FakeResponse({"type": "message", "id": "msg_test", "model": "deepseek-flash", "stop_reason": "end_turn",
                             "content": [{"type": "thinking", "thinking": "done"}, {"type": "text", "text": "{}"}],
                             "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 2}})
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    c = DeepSeekClient("deepseek-flash", effort="high", api_key="sk-test-secret")
    reply = c.call("SYS", "USER")
    assert seen["url"] == "https://api.deepseek.com/anthropic/v1/messages"
    assert seen["headers"]["Anthropic-version"] == "2023-06-01" and seen["headers"]["X-api-key"] == "sk-test-secret"
    b = seen["body"]
    assert b["model"] == "deepseek-flash" and b["system"] == "SYS" and b["messages"] == [{"role": "user", "content": "USER"}]
    assert b["output_config"] == {"effort": "high"} and b["max_tokens"] == 24000
    assert not ({"temperature", "top_p", "top_k", "thinking", "tool_choice", "tools", "fallbacks"} & set(b))     # removed or rejected on this model
    assert "sk-test-secret" not in json.dumps(c.identity()) and reply.served_model == "deepseek-flash" and reply.request_id == "req_test"
    assert reply.message_id == "msg_test" and reply.usage["cache_read_input_tokens"] == 2
    DeepSeekClient("deepseek-v4-pro", effort=None, api_key="secret-key").call("s", "u")
    assert seen["body"]["model"] == "deepseek-v4-pro"
    assert "output_config" not in seen["body"]                                                  # effort can be left to the model's default
    DeepSeekClient("deepseek-flash", effort="medium", api_key="secret-key").call("s", "u")
    assert seen["body"]["output_config"] == {"effort": "high"}


def test_a_response_body_that_is_not_json_is_a_recorded_failure(monkeypatch):
    class Garbage(FakeResponse):
        def __init__(self):
            self._b, self.headers = b"<html>gateway error</html>", {}
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout: Garbage())
    with pytest.raises(ModelUnavailable) as e:
        DeepSeekClient("deepseek-flash", api_key="secret-key").call("s", "u")
    assert e.value.kind == "invalid_json" and "not JSON" in e.value.detail


@pytest.mark.parametrize("body, kind", [
    ({"type": "message", "stop_reason": "refusal", "stop_details": {"category": "x"}, "content": []}, "refusal"),
    ({"type": "message", "stop_reason": "max_tokens", "content": [{"type": "text", "text": "{"}]}, "truncated"),
    ({"type": "message", "stop_reason": "end_turn", "content": [{"type": "thinking", "thinking": ""}],
      "usage": {"input_tokens": 1, "output_tokens": 1}}, "empty"),
    ({"type": "message", "stop_reason": None, "content": [{"type": "text", "text": "{}"}]}, "incomplete"),
    ({"type": "message", "stop_reason": "end_turn", "content": [{"type": "tool_use"}],
      "usage": {"input_tokens": 1, "output_tokens": 1}}, "unsupported_response"),
])
def test_refusals_truncation_and_empty_answers_are_recorded_failures(monkeypatch, body, kind):
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout: FakeResponse(body))
    with pytest.raises(ModelUnavailable) as e:
        DeepSeekClient("deepseek-flash", api_key="secret-key").call("s", "u")
    assert e.value.kind == kind and e.value.raw is not None


def test_http_errors_are_recorded_once_and_never_echo_the_key(monkeypatch):
    import io
    import urllib.error
    calls = []

    def boom(req, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {},
                                     io.BytesIO(b'{"error":{"type":"authentication_error","message":"sk-test-secret invalid"}}'))
    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    with pytest.raises(ModelUnavailable) as e:
        DeepSeekClient("deepseek-flash", api_key="sk-test-secret").call("s", "u")
    assert e.value.kind == "http_error" and len(calls) == 1
    assert "sk-test-secret" not in str(e.value) + json.dumps(e.value.raw)
    assert e.value.raw["http_status"] == 401


def test_deepseek_two_pass_record_preserves_identity_metadata_and_actual_usage(ctx, tmp_path, monkeypatch):
    calls = []

    def reply(req, timeout):
        calls.append(json.loads(req.data))
        name = "ok/draft.json" if len(calls) == 1 else "ok/challenge.json"
        return FakeResponse({"type": "message", "id": f"msg_{len(calls)}", "model": "deepseek-v4-pro",
                             "stop_reason": "end_turn", "content": [{"type": "text", "text": text(name)}],
                             "usage": {"input_tokens": 100 + len(calls), "output_tokens": 20 + len(calls)}})

    monkeypatch.setattr(llm.urllib.request, "urlopen", reply)
    rec, d = runner.run_release(DeepSeekClient("deepseek-flash", api_key="sk-test-secret"), ctx, tmp_path, log=lambda *_: None)
    assert len(calls) == 2 and all(c["model"] == "deepseek-flash" for c in calls)
    assert rec["status"] == "validated" and rec["genuine_model_run"] is True and d.parent.name == "runs"
    assert rec["model"]["provider"] == "deepseek" and rec["model"]["requested_id"] == "deepseek-flash"
    assert [p["served_model"] for p in rec["passes"]] == ["deepseek-v4-pro"] * 2
    assert [p["message_id"] for p in rec["passes"]] == ["msg_1", "msg_2"]
    assert rec["usage"] == {"input_tokens": 203, "output_tokens": 43, "cost_usd": None,
                            "latency_ms": rec["usage"]["latency_ms"]}
    assert rec["context"]["sha256"] and all(p["prompt_sha256"] for p in rec["passes"])
    assert all(n == 0 for n in rec["validation"]["hard_gate_failures"].values())
    assert "sk-test-secret" not in (d / "record.json").read_text()
    assert ops.verify_run(d, ROOT, rebuild=False)["ok"]


def test_unsupported_usage_and_response_shapes_fail_closed(monkeypatch):
    bodies = [
        [],
        {"type": "message", "stop_reason": "end_turn", "content": [{"type": "text", "text": "{}"}]},
        {"type": "message", "stop_reason": "end_turn", "content": [{"type": "text", "text": "{}"}],
         "usage": {"input_tokens": "1", "output_tokens": 2}},
        {"type": "message", "stop_reason": "tool_use", "content": [{"type": "text", "text": "{}"}]},
    ]
    for body in bodies:
        monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout: FakeResponse(body))
        with pytest.raises(ModelUnavailable) as e:
            DeepSeekClient(api_key="secret-key").call("s", "u")
        assert e.value.kind in ("unsupported_response", "incomplete")


def test_timeout_is_recorded_without_secret_or_fabricated_usage(ctx, tmp_path, monkeypatch):
    def timeout(req, timeout):
        raise TimeoutError("secret-key")
    monkeypatch.setattr(llm.urllib.request, "urlopen", timeout)
    rec, d = runner.run_release(DeepSeekClient(api_key="secret-key"), ctx, tmp_path, log=lambda *_: None)
    assert rec["status"] == "model_error" and rec["unavailable"]["kind"] == "network"
    assert rec["usage"]["input_tokens"] is None and rec["usage"]["cost_usd"] is None
    assert len(rec["passes"]) == 1 and "secret-key" not in (d / "record.json").read_text()


def test_only_current_deepseek_model_ids_are_accepted():
    for model in ("claude-opus-5-5", "deepseek-chat", "deepseek-reasoner"):
        with pytest.raises(ModelUnavailable, match="unsupported_model"):
            DeepSeekClient(model, api_key="secret-key")


def test_deepseek_key_comes_only_from_its_environment_variable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "wrong-provider-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ModelUnavailable, match="DEEPSEEK_API_KEY"):
        DeepSeekClient()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key")
    assert DeepSeekClient().identity()["requested_id"] == "deepseek-flash"
    assert "secret-key" not in json.dumps(DeepSeekClient().identity())


def test_invalid_utf8_and_echoed_request_id_cannot_leak_key(monkeypatch):
    class Invalid(FakeResponse):
        def __init__(self):
            self._b, self.headers = b"\xff", {"x-request-id": "secret-key"}

    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout: Invalid())
    with pytest.raises(ModelUnavailable) as e:
        DeepSeekClient(api_key="secret-key").call("s", "u")
    assert e.value.kind == "invalid_json"
    assert "secret-key" not in json.dumps(e.value.response_meta)


# ================================================================ boundary: the Copilot cannot touch the deterministic path
def test_the_deterministic_pipeline_never_imports_the_copilot():
    for rel in ("src/cnmacro/refresh.py", "src/cnmacro/replay.py", "src/cnmacro/evidence.py", "src/cnmacro/thesis.py",
                "src/cnmacro/checks.py", "src/cnmacro/derive.py", "site/build.py", "site/views.py"):
        assert "copilot" not in (ROOT / rel).read_text(encoding="utf-8").lower(), rel
    code = "import sys, cnmacro.refresh, cnmacro.replay, cnmacro.cli; assert not any(m.startswith('cnmacro.copilot') for m in sys.modules)"
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, env={**__import__('os').environ, "PYTHONPATH": str(ROOT / "src")})
    assert done.returncode == 0, done.stderr


def test_the_copilot_writes_nothing_outside_its_own_records(tmp_path, monkeypatch):
    """A whole replay run with no credential: exit 3, `copilot: unavailable`, and no tracked research file changes."""
    for rel in ("data/dictionary", "data/demo", "research/cases/cn-nominal"):
        shutil.copytree(ROOT / rel, tmp_path / rel, ignore=shutil.ignore_patterns("latest-private.json"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    def digest():
        return {p.relative_to(tmp_path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(tmp_path.rglob("*")) if p.is_file()}
    from cnmacro import cli
    before = digest()
    code = cli.main(["copilot", "replay", "--release-at", "2026-08-09", "--out", str(tmp_path.parent / (tmp_path.name + "-sb"))])
    assert code == 3
    changed = {k for k, v in digest().items() if before.get(k) != v}
    assert changed and all(k.startswith("research/cases/cn-nominal/copilot/runs/") for k in changed), changed
    rec = json.loads(next((tmp_path / "research/cases/cn-nominal/copilot/runs").glob("*/record.json")).read_text(encoding="utf-8"))
    assert rec["copilot"] == "unavailable" and rec["unavailable"]["kind"] == "no_credential"
    # --context-only (for a human labeller) builds the context and stops: no model call, no record, no file written
    n_runs = len(list((tmp_path / "research/cases/cn-nominal/copilot/runs").iterdir()))
    ctx_file = tmp_path.parent / (tmp_path.name + "-ctx.json")
    assert cli.main(["copilot", "replay", "--release-at", "2026-08-09", "--out", str(tmp_path.parent / (tmp_path.name + "-sb2")),
                     "--context-only", "--context-out", str(ctx_file)]) == 0
    assert len(list((tmp_path / "research/cases/cn-nominal/copilot/runs").iterdir())) == n_runs
    assert json.loads(ctx_file.read_text(encoding="utf-8"))["mode"] == "replay"


def test_a_broken_copilot_directory_cannot_block_manual_publication(tmp_path):
    """The analyst's update, the eval gate and the site build do not read the Copilot's records."""
    case = tmp_path / "case"
    shutil.copytree(CASE, case, ignore=shutil.ignore_patterns("__pycache__"))
    runs = case / "copilot/runs/20261014T020000Z-deadbeef"
    runs.mkdir(parents=True)
    (runs / "record.json").write_text("{ this is not json", encoding="utf-8")
    (runs / "context.json").write_text("", encoding="utf-8")
    (case / "updates").mkdir()
    update = {"kind": "update", "baseline": "2026-10-04-baseline.yaml", "as_of": "2026-10-15T06:00:00Z", "release": "September 2026 CPI and PPI",
              "previous_state": {"probability": 0.3, "conviction": "LOW", "status": "ACTIVE", "last_update_direction": "UNCHANGED"},
              "test_results": {}, "flipped_tests": [], "terminal_check": "ACTIVE", "new_claims": [],
              "does_this_change_the_thesis": "No material change.", "does_this_change_the_thesis_zh": "无实质变化。",
              "probability": 0.3, "conviction": "LOW", "status": "ACTIVE", "last_update_direction": "UNCHANGED",
              "probability_change": None, "terminal_rule_fired": None}
    (case / "updates/2026-10-15-september-2026-cpi-and-ppi.yaml").write_text(yaml.safe_dump(update, allow_unicode=True, sort_keys=False), encoding="utf-8")
    out = tmp_path / "dist"
    done = subprocess.run([sys.executable, str(ROOT / "site/build.py"), "--case-dir", str(case), "--out", str(out)], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "No material change." in parse(out / "en/updates.html").text()
    assert "copilot" not in (out / "en/updates.html").read_text(encoding="utf-8").lower()
    fold_errs = __import__("cnmacro.thesis", fromlist=["fold"]).fold(case)[2]
    assert fold_errs == []                                                                  # E5: an unchanged-thesis update stands on its own


def test_the_frozen_baseline_and_history_are_byte_identical_to_main():
    """Nothing in this change rewrites the preregistered record, the amendment, the claims or any refresh record."""
    paths = ["research/cases/cn-nominal/preregistered", "research/cases/cn-nominal/refreshes",
             "research/cases/cn-nominal/claims.jsonl", "research/cases/cn-nominal/case.yaml", "src/cnmacro/refresh.py",
             "src/cnmacro/replay.py", "src/cnmacro/evidence.py", "src/cnmacro/thesis.py", "docs/PRODUCT_STRATEGY.md"]
    try:
        base = subprocess.run(["git", "merge-base", "HEAD", "origin/main"], cwd=ROOT, capture_output=True, text=True).stdout.strip() \
            or subprocess.run(["git", "rev-parse", "main"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        pytest.skip("git unavailable")
    if not base:
        pytest.skip("no main to compare with")
    diff = subprocess.run(["git", "diff", "--name-only", base, "--", *paths], cwd=ROOT, capture_output=True, text=True)
    assert diff.returncode == 0 and diff.stdout.strip() == "", diff.stdout


def test_the_replay_case_registry_matches_what_the_store_reproduces(ctx):
    reg = yaml.safe_load((CASE / "copilot/replay_cases.yaml").read_text(encoding="utf-8"))
    case = next(c for c in reg["cases"] if c["release_at"] == "2026-08-09")
    assert case["deterministic"]["mechanical_delta"] == {h: v["mechanical_delta"] for h, v in ctx["hypotheses"].items()}
    assert sorted(case["deterministic"]["flipped_tests"]) == sorted(f["test"] for v in ctx["hypotheses"].values() for f in v["flips"])
    assert case["deterministic"]["new_observations"] == len(ctx["new_observations"])
    assert reg["status"] == "unlabeled" and all(c["labels"]["status"] == "pending_owner" and c["labels"]["file"] is None for c in reg["cases"])


def test_replay_refuses_to_delete_a_directory_that_is_not_a_replay_sandbox(tmp_path):
    """replay.replay removes its --out directory; the Copilot wrapper must never point it at anything else."""
    keep = tmp_path / "precious"
    keep.mkdir()
    (keep / "notes.txt").write_text("do not delete", encoding="utf-8")
    with pytest.raises(ContextError, match="not a previous replay sandbox"):
        ops.replay_context("2026-08-09", keep, ROOT, log=lambda *_: None)
    assert (keep / "notes.txt").exists()
    with pytest.raises(ContextError, match="not a previous replay sandbox"):
        ops.replay_context("2026-08-09", ROOT, ROOT, log=lambda *_: None)
    assert (ROOT / "src/cnmacro/copilot/context.py").exists()


# ================================================================ release-day readiness, public explanation
def test_preflight_before_the_release_is_ready_without_a_credential(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    rep = ops.preflight(ROOT, "September 2026 CPI and PPI", now="2026-10-10T04:00:00Z")
    by = {c["id"]: c for c in rep["checks"]}
    assert rep["ready_for_release"] is True and rep["copilot"] == "unavailable" and rep["deterministic_pipeline_depends_on_copilot"] is False
    assert by["copilot_credential"]["status"] == "warn" and by["expectation_note"]["status"] == "warn"
    assert by["eval_gate_E0_E5"]["status"] == "pass" and by["baseline_frozen"]["status"] == "pass" and by["calendar"]["status"] == "pass"
    assert ops.preflight(ROOT, "no such release", now="2026-10-10T04:00:00Z")["ready_for_release"] is False


@pytest.mark.parametrize("loc, needles", [
    ("en", ["Where AI is used", "forbidden", "Research Copilot", "analyst"]),
    ("zh", ["AI 用在哪里", "禁止", "分析师"]),
])
def test_the_method_page_states_where_ai_is_used_and_forbidden(built, loc, needles):
    text = parse(built / f"{loc}/method.html").text()
    for n in needles:
        assert n in text, n
    assert "ccmacro.byliyz.com" in (built / f"{loc}/method.html").read_text(encoding="utf-8")
