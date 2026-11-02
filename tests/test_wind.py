"""Wind adapter: runtime pin, pinned-code routing, strict parsing, fail-closed batches, atomic publication.

All offline. Replies are synthetic (tests/wind_support.py); no Wind credential or licensed value is involved."""
import copy
import dataclasses
import hashlib
import json
import os
import re

import pandas as pd
import pytest
from wind_support import (FAKE, KLINE_COLUMNS, ROOT, Clock, FakeWind, envelope, error_envelope, good_reply, make_skill,
                          pinned_runtime, economic_payload, kline_payload, SKILL_FILES, sha)

from cnmacro import wind
from cnmacro.store import OBS_COLUMNS, as_of, load_dictionary, load_observations


@pytest.fixture(scope="module")
def metrics():
    return load_dictionary(ROOT / "data/dictionary/metrics.yaml")


@pytest.fixture(scope="module")
def real_runtime():
    return wind.load_runtime(ROOT / "data/dictionary/wind_runtime.yaml")


@pytest.fixture
def skill(tmp_path):
    return make_skill(tmp_path)


@pytest.fixture
def runtime(real_runtime):
    return pinned_runtime(real_runtime)


@pytest.fixture
def plan(metrics, runtime):
    return wind.plan_groups(metrics, runtime)


def run(tmp_path, metrics, runtime, skill, script=None, on_call=None, clock=None, runtime_overrides=None, fake=None):
    plan = wind.plan_groups(metrics, runtime)
    fake = fake or FakeWind(plan, metrics, script, on_call)
    sleeps = []
    out = wind.run_refresh(metrics, dataclasses.replace(runtime, **(runtime_overrides or {})), root=tmp_path,
                           skill_dir=skill, transport=fake, clock=clock or Clock(), sleep=sleeps.append,
                           monotonic=lambda: 0.0)
    return out, fake, sleeps


def snapshots(tmp_path):
    d = tmp_path / "data/private/observations"
    return sorted(d.glob("*")) if d.exists() else []


def assert_nothing_published(tmp_path, out):
    assert out.status == "failed" and out.snapshot is None
    assert snapshots(tmp_path) == []                       # no snapshot, and no half-written .part either
    assert (out.run_dir / "manifest.json").exists()        # the diagnostics stay
    assert out.manifest["publication"]["status"] == "not_published" and out.rows == 0


# ---------------------------------------------------------------- the happy path and its provenance
def test_a_clean_run_publishes_one_snapshot_for_all_thirteen_series(tmp_path, metrics, runtime, skill):
    out, fake, _ = run(tmp_path, metrics, runtime, skill)
    assert out.status == "published" and out.error is None
    assert out.calls == 5 and out.metrics == 14                # 13 Wind series; the 10Y is stored month-end and daily
    snap = snapshots(tmp_path)
    assert [s.name for s in snap] == [f"wind_{out.run_id}.csv"]
    df = load_observations(tmp_path / "data/private/observations")
    assert set(df["metric_id"]) == {m.metric_id for m in wind.p0_metrics(metrics)}
    assert out.rows == len(df)
    assert list(pd.read_csv(snap[0], nrows=0).columns) == OBS_COLUMNS            # the existing Observation contract


def test_rows_use_the_existing_observation_contract(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill)
    df = load_observations(tmp_path / "data/private/observations")
    assert set(df["source"]) == {"Wind"} and set(df["source_class"]) == {"private"}
    assert (df["release_date"] == "").all() and set(df["release_date_basis"]) == {"unknown"}
    assert (df["limitation"].str.contains("retrieved_at")).all()                  # availability starts at retrieved_at
    assert (df["consensus"].isna()).all()                                           # consensus is its own metric, not a column
    codes = {m.metric_id: m.wind.code for m in wind.p0_metrics(metrics)}
    assert all(codes[r.metric_id] == r.source_code for r in df.itertuples())
    assert set(df["quality_flag"]) == {"ok"}


def test_wind_rows_are_available_only_from_their_retrieval(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill)
    df = load_observations(tmp_path / "data/private/observations")
    started = pd.Timestamp(out.manifest["started_at"]).tz_convert("UTC").tz_localize(None)
    assert as_of(df, started - pd.Timedelta(days=30)).empty                         # reference periods are older; still invisible
    assert not as_of(df, pd.Timestamp(out.manifest["completed_at"]).tz_convert("UTC").tz_localize(None)).empty


def test_each_group_gets_its_own_true_retrieval_time(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill)
    df = load_observations(tmp_path / "data/private/observations")
    per = {g["name"]: g["retrieved_at"] for g in out.manifest["groups"]}
    assert len(set(per.values())) == 5
    for g in out.manifest["groups"]:
        assert set(df[df.metric_id.isin(g["metric_ids"])]["retrieved_at"]) == {g["retrieved_at"]}


# ---------------------------------------------------------------- pinned codes, grouping, no discovery
def test_requests_use_exactly_the_pinned_codes(tmp_path, metrics, runtime, skill):
    out, fake, _ = run(tmp_path, metrics, runtime, skill)
    asked = []
    for _, _, params in fake.calls:
        asked += params["question"].split(",") if "question" in params else [params["windcode"]]
    assert sorted(asked) == sorted({m.wind.code for m in wind.p0_metrics(metrics)})
    assert len(asked) == len(set(asked)) == 13                 # a code feeding two stored views is requested once
    assert "000300.SH" in asked


def test_the_thirteen_p0_codes_are_the_reviewed_ones(metrics):
    expected = {"cn_dr007": "M1006337", "cn_cgb10y": "M0325687", "cn_loans_hh_short_flow": "M0057874",
                "cn_loans_hh_mlt_flow": "M0057875", "cn_loans_corp_short_flow": "M0057876",
                "cn_loans_corp_mlt_flow": "M0057877", "cn_hf_prop_bj": "S0203228", "cn_hf_prop_sz": "S0048279",
                "cn_hf_prop_sh": "S0146015", "cn_hf_prop_gz": "S0175476", "mkt_csi300": "000300.SH",
                "cn_cpi_consensus_wind": "M0061676", "cn_ppi_consensus_wind": "M0061677",
                "cn_cgb10y_daily": "M0325687"}                 # Phase 2: the daily view of the same 10Y series
    assert {m.metric_id: m.wind.code for m in wind.p0_metrics(metrics)} == expected
    assert len(set(expected.values())) == 13
    assert all(m.redistribution == "private_only" for m in wind.p0_metrics(metrics))


def test_a_normal_run_never_calls_a_search_tool(tmp_path, metrics, runtime, skill):
    out, fake, _ = run(tmp_path, metrics, runtime, skill)
    tools = {t for _, t, _ in fake.calls}
    assert tools == {"query_economic_indicator_data", "get_index_kline"}
    assert "search_economic_indicator" not in tools
    assert "search_economic_indicator" not in wind.ALLOWED_TOOLS


def test_the_cli_transport_refuses_a_search_call(tmp_path, skill):
    tr = wind.cli_transport(skill, 5, node="node")
    with pytest.raises(wind.WindFailure) as e:
        tr("economic_data", "search_economic_indicator", {"question": "x"}, tmp_path / "r.json")
    assert e.value.code == "WIND_FORBIDDEN_TOOL"
    assert not (tmp_path / "r.json").exists()


def test_a_dictionary_pointing_at_the_search_tool_is_rejected(metrics, runtime):
    bad = copy.deepcopy(metrics)
    bad["cn_dr007"].wind = dataclasses.replace(bad["cn_dr007"].wind, tool="search_economic_indicator")
    with pytest.raises(ValueError, match="not an allowed refresh tool"):
        wind.plan_groups(bad, runtime)


def test_five_grouped_calls_and_no_query_exceeds_ten_codes(plan, runtime):
    assert [g.name for g in plan] == ["rates", "credit", "property", "consensus", "market"]
    assert [len(g.codes) for g in plan] == [2, 4, 4, 2, 1]
    assert runtime.max_codes_per_query == 10 and all(len(g.codes) <= 10 for g in plan)
    assert sum(len(g.codes) for g in plan) == 13


def test_an_eleven_code_group_is_rejected(metrics, runtime):
    bad = copy.deepcopy(metrics)
    src = bad["cn_hf_prop_bj"]
    for i in range(7):                                         # 4 property + 7 = 11 codes in one group
        mid = f"fx_extra_{i}"
        bad[mid] = dataclasses.replace(src, metric_id=mid, wind=dataclasses.replace(src.wind, code=f"S09000{i:02d}"))
    with pytest.raises(ValueError, match="exceed the 10-code query cap"):
        wind.plan_groups(bad, runtime)


def test_the_index_route_needs_the_exact_windcode(metrics, runtime):
    bad = copy.deepcopy(metrics)
    bad["mkt_csi300"].wind = dataclasses.replace(bad["mkt_csi300"].wind, code="沪深300")
    with pytest.raises(ValueError, match="exact windcode"):
        wind.plan_groups(bad, runtime)
    group = next(g for g in wind.plan_groups(metrics, runtime) if g.name == "market")
    req = wind.build_request(group, pd.Timestamp("2026-10-10").date())
    assert req["windcode"] == "000300.SH" and req["period"] == "1d" and set(req) == {"windcode", "begin_date", "end_date", "period"}


def test_economic_requests_carry_explicit_bounded_dates(plan):
    today = pd.Timestamp("2026-10-10").date()
    for g in plan:
        req = wind.build_request(g, today)
        begin, end = (req.get("beginDate") or req["begin_date"]), (req.get("endDate") or req["end_date"])
        span = (pd.Timestamp(end) - pd.Timestamp(begin)).days
        assert 0 < span <= 520, (g.name, span)
    cons = next(g for g in plan if g.name == "consensus")
    assert wind.build_request(cons, today)["endDate"] > "2026-10-10"                # a small forward window
    rates = next(g for g in plan if g.name == "rates")
    assert wind.build_request(rates, today)["endDate"] == "2026-10-10"             # actuals never ask for the future


# ---------------------------------------------------------------- runtime pin
def test_runtime_fingerprint_matches_the_pinned_skill(skill, runtime):
    r = wind.verify_runtime(skill, runtime, "test")
    assert r.version == "9.9.9" and wind.runtime_differences(r, runtime) == []
    assert set(r.hashes) == set(SKILL_FILES) and all(len(h) == 64 for h in r.hashes.values())


def test_the_runtime_contract_pins_the_required_files(real_runtime):
    assert {"scripts/cli.mjs", "scripts/tool-manifest.json", "scripts/call-rules.json"} <= set(real_runtime.files)
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in real_runtime.files.values())


@pytest.mark.parametrize("change", ["content", "version", "missing"])
def test_drift_before_the_run_aborts_with_no_call(tmp_path, metrics, runtime, skill, change):
    cli = skill / "scripts/cli.mjs"
    if change == "content":
        (skill / "scripts/call-rules.json").write_text('{"changed": true}', encoding="utf-8")
    elif change == "version":
        cli.write_text(cli.read_text().replace("9.9.9", "9.9.10"), encoding="utf-8")
    else:
        (skill / "scripts/update-check.mjs").unlink()
    out, fake, _ = run(tmp_path, metrics, runtime, skill)
    assert out.error["code"] == "WIND_RUNTIME_DRIFT" and out.calls == 0 and fake.calls == []
    assert out.error["details"]
    assert_nothing_published(tmp_path, out)


def test_drift_during_the_run_stops_it_and_publishes_nothing(tmp_path, metrics, runtime, skill):
    def self_update(n):                                         # the skill rewrites itself after the second call
        if n == 2:
            (skill / "scripts/cli.mjs").write_text(SKILL_FILES["scripts/cli.mjs"] + "// updated\n", encoding="utf-8")
    out, fake, _ = run(tmp_path, metrics, runtime, skill, on_call=self_update)
    assert out.error["code"] == "WIND_RUNTIME_DRIFT"
    assert out.calls == 2 and len(fake.calls) == 2              # the changed skill is never run a third time
    assert out.manifest["runtime"]["unchanged"] is False
    assert_nothing_published(tmp_path, out)


def test_drift_after_the_last_call_is_caught_before_publication(tmp_path, metrics, runtime, skill):
    def late_update(n):
        if n == 5:
            (skill / "scripts/tool-manifest.json").write_text('{"tools": []}', encoding="utf-8")
    out, _, _ = run(tmp_path, metrics, runtime, skill, on_call=late_update)
    assert out.error["code"] == "WIND_RUNTIME_DRIFT" and out.calls == 5
    assert_nothing_published(tmp_path, out)


def test_the_manifest_records_both_runtime_readings(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill)
    rt = out.manifest["runtime"]
    assert rt["pre"] == rt["post"] and rt["unchanged"] is True
    assert rt["pre"]["version"] == "9.9.9" and rt["pre"]["files"] == rt["expected"]["files"]


def test_the_skill_location_can_be_overridden_locally(tmp_path, skill):
    assert wind.locate_skill_dir({"CCMACRO_WIND_SKILL_DIR": str(skill)}) == skill
    with pytest.raises(wind.WindFailure) as e:
        wind.locate_skill_dir({"CCMACRO_WIND_SKILL_DIR": str(tmp_path / "nope")})
    assert e.value.code == "WIND_SKILL_NOT_FOUND"
    installed = tmp_path / "home/.agents/skills/wind-mcp-skill"
    installed.mkdir(parents=True)
    assert wind.locate_skill_dir({}, home=tmp_path / "home") == installed         # the official install location


def test_pinning_rewrites_only_the_version_and_hashes(tmp_path, real_runtime):
    src = (ROOT / "data/dictionary/wind_runtime.yaml").read_text(encoding="utf-8")
    p = tmp_path / "wind_runtime.yaml"
    p.write_text(src, encoding="utf-8")
    new = wind.RuntimeReading("9.9.9", {rel: sha(rel) for rel in real_runtime.files})
    wind.pin_runtime(p, new)
    after = wind.load_runtime(p)
    assert after.version == "9.9.9" and after.files == {rel: sha(rel) for rel in real_runtime.files}
    assert wind.runtime_differences(new, after) == []
    changed = [l for l in p.read_text(encoding="utf-8").splitlines() if l not in src.splitlines()]
    assert len(changed) == 1 + len(real_runtime.files)         # version line + one hash per file
    assert after.groups == real_runtime.groups and after.call_budget == real_runtime.call_budget


# ---------------------------------------------------------------- operational safety
def test_network_error_is_retried_identically_and_then_succeeds(tmp_path, metrics, runtime, skill):
    out, fake, sleeps = run(tmp_path, metrics, runtime, skill, script={"credit": [error_envelope("NETWORK_ERROR")]})
    assert out.status == "published" and out.calls == 6
    credit = [c for c in fake.calls if "question" in c[2] and c[2]["question"].startswith("M0057874")]
    assert len(credit) == 2 and credit[0] == credit[1]                          # an identical retry
    g = next(g for g in out.manifest["groups"] if g["name"] == "credit")
    assert g["retries"] == 1 and [a["outcome"] for a in g["attempts"]] == ["NETWORK_ERROR", "ok"]
    assert runtime.retry_pause_s in sleeps                                      # paused before the retry


def test_network_error_exhaustion_halts_the_batch(tmp_path, metrics, runtime, skill):
    out, fake, _ = run(tmp_path, metrics, runtime, skill, script={"rates": [error_envelope("NETWORK_ERROR")] * 5})
    assert out.error["code"] == "NETWORK_ERROR" and out.error["group"] == "rates"
    assert out.calls == 3 == 1 + runtime.network_retries                         # one try and two retries, no more
    assert len(fake.calls) == 3                                                  # later groups were never called
    assert_nothing_published(tmp_path, out)


def test_a_transport_timeout_counts_as_a_network_error(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"rates": [wind.WindFailure("NETWORK_ERROR", "timeout")]})
    assert out.status == "published" and out.calls == 6


@pytest.mark.parametrize("reply,code", [
    (error_envelope("AUTH_ERROR", "bad key"), "AUTH_ERROR"),
    (error_envelope("RATE_LIMIT_ERROR"), "RATE_LIMIT_ERROR"),
    (error_envelope("backend_error", "boom"), "BACKEND_ERROR"),
    (error_envelope("PARAM_VALIDATION_ERROR", "x"), "CLI_ERROR"),
])
def test_these_errors_halt_immediately_without_a_retry(tmp_path, metrics, runtime, skill, reply, code):
    out, fake, sleeps = run(tmp_path, metrics, runtime, skill, script={"rates": [reply]})
    assert out.error["code"] == code and out.calls == 1 and len(fake.calls) == 1
    assert runtime.retry_pause_s not in sleeps
    assert_nothing_published(tmp_path, out)


def test_quota_exhaustion_is_normalized_and_halts(tmp_path, metrics, runtime, skill):
    hard = error_envelope("backend_error", "账户积分余额不足，无法完成当前操作。请提示用户先进行充值")
    out, fake, _ = run(tmp_path, metrics, runtime, skill, script={"rates": [hard]})
    assert out.error["code"] == "BLOCKED_QUOTA" and out.calls == 1
    assert_nothing_published(tmp_path, out)


def test_quota_exhaustion_is_also_caught_in_a_soft_reply(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"credit": [envelope("账户积分余额不足，请充值")]})
    assert out.error["code"] == "BLOCKED_QUOTA" and out.error["group"] == "credit"
    assert_nothing_published(tmp_path, out)


def test_calls_are_serial_and_spaced(tmp_path, metrics, runtime, skill):
    out, fake, sleeps = run(tmp_path, metrics, runtime, skill)
    assert out.calls == 5 and sleeps == [runtime.min_spacing_s] * 4              # four gaps between five calls, no retries
    assert runtime.min_spacing_s >= 4


def test_the_per_run_call_budget_is_a_hard_cap(tmp_path, metrics, runtime, skill):
    out, fake, _ = run(tmp_path, metrics, runtime, skill, runtime_overrides={"call_budget": 4})
    assert out.error["code"] == "CALL_BUDGET_EXCEEDED" and out.calls == 0 and fake.calls == []   # 5 groups > 4: refused up front
    assert_nothing_published(tmp_path, out)


def test_retries_count_against_the_budget(tmp_path, metrics, runtime, skill):
    out, fake, _ = run(tmp_path, metrics, runtime, skill, runtime_overrides={"call_budget": 5},
                       script={"rates": [error_envelope("NETWORK_ERROR")], "credit": [error_envelope("NETWORK_ERROR")]})
    assert out.error["code"] == "CALL_BUDGET_EXCEEDED" and len(fake.calls) == 5
    assert_nothing_published(tmp_path, out)


def test_the_default_budget_covers_the_five_groups_with_headroom(real_runtime):
    assert 5 < real_runtime.call_budget <= 15 and real_runtime.network_retries == 2


# ---------------------------------------------------------------- soft failures and incomplete results
def test_soft_permission_notice_is_blocked_permission(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"rates": [envelope("受限指标已剔除：无权限：M0325687,M1006337")]})
    assert out.error["code"] == "BLOCKED_PERMISSION" and out.error["details"] == ["M0325687", "M1006337"]
    assert out.calls == 1
    assert_nothing_published(tmp_path, out)


def test_a_permission_notice_beside_partial_data_still_fails_closed(tmp_path, metrics, runtime, skill, plan):
    rates = next(g for g in plan if g.name == "rates")
    partial = json.dumps({"content": [{"type": "text", "text": json.dumps(economic_payload(rates, metrics, drop={"M0325687"}))},
                                      {"type": "text", "text": "受限指标已剔除：无权限：M0325687"}], "isError": False})
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"rates": [partial]})
    assert out.error["code"] == "BLOCKED_PERMISSION"
    assert_nothing_published(tmp_path, out)


def test_soft_no_results_notice(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"property": [envelope("没有搜索到指标，S0203228")]})
    assert out.error["code"] == "NO_RESULTS" and out.error["group"] == "property"
    assert_nothing_published(tmp_path, out)


def test_an_unrecognised_text_reply_is_not_a_success(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"rates": [envelope("something went wrong, try later")]})
    assert out.error["code"] == "MALFORMED_RESULT"
    assert_nothing_published(tmp_path, out)


@pytest.mark.parametrize("reply", ["not json at all", "[1, 2, 3]", json.dumps({"content": "nope"})])
def test_garbage_output_is_malformed(tmp_path, metrics, runtime, skill, reply):
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"rates": [reply]})
    assert out.error["code"] == "MALFORMED_RESULT"
    assert_nothing_published(tmp_path, out)


def test_a_missing_requested_metric_is_never_silently_dropped(tmp_path, metrics, runtime, skill, plan):
    credit = next(g for g in plan if g.name == "credit")
    short = envelope(economic_payload(credit, metrics, drop={"M0057877"}))
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"credit": [short]})
    assert out.error["code"] == "INCOMPLETE_RESULT" and out.error["details"] == ["M0057877"]
    assert_nothing_published(tmp_path, out)


def test_the_ten_indicator_cap_notice_fails_closed_when_a_code_is_missing(tmp_path, metrics, runtime, skill, plan):
    credit = next(g for g in plan if g.name == "credit")
    payload = economic_payload(credit, metrics, drop={"M0057877"})
    payload["summary"] = "单次最多提取10个指标数据，请按主题或地区拆分，并针对未覆盖范围继续调用"
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"credit": [envelope(payload)]})
    assert out.error["code"] == "INCOMPLETE_RESULT" and "cap" in out.error["message"]
    assert_nothing_published(tmp_path, out)


def test_the_cap_notice_is_harmless_when_every_requested_code_is_present(tmp_path, metrics, runtime, skill, plan):
    credit = next(g for g in plan if g.name == "credit")
    payload = economic_payload(credit, metrics)
    payload["summary"] = "单次最多提取10个指标数据，请按主题或地区拆分，并针对未覆盖范围继续调用"
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"credit": [envelope(payload)]})
    assert out.status == "published"
    assert next(g for g in out.manifest["groups"] if g["name"] == "credit")["cap_notice"] is True


def test_an_unrequested_code_is_drift(tmp_path, metrics, runtime, skill, plan):
    rates = next(g for g in plan if g.name == "rates")
    payload = economic_payload(rates, metrics)
    stray = copy.deepcopy(payload["metrics"][0])
    stray["meta"]["code"] = "M9999999"
    payload["metrics"].append(stray)
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"rates": [envelope(payload)]})
    assert out.error["code"] == "WIND_METADATA_DRIFT" and out.error["details"] == ["M9999999"]


def test_a_series_with_no_usable_observation_is_incomplete(tmp_path, metrics, runtime, skill, plan):
    rates = next(g for g in plan if g.name == "rates")
    out, _, _ = run(tmp_path, metrics, runtime, skill,
                    script={"rates": [envelope(economic_payload(rates, metrics, values=lambda n: [None] * n))]})
    assert out.error["code"] == "INCOMPLETE_RESULT"
    assert_nothing_published(tmp_path, out)


# ---------------------------------------------------------------- metadata drift
@pytest.mark.parametrize("what,tweak", [
    ("name", lambda w, m: m.update(name=m["name"] + "（修订）") if w.code == "M1006337" else None),
    ("freq", lambda w, m: m.update(freq="周") if w.code == "M1006337" else None),
    ("unit", lambda w, m: m.update(unit="‰") if w.code == "M1006337" else None),
])
def test_metadata_drift_fails_closed(tmp_path, metrics, runtime, skill, plan, what, tweak):
    rates = next(g for g in plan if g.name == "rates")
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"rates": [envelope(economic_payload(rates, metrics, tweak=tweak))]})
    assert out.error["code"] == "WIND_METADATA_DRIFT" and out.calls == 1
    assert any(what in d and "cn_dr007" in d for d in out.error["details"])
    assert_nothing_published(tmp_path, out)


def test_a_field_that_vanishes_is_drift_too(tmp_path, metrics, runtime, skill, plan):
    rates = next(g for g in plan if g.name == "rates")
    out, _, _ = run(tmp_path, metrics, runtime, skill,
                    script={"rates": [envelope(economic_payload(rates, metrics, tweak=lambda w, m: m.pop("unit")))]})
    assert out.error["code"] == "WIND_METADATA_DRIFT"
    assert_nothing_published(tmp_path, out)


def test_known_gaps_come_from_the_dictionary_not_from_code(metrics):
    w = metrics["mkt_csi300"].wind
    assert {g["field"] for g in w.known_gaps} == {"name", "unit"} and w.expected_name is None and w.expected_unit is None
    ok = wind.Series("000300.SH", {"name": None, "freq": "D", "unit": None}, [], [])
    assert wind.metadata_differences(w, ok) == []
    now_supplied = wind.Series("000300.SH", {"name": None, "freq": "D", "unit": "点"}, [], [])
    assert wind.metadata_differences(w, now_supplied)                                # Wind began supplying a unit: review the contract
    assert metrics["cn_dr007"].wind.known_gaps == []                                  # a field with a value has no exemption


def test_kline_columns_must_still_exist(tmp_path, metrics, runtime, skill, plan):
    market = next(g for g in plan if g.name == "market")
    cols = [c for c in KLINE_COLUMNS if c != "MATCH"]
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"market": [envelope(kline_payload(market, metrics, columns=cols))]})
    assert out.error["code"] == "WIND_METADATA_DRIFT" and out.error["details"] == ["MATCH"]
    assert_nothing_published(tmp_path, out)


def test_an_empty_kline_is_no_results(tmp_path, metrics, runtime, skill, plan):
    market = next(g for g in plan if g.name == "market")
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"market": [envelope(kline_payload(market, metrics, rows=[]))]})
    assert out.error["code"] == "NO_RESULTS"
    assert_nothing_published(tmp_path, out)


# ---------------------------------------------------------------- strict normalization
def _series_for(metrics, mid, dates, values):
    w = metrics[mid].wind
    return wind.Series(w.code, {"name": w.expected_name, "freq": w.expected_freq, "unit": w.expected_unit}, dates, values)


def test_missing_values_are_dropped_not_imputed(metrics):
    rows, st = wind.observation_rows(metrics["cn_dr007"], _series_for(metrics, "cn_dr007", ["20261007", "20261008", "20261009"], [1.5, None, "INVALID"]),
                                     "2026-10-10T08:00:00+00:00")
    assert [r["reference_period"] for r in rows] == ["2026-10-07"] and st == {"rows": 1, "null_values": 2}


@pytest.mark.parametrize("dates,values", [
    (["2026-10-07"], [1.0]),                                   # not yyyyMMdd
    (["20261307"], [1.0]),                                     # impossible month
    (["20261007", "20261007"], [1.0, 2.0]),                    # duplicate reference period
    (["20261007"], ["abc"]),                                   # not numeric
    (["20261007"], [True]),                                    # boolean
])
def test_malformed_series_are_rejected(metrics, dates, values):
    s = _series_for(metrics, "cn_dr007", dates, values)
    with pytest.raises(wind.WindFailure) as e:
        wind.observation_rows(metrics["cn_dr007"], s, "2026-10-10T08:00:00+00:00")
    assert e.value.code == "MALFORMED_RESULT"


def test_misaligned_arrays_fail_closed(tmp_path, metrics, runtime, skill, plan):
    rates = next(g for g in plan if g.name == "rates")
    payload = economic_payload(rates, metrics)
    payload["metrics"][0]["value"] = payload["metrics"][0]["value"][:-1]
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"rates": [envelope(payload)]})
    assert out.error["code"] == "MALFORMED_RESULT"


def test_periods_follow_each_metrics_own_frequency(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill)
    df = load_observations(tmp_path / "data/private/observations")
    fmt = {"D": r"\d{4}-\d{2}-\d{2}", "M": r"\d{4}-\d{2}"}
    for r in df.itertuples():
        assert re.fullmatch(fmt[metrics[r.metric_id].frequency], r.reference_period), (r.metric_id, r.reference_period)


def test_values_are_stored_as_returned_never_rescaled(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill)
    df = load_observations(tmp_path / "data/private/observations")
    dr = df[df.metric_id == "cn_dr007"].sort_values("reference_period")["value"].tolist()
    assert dr == [FAKE, FAKE + 1, FAKE + 2]


def test_month_end_rule_keeps_only_completed_months(metrics):
    w = metrics["cn_cgb10y"]
    s = _series_for(metrics, "cn_cgb10y", ["20260828", "20260831", "20260929", "20260930", "20261008"], [1.0, 2.0, 3.0, 4.0, 5.0])
    rows, _ = wind.observation_rows(w, s, "2026-10-10T08:00:00+00:00")
    assert [(r["reference_period"], r["value"]) for r in rows] == [("2026-08", "2.0"), ("2026-09", "4.0")]
    assert all("last Wind observation dated within the month" in r["limitation"] for r in rows)
    assert metrics["cn_cgb10y"].frequency == "M"                                        # one analytical concept, still monthly


def test_month_end_uses_the_beijing_calendar(metrics):
    w = metrics["cn_cgb10y"]
    s = _series_for(metrics, "cn_cgb10y", ["20260929", "20260930"], [3.0, 4.0])
    after = wind.observation_rows(w, s, "2026-09-30T17:00:00+00:00")[0]                 # already 1 Oct in Beijing
    assert [r["reference_period"] for r in after] == ["2026-09"]
    with pytest.raises(wind.WindFailure) as e:                                          # 30 Sep 23:00 Beijing: September not over
        wind.observation_rows(w, s, "2026-09-30T15:00:00+00:00")
    assert e.value.code == "INCOMPLETE_RESULT"


def test_consensus_is_experimental_and_never_the_consensus_column(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill)
    df = load_observations(tmp_path / "data/private/observations")
    cons = df[df.metric_id.isin(["cn_cpi_consensus_wind", "cn_ppi_consensus_wind"])]
    assert len(cons) == 6 and cons["limitation"].str.contains("EXPERIMENTAL").all()          # 2 series x 3 target months
    assert not df[~df.metric_id.isin(["cn_cpi_consensus_wind", "cn_ppi_consensus_wind"])]["limitation"].str.contains("EXPERIMENTAL").any()
    assert df["consensus"].isna().all() and not {"cn_cpi_yoy", "cn_ppi_yoy"} & set(df.metric_id)
    for mid in ("cn_cpi_consensus_wind", "cn_ppi_consensus_wind"):
        assert metrics[mid].wind.experimental and metrics[mid].wind.evidence_use == "snapshot_only"


def test_the_four_cities_stay_separate(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill)
    df = load_observations(tmp_path / "data/private/observations")
    cities = {"cn_hf_prop_bj", "cn_hf_prop_sz", "cn_hf_prop_sh", "cn_hf_prop_gz"}
    assert set(df.metric_id) >= cities
    assert not [m for m in metrics if "tier1" in m or "tier_1" in m]                    # no synthetic aggregate
    assert all(any("never summed" in n or "Not aggregated" in n for n in metrics[c].caliber_notes) for c in cities)


# ---------------------------------------------------------------- manifest and raw provenance
def test_the_manifest_is_a_complete_private_audit_record(tmp_path, metrics, runtime, skill):
    out, fake, _ = run(tmp_path, metrics, runtime, skill)
    m = json.loads((out.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert m["run_id"] == out.run_id and m["status"] == "published" and m["error"] is None
    assert m["started_at"] < m["completed_at"] and m["runtime"]["version"] == "9.9.9" and "skill" not in m
    assert m["budget"] == {"max_calls": runtime.call_budget, "calls_made": 5}
    assert m["metrics"] == 14 and m["rows"] == out.rows
    assert m["publication"]["status"] == "published" and m["publication"]["file"] == f"data/private/observations/wind_{out.run_id}.csv"
    assert m["publication"]["sha256"] == hashlib.sha256(out.snapshot.read_bytes()).hexdigest()
    assert [g["name"] for g in m["groups"]] == ["rates", "credit", "property", "consensus", "market"]
    for g in m["groups"]:
        assert g["status"] == "ok" and g["retries"] == 0 and g["server"] and g["tool"] and g["codes"] and g["params"]
        a = g["attempts"][0]
        raw = out.run_dir / a["raw_file"]
        assert raw.exists() and hashlib.sha256(raw.read_bytes()).hexdigest() == a["raw_sha256"]
        assert a["elapsed_s"] >= 0 and a["outcome"] == "ok"
        assert sum(g["rows"].values()) > 0
    assert sum(sum(g["rows"].values()) for g in m["groups"]) == m["rows"]


def test_failed_runs_keep_their_raw_diagnostics(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"credit": [error_envelope("backend_error", "boom")]})
    m = out.manifest
    assert m["status"] == "failed" and m["error"]["code"] == "BACKEND_ERROR" and m["error"]["group"] == "credit"
    failed = next(g for g in m["groups"] if g["name"] == "credit")
    assert failed["status"] == "failed" and (out.run_dir / failed["attempts"][0]["raw_file"]).exists()
    assert [g["status"] for g in m["groups"]] == ["ok", "failed"]
    assert (out.run_dir / "requests").is_dir() and (out.run_dir / "raw").is_dir()
    assert_nothing_published(tmp_path, out)


def test_the_manifest_holds_no_observation_values(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill)
    text = (out.run_dir / "manifest.json").read_text(encoding="utf-8")
    assert not any(re.search(rf"\b{re.escape(str(FAKE + i))}\b", text) for i in range(0, 4))


# ---------------------------------------------------------------- atomic, append-only publication
def test_a_failed_run_publishes_no_observation_csv(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill, script={"market": [error_envelope("AUTH_ERROR")]})   # last group fails
    assert out.calls == 5 and out.error["code"] == "AUTH_ERROR"
    assert_nothing_published(tmp_path, out)            # four groups had already succeeded; none of it is published


def test_nothing_is_appended_until_the_whole_batch_is_validated(tmp_path, metrics, runtime, skill):
    seen = []
    def peek(n):
        seen.append(snapshots(tmp_path))
    out, _, _ = run(tmp_path, metrics, runtime, skill, on_call=peek)
    assert out.status == "published" and seen == [[]] * 5                                  # empty after every call, until the end
    assert len(snapshots(tmp_path)) == 1


def test_publication_is_atomic_if_the_rename_fails(tmp_path, metrics, runtime, skill, monkeypatch):
    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        run(tmp_path, metrics, runtime, skill)
    assert snapshots(tmp_path) == []                                                       # no snapshot and no .part left behind
    [run_dir] = list((tmp_path / "data/private/wind/runs").iterdir())
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert m["status"] == "failed" and m["error"]["code"] == "UNEXPECTED_ERROR" and (run_dir / "normalized.tmp.csv").exists()


def test_the_part_file_is_never_read_as_an_observation_file(tmp_path):
    d = tmp_path / "obs"
    d.mkdir()
    (d / ".wind_x.csv.part").write_text("metric_id\nnot,real\n", encoding="utf-8")
    assert load_observations(d).empty


def test_each_successful_run_adds_a_new_immutable_snapshot(tmp_path, metrics, runtime, skill):
    first, _, _ = run(tmp_path, metrics, runtime, skill, clock=Clock("2026-10-10T08:00:00+00:00"))
    before = {s.name: s.read_bytes() for s in snapshots(tmp_path)}
    second, _, _ = run(tmp_path, metrics, runtime, skill, clock=Clock("2026-10-11T08:00:00+00:00"))
    after = {s.name: s.read_bytes() for s in snapshots(tmp_path)}
    assert len(before) == 1 and len(after) == 2 and first.run_id != second.run_id
    assert after[f"wind_{first.run_id}.csv"] == before[f"wind_{first.run_id}.csv"]        # the earlier snapshot is untouched
    df = load_observations(tmp_path / "data/private/observations")
    assert not df.duplicated(["metric_id", "reference_period", "retrieved_at"]).any()


def test_two_runs_in_the_same_second_never_overwrite_each_other(tmp_path, metrics, runtime, skill):
    fixed = lambda: "2026-10-10T08:00:00+00:00"                                            # a frozen clock: identical run ids
    a, _, _ = run(tmp_path, metrics, runtime, skill, clock=fixed)
    b, _, _ = run(tmp_path, metrics, runtime, skill, clock=fixed)
    assert a.run_id != b.run_id and b.run_id.startswith(a.run_id)
    assert len(snapshots(tmp_path)) == 2


def test_consensus_snapshots_accumulate_one_per_retrieval(tmp_path, metrics, runtime, skill):
    run(tmp_path, metrics, runtime, skill, clock=Clock("2026-10-10T08:00:00+00:00"))
    run(tmp_path, metrics, runtime, skill, clock=Clock("2026-10-11T08:00:00+00:00"))
    df = load_observations(tmp_path / "data/private/observations")
    cpi = df[df.metric_id == "cn_cpi_consensus_wind"]
    per_period = cpi.groupby("reference_period")["retrieved_at"].nunique()
    assert (per_period == 2).all()                                                         # the same target month, two snapshots
    latest = as_of(df, "2026-10-12")
    assert (latest[latest.metric_id == "cn_cpi_consensus_wind"]["retrieved_at"].str.startswith("2026-10-11")).all()
    earlier = as_of(df, "2026-10-10T20:00:00")
    assert (earlier[earlier.metric_id == "cn_cpi_consensus_wind"]["retrieved_at"].str.startswith("2026-10-10")).all()


def test_an_existing_snapshot_is_never_overwritten(tmp_path):
    staged = tmp_path / "staged.csv"
    staged.write_text("a\n1\n", encoding="utf-8")
    out_dir = tmp_path / "obs"
    out_dir.mkdir()
    (out_dir / "wind_r1.csv").write_text("kept\n", encoding="utf-8")
    with pytest.raises(wind.WindFailure):
        wind.publish_snapshot(staged, out_dir, "r1")
    assert (out_dir / "wind_r1.csv").read_text(encoding="utf-8") == "kept\n"


# ---------------------------------------------------------------- the key never reaches this code
def test_the_adapter_never_touches_the_api_key_or_its_config():
    src = (ROOT / "src/cnmacro/wind.py").read_text(encoding="utf-8")
    assert "WIND_API_KEY" not in src and ".wind-aifinmarket" not in src and "config.json" not in src
    assert "api_key" not in src.lower()
    # the only environment variable it reads is the skill-directory override
    assert src.count("os.environ") == 1 and "getenv" not in src and wind.SKILL_DIR_ENV == "CCMACRO_WIND_SKILL_DIR"


# ---------------------------------------------------------------- one series, two stored views (V1.2 Phase 2)
def test_a_second_view_of_a_code_must_share_the_owners_query_group(metrics, runtime):
    """The Wind-specific half of the second-view rule: one request feeds both views. (Aggregate, shared metadata and
    the declaration itself are neutral and are checked when the dictionary loads.)"""
    bad = copy.deepcopy(metrics)
    bad["cn_cgb10y_daily"].wind = dataclasses.replace(bad["cn_cgb10y_daily"].wind, query_group="credit")
    with pytest.raises(ValueError, match="must share cn_cgb10y's query_group"):
        wind.plan_groups(bad, runtime)


def test_both_views_of_the_10y_come_from_one_request(tmp_path, metrics, runtime, skill):
    out, fake, _ = run(tmp_path, metrics, runtime, skill)
    rates = [p for _, _, p in fake.calls if "question" in p and "M0325687" in p["question"]]
    assert len(rates) == 1 and rates[0]["question"].split(",").count("M0325687") == 1
    df = load_observations(tmp_path / "data/private/observations")
    month_end, daily = df[df.metric_id == "cn_cgb10y"], df[df.metric_id == "cn_cgb10y_daily"]
    assert list(month_end["reference_period"]) == ["2026-08", "2026-09"]            # completed months only
    assert list(daily["reference_period"]) == ["2026-08-28", "2026-08-31", "2026-09-29", "2026-09-30", "2026-10-08"]
    assert set(daily["source_code"]) == set(month_end["source_code"]) == {"M0325687"}
    assert set(daily["retrieved_at"]) == set(month_end["retrieved_at"])


# ---------------------------------------------------------------- V1.2.1: Wind publishes through the provider-neutral core
def _routed_metrics(tmp_path, *, wind_access=None):
    """The real dictionary with cn_dr007 routed to a second provider from before the (synthetic) run, so Wind is a past route."""
    import shutil
    from provider_support import DICT_REL, ROUTED, edited, route_cn_dr007
    p = tmp_path / "metrics.yaml"
    shutil.copy(ROOT / DICT_REL, p)
    route_cn_dr007(p, activate_at="2026-10-01T00:00:00Z")
    if wind_access:
        edited(p, lambda e: e["sources"][0]["access"].update(wind_access))
    return load_dictionary(p), ROUTED


def test_a_clean_run_records_the_route_state_of_every_metric_and_publishes_no_candidates(tmp_path, metrics, runtime, skill):
    out, _, _ = run(tmp_path, metrics, runtime, skill)
    pub = out.manifest["publication"]
    assert set(pub) == {"status", "file", "rows", "sha256"} and pub["file"] == f"data/private/observations/wind_{out.run_id}.csv"
    states = out.manifest["route_states"]
    assert set(states) == {m.metric_id for m in wind.p0_metrics(metrics)}
    assert all(s["provider"] == "wind" and s["effective_at"] == "genesis" and s["series_key"] == metrics[mid].wind.code for mid, s in states.items())
    assert not (tmp_path / "data/private/candidates").exists()


def test_wind_rows_of_a_metric_routed_elsewhere_are_published_as_candidates(tmp_path, runtime, skill):
    """`refresh-private` still collects Wind, but a metric whose active route has moved on gets its Wind rows only as candidates."""
    routed, moved = _routed_metrics(tmp_path)
    out, _, _ = run(tmp_path, routed, runtime, skill)
    assert out.status == "published"
    active = load_observations(tmp_path / "data/private/observations")
    cand = load_observations(tmp_path / "data/private/candidates")
    assert moved not in set(active["metric_id"]) and set(cand["metric_id"]) == {moved}
    assert len(set(active["metric_id"])) == 13 and out.rows == len(active) + len(cand)
    pub = out.manifest["publication"]
    assert pub["candidates"]["file"] == f"data/private/candidates/wind_{out.run_id}.csv" and pub["candidates"]["rows"] == len(cand)
    assert out.manifest["route_states"][moved]["provider"] == "altprov"


def test_a_route_whose_access_is_not_permitted_is_refused_before_any_billable_call(tmp_path, runtime, skill):
    routed, _ = _routed_metrics(tmp_path, wind_access={"automated_retrieval": "unknown"})
    out, fake, _ = run(tmp_path, routed, runtime, skill)
    assert out.status == "failed" and out.error["code"] == "ACCESS_NOT_PERMITTED"
    assert fake.calls == [] and out.calls == 0                           # nothing was fetched
    assert_nothing_published(tmp_path, out)
