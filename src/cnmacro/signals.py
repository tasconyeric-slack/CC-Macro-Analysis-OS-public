"""Private research diagnostics (V1.2 Phase 2): deterministic signals over an as-of information set.

Contract: data/dictionary/private_signals.yaml, frozen from docs/specs/v1.2-phase2-research-contract.md;
binding to this code: docs/specs/v1.2-phase2-binding.md.

    atomic      A1 DR007 trend · A2 10Y pricing · B1/B2 credit pulses · C1 city momentum · C2 breadth
                D1 market regime · X1 consensus snapshot (experimental, no values used)
    assessment  R1 domestic demand · R2 policy transmission · R3 market confirmation · R4 H0 flag

Everything here is a pure function of (observation frame, dictionary, contract, as-of time, public test
results). Nothing is fetched, fitted, imputed or written, and no result can reach a terminal rule: a
SignalResult is a research diagnostic, not an EvidenceTest. The frame is passed through `store.as_of`
again here, so a private row is never used before its own `retrieved_at`, whatever the caller did.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

from .evidence import HYPOTHESES, TestResult, evaluate_condition
from .store import Metric, as_of, eligible_signal_input, utc_naive

SIGNALS_CONTRACT = Path("data/dictionary/private_signals.yaml")
INSUFFICIENT = "INSUFFICIENT_DATA"
ROLES = ("PRIMARY_EVIDENCE", "CONFIRMATORY", "CONTEXT_ONLY", "COMPETING_EXPLANATION", "EXPERIMENTAL")
NON_CONFIRMING = ("CONTEXT_ONLY", "EXPERIMENTAL")
MAPPINGS = ("STRONG_CONFIRMATORY", "CONFIRMATORY", "WEAK", "CONTEXT", "RELEVANT", "COUNTER_CHECK",
            "STRONG_COUNTER_CHECK", "EXPERIMENTAL")
# What each method's code computes, versioned. Changing a method's arithmetic or rules bumps its number,
# which changes the definition hash of every signal using it, which forces a new signal version.
METHOD_VERSIONS = {"median_shift": 1, "level_changes": 1, "credit_pulse": 1, "city_momentum": 1,
                   "property_breadth": 1, "market_regime": 1, "consensus_snapshot": 1,
                   "domestic_demand_confirmation": 1, "policy_transmission": 1, "market_confirmation": 1,
                   "h0_competing_explanation": 2}
REQUIRED_THRESHOLDS = {
    "median_shift": {"easing_at_or_below_bp", "tightening_at_or_above_bp"},
    "level_changes": {"rising_at_or_above_bp", "falling_at_or_below_bp"},
    "credit_pulse": {"positive_delta_above"},
    "city_momentum": {"positive_at_or_above_pct", "negative_at_or_below_pct"},
    "property_breadth": {"broad_min_positive", "broad_improvement_median_above_pct", "weak_max_positive",
                         "broad_weakness_median_below_pct"},
    "market_regime": {"equity_up_at_or_above_pct", "equity_down_at_or_below_pct", "yield_up_at_or_above_bp",
                      "yield_down_at_or_below_bp"},
    "consensus_snapshot": set(), "domestic_demand_confirmation": {"positive_min_channels", "negative_min_channels"},
    "policy_transmission": {"visible_min_responding"}, "market_confirmation": set(), "h0_competing_explanation": set(),
}
DOC_ONLY = ("title", "caveats")      # editable without a version bump; everything else is the definition


@dataclass
class SignalDef:
    signal_id: str
    version: int
    layer: str                       # atomic | assessment
    block: str                       # A | B | C | D | X | R
    title: str
    method: str
    inputs: dict
    window: dict
    formula: str
    thresholds: dict
    classification: list
    minimum_coverage: dict
    research_role: str
    hypothesis_mapping: dict
    caveats: list = field(default_factory=list)
    per_input: bool = False
    validation: dict | None = None

    @property
    def sha256(self) -> str:
        """Hash of the definition (all but title/caveats) plus the code's method version."""
        body = {k: v for k, v in asdict(self).items() if k not in DOC_ONLY}
        body["method_version"] = METHOD_VERSIONS[self.method]
        return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

    def input_metrics(self) -> dict[str, str]:
        m = self.inputs.get("metrics") or []
        return dict(m) if isinstance(m, dict) else {x: x for x in m}

    def input_signals(self) -> list[str]:
        return list(self.inputs.get("signals") or [])


@dataclass
class SignalContract:
    contract_version: int
    precision: int
    holidays: list[tuple[str, date, date]]
    holiday_horizon: date
    signals: list[SignalDef]
    sha256: str

    def get(self, signal_id: str) -> SignalDef:
        return next(s for s in self.signals if s.signal_id == signal_id)


@dataclass
class SignalResult:
    """One diagnostic. `status` is the class (or INSUFFICIENT_DATA); numbers are kept continuous."""
    signal_id: str
    signal_version: int
    definition_sha256: str
    title: str
    layer: str
    block: str
    status: str
    research_role: str
    mapped_hypotheses: dict
    coverage_status: str                     # COMPLETE | PARTIAL | INSUFFICIENT
    coverage_detail: list[str]
    numeric_components: dict
    components: dict
    input_observation_ids: list[str]
    input_signals: list[str]
    input_public_tests: dict
    calculation_method: str
    thresholds: dict
    caveats: list[str]
    run_id: str = ""
    as_of: str = ""
    private_only: bool = True


# ---------------------------------------------------------------- the contract
def load_signal_contract(path: str | Path = SIGNALS_CONTRACT, metrics: dict[str, Metric] | None = None) -> SignalContract:
    """Load and validate the frozen contract. Raises ValueError listing every problem."""
    text = Path(path).read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    errs: list[str] = []
    if raw.get("private_only") is not True:
        errs.append("the contract must declare private_only: true")
    defs: list[SignalDef] = []
    seen: dict[str, SignalDef] = {}
    for entry in raw.get("signals") or []:
        try:
            d = SignalDef(**entry)
        except TypeError as e:
            errs.append(f"{entry.get('signal_id')}: {e}")
            continue
        sid = d.signal_id
        if sid in seen:
            errs.append(f"{sid}: duplicate signal_id")
        if not isinstance(d.version, int) or d.version < 1:
            errs.append(f"{sid}: version must be a positive integer")
        if d.method not in METHOD_VERSIONS:
            errs.append(f"{sid}: unknown method '{d.method}'")
            continue
        if d.research_role not in ROLES:
            errs.append(f"{sid}: research_role '{d.research_role}' not in {ROLES}")
        if d.research_role == "PRIMARY_EVIDENCE":
            errs.append(f"{sid}: no Phase 2 signal is PRIMARY_EVIDENCE; promotion needs a new prospective amendment")
        for h, how in d.hypothesis_mapping.items():
            if h not in HYPOTHESES or how not in MAPPINGS:
                errs.append(f"{sid}: hypothesis_mapping {h}: {how} is not in {sorted(HYPOTHESES)} x {MAPPINGS}")
            if d.research_role in NON_CONFIRMING and how in ("CONFIRMATORY", "STRONG_CONFIRMATORY"):
                errs.append(f"{sid}: a {d.research_role} signal cannot be {how} for {h}")
        missing = REQUIRED_THRESHOLDS[d.method] - set(d.thresholds)
        if missing:
            errs.append(f"{sid}: thresholds missing {sorted(missing)}")
        if d.method == "consensus_snapshot" and d.research_role != "EXPERIMENTAL":
            errs.append(f"{sid}: consensus stays EXPERIMENTAL; a surprise model needs its own prospective contract")
        for up in d.input_signals():
            if up not in seen:
                errs.append(f"{sid}: input signal {up} must be defined earlier in the contract")
                continue
            role = seen[up].research_role
            if role == "EXPERIMENTAL":
                errs.append(f"{sid}: takes the EXPERIMENTAL signal {up}; experimental signals feed nothing")
            if role == "CONTEXT_ONLY" and d.research_role not in ("CONTEXT_ONLY", "COMPETING_EXPLANATION"):
                errs.append(f"{sid}: a {d.research_role} signal cannot take the CONTEXT_ONLY signal {up}")
        if metrics is not None:
            for mid in d.input_metrics().values():
                m = metrics.get(mid)
                if m is None:
                    errs.append(f"{sid}: input metric {mid} is not in the dictionary")
                elif not eligible_signal_input(m):
                    errs.append(f"{sid}: input metric {mid} is not a private routed metric whose every named route is "
                                "EXACT/FUNCTIONALLY_EQUIVALENT and validated")
        seen[sid] = d
        defs.append(d)
    hc = raw.get("holiday_caveat_windows") or {}
    holidays = [(w["name"], _date(w["start"]), _date(w["end"])) for w in hc.get("windows") or []]
    if errs:
        raise ValueError("private_signals.yaml errors:\n  - " + "\n  - ".join(errs))
    return SignalContract(raw["contract_version"], int(raw.get("precision", 6)), holidays,
                          _date(hc.get("horizon_end", "1900-01-01")), defs,
                          hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest())


def _date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


# ---------------------------------------------------------------- evaluation context
@dataclass
class _Ctx:
    frame: pd.DataFrame
    metrics: dict[str, Metric]
    contract: SignalContract
    when: pd.Timestamp                         # naive UTC
    public_tests: dict[str, TestResult] | None
    results: dict[str, list[SignalResult]] = field(default_factory=dict)

    @property
    def today(self) -> date:
        """The as-of date in Beijing, the calendar the private observations are dated in."""
        return self.when.tz_localize("UTC").tz_convert("Asia/Shanghai").date()

    def r(self, x: float) -> float:
        return round(float(x), self.contract.precision)

    def points(self, metric_id: str) -> list[tuple[pd.Period, float, str]]:
        """(period, value, input id) for one metric, latest vintage per period, oldest first."""
        sub = self.frame[(self.frame["metric_id"] == metric_id) & self.frame["value"].notna()]
        if sub.empty:
            return []
        sub = sub.sort_values("retrieved_at").drop_duplicates("reference_period", keep="last")
        freq = self.metrics[metric_id].frequency
        out = []
        for _, row in sub.iterrows():
            stem = Path(str(row.get("_file") or "unknown")).stem
            out.append((pd.Period(row["reference_period"], freq=freq), float(row["value"]),
                        f"obs:{metric_id}@{row['reference_period']}#{stem}"))
        return sorted(out, key=lambda t: t[0])

    def one(self, signal_id: str) -> SignalResult | None:
        got = self.results.get(signal_id) or []
        return got[0] if len(got) == 1 else None

    def status(self, signal_id: str) -> str | None:
        """The upstream class, or None when it is missing or INSUFFICIENT_DATA (never a neutral stand-in)."""
        r = self.one(signal_id)
        return None if r is None or r.status == INSUFFICIENT else r.status


def _result(d: SignalDef, ctx: _Ctx, status: str, *, sid: str | None = None, numeric=None, components=None,
            inputs=None, coverage="COMPLETE", detail=None, input_signals=None, public=None, caveats=None) -> SignalResult:
    if status == INSUFFICIENT:
        coverage = "INSUFFICIENT"
    return SignalResult(
        signal_id=sid or d.signal_id, signal_version=d.version, definition_sha256=d.sha256, title=d.title,
        layer=d.layer, block=d.block, status=status, research_role=d.research_role,
        mapped_hypotheses=dict(d.hypothesis_mapping), coverage_status=coverage, coverage_detail=list(detail or []),
        numeric_components=dict(numeric or {}), components=dict(components or {}),
        input_observation_ids=list(inputs or []), input_signals=list(input_signals or []),
        input_public_tests=dict(public or {}), calculation_method=" ".join(d.formula.split()),
        thresholds=copy.deepcopy(d.thresholds), caveats=list(d.caveats) + list(caveats or []))


def _stale_days(ctx: _Ctx, last: pd.Period) -> int:
    return (ctx.today - last.to_timestamp().date()).days


def _daily_coverage(ctx: _Ctx, d: SignalDef, pts: list, need: int, label: str) -> list[str]:
    """Problems that stop a trading-observation signal from classifying (empty list = covered)."""
    if len(pts) < need:
        return [f"{label}: {len(pts)} observations in the information set, {need} required"]
    age = _stale_days(ctx, pts[-1][0])
    if age > d.minimum_coverage["max_staleness_days"]:
        return [f"{label}: latest observation {pts[-1][0]} is {age} days old, at most "
                f"{d.minimum_coverage['max_staleness_days']} allowed"]
    return []


def _move(x: float | None, up: float, down: float, labels=("UP", "FLAT", "DOWN")) -> str | None:
    if x is None:
        return None
    return labels[0] if x >= up else labels[2] if x <= down else labels[1]


def decide(rule, known: dict, domains: dict) -> str:
    """Apply `rule` when an input is missing (None) only if every value it could take gives the same answer.
    A missing input is therefore never treated as neutral."""
    missing = [k for k, v in known.items() if v is None]
    outcomes = set()
    for combo in itertools.product(*(domains[k] for k in missing)):
        outcomes.add(rule(**{**known, **dict(zip(missing, combo))}))
    return outcomes.pop() if len(outcomes) == 1 else INSUFFICIENT


def _upstream(ctx: _Ctx, ids: list[str]) -> tuple[list[str], list[str]]:
    """(input signal refs, union of their input observation ids) for an assessment's provenance."""
    refs, obs = [], []
    for sid in ids:
        for r in ctx.results.get(sid) or []:
            refs.append(f"{r.signal_id}@v{r.signal_version}={r.status}")
            obs += r.input_observation_ids
    return refs, sorted(set(obs))


def _coverage_of(status: str, known: dict) -> tuple[str, list[str]]:
    missing = sorted(k for k, v in known.items() if v is None)
    if status == INSUFFICIENT:
        return "INSUFFICIENT", [f"undetermined: missing or insufficient input(s) {missing}"]
    if missing:
        return "PARTIAL", [f"determined despite missing input(s) {missing}: every value they could take gives {status}"]
    return "COMPLETE", []


# ---------------------------------------------------------------- Block A
def median_shift(d: SignalDef, ctx: _Ctx) -> list[SignalResult]:
    (mid,) = d.input_metrics().values()
    w, t = d.window, d.thresholds
    pts = ctx.points(mid)
    need = w["recent"] + w["previous"]
    gaps = _daily_coverage(ctx, d, pts, max(need, d.minimum_coverage["observations"]), mid)
    if gaps:
        return [_result(d, ctx, INSUFFICIENT, detail=gaps, inputs=[p[2] for p in pts[-need:]])]
    recent, previous = pts[-w["recent"]:], pts[-need:-w["recent"]]
    rm, pm = statistics.median(v for _, v, _ in recent), statistics.median(v for _, v, _ in previous)
    delta = ctx.r((rm - pm) * 100)
    status = ("EASING" if delta <= t["easing_at_or_below_bp"] else
              "TIGHTENING" if delta >= t["tightening_at_or_above_bp"] else "STABLE")
    return [_result(d, ctx, status,
                    numeric={"recent_20d_median_pct": ctx.r(rm), "previous_20d_median_pct": ctx.r(pm), "delta_bp": delta},
                    components={"recent_window": [str(recent[0][0]), str(recent[-1][0])],
                                "previous_window": [str(previous[0][0]), str(previous[-1][0])],
                                "observations_used": len(recent) + len(previous)},
                    inputs=[p[2] for p in previous + recent])]


def level_changes(d: SignalDef, ctx: _Ctx) -> list[SignalResult]:
    (mid,) = d.input_metrics().values()
    t, cov = d.thresholds, d.minimum_coverage
    pts = ctx.points(mid)
    gaps = _daily_coverage(ctx, d, pts, cov["observations"], mid)
    if gaps:
        return [_result(d, ctx, INSUFFICIENT, detail=gaps, inputs=[p[2] for p in pts[-cov["observations"]:]])]
    numeric, used, detail = {}, set(), []
    for n in d.window["changes"]:
        if len(pts) >= n + 1:
            numeric[f"change_{n}d_bp"] = ctx.r((pts[-1][1] - pts[-1 - n][1]) * 100)
            used |= {pts[-1][2], pts[-1 - n][2]}
        else:
            numeric[f"change_{n}d_bp"] = None
            detail.append(f"change_{n}d_bp: {len(pts)} observations, {n + 1} required")
    numeric["latest_yield_pct"] = ctx.r(pts[-1][1])
    status = _move(numeric["change_20d_bp"], t["rising_at_or_above_bp"], t["falling_at_or_below_bp"],
                   ("RISING", "FLAT", "FALLING"))
    return [_result(d, ctx, status, numeric=numeric, components={"latest_date": str(pts[-1][0])},
                    inputs=sorted(used), coverage="PARTIAL" if detail else "COMPLETE", detail=detail)]


# ---------------------------------------------------------------- Block B
def credit_pulse(d: SignalDef, ctx: _Ctx) -> list[SignalResult]:
    legs = d.input_metrics()                                         # {short_term: id, medium_long_term: id}
    n, t = d.window["months"], d.thresholds
    series = {leg: {p: (v, ref) for p, v, ref in ctx.points(mid)} for leg, mid in legs.items()}
    common = set.intersection(*(set(s) for s in series.values()))
    if not common:
        return [_result(d, ctx, INSUFFICIENT, detail=["no month observed for every component"])]
    last = max(common)
    as_of_month = pd.Period(ctx.today, freq="M")
    if (as_of_month - last).n > d.minimum_coverage["max_staleness_months"]:
        return [_result(d, ctx, INSUFFICIENT, detail=[f"latest common month {last} is more than "
                                                      f"{d.minimum_coverage['max_staleness_months']} months before {as_of_month}"])]
    recent = [last - k for k in range(n - 1, -1, -1)]
    year_ago = [p - 12 for p in recent]
    missing = [f"{legs[leg]}@{p}" for leg in legs for p in year_ago + recent if p not in series[leg]]
    if missing:
        return [_result(d, ctx, INSUFFICIENT, detail=[f"missing component-months {missing}"],
                        inputs=sorted(series[leg][p][1] for leg in legs for p in year_ago + recent if p in series[leg]))]
    numeric, positive = {}, []
    sums = {}
    for leg in legs:
        now = sum(series[leg][p][0] for p in recent)
        before = sum(series[leg][p][0] for p in year_ago)
        delta = ctx.r(now - before)
        sums[leg] = (now, before)
        numeric.update({f"{leg}_recent_3m": ctx.r(now), f"{leg}_year_ago_3m": ctx.r(before), f"{leg}_yoy_delta": delta})
        if delta > t["positive_delta_above"]:
            positive.append(leg)
    breadth = len(positive)
    numeric["breadth"] = breadth
    detail = []
    shares = {}
    for when, i in (("recent", 0), ("year_ago", 1)):
        st, ml = sums["short_term"][i], sums["medium_long_term"][i]
        if st >= 0 and ml >= 0 and st + ml > 0:
            shares[when] = ml / (st + ml)
        else:
            detail.append(f"ml_share_{when}: undefined (a component is negative or the total is not positive)")
    numeric["ml_share_recent"] = ctx.r(shares["recent"]) if "recent" in shares else None
    numeric["ml_share_year_ago"] = ctx.r(shares["year_ago"]) if "year_ago" in shares else None
    numeric["ml_share_change_pp"] = ctx.r((shares["recent"] - shares["year_ago"]) * 100) if len(shares) == 2 else None
    status = {2: "BROADENING", 1: "MIXED", 0: "WEAKENING"}[breadth]
    return [_result(d, ctx, status, numeric=numeric,
                    components={"latest_month": str(last), "recent_months": [str(p) for p in recent],
                                "year_ago_months": [str(p) for p in year_ago], "positive_components": positive},
                    inputs=sorted(series[leg][p][1] for leg in legs for p in year_ago + recent),
                    coverage="PARTIAL" if detail else "COMPLETE", detail=detail)]


# ---------------------------------------------------------------- Block C
def _holiday_caveats(ctx: _Ctx, start: date, end: date) -> list[str]:
    out = [f"window {start}..{end} touches {name} ({a}..{b}); holiday effects are caveated, not adjusted"
           for name, a, b in ctx.contract.holidays if a <= end and b >= start]
    if end > ctx.contract.holiday_horizon:
        out.append(f"window ends after the holiday table's horizon ({ctx.contract.holiday_horizon}); holidays there are not flagged")
    return out


def city_momentum(d: SignalDef, ctx: _Ctx) -> list[SignalResult]:
    """One result per city, computed from that city's series alone: areas are never combined across cities."""
    w, t, cov = d.window, d.thresholds, d.minimum_coverage
    out = []
    for city, mid in d.input_metrics().items():
        sid = f"{d.signal_id}.{city}"
        pts = ctx.points(mid)
        if not pts:
            out.append(_result(d, ctx, INSUFFICIENT, sid=sid, detail=[f"{mid}: no observations in the information set"],
                               components={"city": city, "metric_id": mid}))
            continue
        end = pts[-1][0].to_timestamp().date()
        age = (ctx.today - end).days
        r_start, p_end = end - timedelta(days=w["recent"] - 1), end - timedelta(days=w["recent"])
        p_start = p_end - timedelta(days=w["previous"] - 1)
        rec = [p for p in pts if r_start <= p[0].to_timestamp().date() <= end]
        prev = [p for p in pts if p_start <= p[0].to_timestamp().date() <= p_end]
        comp = {"city": city, "metric_id": mid, "recent_window": [str(r_start), str(end)],
                "previous_window": [str(p_start), str(p_end)],
                "observed_days": {"recent": len(rec), "previous": len(prev)}}
        gaps = []
        if age > cov["max_staleness_days"]:
            gaps.append(f"{mid}: latest observation {end} is {age} days old, at most {cov['max_staleness_days']} allowed")
        for name, got in (("recent", rec), ("previous", prev)):
            if len(got) < cov["observed_days_per_window"]:
                gaps.append(f"{mid}: {len(got)} observed days in the {name} 28-day window, {cov['observed_days_per_window']} required")
        prev_avg = sum(v for _, v, _ in prev) / len(prev) if prev else None
        if not gaps and prev_avg <= 0:
            gaps.append(f"{mid}: previous-window average is not positive; momentum undefined")
        caveats = _holiday_caveats(ctx, p_start, end)
        if gaps:
            out.append(_result(d, ctx, INSUFFICIENT, sid=sid, detail=gaps, components=comp,
                               inputs=[p[2] for p in prev + rec], caveats=caveats))
            continue
        rec_avg = sum(v for _, v, _ in rec) / len(rec)
        mom = ctx.r((rec_avg / prev_avg - 1) * 100)
        status = _move(mom, t["positive_at_or_above_pct"], t["negative_at_or_below_pct"], ("POSITIVE", "FLAT", "NEGATIVE"))
        out.append(_result(d, ctx, status, sid=sid, components=comp, caveats=caveats,
                           numeric={"recent_28d_avg": ctx.r(rec_avg), "previous_28d_avg": ctx.r(prev_avg),
                                    "momentum_pct": mom},
                           inputs=[p[2] for p in prev + rec]))
    return out


def property_breadth(d: SignalDef, ctx: _Ctx) -> list[SignalResult]:
    t = d.thresholds
    (up,) = d.input_signals()
    cities = ctx.results.get(up) or []
    refs, obs = _upstream(ctx, [up])
    valid = [c for c in cities if c.status != INSUFFICIENT]
    if len(valid) < d.minimum_coverage["valid_cities"]:
        bad = [c.signal_id for c in cities if c.status == INSUFFICIENT]
        return [_result(d, ctx, INSUFFICIENT, input_signals=refs, inputs=obs,
                        detail=[f"{len(valid)} of {len(cities)} cities classified, {d.minimum_coverage['valid_cities']} required; "
                                f"insufficient: {bad}"])]
    momenta = [c.numeric_components["momentum_pct"] for c in valid]       # momenta only; areas are never added
    n_pos = sum(c.status == "POSITIVE" for c in valid)
    n_neg = sum(c.status == "NEGATIVE" for c in valid)
    med = ctx.r(statistics.median(momenta))
    if n_pos >= t["broad_min_positive"] and med > t["broad_improvement_median_above_pct"]:
        status = "BROAD_IMPROVEMENT"
    elif n_pos <= t["weak_max_positive"] and med < t["broad_weakness_median_below_pct"]:
        status = "BROAD_WEAKNESS"
    else:
        status = "MIXED"
    return [_result(d, ctx, status, input_signals=refs, inputs=obs,
                    numeric={"number_positive": n_pos, "number_negative": n_neg, "median_city_momentum_pct": med},
                    components={"cities": {c.components["city"]: c.status for c in valid}})]


# ---------------------------------------------------------------- Block D
def market_regime(d: SignalDef, ctx: _Ctx) -> list[SignalResult]:
    t, w = d.thresholds, d.window
    eq_id, y_id = d.input_metrics().values()
    (liq_id,) = d.input_signals()
    numeric, inputs, detail = {}, [], []
    eq_pts, y_pts = ctx.points(eq_id), ctx.points(y_id)
    ret = chg = None
    gaps = _daily_coverage(ctx, d, eq_pts, max(w["equity_return"] + 1, d.minimum_coverage["observations"]), eq_id)
    if gaps:
        detail += gaps
    else:
        a, b = eq_pts[-1 - w["equity_return"]], eq_pts[-1]
        ret = ctx.r((b[1] / a[1] - 1) * 100) if a[1] > 0 else None
        inputs += [a[2], b[2]]
    gaps = _daily_coverage(ctx, d, y_pts, max(w["yield_change"] + 1, d.minimum_coverage["observations"]), y_id)
    if gaps:
        detail += gaps
    else:
        a, b = y_pts[-1 - w["yield_change"]], y_pts[-1]
        chg = ctx.r((b[1] - a[1]) * 100)
        inputs += [a[2], b[2]]
    numeric.update(csi300_return_20d_pct=ret, cgb10y_change_20d_bp=chg)
    known = {"equity": _move(ret, t["equity_up_at_or_above_pct"], t["equity_down_at_or_below_pct"]),
             "rates": _move(chg, t["yield_up_at_or_above_bp"], t["yield_down_at_or_below_bp"]),
             "liquidity": ctx.status(liq_id)}

    def rule(equity, rates, liquidity):
        if equity == "UP" and rates == "UP" and liquidity != "TIGHTENING":
            return "REFLATION_CONFIRMATION"
        if equity == "UP" and rates in ("FLAT", "DOWN") and liquidity == "EASING":
            return "LIQUIDITY_DRIVEN_RALLY"
        if equity == "DOWN" and rates == "DOWN":
            return "WEAK_GROWTH_PRICING"
        if equity == "DOWN":
            return "RISK_OFF_OR_MIXED"
        return "MIXED"

    moves = ("UP", "FLAT", "DOWN")
    status = decide(rule, known, {"equity": moves, "rates": moves, "liquidity": ("EASING", "STABLE", "TIGHTENING")})
    coverage, cdetail = _coverage_of(status, known)
    refs, _ = _upstream(ctx, [liq_id])
    return [_result(d, ctx, status, numeric=numeric, components={"moves": known}, inputs=inputs,
                    input_signals=refs, coverage=coverage, detail=detail + cdetail)]


# ---------------------------------------------------------------- consensus (experimental)
def consensus_snapshot(d: SignalDef, ctx: _Ctx) -> list[SignalResult]:
    """Which consensus snapshots are in the information set, and when they were retrieved. No value is read:
    no surprise, revision or score can be computed here."""
    snaps, inputs = {}, []
    for mid in d.input_metrics().values():
        sub = ctx.frame[ctx.frame["metric_id"] == mid]
        snaps[mid] = [{"target_period": r["reference_period"], "retrieved_at": r["retrieved_at"],
                       "snapshot": Path(str(r.get("_file") or "unknown")).stem}
                      for _, r in sub.sort_values("reference_period").iterrows()]
        inputs += [f"obs:{mid}@{s['target_period']}#{s['snapshot']}" for s in snaps[mid]]
    status = "EXPERIMENTAL_SNAPSHOT_ONLY" if any(snaps.values()) else INSUFFICIENT
    return [_result(d, ctx, status, components={"snapshots": snaps, "validation": d.validation}, inputs=inputs,
                    detail=[] if any(snaps.values()) else ["no consensus snapshot in the information set"])]


# ---------------------------------------------------------------- assessments
CREDIT = ("BROADENING", "MIXED", "WEAKENING")
PROPERTY = ("BROAD_IMPROVEMENT", "MIXED", "BROAD_WEAKNESS")


def domestic_demand_confirmation(d: SignalDef, ctx: _Ctx) -> list[SignalResult]:
    hh_id, corp_id, prop_id = d.input_signals()
    t = d.thresholds
    channel = {"BROADENING": "positive", "WEAKENING": "negative", "MIXED": "mixed",
               "BROAD_IMPROVEMENT": "positive", "BROAD_WEAKNESS": "negative"}
    known = {k: channel.get(ctx.status(s)) for k, s in (("household", hh_id), ("corporate", corp_id), ("property", prop_id))}

    def rule(household, corporate, property):
        states = (household, corporate, property)
        if (states.count("positive") >= t["positive_min_channels"]
                and household != "negative" and property != "negative"):
            return "POSITIVE"
        if states.count("negative") >= t["negative_min_channels"]:
            return "NEGATIVE"
        return "MIXED"

    dom = ("positive", "mixed", "negative")
    status = decide(rule, known, {k: dom for k in known})
    coverage, detail = _coverage_of(status, known)
    refs, obs = _upstream(ctx, d.input_signals())
    return [_result(d, ctx, status, components={"channels": known}, input_signals=refs, inputs=obs,
                    coverage=coverage, detail=detail)]


def policy_transmission(d: SignalDef, ctx: _Ctx) -> list[SignalResult]:
    liq_id, corp_id, hh_id, prop_id = d.input_signals()
    t = d.thresholds
    known = {"liquidity": ctx.status(liq_id), "corporate": ctx.status(corp_id), "household": ctx.status(hh_id),
             "property": ctx.status(prop_id)}

    def rule(liquidity, corporate, household, property):
        if liquidity != "EASING":
            return "NO_CLEAR_EASING"
        responding = (corporate == "BROADENING") + (household == "BROADENING") + (property == "BROAD_IMPROVEMENT")
        if responding >= t["visible_min_responding"]:
            return "TRANSMISSION_VISIBLE"
        return "EASING_WITHOUT_RESPONSE" if responding == 0 else "MIXED"

    status = decide(rule, known, {"liquidity": ("EASING", "STABLE", "TIGHTENING"), "corporate": CREDIT,
                                  "household": CREDIT, "property": PROPERTY})
    coverage, detail = _coverage_of(status, known)
    refs, obs = _upstream(ctx, d.input_signals())
    responding = [k for k, v in known.items() if v in ("BROADENING", "BROAD_IMPROVEMENT")]
    return [_result(d, ctx, status, components={"inputs": known, "responding_channels": responding},
                    input_signals=refs, inputs=obs, coverage=coverage, detail=detail)]


def market_confirmation(d: SignalDef, ctx: _Ctx) -> list[SignalResult]:
    (up,) = d.input_signals()
    regime = ctx.status(up)
    mapping = {"REFLATION_CONFIRMATION": "CONFIRMS", "LIQUIDITY_DRIVEN_RALLY": "DOES_NOT_CONFIRM",
               "WEAK_GROWTH_PRICING": "CONTRADICTS", "RISK_OFF_OR_MIXED": "MIXED", "MIXED": "MIXED"}
    status = mapping[regime] if regime else INSUFFICIENT
    refs, obs = _upstream(ctx, [up])
    return [_result(d, ctx, status, components={"regime": regime}, input_signals=refs, inputs=obs,
                    detail=[] if regime else [f"{up} is insufficient"])]


def h0_competing_explanation(d: SignalDef, ctx: _Ctx) -> list[SignalResult]:
    r1, hh_id, corp_id, prop_id, mkt_id = d.input_signals()
    pt = d.inputs["public_tests"]
    results = ctx.public_tests or {}

    def at_least(spec) -> bool | None:
        return evaluate_condition({"at_least": spec["at_least"], "of": [{"test": t} for t in spec["of"]]}, results)

    price, external = at_least(pt["price_improving"]), at_least(pt["external_improving"])
    nominal = price            # v2: the nominal premise is the price evidence alone; external strength is context
    mkt = ctx.one(mkt_id)
    equity = mkt.components.get("moves", {}).get("equity") if mkt else None
    known_all = {"nominal_improving": nominal, "r1": ctx.status(r1), "household": ctx.status(hh_id),
                 "corporate": ctx.status(corp_id), "property": ctx.status(prop_id),
                 "market_up": None if equity is None else equity == "UP"}

    def weak(household, property):
        return ((household == "WEAKENING" or property == "BROAD_WEAKNESS")
                and household != "BROADENING" and property != "BROAD_IMPROVEMENT")

    def flag(cond: bool) -> str:
        return "ELEVATED" if cond else "NOT_ELEVATED"

    rules = {
        "H0_SUPPLY_LED_RISK": (lambda nominal_improving, r1: flag(nominal_improving and r1 in ("MIXED", "NEGATIVE")),
                               ("nominal_improving", "r1")),
        "FINANCIAL_MARKET_CONFIRMATION_WITHOUT_REAL_DEMAND": (
            lambda market_up, household, property: flag(market_up and weak(household, property)),
            ("market_up", "household", "property")),
        "POLICY_SUPPLY_LED_CREDIT_RISK": (
            lambda corporate, household, property: flag(corporate == "BROADENING" and weak(household, property)),
            ("corporate", "household", "property")),
    }
    domains = {"nominal_improving": (True, False), "r1": ("POSITIVE", "MIXED", "NEGATIVE"), "household": CREDIT,
               "corporate": CREDIT, "property": PROPERTY, "market_up": (True, False)}
    flags = {name: decide(fn, {k: known_all[k] for k in keys}, domains) for name, (fn, keys) in rules.items()}
    status = ("ELEVATED" if "ELEVATED" in flags.values() else
              "NOT_ELEVATED" if all(v == "NOT_ELEVATED" for v in flags.values()) else INSUFFICIENT)
    tests = sorted(set(pt["price_improving"]["of"]) | set(pt["external_improving"]["of"]) | set(pt["h0_context"]))
    public = {t: (results[t].outcome if t in results else "not_evaluated") for t in tests}
    h0_context = {t: {"outcome": results[t].outcome, "effect_on_H0": results[t].effect} if t in results else None
                  for t in pt["h0_context"]}
    detail = [f"{k}: undetermined, missing input(s) {[x for x in rules[k][1] if known_all[x] is None]}"
              for k, v in flags.items() if v == INSUFFICIENT]
    if ctx.public_tests is None:
        detail.append("no public evidence state was supplied")
    refs, obs = _upstream(ctx, d.input_signals())
    coverage = "INSUFFICIENT" if status == INSUFFICIENT else "PARTIAL" if detail else "COMPLETE"
    return [_result(d, ctx, status, components={"flags": flags, "price_improving": price, "external_improving": external,
                                                "nominal_improving": nominal, "h0_public_context": h0_context,
                                                "inputs": known_all},
                    input_signals=refs, inputs=obs, public=public, coverage=coverage, detail=detail)]


METHODS = {f.__name__: f for f in (median_shift, level_changes, credit_pulse, city_momentum, property_breadth,
                                   market_regime, consensus_snapshot, domestic_demand_confirmation,
                                   policy_transmission, market_confirmation, h0_competing_explanation)}
assert set(METHODS) == set(METHOD_VERSIONS)


def compute_signals(obs: pd.DataFrame, metrics: dict[str, Metric], contract: SignalContract, when,
                    public_tests: dict[str, TestResult] | None) -> list[SignalResult]:
    """Every signal in contract order, from the information set as of `when` (naive input is UTC)."""
    when = utc_naive(when)
    ctx = _Ctx(as_of(obs, when), metrics, contract, when, public_tests)
    out: list[SignalResult] = []
    for d in contract.signals:
        res = METHODS[d.method](d, ctx)
        ctx.results[d.signal_id] = res
        out += res
    return out
