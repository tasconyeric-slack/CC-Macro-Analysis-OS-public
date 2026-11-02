"""The V1.2.1 provider-neutral core: the route model, point-in-time `route_at`, the route filter that runs BEFORE
`as_of`, the access policy, and the shared normalization layer. Synthetic providers only (tests/provider_support.py)."""
import copy
import re
import shutil
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import pytest
import yaml
from provider_support import (ALT, DICT_REL, ROUTED, access, alt_route, append_activation, edited, entry, read, route_cn_dr007,
                              route_metric, wind_route_for, write)
from signal_support import PRICE_UP, ROOT, WHEN, Scenario, frame, public_results, series_key

from cnmacro import checks, normalize, store
from cnmacro.claims import load_claims
from cnmacro.signals import compute_signals, load_signal_contract
from cnmacro.store import (GENESIS, OBS_COLUMNS, as_of, load_dictionary, load_observations, route_at,
                           route_change_at)

E = "2026-10-12T00:00:00Z"                      # the activation time used throughout
REAL = ROOT / DICT_REL


@pytest.fixture(scope="module")
def real():
    return load_dictionary(REAL)


@pytest.fixture
def path(tmp_path) -> Path:
    p = tmp_path / "metrics.yaml"
    shutil.copy(REAL, p)
    return p


@pytest.fixture
def routed(path):
    """cn_dr007 on Wind from genesis and on `altprov` from E."""
    route_cn_dr007(path, activate_at=E)
    return load_dictionary(path)


# ---------------------------------------------------------------- the model and the Wind compatibility shim
def test_every_wind_metric_is_routed_through_the_synthesized_genesis_route_and_no_other_metric_is(real):
    wind = [m for m in real.values() if m.wind is not None]
    assert len(wind) == 14 and all(m.routed for m in wind)
    for m in wind:
        assert [(r.provider, r.series_key, r.equivalence, r.validation) for r in m.sources] == [("wind", m.wind.code, "EXACT", "PASSED")]
        assert [(c.effective_at, c.active) for c in m.route_history] == [(GENESIS, "wind")]
        assert route_at(m, "2026-10-12").provider == "wind"
        assert m.sources[0].access.permits("automated_retrieval") and not m.sources[0].access.permits("manual_import")
    others = [m for m in real.values() if m.wind is None]
    assert others and all(not m.routed and m.sources == [] and m.route_history == [] and route_at(m, "2026-10-12") is None for m in others)


def test_a_wind_metric_may_declare_explicit_sources_beside_its_wind_contract(routed):
    m = routed[ROUTED]
    assert [r.provider for r in m.sources] == ["wind", ALT] and m.sources[1].collect
    assert [(c.effective_at, c.active) for c in m.route_history] == [(GENESIS, "wind"), (E, ALT)]


def test_a_unquoted_yaml_timestamp_is_read_as_utc(path):
    route_cn_dr007(path)
    raw = read(path)
    entry(raw)["route_history"].append({"effective_at": "@@", "active": ALT, "decision": "x"})
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True).replace("'@@'", "2026-10-12T00:00:00Z"), encoding="utf-8")
    assert load_dictionary(path)[ROUTED].route_history[-1].effective_at == E


# ---------------------------------------------------------------- route_at: exactly one active route at every T
def test_route_at_is_a_function_of_time_and_genesis_sorts_before_everything(routed):
    m = routed[ROUTED]
    assert route_at(m, "1900-01-01").provider == "wind"
    assert route_at(m, "2026-10-11T23:59:59Z").provider == "wind"
    assert route_at(m, E).provider == ALT                              # effective_at <= T: the record applies from E itself
    assert route_at(m, "2026-10-12T00:00:00").provider == ALT          # naive input is UTC
    assert route_at(m, "2026-10-12T08:00:00+08:00").provider == ALT   # 08:00 Beijing is exactly E (00:00 UTC)
    assert route_at(m, "2026-10-12T07:59:59+08:00").provider == "wind"  # one second earlier
    assert route_at(m, "2099-01-01").provider == ALT
    assert route_change_at(m, "2026-10-11").effective_at == GENESIS and route_change_at(m, "2026-10-13").effective_at == E


def test_exactly_one_route_is_active_and_nothing_falls_back(path):
    route_cn_dr007(path, activate_at=E)
    raw = read(path)
    entry(raw)["sources"].append(alt_route(series_key="THIRD:cn_dr007", provider="thirdprov") | {"provider": "thirdprov"})
    write(path, raw)
    m = load_dictionary(path)[ROUTED]
    seen = {route_at(m, t).provider for t in ("1900-01-01", "2026-10-11", E, "2026-12-01", "2099-01-01")}
    assert seen == {"wind", ALT}                                       # a declared, collected route that no record names is never active
    assert route_at(m, "2099-01-01").provider == ALT                   # and a stale or missing day never changes the answer


@pytest.mark.parametrize("mutate, match", [
    (lambda e: e["route_history"].__setitem__(0, {"effective_at": "2026-01-01T00:00:00Z", "active": "wind"}), "begin with a `genesis`|must begin with"),
    (lambda e: e["route_history"].append({"effective_at": "2026-10-11T00:00:00Z", "active": "wind"}), "strictly later"),
    (lambda e: e["route_history"].append({"effective_at": E, "active": "wind"}), "strictly later"),
    (lambda e: e["route_history"].append({"effective_at": "2026-11-01T00:00:00Z", "active": "nowhere"}), "undeclared route"),
    (lambda e: e["route_history"].append({"effective_at": "genesis", "active": "wind"}), "only the first record may be `genesis`"),
    (lambda e: e["route_history"].append({"effective_at": "2026-11-01", "active": "wind"}), "not a UTC ISO timestamp"),
    (lambda e: e["sources"][1].update(equivalence="APPROXIMATE"), "needs EXACT or FUNCTIONALLY_EQUIVALENT"),
    (lambda e: e["sources"][1].update(equivalence="UNKNOWN"), "needs EXACT or FUNCTIONALLY_EQUIVALENT"),
    (lambda e: e["sources"][1].update(equivalence="NOT_EQUIVALENT"), "needs EXACT or FUNCTIONALLY_EQUIVALENT"),
    (lambda e: e["sources"][1].update(equivalence_basis=""), "needs EXACT or FUNCTIONALLY_EQUIVALENT"),
    (lambda e: e["sources"][1].update(validation="PENDING"), "needs PASSED"),
    (lambda e: e["sources"][1].update(validation="FAILED"), "needs PASSED"),
    (lambda e: e["sources"][1].update(validation_basis=""), "needs PASSED"),
    (lambda e: e["sources"][1].update(equivalence="MAYBE"), "equivalence 'MAYBE'"),
    (lambda e: e["sources"][1].update(provider="Alt_Prov"), r"must match \[a-z0-9-\]\+"),
    (lambda e: e["sources"].append(alt_route()), "declared twice"),
    (lambda e: e["sources"][1]["access"].update(basis=""), "access.basis"),
    (lambda e: e["sources"][1]["access"].update(private_use="maybe"), "access.private_use"),
    (lambda e: e["sources"][1].pop("access"), "needs an `access` block"),
    (lambda e: e.pop("route_history"), "route_history must begin with"),
    (lambda e: e["sources"].pop(0), "must list the wind route"),
])
def test_the_loader_rejects_a_route_model_that_breaks_the_rules(path, mutate, match):
    route_cn_dr007(path, activate_at=E)
    edited(path, mutate)
    with pytest.raises(ValueError, match=match):
        load_dictionary(path)


def test_a_route_that_is_only_a_candidate_may_be_unvalidated_approximate_or_unpermitted(path):
    """The gates bind only the routes a history record names; a candidate can be anything until a record names it."""
    route_cn_dr007(path, alt=alt_route(equivalence="APPROXIMATE", validation="PENDING", equivalence_basis="", validation_basis="",
                                       access=access("unknown", "unknown", "unknown")))
    m = load_dictionary(path)[ROUTED]
    assert route_at(m, "2099-01-01").provider == "wind"


def test_route_history_without_sources_or_a_wind_contract_is_rejected(path):
    raw = read(path)
    e = entry(raw, "cn_ppi_yoy")                                        # a public metric: no wind:, no sources:
    e["route_history"] = [{"effective_at": "genesis", "active": "wind"}]
    write(path, raw)
    with pytest.raises(ValueError, match="route_history without sources"):
        load_dictionary(path)


def test_a_series_belongs_to_one_metric_unless_a_second_view_is_declared(path):
    raw = read(path)
    entry(raw, "cn_dr007")["sources"] = [wind_route_for(entry(raw, "cn_dr007")), alt_route()]
    entry(raw, "cn_dr007")["route_history"] = [{"effective_at": "genesis", "active": "wind"}]
    other = entry(raw, "cn_loans_hh_short_flow")
    other["sources"] = [wind_route_for(other), alt_route("cn_dr007") | {"series_key": "ALTPROV:cn_dr007"}]
    other["route_history"] = [{"effective_at": "genesis", "active": "wind"}]
    write(path, raw)
    with pytest.raises(ValueError, match="one analytical concept per series"):
        load_dictionary(path)


# ---------------------------------------------------------------- activation is an event, not a schedule
def test_an_activation_dated_after_now_is_rejected(path):
    """A future-dated record would make the LAST record differ from route_at(metric, now): G3 and G5 would gate the wrong route."""
    route_cn_dr007(path, activate_at="2027-03-01T00:00:00Z")                  # after the suite's pinned "now" (2026-12-31)
    with pytest.raises(ValueError, match="in the future; an activation is an event"):
        load_dictionary(path)


def test_the_acceptance_moment_is_exact_and_timezone_aware(path):
    route_cn_dr007(path, activate_at=E)
    assert load_dictionary(path, now=E)[ROUTED].route_history[-1].effective_at == E          # dated exactly now: accepted
    assert load_dictionary(path, now="2026-10-12T00:00:01Z")[ROUTED]
    with pytest.raises(ValueError, match="in the future"):
        load_dictionary(path, now="2026-10-11T23:59:59Z")
    with pytest.raises(ValueError, match="in the future"):
        load_dictionary(path, now="2026-10-12T07:59:59+08:00")                               # one second before E in Beijing time
    assert load_dictionary(path, now="2026-10-12T08:00:00+08:00")[ROUTED]


def test_a_genesis_only_history_never_depends_on_the_clock(path):
    route_cn_dr007(path)
    assert load_dictionary(path, now="1999-01-01T00:00:00Z")[ROUTED]


def test_the_last_record_is_the_route_in_force_now(real, path):
    """What makes the G3 and G5 gates about the right route: with no future-dated record, route_at(now) is the last record."""
    now = store.now_utc()
    for m in real.values():
        if m.routed:
            assert route_at(m, now).provider == m.route_history[-1].active
    route_cn_dr007(path, activate_at=E)
    append_activation(path, "2026-11-01T00:00:00Z", active="wind", decision="reviewed change 2")
    append_activation(path, "2026-11-20T00:00:00Z", active=ALT, decision="reviewed change 3")
    m = load_dictionary(path)[ROUTED]
    assert [c.active for c in m.route_history] == ["wind", ALT, "wind", ALT]
    assert route_at(m, now).provider == m.route_history[-1].active == ALT
    assert route_at(m, "2026-11-10").provider == "wind"                                       # and earlier instants still resolve as of then


def test_the_default_clock_is_the_wall_clock(path, monkeypatch):
    monkeypatch.undo()                                                                        # drop the suite's pinned clock
    assert store.now_utc() > pd.Timestamp("2026-01-01")
    route_cn_dr007(path, activate_at="2099-01-01T00:00:00Z")
    with pytest.raises(ValueError, match="in the future"):
        load_dictionary(path)
    route_cn_dr007(path, activate_at="2026-01-02T00:00:00Z")                                  # long before the real now
    assert load_dictionary(path)[ROUTED].route_history[-1].effective_at == "2026-01-02T00:00:00Z"


@pytest.mark.parametrize("decision", [None, "", "   "])
def test_every_activation_record_must_cite_its_decision(path, decision):
    route_cn_dr007(path)
    extra = {} if decision is None else {"decision": decision}
    edited(path, lambda e: e["route_history"].append({"effective_at": E, "active": ALT, **extra}))
    with pytest.raises(ValueError, match=r"route_history\[1\]: decision .* is required"):
        load_dictionary(path)


def test_the_genesis_record_needs_no_decision_but_an_activation_with_one_loads(real, path):
    assert real[ROUTED].route_history[0].decision == ""                 # the compatibility shim writes none
    route_cn_dr007(path, activate_at=E)
    assert load_dictionary(path)[ROUTED].route_history[1].decision == "synthetic reviewed change"


# ---------------------------------------------------------------- the static route contract is provider-neutral
def _raw_route(path, fn, metric_id=ROUTED, *, alt=None):
    """cn_dr007 (or another Wind metric) with an explicit Wind route and an `altprov` candidate; then `fn(entry, alt route)`."""
    route_metric(path, metric_id, alt=alt)
    edited(path, lambda e: fn(e, e["sources"][1]), metric_id)


FREQ_GAPS = [{"field": "name", "reason": "x"}, {"field": "unit", "reason": "x"}]


@pytest.mark.parametrize("name, fn, match", [
    ("month_end on a daily metric",
     lambda e, r: r.update(aggregate="month_end", expected={"name": "n", "freq": "D", "unit": "u"}, known_gaps=[]),
     r"altprov: month_end aggregation needs metric frequency M and provider frequency D \(metric is D"),
    ("month_end whose provider is not daily",
     lambda e, r: (e.update(frequency="M"), r.update(aggregate="month_end", expected={"name": "n", "freq": "M", "unit": "u"}, known_gaps=[])),
     r"altprov: month_end aggregation needs metric frequency M and provider frequency D \(metric is M, expected.freq is M"),
    ("month_end with the provider frequency undeclared",
     lambda e, r: (e.update(frequency="M"), r.update(aggregate="month_end", expected={"name": "n", "unit": "u"},
                                                     known_gaps=[{"field": "freq", "reason": "not supplied"}])),
     r"altprov: month_end aggregation needs .*expected.freq is None"),
    ("a different frequency with no aggregation",
     lambda e, r: r.update(expected={"name": "n", "freq": "M", "unit": "u"}, known_gaps=[]),
     r"altprov: provider frequency M differs from metric frequency D with no aggregation"),
    ("a frequency outside the provider vocabulary",
     lambda e, r: r.update(expected={"name": "n", "freq": "X", "unit": "u"}, known_gaps=[]), r"expected.freq 'X' is not one of"),
    ("an unknown aggregate", lambda e, r: r.update(aggregate="week_end"), r"aggregate 'week_end' not in"),
    ("metadata missing and not declared a gap",
     lambda e, r: r.update(expected={"freq": "D"}, known_gaps=[{"field": "unit", "reason": "x"}]),
     r"altprov: no expected.name and no known_gap for it"),
    ("metadata both pinned and declared a gap",
     lambda e, r: r.update(expected={"name": "n", "freq": "D", "unit": "u"}, known_gaps=[{"field": "unit", "reason": "x"}]),
     r"altprov: expected.unit is set but also listed as a known gap"),
    ("a gap with no reason",
     lambda e, r: r.update(known_gaps=[*r["known_gaps"][:2], {"field": "unit", "reason": " "}]), r"known_gaps entries need exactly"),
    ("a gap for an unknown field",
     lambda e, r: r.update(known_gaps=[*r["known_gaps"], {"field": "colour", "reason": "x"}]), r"known_gaps entries need exactly"),
    ("a gap declared twice",
     lambda e, r: r.update(known_gaps=[*r["known_gaps"], r["known_gaps"][0]]), r"known_gap for name is declared twice"),
    ("an unknown expected key", lambda e, r: r.update(expected={"colour": "red"}), r"expected.colour is not one of"),
])
def test_an_internally_inconsistent_route_cannot_load(path, name, fn, match):
    _raw_route(path, fn)
    with pytest.raises(ValueError, match=match):
        load_dictionary(path)


def test_a_consistent_second_provider_route_loads_with_its_own_unit_vocabulary_and_gaps(path):
    """The provider's raw unit label is its own: only presence (or a declared gap) is required, never equality with the canonical unit."""
    canonical = load_dictionary(REAL)[ROUTED].unit
    _raw_route(path, lambda e, r: r.update(expected={"name": "DR007 (provider)", "freq": "D", "unit": "per cent per annum"}, known_gaps=[]))
    m = load_dictionary(path)[ROUTED]
    assert m.sources[1].expected["unit"] == "per cent per annum" and m.sources[1].expected["unit"] != canonical
    _raw_route(path, lambda e, r: r.update(expected={"freq": "D"}, known_gaps=FREQ_GAPS))
    assert load_dictionary(path)[ROUTED].sources[1].known_gaps == FREQ_GAPS                     # declared gaps load


def test_month_end_is_checked_for_any_provider_not_only_wind(path):
    """cn_cgb10y is monthly: a second provider's month-end view of a daily series is consistent; a monthly one is not."""
    ok = alt_route("cn_cgb10y", aggregate="month_end", expected={"name": "n", "freq": "D", "unit": "u"}, known_gaps=[])
    route_metric(path, "cn_cgb10y", alt=ok)
    assert load_dictionary(path)["cn_cgb10y"].sources[1].aggregate == "month_end"
    bad = alt_route("cn_cgb10y", expected={"name": "n", "freq": "D", "unit": "u"}, known_gaps=[])          # no aggregate, D on an M metric
    route_metric(path, "cn_cgb10y", alt=bad)
    with pytest.raises(ValueError, match=r"altprov: provider frequency D differs from metric frequency M"):
        load_dictionary(path)


def test_the_wind_shim_is_held_to_the_same_neutral_rules(path):
    raw = read(path)
    entry(raw, "mkt_csi300")["wind"]["known_gaps"] = []                                          # it pins no name or unit and declares no gap
    write(path, raw)
    with pytest.raises(ValueError, match=r"wind: no expected.name and no known_gap for it"):
        load_dictionary(path)
    raw = read(path)
    e = entry(raw, "cn_dr007")
    e["wind"]["known_gaps"] = [{"field": "name", "reason": "x"}]                                 # pinned AND declared a gap
    e["wind"]["expected_freq"] = "M"                                                             # and a frequency the metric does not have
    write(path, raw)
    with pytest.raises(ValueError) as err:
        load_dictionary(path)
    assert "wind: expected.name is set but also listed as a known gap" in str(err.value)
    assert "wind: provider frequency M differs from metric frequency D" in str(err.value)


def _second_view_dictionary(path, fn):
    raw = read(path)
    fn(raw, entry(raw, "cn_cgb10y"), entry(raw, "cn_cgb10y_daily"))
    write(path, raw)


@pytest.mark.parametrize("name, fn, match", [
    ("a shared series with no declared second view",
     lambda raw, own, view: view["wind"].update(same_series_as=None), r"one analytical concept per series"),
    ("a second view that names itself",
     lambda raw, own, view: view["wind"].update(same_series_as="cn_cgb10y_daily"), r"same_series_as names the metric itself"),
    ("a second view of a metric that does not exist",
     lambda raw, own, view: view["wind"].update(same_series_as="cn_nowhere"), r"must be a routed metric with a wind route"),
    ("a second view of an unrouted metric",
     lambda raw, own, view: view["wind"].update(same_series_as="cn_ppi_yoy"), r"must be a routed metric with a wind route"),
    ("a second view of a metric with another series",
     lambda raw, own, view: view["wind"].update(same_series_as="cn_dr007"), r"its wind route is series M1006337, not M0325687"),
    ("a second view with the same aggregate as its owner",
     lambda raw, own, view: (view["wind"].update(aggregate="month_end"), view.update(frequency="M")),
     r"a second view of M0325687 needs a different aggregate from cn_cgb10y"),
    ("a second view with provider metadata of its own",
     lambda raw, own, view: view["wind"].update(expected_unit="bp"), r"shares the owner's provider metadata"),
    ("an owner declared after its second view",
     lambda raw, own, view: raw["metrics"].insert(raw["metrics"].index(own), raw["metrics"].pop(raw["metrics"].index(view))),
     r"must come before this metric"),
])
def test_a_second_view_of_a_series_must_be_a_sane_pair(path, name, fn, match):
    _second_view_dictionary(path, fn)
    with pytest.raises(ValueError, match=match):
        load_dictionary(path)


def test_a_second_view_cannot_chain_through_another_second_view(path):
    def add_third(raw, own, view):
        third = copy.deepcopy(view)
        third.update(metric_id="cn_cgb10y_third", name="third view")
        third["wind"] = {**third["wind"], "same_series_as": "cn_cgb10y_daily", "aggregate": "month_end"}
        third["frequency"] = "M"
        raw["metrics"].append(third)
    _second_view_dictionary(path, add_third)
    with pytest.raises(ValueError, match=r"which is itself a second view; name the owner"):
        load_dictionary(path)


def test_the_real_pair_of_views_is_a_sane_pair(real):
    own, view = real["cn_cgb10y"], real["cn_cgb10y_daily"]
    assert view.sources[0].same_series_as == "cn_cgb10y" and own.sources[0].series_key == view.sources[0].series_key
    assert (own.sources[0].aggregate, view.sources[0].aggregate) == ("month_end", None) and own.sources[0].expected == view.sources[0].expected


# ---------------------------------------------------------------- the frozen docs say what the code does
def test_the_provider_docs_record_that_the_core_is_built_and_what_is_still_deferred():
    design = (ROOT / "docs/provider/provider-independence-design.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs/provider/v1.2.1-implementation-plan.md").read_text(encoding="utf-8")
    assert "PROPOSAL, not implemented" not in design and "No provider code is implemented" not in plan
    head = design[: design.index("## 0. Target shape")]
    assert "provider-neutral core is IMPLEMENTED" in head and "NOT" in head                       # adapters and activations are still not built
    assert "provider-neutral\n> core (Order of work, step 2) is IMPLEMENTED" in plan and "no route is activated" in plan
    status = design[design.index("## 19. Implementation status"):]
    for must in ("Activation is an event, never a schedule", "identity is frozen", "whole recorded route", "provider-neutral",
                 "NO_PROVIDER_SELECTED", "F-POLICY", "Nothing in the core blocks the adapters"):
        assert must in status, must


# ---------------------------------------------------------------- the access policy fails closed
@pytest.mark.parametrize("mode", ["automated_retrieval", "manual_import"])
@pytest.mark.parametrize("status", ["unknown", "prohibited"])
def test_an_adapter_is_refused_before_any_work_unless_the_mode_is_permitted(real, mode, status):
    route = copy.deepcopy(real[ROUTED].sources[0])
    setattr(route.access, mode, "permitted")
    setattr(route.access, "private_use", "permitted")
    normalize.require_access(route, mode)                                # explicitly permitted: fine
    setattr(route.access, mode, status)
    with pytest.raises(normalize.ProviderFailure) as e:
        normalize.require_access(route, mode)
    assert e.value.code == "ACCESS_NOT_PERMITTED" and mode in e.value.detail


def test_storing_values_at_all_needs_private_use_permitted(real):
    route = copy.deepcopy(real[ROUTED].sources[0])
    route.access.private_use = "unknown"
    with pytest.raises(normalize.ProviderFailure, match="private_use"):
        normalize.require_access(route, "automated_retrieval")


@pytest.mark.parametrize("change, match", [
    ({"private_use": "unknown"}, "private_use"),
    ({"private_use": "prohibited"}, "private_use"),
    ({"automated_retrieval": "unknown", "manual_import": "unknown"}, "neither automated_retrieval nor manual_import"),
    ({"automated_retrieval": "prohibited", "manual_import": "prohibited"}, "neither automated_retrieval nor manual_import"),
])
def test_a_route_cannot_be_the_active_route_without_permitted_access(path, change, match):
    route_cn_dr007(path, activate_at=E, alt=alt_route())
    edited(path, lambda e: e["sources"][1]["access"].update(change))
    with pytest.raises(ValueError, match=match):
        load_dictionary(path)
    # the same route is fine as a candidate: nothing names it yet
    route_cn_dr007(path, alt=alt_route())
    edited(path, lambda e: e["sources"][1]["access"].update(change))
    assert load_dictionary(path)[ROUTED]


def test_a_public_metric_needs_redistribution_permitted_on_its_active_route(path):
    route_cn_dr007(path)
    edited(path, lambda e: e.update(redistribution="public"))
    with pytest.raises(ValueError, match="redistribution: permitted"):
        load_dictionary(path)
    edited(path, lambda e: e["sources"][0]["access"].update(redistribution="permitted"))
    assert load_dictionary(path)[ROUTED].redistribution == "public"
    edited(path, lambda e: e.update(redistribution="unclear"))
    with pytest.raises(ValueError, match="private_only unless"):
        load_dictionary(path)


# ---------------------------------------------------------------- routed-metric scope
def _public_frame():
    return load_observations(ROOT / "data/demo/observations")


def test_public_metrics_are_untouched_by_routing(real):
    obs = _public_frame()
    assert not obs.empty and not any(real[m].routed for m in set(obs["metric_id"]) if m in real)
    for when in ("2024-01-01", "2026-06-30T12:00:00Z", "2026-10-06T00:00:00Z", "2099-01-01"):
        pd.testing.assert_frame_equal(normalize.select_active(obs, real, when), obs)
        pd.testing.assert_frame_equal(normalize.as_of_routed(obs, real, when), as_of(obs, when))


def test_the_public_eval_gate_gives_the_same_result_with_and_without_the_route_filter(real, monkeypatch):
    obs, case = _public_frame(), ROOT / "research/cases/cn-nominal"
    claims = load_claims(case / "claims.jsonl")
    with_filter = checks.run_all(obs, real, claims, case, public_only=True)
    monkeypatch.setattr(checks, "as_of_routed", lambda df, metrics, when: as_of(df, when))   # the behaviour before routing
    without = checks.run_all(obs, real, claims, case, public_only=True)
    assert [asdict(c) for c in with_filter] == [asdict(c) for c in without]


def test_a_signal_input_must_be_routed_and_every_route_its_history_names_must_pass_the_gates(real, tmp_path):
    contract = ROOT / "data/dictionary/private_signals.yaml"
    raw = yaml.safe_load(contract.read_text(encoding="utf-8"))
    {s["signal_id"]: s for s in raw["signals"]}["C1_property_city_momentum"]["inputs"]["metrics"].update(bj="cn_ppi_yoy")
    p = tmp_path / "private_signals.yaml"
    p.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="not a private routed metric"):
        load_signal_contract(p, real)
    load_signal_contract(contract, real)                                 # the real contract: every input is routed


# ---------------------------------------------------------------- the route filter runs BEFORE as_of
def _key(provider, metric_id):
    """A series key for any metric: the pinned Wind code where there is one, otherwise a made-up key."""
    try:
        return series_key(provider, metric_id)
    except AttributeError:
        return f"{provider.upper()}:{metric_id}"


def _two_providers(metric_id=ROUTED, wind_at="2026-10-10T07:59:00+00:00", alt_at="2026-10-11T07:59:00+00:00"):
    """The same periods from two providers; the inactive one is retrieved LATER."""
    rows = []
    for provider, label, at, value in (("wind", "Wind", wind_at, 1.0), (ALT, ALT, alt_at, 9.0)):
        for day in ("2026-10-07", "2026-10-08", "2026-10-09"):
            r = {c: "" for c in OBS_COLUMNS}
            r.update(metric_id=metric_id, reference_period=day, value=value, release_date_basis="unknown", retrieved_at=at,
                     source=label, source_code=_key(provider, metric_id), source_class="private", quality_flag="ok",
                     limitation="synthetic", _file=f"data/private/observations/{provider}_x.csv")
            rows.append(r)
    df = pd.DataFrame(rows, columns=OBS_COLUMNS + ["_file"])
    df["value"] = pd.to_numeric(df["value"])
    return df


def test_a_later_retrieved_inactive_provider_cannot_displace_the_active_one(routed):
    df, t = _two_providers(), "2026-10-11T12:00:00Z"                    # before E: Wind is active
    assert set(as_of(df, t)["value"]) == {9.0}                          # the hazard: as_of alone keeps the LATEST retrieved row
    got = normalize.as_of_routed(df, routed, t)
    assert set(got["value"]) == {1.0} and set(got["source"]) == {"Wind"} and len(got) == 3     # one provider, no holes


def test_after_activation_the_filter_selects_the_new_provider_and_its_earlier_candidate_history(routed):
    df = _two_providers(alt_at="2026-10-08T07:59:00+00:00")             # the alternative was retrieved BEFORE Wind
    before = normalize.as_of_routed(df, routed, "2026-10-11T12:00:00Z")
    after = normalize.as_of_routed(df, routed, "2026-10-13T12:00:00Z")
    assert set(before["source"]) == {"Wind"}
    assert set(after["source"]) == {ALT} and len(after) == 3            # its T1 rows are history now, and no Wind row is mixed in


def test_the_filter_keys_on_the_series_key_as_well_as_the_provider(routed):
    df = _two_providers()
    df.loc[df["source"] == "Wind", "source_code"] = "SOMETHING-ELSE"    # Wind rows, but not the pinned series
    assert normalize.select_active(df, routed, "2026-10-11T12:00:00Z").empty


def test_the_filter_touches_only_routed_metrics(routed):
    df = pd.concat([_two_providers(), _two_providers("cn_loans_hh_short_flow"), _two_providers("cn_ppi_yoy")], ignore_index=True)
    got = normalize.select_active(df, routed, "2026-10-13T12:00:00Z")
    by = {m: set(g["source"]) for m, g in got.groupby("metric_id")}
    assert by[ROUTED] == {ALT}                                          # routed to the alternative from E
    assert by["cn_loans_hh_short_flow"] == {"Wind"}                     # routed to Wind only: the other provider's rows are dropped
    assert by["cn_ppi_yoy"] == {"Wind", ALT}                            # a public metric: every row passes untouched


# ---------------------------------------------------------------- a provider swap does not change what a signal means
def test_identical_observations_from_two_providers_give_identical_signals(real, path):
    contract = load_signal_contract(ROOT / "data/dictionary/private_signals.yaml", real)
    route_cn_dr007(path, activate_at="2026-10-09T00:00:00Z")           # the alternative is authoritative at WHEN
    swapped = load_dictionary(path)
    same = dict(dr007=(1.9, 1.7), dr007_n=40, cgb_change_bp=None, csi_return_pct=None, hh=None, corp=None, cities={}, consensus=False)
    wind_frame = frame(Scenario(**same))
    alt_frame = frame(Scenario(provider=ALT, file=f"{ALT}_SYNTHETIC1", **same))
    assert list(wind_frame["value"]) == list(alt_frame["value"])        # the same numbers, only the provider differs
    a = compute_signals(normalize.as_of_routed(wind_frame, real, WHEN), real, contract, WHEN, public_results(PRICE_UP))
    b = compute_signals(normalize.as_of_routed(alt_frame, swapped, WHEN), swapped, contract, WHEN, public_results(PRICE_UP))
    a1, b1 = a[0], b[0]
    assert a1.signal_id == b1.signal_id == "A1_dr007_liquidity_trend" and a1.status == b1.status != "INSUFFICIENT_DATA"
    assert (a1.numeric_components, a1.components, a1.definition_sha256) == (b1.numeric_components, b1.components, b1.definition_sha256)
    assert [re.sub(r"#\w+$", "", i) for i in a1.input_observation_ids] == [re.sub(r"#\w+$", "", i) for i in b1.input_observation_ids]
    assert a1.input_observation_ids != b1.input_observation_ids         # they differ only in the file stems


# ---------------------------------------------------------------- the shared normalization layer
def _row(real, period="2026-10-09", at="2026-10-10T08:00:00+00:00", provider="wind", label="Wind", metric=ROUTED):
    m = real[metric]
    return normalize.observation_row(m, period, 1.5, at, source=label, series_key=series_key(provider, metric), limitation="synthetic")


def test_validate_rows_checks_the_batch_against_the_route(real):
    assert normalize.validate_rows([_row(real)], real, "wind", "Wind") == []
    assert any("source is not Wind" in e for e in normalize.validate_rows([_row(real, label="wind")], real, "wind", "Wind"))
    assert any("source_code" in e for e in normalize.validate_rows([_row(real) | {"source_code": "X"}], real, "wind", "Wind"))
    assert any("source_class" in e for e in normalize.validate_rows([_row(real) | {"source_class": "public"}], real, "wind", "Wind"))
    assert any("release date" in e for e in normalize.validate_rows([_row(real) | {"release_date": "2026-10-09"}], real, "wind", "Wind"))
    assert any("duplicate" in e for e in normalize.validate_rows([_row(real), _row(real)], real, "wind", "Wind"))
    assert any("period" in e for e in normalize.validate_rows([_row(real, period="2026-10")], real, "wind", "Wind"))
    assert any("no route for provider" in e for e in normalize.validate_rows([_row(real)], real, ALT))
    assert any("not in the dictionary" in e for e in normalize.validate_rows([_row(real) | {"metric_id": "nope"}], real, "wind", "Wind"))


def test_the_row_builder_takes_source_class_from_the_metric_not_the_provider_name(real):
    assert _row(real)["source_class"] == "private" and _row(real)["release_date"] == ""
    assert list(_row(real)) == OBS_COLUMNS


def _daily(*days):
    return [(d, float(i)) for i, d in enumerate(days, 1)]


def test_the_month_end_rule_keeps_only_completed_months():
    pts = _daily("20260828", "20260831", "20260929", "20260930", "20261008")
    emitted, skipped = normalize.month_end_points(pts, "2026-10-10T08:00:00+00:00")
    assert [(a, b, c) for a, b, c in emitted] == [("20260801", "20260831", 2.0), ("20260901", "20260930", 4.0)] and skipped == []


def test_the_month_end_coverage_guard_refuses_a_truncated_batch():
    """A download that stops mid-month must not store an earlier day as that month's month-end."""
    truncated = _daily("20260810", "20260828")                           # August is 'complete' by the calendar, but the batch ends on 28 Aug
    emitted, skipped = normalize.month_end_points(truncated, "2026-10-10T08:00:00+00:00")
    assert emitted == [] and skipped == ["202608"]
    # a later month in the batch proves the batch extends past August
    ok, _ = normalize.month_end_points(truncated + [("20260915", 9.0)], "2026-10-10T08:00:00+00:00")
    assert [(a, b) for a, b, _ in ok] == [("20260801", "20260828")]
    # an adapter whose response is complete through a date can say so (an API request window; a file cannot)
    ok, skipped = normalize.month_end_points(truncated, "2026-10-10T08:00:00+00:00", covered_through="20261010")
    assert [a for a, _, _ in ok] == ["20260801"] and skipped == []
    again, skipped = normalize.month_end_points(truncated, "2026-10-10T08:00:00+00:00", covered_through="20260828")
    assert again == [] and skipped == ["202608"]                         # complete only through the 28th: still not August


def test_the_month_end_rule_uses_the_beijing_calendar():
    pts = _daily("20260929", "20260930")
    assert [a for a, _, _ in normalize.month_end_points(pts, "2026-09-30T17:00:00+00:00", covered_through="20261001")[0]] == ["20260901"]
    assert normalize.month_end_points(pts, "2026-09-30T15:00:00+00:00", covered_through="20260930") == ([], [])


def test_metadata_drift_is_detected_and_a_known_gap_must_stay_a_gap():
    expected = {"name": "DR007", "freq": "D", "unit": None}
    assert normalize.metadata_differences(expected, {"name": "DR007", "freq": "D", "unit": None}) == []
    assert len(normalize.metadata_differences(expected, {"name": "other", "freq": "D", "unit": None})) == 1
    assert "known gap" in normalize.metadata_differences(expected, {"name": "DR007", "freq": "D", "unit": "%"})[0]


def test_publish_splits_rows_by_the_route_active_at_publication_time(routed, tmp_path):
    wind_row, alt_row = _row(routed), _row(routed, provider=ALT, label=ALT)
    before = normalize.publish([wind_row, alt_row], routed, ALT, "r1", root=tmp_path, stage_dir=_stage(tmp_path),
                               at="2026-10-11T08:00:00+00:00", started_at="2026-10-10T07:00:00+00:00")
    assert before["observations"]["rows"] == 1 and before["candidates"]["rows"] == 1      # Wind is active before E
    assert before["observations"]["file"] == "data/private/observations/altprov_r1.csv"
    assert before["candidates"]["file"] == "data/private/candidates/altprov_r1.csv"
    assert before["route_states"][ROUTED] == {"provider": "wind", "series_key": series_key("wind", ROUTED), "effective_at": GENESIS}
    obs = pd.read_csv(tmp_path / before["observations"]["file"], dtype=str)
    cand = pd.read_csv(tmp_path / before["candidates"]["file"], dtype=str)
    assert set(obs["source"]) == {"Wind"} and set(cand["source"]) == {ALT}


def _stage(tmp_path):
    d = tmp_path / "stage"
    d.mkdir(exist_ok=True)
    return d


def test_a_publication_with_no_active_row_writes_only_a_candidates_file(routed, tmp_path):
    out = normalize.publish([_row(routed, provider=ALT, label=ALT)], routed, ALT, "r2", root=tmp_path, stage_dir=_stage(tmp_path),
                            at="2026-10-11T08:00:00+00:00", started_at="2026-10-10T07:00:00+00:00")
    assert out["observations"] is None and out["candidates"]["rows"] == 1
    assert not (tmp_path / "data/private/observations").exists()


def test_a_row_published_as_active_must_have_been_retrieved_inside_the_runs_own_window(routed, tmp_path):
    backdated = _row(routed, at="2026-10-01T08:00:00+00:00")             # retrieved before this run started
    with pytest.raises(normalize.ProviderFailure) as e:
        normalize.publish([backdated], routed, "wind", "r3", root=tmp_path, stage_dir=_stage(tmp_path),
                          at="2026-10-11T08:00:00+00:00", started_at="2026-10-10T07:00:00+00:00")
    assert e.value.code == "ROUTE_BACKFILL_AFTER_ACTIVATION" and not (tmp_path / "data/private/observations").exists()
    # the same back-dated row is accepted into candidates/ (its route was never active)
    cand = _row(routed, provider=ALT, label=ALT, at="2026-10-01T08:00:00+00:00")
    out = normalize.publish([cand], routed, ALT, "r4", root=tmp_path, stage_dir=_stage(tmp_path),
                            at="2026-10-11T08:00:00+00:00", started_at="2026-10-10T07:00:00+00:00")
    assert out["candidates"]["rows"] == 1


def test_a_publication_is_never_overwritten(routed, tmp_path):
    kw = dict(root=tmp_path, stage_dir=_stage(tmp_path), at="2026-10-11T08:00:00+00:00", started_at="2026-10-10T07:00:00+00:00")
    normalize.publish([_row(routed)], routed, "wind", "r5", **kw)
    first = (tmp_path / "data/private/observations/wind_r5.csv").read_bytes()
    with pytest.raises(normalize.ProviderFailure, match="append-only"):
        normalize.publish([_row(routed, period="2026-10-08")], routed, "wind", "r5", **kw)
    assert (tmp_path / "data/private/observations/wind_r5.csv").read_bytes() == first
