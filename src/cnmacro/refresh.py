"""Public data refresh: one idempotent command from official sources to the published site.

    cnmacro refresh-public

  1. decide which public metrics may have new data (official release calendar; NBS agenda;
     publication lags for sources without a dated calendar)
  2. fetch those metrics from every reachable official/public route
  3. append only genuinely new observations (a new period, or a revised value as a new vintage)
  4. keep release_date / retrieved_at / provenance on every row
  5-7. re-run the evidence tests of the preregistered case (baseline + amendments) as of now
     and as of the previous evidence state; record flips and marginal changes
  8. write an append-only refresh record (research/cases/<case>/refreshes/<time>.json)
  9. run the deterministic eval gate (E0-E5)
 10. rebuild the public site

Automatic vs analyst layers: a refresh updates facts only (observations, derived values, test
outcomes, terminal check, a factual diff, a mechanical `suggested_direction`). It never
changes the thesis probability. Only a preregistered terminal rule may change the thesis
status automatically, through an update file that names the rule. Probability changes need
an analyst update that passes E5.

Running it twice in a row is a no-op: the second run finds no new observations and writes nothing.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd
import yaml

from . import checks, ingest
from .claims import load_claims
from .derive import Deriver
from .evidence import evaluate_test, load_tests, terminal_rule, window_is_open
from .store import as_of, load_dictionary, load_observations, to_period, utc_naive
from .thesis import case_files, effective_case, fold, load_yaml

# Typical publication lag (days after the end of the reference month) for routes without a
# dated official calendar in the repo. Used only to decide whether a fetch is worth trying;
# a metric fetched too early simply yields nothing new and is tried again next run.
LAG_DAYS = {
    "fred:POILBREUSDM": 40, "fred:PCOPPUSDM": 40,      # IMF primary commodity prices via FRED
    "fred": 5,                                          # monthly averages of daily market series
    "pboc": 12, "gacc_us": 12,
    "nbs:PBOC": 12, "nbs:MOF": 20, "nbs:GACC": 9,       # other agencies republished on the NBS portal
    "nbs": 20,                                          # NBS series with no calendar entry
}
VALUE_TOL = 1e-6


@dataclass
class Paths:
    root: Path
    case_dir: Path
    obs_dir: Path
    dictionary: Path
    calendar: Path
    site_out: Path | None

    @classmethod
    def default(cls, root: Path | str = ".") -> "Paths":
        root = Path(root)
        return cls(root, root / "research/cases/cn-nominal", root / "data/demo/observations",
                   root / "data/dictionary/metrics.yaml", root / "data/dictionary/release_calendar.yaml",
                   root / "site/dist")


@dataclass
class RefreshResult:
    status: str                                   # no_new_data | refreshed | eval_failed | dry_run
    as_of: str
    due: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    new_rows: int = 0
    record: str | None = None
    terminal_update: str | None = None
    eval_status: dict = field(default_factory=dict)
    flipped: list = field(default_factory=list)


# ---------------------------------------------------------------- what may be new
def route(m) -> str | None:
    if m.redistribution != "public":
        return None
    code = m.source_code or ""
    if code.startswith("nbs:"):
        return "nbs"
    if m.source_primary == "FRED" and code:
        return "fred"
    if m.source_primary == "PBOC":
        return "pboc"
    if m.metric_id == "cn_exports_us_ytd_yoy":
        return "gacc_us"
    return None


def lag_days(m) -> int:
    r = route(m)
    for key in (f"{r}:{m.source_code}", f"{r}:{m.source_primary}", r):
        if key in LAG_DAYS:
            return LAG_DAYS[key]
    return 30


def held_latest(obs: pd.DataFrame, m) -> pd.Period | None:
    sub = obs[obs.metric_id == m.metric_id]
    if sub.empty:
        return None
    return max(to_period(p, m.frequency) for p in sub.reference_period)


def expected_latest(m, calendar: dict, now: pd.Timestamp) -> pd.Period | None:
    """Latest period that should be public by `now`: from the official calendar when it covers
    this metric, otherwise from the route's typical publication lag."""
    released = [to_period(p, m.frequency) for (mid, p), (t, _) in calendar.items()
                if mid == m.metric_id and utc_naive(t) <= now]
    if released:
        return max(released)
    if m.frequency != "M":
        return None  # quarterly series (GDP) are always on the official calendar
    return (now - pd.Timedelta(days=lag_days(m))).to_period("M") - 1


def due_metrics(metrics: dict, obs: pd.DataFrame, calendar: dict, now: pd.Timestamp) -> dict[str, dict]:
    due = {}
    for mid, m in metrics.items():
        if not route(m):
            continue
        held, want = held_latest(obs, m), expected_latest(m, calendar, now)
        if want is not None and (held is None or want > held):
            due[mid] = {"route": route(m), "held": str(held) if held else None, "expected": str(want)}
    return due


def full_calendar(paths: Paths, now: pd.Timestamp, use_agenda: bool = True) -> tuple[dict, str]:
    """Verified calendar entries in the repo plus the NBS agenda around `now` (when reachable)."""
    cal = ingest.load_calendar(paths.calendar)
    note = "repo calendar only"
    if use_agenda:
        try:
            start, end = (now - pd.Timedelta(days=75)).date().isoformat(), (now + pd.Timedelta(days=45)).date().isoformat()
            agenda, _ = ingest.agenda_calendar(start, end)
            cal = {**agenda, **cal}
            note = f"repo calendar + NBS agenda {start}..{end}"
        except Exception as ex:  # the agenda only extends the calendar; never fatal
            note = f"repo calendar only (NBS agenda unreachable: {type(ex).__name__})"
    return cal, note


# ---------------------------------------------------------------- fetching
def _start_month(held: str | None, months_back: int = 12) -> str:
    if not held:
        return "2019-01"
    p = pd.Period(held[:7] if "Q" not in held else f"{held[:4]}-{(int(held[-1]) - 1) * 3 + 1:02d}", "M")
    return str(p - months_back)


def _script_rows(script: str, start_year: int, metrics: dict, calendar: dict, got: str) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / f"{Path(script).stem}.csv"
        subprocess.run([sys.executable, script, "--start", str(start_year), "--out", str(out)],
                       check=True, capture_output=True, text=True, timeout=1800)
        pub, _ = ingest.inbox_rows(out, metrics, calendar, got=got)
    return pub


def fetch_live(route_name: str, ms: list, held: dict, metrics: dict, calendar: dict, got: str,
               root: Path) -> dict[str, list[dict]]:
    """{target csv name: rows} for one route. Raises on network failure."""
    if route_name == "nbs":
        return {f"nbs_{m.metric_id}.csv": ingest.nbs_rows(m, calendar, _start_month(held[m.metric_id]), got)
                for m in ms}
    if route_name == "fred":
        return {f"fred_{m.metric_id}.csv": ingest.fred_rows(m, _start_month(held[m.metric_id]) + "-01", calendar, got)
                for m in ms}
    year = pd.Timestamp(got).year - 1
    if route_name == "pboc":
        rows = _script_rows(str(root / "scripts/fetch_pboc.py"), year, metrics, calendar, got)
        return {"inbox_pboc.csv": rows}
    if route_name == "gacc_us":
        rows = _script_rows(str(root / "scripts/fetch_gacc_us.py"), year, metrics, calendar, got)
        return {"inbox_gacc_us.csv": rows}
    raise ValueError(f"unknown route {route_name}")


def new_rows(rows: list[dict], obs: pd.DataFrame) -> list[dict]:
    """Only genuinely new information: a period not held, or a value that differs from the
    latest held vintage (kept as a new vintage, release date unknown, flagged 'revised')."""
    latest = {}
    if not obs.empty:
        last = obs.sort_values("retrieved_at").drop_duplicates(["metric_id", "reference_period"], keep="last")
        latest = {(r.metric_id, r.reference_period): r.value for r in last.itertuples()}
    out, seen = [], set()
    for r in rows:
        key = (r["metric_id"], r["reference_period"])
        if key in seen:
            continue
        seen.add(key)
        if key not in latest:
            out.append(r)
        elif abs(float(r["value"]) - float(latest[key])) > VALUE_TOL:
            out.append({**r, "release_date": "", "release_date_basis": "unknown", "quality_flag": "revised",
                        "limitation": f"revised value seen at retrieval (earlier vintage {latest[key]} kept); "
                                      "revision date unknown, availability taken as retrieval time"})
    return out


# ---------------------------------------------------------------- evidence diff
def previous_evidence_as_of(case_dir: Path) -> str:
    stamps = [load_yaml(case_files(case_dir)[0])["as_of"]]
    stamps += [load_yaml(p)["as_of"] for p in case_files(case_dir)[1]]
    stamps += [json.loads(p.read_text(encoding="utf-8"))["as_of"] for p in sorted((case_dir / "refreshes").glob("*.json"))]
    return max(stamps, key=utc_naive)


def evaluate(obs, metrics, case, when) -> tuple[dict, dict]:
    d = Deriver(as_of(obs, when), metrics)
    res = {t.id: evaluate_test(t, d) for t in load_tests(case["evidence_tests"])}
    is_open = window_is_open(case.get("horizon", {}), d, when)
    status, rule = terminal_rule(case["terminal_rules"], res, is_open)
    return res, {"status": status, "rule_fired": rule, "window_open": is_open}


EFFECT = {"supports": 1, "challenges": -1, "none": 0}


def suggested_direction(flips: list[dict]) -> dict:
    """Mechanical tally of flips toward or away from the thesis. Not a judgment: H0 support
    counts against the thesis; insufficient data counts as neutral."""
    score = 0
    for f in flips:
        sign = -1 if f["hypothesis"] == "H0" else 1
        score += sign * (EFFECT.get(f["effect_to"], 0) - EFFECT.get(f["effect_from"], 0))
    direction = "toward_thesis" if score > 0 else "against_thesis" if score < 0 else "neutral"
    return {"direction": direction, "score": score,
            "note": "mechanical tally of evidence-test flips; the analyst judgment is unchanged until an update is appended"}


def diff_results(before: dict, after: dict) -> tuple[list[dict], list[dict]]:
    flips, marginal = [], []
    for k, a in after.items():
        b = before.get(k)
        if b is None:
            continue
        if a.outcome != b.outcome:
            flips.append({"test": k, "hypothesis": a.hypothesis, "from": b.outcome, "to": a.outcome,
                          "effect_from": b.effect, "effect_to": a.effect, "period_from": b.latest_period,
                          "period_to": a.latest_period})
        if (a.latest_period != b.latest_period or a.observed != b.observed) and a.observed is not None:
            marginal.append({"test": k, "hypothesis": a.hypothesis, "period_from": b.latest_period,
                             "period_to": a.latest_period, "observed_from": b.observed, "observed_to": a.observed,
                             "change": None if b.observed is None else round(a.observed - b.observed, 4)})
    return flips, marginal


# ---------------------------------------------------------------- eval + site
def run_eval(paths: Paths, metrics) -> tuple[list, dict]:
    obs = load_observations(paths.obs_dir)
    claims_path = paths.case_dir / "claims.jsonl"
    claims = load_claims(claims_path) if claims_path.exists() else []
    results = checks.run_all(obs, metrics, claims, paths.case_dir, public_only=True)
    report = checks.write_report(results, paths.case_dir / "eval/latest.json", "public", paths.case_dir)
    return results, report


def build_site(paths: Paths, banner: str | None = None) -> None:
    if paths.site_out is None:
        return
    cmd = [sys.executable, str(Path(__file__).resolve().parents[2] / "site/build.py"),
           "--case-dir", str(paths.case_dir), "--obs-dir", str(paths.obs_dir),
           "--calendar", str(paths.calendar), "--dictionary", str(paths.dictionary), "--out", str(paths.site_out)]
    if banner:
        cmd += ["--banner", banner]
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------- orchestration
Fetcher = Callable[[str, list, dict, dict, dict, str], dict]


def refresh_public(paths: Paths, now: str | None = None, fetcher: Fetcher | None = None,
                   force_all: bool = False, dry_run: bool = False, use_agenda: bool = True,
                   build: bool = True, banner: str | None = None, log=print) -> RefreshResult:
    now_s = now or ingest.now_iso()
    now_t = utc_naive(now_s)
    metrics = load_dictionary(paths.dictionary)
    obs = load_observations(paths.obs_dir)
    calendar, cal_note = full_calendar(paths, now_t, use_agenda)
    log(f"calendar: {cal_note}")

    if force_all:
        due = {mid: {"route": route(m), "held": str(held_latest(obs, m) or ""), "expected": None}
               for mid, m in metrics.items() if route(m)}
    else:
        due = due_metrics(metrics, obs, calendar, now_t)
    res = RefreshResult("no_new_data", now_s, due=due)
    if not due:
        log("nothing due: every public metric is at or ahead of its expected latest period")
        return res
    for mid, d in sorted(due.items()):
        log(f"due: {mid} ({d['route']}) held {d['held']} expected {d['expected']}")

    fetch = fetcher or (lambda r, ms, held, mets, cal, got: fetch_live(r, ms, held, mets, cal, got, paths.root))
    by_route: dict[str, list] = {}
    for mid, d in due.items():
        by_route.setdefault(d["route"], []).append(metrics[mid])
    appended: dict[str, list[dict]] = {}
    all_obs = obs
    for r, ms in sorted(by_route.items()):
        held = {m.metric_id: due[m.metric_id]["held"] for m in ms}
        try:
            batches = fetch(r, ms, held, metrics, calendar, now_s)
        except Exception as ex:
            res.sources[r] = {"ok": False, "error": f"{type(ex).__name__}: {ex}"[:300], "metrics": sorted(held)}
            log(f"source {r}: FAILED ({res.sources[r]['error']})")
            continue
        n_new = 0
        for fname, rows in batches.items():
            fresh = new_rows(rows, all_obs)
            if fresh:
                appended.setdefault(fname, []).extend(fresh)
                all_obs = pd.concat([all_obs, pd.DataFrame(fresh).assign(_file=str(paths.obs_dir / fname))],
                                    ignore_index=True)
                n_new += len(fresh)
        res.sources[r] = {"ok": True, "fetched": sum(len(v) for v in batches.values()), "new": n_new,
                          "metrics": sorted(held)}
        log(f"source {r}: fetched {res.sources[r]['fetched']} rows, {n_new} new")

    res.new_rows = sum(len(v) for v in appended.values())
    if res.new_rows == 0:
        log("no new observations")
        return res
    if dry_run:
        res.status = "dry_run"
        log(f"dry run: {res.new_rows} new rows not written")
        return res

    for fname, rows in appended.items():
        ingest.append_rows(rows, paths.obs_dir / fname)
    obs = load_observations(paths.obs_dir)

    # evidence: case in force, previous evidence state vs now
    case, amendments, _ = effective_case(paths.case_dir)
    prev = previous_evidence_as_of(paths.case_dir)
    before, term_before = evaluate(obs, metrics, case, prev)
    after, term_after = evaluate(obs, metrics, case, now_s)
    flips, marginal = diff_results(before, after)
    res.flipped = flips
    state, _, _ = fold(paths.case_dir)
    base_path, _ = case_files(paths.case_dir)

    record = {
        "kind": "evidence_refresh",
        "as_of": now_s,
        "previous_evidence_as_of": prev,
        "case_in_force": {"baseline": base_path.name, "amendments": [a["_file"] for a in amendments]},
        "calendar": cal_note,
        "sources": res.sources,
        "due": due,
        "new_observations": [{k: r[k] for k in ("metric_id", "reference_period", "value", "release_date",
                                                 "release_date_basis", "source", "quality_flag")}
                             for rows in appended.values() for r in rows],
        "flipped_tests": flips,
        "marginal_changes": marginal,
        "test_results": {k: asdict(v) for k, v in after.items()},
        "terminal": {"before": term_before, "after": term_after},
        "analyst_judgment": {k: state[k] for k in ("probability", "conviction", "status", "last_update_direction")}
                            | {"as_of": state["as_of"], "changed_by_this_refresh": False},
        "suggested_direction": suggested_direction(flips),
    }

    # a preregistered terminal rule is the only automatic route to a status change
    if term_after["status"] != state["status"] and term_after["status"] != "ACTIVE":
        upd = paths.case_dir / "updates" / f"{now_s[:10]}-terminal-{term_after['status'].lower()}.yaml"
        direction = "STRENGTHENED" if term_after["status"] == "CONFIRMED" else "WEAKENED"
        doc = {"kind": "update", "author": "automation (preregistered terminal rule)",
               "baseline": base_path.name, "as_of": now_s, "release": "terminal rule check",
               "previous_state": {k: state[k] for k in ("probability", "conviction", "status", "last_update_direction")},
               "test_results": record["test_results"], "flipped_tests": flips,
               "terminal_check": term_after["status"], "terminal_rule_fired": term_after["rule_fired"],
               "probability": state["probability"], "conviction": state["conviction"],
               "status": term_after["status"], "last_update_direction": direction, "probability_change": None,
               "does_this_change_the_thesis": (
                   f"Preregistered terminal rule {term_after['rule_fired']} fired. Status set by rule; the "
                   "probability is left for the analyst's next update.")}
        upd.parent.mkdir(parents=True, exist_ok=True)
        upd.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
        res.terminal_update = str(upd)
        record["analyst_judgment"]["status_changed_by_terminal_rule"] = term_after["rule_fired"]

    rec_dir = paths.case_dir / "refreshes"
    rec_dir.mkdir(parents=True, exist_ok=True)
    rec_path = rec_dir / f"{now_t.strftime('%Y-%m-%dT%H%MZ')}.json"
    rec_path.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    res.record = str(rec_path)
    log(f"wrote {rec_path}: {res.new_rows} new observations, {len(flips)} flipped test(s)")

    results, report = run_eval(paths, metrics)
    res.eval_status = {c.id: c.status for c in results}
    if any(c.status == "fail" for c in results):
        res.status = "eval_failed"
        for c in results:
            if c.status == "fail":
                log(f"eval {c.id} FAIL: {c.details[:5]}")
        return res
    if build:
        build_site(paths, banner)
    res.status = "refreshed"
    return res
