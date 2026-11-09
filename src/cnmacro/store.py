"""Metric dictionary and observation store.

Observations are append-only rows. Each pull appends rows with its own
`retrieved_at`, so the store doubles as a forward vintage record.

A *routed* metric (one with a `wind:` contract or an explicit `sources:` list) also carries provider
routes and an append-only route history; `route_at` says which route is authoritative at a time T.
Public metrics without either are never routed and none of this applies to them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import yaml

if TYPE_CHECKING:
    from .wind import WindContract

OBS_COLUMNS = [
    "metric_id",
    "reference_period",   # 2026-08 | 2026Q3 | 2026-09-30
    "value",
    "release_date",       # ISO date or datetime when the market learned it; empty if unknown
    "release_date_basis",  # official_calendar | source_field | unknown
    "retrieved_at",       # ISO datetime of our pull (forward vintage capture)
    "source",             # NBS | PBOC | GACC | FRED | Wind | manual
    "source_code",        # e.g. FRED series id or Wind EDB code; empty if none
    "source_class",       # public | private
    "consensus",          # optional
    "quality_flag",       # ok | revised | caliber_break | suspect
    "limitation",         # free text, required when release_date is unknown
]
REQUIRED = ["metric_id", "reference_period", "value", "retrieved_at", "source", "source_class"]
SOURCE_CLASSES = {"public", "private"}
FREQ_PANDAS = {"M": "M", "Q": "Q", "D": "D"}
# core + diagnostic are the budgeted public thesis evidence. `supplemental` is private research
# diagnostics: outside that budget, and never an automatic input to a preregistered terminal rule.
TIERS = ("core", "diagnostic", "supplemental")

# ---------------------------------------------------------------- provider routes (docs/provider/provider-independence-design.md)
GENESIS = "genesis"                      # the first route-history record: before every timestamp
PROVIDER_KEY = re.compile(r"^[a-z0-9-]+$")   # "_" separates provider and run id in publication file names
EQUIVALENCES = ("EXACT", "FUNCTIONALLY_EQUIVALENT", "APPROXIMATE", "NOT_EQUIVALENT", "UNKNOWN")
ACTIVATABLE = ("EXACT", "FUNCTIONALLY_EQUIVALENT")       # the only equivalences a history record may name
VALIDATIONS = ("PENDING", "PASSED", "FAILED")
PERMISSIONS = ("permitted", "unknown", "prohibited")      # `unknown` fails closed everywhere
AGGREGATES = (None, "month_end")
PROVIDER_FREQS = ("D", "W", "M", "Q", "A")                # a provider's own frequency vocabulary
EXPECTED_FIELDS = ("name", "freq", "unit")                # the metadata a route pins, or declares a known gap for


@dataclass
class AccessPolicy:
    """What we may do with a route. Not evidence of equivalence; the two are never mixed."""
    automated_retrieval: str          # network fetch by an adapter
    manual_import: str                # a human-saved producer file parsed locally
    private_use: str                  # storing and using the values privately at all
    redistribution: str               # only ever relevant to a public metric
    basis: str                        # terms page and date read, or the recorded human decision

    def permits(self, what: str) -> bool:
        """True only for an explicit `permitted`; `unknown` is treated as prohibited."""
        return getattr(self, what) == "permitted"


@dataclass
class SourceRoute:
    """One declared way of delivering a routed metric. The provider never defines what the metric means."""
    provider: str                     # adapter key, [a-z0-9-]
    series_key: str                   # stable provider-native identifier (EDB code, ts_code, ...); never a URL
    equivalence: str                  # SEMANTIC ONLY: EXACT | FUNCTIONALLY_EQUIVALENT | APPROXIMATE | NOT_EQUIVALENT | UNKNOWN
    access: AccessPolicy              # required: there is no default permission
    equivalence_basis: str = ""       # the semantic evidence: method identity, identity transformation, overlap
    validation: str = "PENDING"       # activation validation: PENDING | PASSED | FAILED
    validation_basis: str = ""        # the candidate-period comparison, no values
    collect: bool = False             # collect this route in parallel while it is not active (a candidate)
    aggregate: str | None = None      # month_end: this view is the last observation of each completed month
    same_series_as: str | None = None  # one fetch feeds two views of the same series
    expected: dict = field(default_factory=dict)       # {name, freq, unit}; drift fails closed
    known_gaps: list[dict] = field(default_factory=list)
    params: dict = field(default_factory=dict)         # adapter-specific; never read by the core


@dataclass
class RouteChange:
    """One immutable route-history record."""
    effective_at: str                 # "genesis", or a UTC ISO timestamp
    active: str                       # provider key of a declared route
    decision: str = ""                # the reviewed change this record rests on


@dataclass
class Metric:
    metric_id: str
    name: str
    tier: str                 # core | diagnostic | supplemental
    frequency: str            # M | Q | D
    unit: str
    transform: str            # level | yoy | mom | cumulative_level | cumulative_yoy | rate
    hypotheses: list[str]
    role: str                 # the one-line reason this metric is in the budget
    source_primary: str
    source_code: str | None = None
    source_fallback: str | None = None
    release: str | None = None
    caliber_notes: list[str] = field(default_factory=list)
    name_zh: str | None = None
    role_zh: str | None = None
    redistribution: str = "unclear"   # public | private_only | unclear
    jan_feb_combined: bool = False    # NBS/MOF publish January-February as one release; no single Jan/Feb values
    wind: WindContract | None = None  # pinned Wind route; filled only from the capability spike, never guessed
    sources: list[SourceRoute] = field(default_factory=list)          # declared routes (routed metrics only)
    route_history: list[RouteChange] = field(default_factory=list)    # append-only; first record is `genesis`

    category: str | None = None       # public portal grouping; validated by the site build

    @property
    def routed(self) -> bool:
        return bool(self.sources)


def load_dictionary(path: str | Path, *, now=None) -> dict[str, Metric]:
    """Load and validate the dictionary. `now` (default: the wall clock) is the moment a route-history record is
    accepted: no activation may be dated after it (see _validate_routes)."""
    at = utc_naive(now) if now is not None else now_utc()
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    metrics = {}
    for m in raw["metrics"]:
        m = dict(m)
        if isinstance(m.get("wind"), dict):
            from .wind import WindContract
            m["wind"] = WindContract(**m["wind"])
        m["sources"] = [_route(m.get("metric_id"), r) for r in m.get("sources") or []]
        m["route_history"] = [_change(c) for c in m.get("route_history") or []]
        metric = Metric(**m)
        if metric.metric_id in metrics:
            raise ValueError(f"duplicate metric_id {metric.metric_id}")
        if metric.tier not in TIERS:
            raise ValueError(f"{metric.metric_id}: tier '{metric.tier}' not in {TIERS}")
        if metric.wind is not None:
            from .wind import check_wind_enums
            check_wind_enums(metric)
        _build_routes(metric, at)
        metrics[metric.metric_id] = metric
    _check_series_keys(metrics)
    return metrics


def _route(metric_id: str, raw: dict) -> SourceRoute:
    raw = dict(raw)
    access = raw.pop("access", None)
    if not isinstance(access, dict):
        raise ValueError(f"{metric_id}: every source needs an `access` block; there is no default permission")
    return SourceRoute(access=AccessPolicy(**access), **raw)


def _change(raw: dict) -> RouteChange:
    raw = dict(raw)
    at = raw.get("effective_at")
    if isinstance(at, datetime):                      # an unquoted YAML timestamp
        if at.tzinfo is None:
            raise ValueError(f"route_history effective_at {at} has no timezone; write UTC ('...Z')")
        raw["effective_at"] = at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return RouteChange(**raw)


def _wind_route(m: Metric) -> SourceRoute:
    """The compatibility shim: today's `wind:` block, read as the incumbent route. Same behaviour as before."""
    w = m.wind
    return SourceRoute(
        provider="wind", series_key=w.code, equivalence="EXACT",
        equivalence_basis="incumbent: the canonical definition was pinned on this route (Phase 1)",
        validation="PASSED", validation_basis="incumbent",
        access=AccessPolicy(automated_retrieval="permitted", manual_import="prohibited", private_use="permitted",
                            redistribution="prohibited",
                            basis="the researcher's own Wind subscription; docs/wind-capability-note.md"),
        aggregate=w.aggregate, same_series_as=w.same_series_as,
        expected={k: v for k, v in (("name", w.expected_name), ("freq", w.expected_freq), ("unit", w.expected_unit)) if v is not None},
        known_gaps=list(w.known_gaps), params={"wind": True})


def _build_routes(m: Metric, now: pd.Timestamp) -> None:
    """Routing exists only for a metric with a `wind:` contract or explicit `sources:`; others are untouched."""
    if m.wind is None and not m.sources:
        if m.route_history:
            raise ValueError(f"{m.metric_id}: route_history without sources")
        return
    if not m.sources:                                  # wind: only -> the synthesized genesis route and history
        m.sources = [_wind_route(m)]
        m.route_history = [RouteChange(GENESIS, "wind")]
    elif m.wind is not None:
        wind = next((r for r in m.sources if r.provider == "wind"), None)
        if wind is None or wind.series_key != m.wind.code:
            raise ValueError(f"{m.metric_id}: has a wind: contract, so `sources` must list the wind route with series_key {m.wind.code}")
        first = m.route_history[0] if m.route_history else None
        if first is None or (first.effective_at, first.active) != (GENESIS, "wind"):
            raise ValueError(f"{m.metric_id}: with a wind: contract, route_history must begin with {{effective_at: genesis, active: wind}}")
    _validate_routes(m, now)


def _timestamp(value: str) -> pd.Timestamp:
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        raise ValueError("no timezone")
    return t.tz_convert("UTC").tz_localize(None)


def _route_contract_errors(m: Metric, r: SourceRoute) -> list[str]:
    """The provider-neutral static rules of one declared route (docs/provider/provider-independence-design.md §8):
    its frequency fits the metric, and the metadata it pins is complete or declared as a known gap. Raw provider unit
    labels are deliberately NOT compared with the canonical unit: an adapter maps its own vocabulary."""
    if not isinstance(r.expected, dict) or not isinstance(r.known_gaps, list):
        return [f"{r.provider}: `expected` must be a mapping and `known_gaps` a list"]
    errs = []
    if r.aggregate not in AGGREGATES:
        errs.append(f"{r.provider}: aggregate '{r.aggregate}' not in {AGGREGATES}")
    for k in sorted(set(r.expected) - set(EXPECTED_FIELDS)):
        errs.append(f"{r.provider}: expected.{k} is not one of {EXPECTED_FIELDS}")
    gaps: set[str] = set()
    for g in r.known_gaps:
        if (not isinstance(g, dict) or set(g) != {"field", "reason"} or g["field"] not in EXPECTED_FIELDS
                or not str(g["reason"]).strip()):
            errs.append(f"{r.provider}: known_gaps entries need exactly `field` (one of {EXPECTED_FIELDS}) and a `reason`")
        elif g["field"] in gaps:
            errs.append(f"{r.provider}: known_gap for {g['field']} is declared twice")
        else:
            gaps.add(g["field"])
    for f in EXPECTED_FIELDS:
        has = r.expected.get(f) not in (None, "")
        if not has and f not in gaps:
            errs.append(f"{r.provider}: no expected.{f} and no known_gap for it; metadata the provider does not supply must be declared")
        if has and f in gaps:
            errs.append(f"{r.provider}: expected.{f} is set but also listed as a known gap")
    freq = r.expected.get("freq")
    if freq is not None and freq not in PROVIDER_FREQS:
        errs.append(f"{r.provider}: expected.freq '{freq}' is not one of {PROVIDER_FREQS}")
    if r.aggregate == "month_end":                       # D -> M is the only aggregation: both ends must be pinned
        if m.frequency != "M" or freq != "D":
            errs.append(f"{r.provider}: month_end aggregation needs metric frequency M and provider frequency D "
                        f"(metric is {m.frequency}, expected.freq is {freq})")
    elif freq in PROVIDER_FREQS and freq != m.frequency:
        errs.append(f"{r.provider}: provider frequency {freq} differs from metric frequency {m.frequency} with no aggregation")
    return errs


def _validate_routes(m: Metric, now: pd.Timestamp) -> None:
    """The single-file rules of the route model: shape, order, the static route contract, and the activation gates
    G1, G2, G3 and G5. What this cannot show is that the history was never edited between commits: that is audited
    across versions (checks.route_history_integrity), not here.

    Activation is an event, not a schedule: a non-genesis record may not be dated after `now`, and it must cite its
    decision. So the last record is always in force, and it is the route that is active now (G3, G5)."""
    errs, by = [], {}
    for r in m.sources:
        if not isinstance(r.provider, str) or not PROVIDER_KEY.match(r.provider):
            errs.append(f"provider '{r.provider}' must match [a-z0-9-]+")
        if r.provider in by:
            errs.append(f"provider {r.provider} is declared twice")
        by[r.provider] = r
        if not isinstance(r.series_key, str) or not r.series_key.strip():
            errs.append(f"{r.provider}: series_key is required")
        if r.equivalence not in EQUIVALENCES:
            errs.append(f"{r.provider}: equivalence '{r.equivalence}' not in {EQUIVALENCES}")
        if r.validation not in VALIDATIONS:
            errs.append(f"{r.provider}: validation '{r.validation}' not in {VALIDATIONS}")
        for what in ("automated_retrieval", "manual_import", "private_use", "redistribution"):
            if getattr(r.access, what) not in PERMISSIONS:
                errs.append(f"{r.provider}: access.{what} '{getattr(r.access, what)}' not in {PERMISSIONS}")
        if not str(r.access.basis).strip():
            errs.append(f"{r.provider}: access.basis (the terms read, or the recorded decision) is required")
        errs += _route_contract_errors(m, r)
    h = m.route_history
    if not h:
        errs.append("route_history is empty; its first record must be {effective_at: genesis}")
    else:
        if h[0].effective_at != GENESIS:
            errs.append("route_history must begin with a `genesis` record")
        prev = None
        for i, c in enumerate(h):
            if c.active not in by:
                errs.append(f"route_history[{i}] names undeclared route '{c.active}'")
            if i == 0:
                continue
            if c.effective_at == GENESIS:
                errs.append(f"route_history[{i}]: only the first record may be `genesis`")
                continue
            if not str(c.decision or "").strip():
                errs.append(f"route_history[{i}]: decision (the reviewed change this record rests on) is required")
            try:
                t = _timestamp(c.effective_at)
            except (ValueError, TypeError):
                errs.append(f"route_history[{i}]: effective_at '{c.effective_at}' is not a UTC ISO timestamp")
                continue
            if t > now:
                errs.append(f"route_history[{i}]: effective_at {c.effective_at} is in the future; an activation is an event "
                            "recorded when it takes effect, never a scheduled switch")
            if prev is not None and t <= prev:
                errs.append(f"route_history[{i}]: effective_at must be strictly later than the previous record")
            prev = t
        for name in dict.fromkeys(c.active for c in h):          # G1 and G2, for every route a record names
            r = by.get(name)
            if r is None:
                continue
            if r.equivalence not in ACTIVATABLE or not r.equivalence_basis.strip():
                errs.append(f"{name}: named in route_history but equivalence is {r.equivalence} "
                            f"(needs EXACT or FUNCTIONALLY_EQUIVALENT, with an equivalence_basis)")
            if r.validation != "PASSED" or not r.validation_basis.strip():
                errs.append(f"{name}: named in route_history but validation is {r.validation} "
                            f"(needs PASSED, with a validation_basis)")
        active = by.get(h[-1].active)         # G3 and G5, for the route active now: no record is future-dated, so the last one
        if active is not None:                # is in force, and it equals route_at(metric, now)
            if not active.access.permits("private_use"):
                errs.append(f"{active.provider}: active route has access.private_use {active.access.private_use}; it must be permitted")
            if not (active.access.permits("automated_retrieval") or active.access.permits("manual_import")):
                errs.append(f"{active.provider}: active route permits neither automated_retrieval nor manual_import")
            if m.redistribution == "public":
                if not active.access.permits("redistribution"):
                    errs.append(f"{active.provider}: a public metric needs access.redistribution: permitted on its active route")
            elif m.redistribution != "private_only":
                errs.append(f"redistribution is '{m.redistribution}'; a routed metric is private_only unless a written decision makes it public")
    if errs:
        raise ValueError(f"{m.metric_id}: route model errors:\n  - " + "\n  - ".join(errs))


def _check_series_keys(metrics: dict[str, Metric]) -> None:
    """One (provider, series_key) is one analytical concept, except an explicit `same_series_as` pair: one fetch
    feeding two views of the same provider series. The later metric names the earlier one (the owner), the owner is
    not itself a second view, the two routes share provider, series_key and provider metadata, and the views differ
    in `aggregate` (otherwise they would be the same view twice)."""
    order = {mid: i for i, mid in enumerate(metrics)}
    owner: dict[tuple[str, str], tuple[str, SourceRoute]] = {}
    errs = []
    for m in metrics.values():
        for r in m.sources:
            key = (r.provider, r.series_key)
            if key in owner:
                other_id, _ = owner[key]
                if r.same_series_as != other_id:
                    errs.append(f"{m.metric_id}: {r.provider} series {r.series_key} is already routed for {other_id}; "
                                "one analytical concept per series (declare same_series_as for a second view)")
            else:
                owner[key] = (m.metric_id, r)
            if r.same_series_as is None:
                continue
            who, o = f"{m.metric_id}/{r.provider}", metrics.get(r.same_series_as)
            theirs = None if o is None else next((x for x in o.sources if x.provider == r.provider), None)
            if r.same_series_as == m.metric_id:
                errs.append(f"{who}: same_series_as names the metric itself")
            elif o is None or theirs is None:
                errs.append(f"{who}: same_series_as {r.same_series_as} must be a routed metric with a {r.provider} route")
            elif theirs.series_key != r.series_key:
                errs.append(f"{who}: same_series_as {r.same_series_as}, but its {r.provider} route is series {theirs.series_key}, not {r.series_key}")
            elif order[r.same_series_as] > order[m.metric_id]:
                errs.append(f"{who}: same_series_as {r.same_series_as} must come before this metric (the owner is declared first)")
            elif theirs.same_series_as is not None:
                errs.append(f"{who}: same_series_as {r.same_series_as}, which is itself a second view; name the owner")
            elif r.aggregate == theirs.aggregate:
                errs.append(f"{who}: a second view of {r.series_key} needs a different aggregate from {r.same_series_as}")
            elif r.expected != theirs.expected:
                errs.append(f"{who}: a second view of {r.series_key} shares the owner's provider metadata (expected)")
    if errs:
        raise ValueError("route model errors:\n  - " + "\n  - ".join(errs))


def route_change_at(metric: Metric, at) -> RouteChange | None:
    """The route-history record in force at `at` (naive input is UTC); None for a metric that is not routed."""
    if not metric.route_history:
        return None
    t = utc_naive(at)
    current = metric.route_history[0]                    # `genesis` sorts before every timestamp
    for c in metric.route_history[1:]:
        if utc_naive(c.effective_at) <= t:
            current = c
    return current


def route_at(metric: Metric, at) -> SourceRoute | None:
    """The one route that is authoritative for `metric` at `at`; None for a metric that is not routed.
    There is no fallback: the answer changes only when a reviewed record is appended to the history."""
    change = route_change_at(metric, at)
    return None if change is None else next(r for r in metric.sources if r.provider == change.active)


def eligible_signal_input(m: Metric) -> bool:
    """A private signal input is private_only and routed, and every route its history names is semantically
    EXACT/FE and validated: the engine needs the economic semantics, never a particular provider."""
    named = {c.active for c in m.route_history}
    return (m.redistribution == "private_only" and m.routed
            and all(r.equivalence in ACTIVATABLE and r.validation == "PASSED" for r in m.sources if r.provider in named))


def read_observation_file(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df["_file"] = str(path)
    return df


def _combine(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=OBS_COLUMNS + ["_file"])
    df = pd.concat(frames, ignore_index=True)
    for c in OBS_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["consensus"] = pd.to_numeric(df["consensus"], errors="coerce")
    return df


def load_observations(*dirs: str | Path) -> pd.DataFrame:
    """Load every observations CSV in the given directories."""
    frames = []
    for d in dirs:
        d = Path(d)
        if not d.exists():
            continue
        frames += [read_observation_file(f) for f in sorted(d.glob("*.csv"))]
    return _combine(frames)


def load_observation_files(files: list[str | Path]) -> pd.DataFrame:
    """Load exactly these observation files (the verified private publications), in the given order."""
    return _combine([read_observation_file(f) for f in files])


RELEASE_TZ = "Asia/Shanghai"
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def utc_naive(value) -> pd.Timestamp:
    """All comparisons happen in naive UTC. Aware values are converted; naive datetimes are taken as UTC."""
    t = pd.Timestamp(value)
    return t.tz_convert("UTC").tz_localize(None) if t.tzinfo is not None else t


def now_utc() -> pd.Timestamp:
    """The wall clock, naive UTC. The loader reads it in exactly one place: the acceptance check on route-history
    records. A record that passes can never fail later, so replay is unaffected. Tests pin it."""
    return utc_naive(datetime.now(timezone.utc))


def release_time(value) -> pd.Timestamp:
    """A date-only official release date means some time that Beijing day: taken as the end of the day."""
    s = str(value).strip()
    if DATE_ONLY.match(s):
        end = pd.Timestamp(s, tz=RELEASE_TZ) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        return utc_naive(end)
    return utc_naive(s)


def available_at(row) -> pd.Timestamp:
    """When this observation could first have been known to us.

    Private (licensed) observations are available only from our own retrieval time, whatever
    their reference period or any nominal release date: a provider's current-vintage history
    pulled today was not in our information set yesterday. Public observations use the
    official release date if known, otherwise our retrieval time (conservative: we never claim
    to have known something earlier than we can prove).
    """
    if row.get("source_class") == "private":
        return utc_naive(row["retrieved_at"])
    if row["release_date"]:
        return release_time(row["release_date"])
    return utc_naive(row["retrieved_at"])


def as_of(df: pd.DataFrame, when: str | pd.Timestamp) -> pd.DataFrame:
    """Information set at `when` (naive input is UTC): rows already available, latest vintage per point."""
    when = utc_naive(when)
    if df.empty:
        return df
    av = df.apply(available_at, axis=1)
    got = pd.to_datetime(df["retrieved_at"], utc=True).dt.tz_localize(None)
    # Must be released by `when`; if we pulled it before `when`, prefer vintages we actually held.
    sub = df[av <= when].copy()
    sub["_got"] = got[av <= when]
    held = sub[sub["_got"] <= when]
    base = held if not held.empty else sub
    base = base.sort_values("_got")
    return base.drop_duplicates(["metric_id", "reference_period"], keep="last").drop(columns="_got")


def to_period(s: str, freq: str) -> pd.Period:
    return pd.Period(s, freq=FREQ_PANDAS[freq])


def series(df: pd.DataFrame, metric_id: str, freq: str) -> pd.Series:
    """Latest-vintage series for one metric, indexed by pandas Period."""
    sub = df[df["metric_id"] == metric_id]
    if sub.empty:
        return pd.Series(dtype=float)
    sub = sub.sort_values("retrieved_at").drop_duplicates("reference_period", keep="last")
    idx = [to_period(p, freq) for p in sub["reference_period"]]
    return pd.Series(sub["value"].values, index=pd.PeriodIndex(idx), name=metric_id).sort_index()
