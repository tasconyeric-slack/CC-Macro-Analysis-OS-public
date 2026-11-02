"""Context Builder: the only thing the model is ever shown.

Built from existing components (`store.as_of`, `Deriver`, `refresh.evaluate` / `diff_results`,
`thesis.effective_case`). It is a pure function of (store, case, release, as_of, prior_as_of): the same
inputs give byte-identical JSON and therefore the same `sha256`, which is what makes a Run Record
reproducible. It never reads `data/private`, never fetches, and never includes an observation that was
not available at `as_of`.

Code decides what the model can cite: `allowlist` is the closed set of evidence identifiers
(`obs:` / `drv:` refs that resolve at `as_of`, plus `test:` ids). Values are computed here and rendered
later by `contract.render`; the model only ever sees them, it never types them.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from .. import checks, ingest
from ..claims import period_tokens
from ..derive import REF_RE, Deriver, parse_drv
from ..evidence import load_tests
from ..refresh import EFFECT, Paths, diff_results, evaluate
from ..store import as_of as store_as_of
from ..store import available_at, load_dictionary, load_observations, release_time, utc_naive
from ..thesis import case_files, effective_case, load_yaml
from . import CONTEXT_VERSION, records

HYPOTHESES = ("H1", "H2", "H3", "H4", "H0")
FEATURE_LAGS = (1, 3, 6)             # drv:diff(metric,n): change over n periods
BEFORE_MINUTES = 60                  # same default as replay.replay: the information set just before the release
FORWARD_DAYS = 45                    # scheduled releases this far ahead may be named in prose
MAX_ALLOWLIST = 300                  # bounded context: a release is a handful of series, not the store
PERIODS = re.compile(r"\b(19|20)\d{2}(Q[1-4]|-\d{2})?\b")
PROTECT = re.compile(r"\b(19|20)\d{2}(Q[1-4]|-\d{2})?\b|\bH[0-4]\b")      # period labels and hypothesis labels survive masking
FIGURE = re.compile(r"[-+]?\d+(?:[.,]\d+)*(?:\s?(?:%|pp\b|bp\b))?")


def mask_figures(text):
    """Analyst-written prose may contain numbers; the model may not write any. Figures become [figure] (period
    labels such as 2026-09 and H0-H4 are kept), so the model has nothing to echo and the number gate is not
    tripped by the analyst's own words."""
    if not isinstance(text, str):
        return text
    keep: list[str] = []

    def hold(m):
        keep.append(m.group(0))
        return chr(0xE000 + len(keep) - 1)                  # a private-use character: no digit for FIGURE to match
    t = FIGURE.sub("[figure]", PROTECT.sub(hold, text))
    return "".join(keep[ord(ch) - 0xE000] if 0xE000 <= ord(ch) < 0xE000 + len(keep) else ch for ch in t)


class ContextError(ValueError):
    """The context cannot be built honestly; the run must not start."""


@dataclass
class ReleaseSpec:
    release_id: str
    name: str
    period: str
    release_at: str                  # ISO with offset, as in release_calendar.yaml
    metrics: list[str]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def iso_utc(value) -> str:
    return utc_naive(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_release(calendar: Path, name: str) -> ReleaseSpec:
    """A verified entry of data/dictionary/release_calendar.yaml, by exact name or unique substring."""
    rels = yaml.safe_load(Path(calendar).read_text(encoding="utf-8"))["releases"]
    exact = [r for r in rels if r["name"].lower() == name.lower()]
    hits = exact or [r for r in rels if name.lower() in r["name"].lower()]
    if len(hits) != 1:
        raise ContextError(f"release {name!r} matches {len(hits)} calendar entries; "
                           f"known: {[r['name'] for r in rels][:6]} ...")
    r = hits[0]
    return ReleaseSpec(slug(r["name"]), r["name"], str(r["period"]), str(r["release"]), list(r["metrics"]))


def default_prior(release_at: str) -> str:
    return iso_utc(release_time(release_at) - pd.Timedelta(minutes=BEFORE_MINUTES))


# ---------------------------------------------------------------- formatting: code owns every rendered number
def _unit_info(ref: str, metrics: dict) -> tuple[str, str, str, str]:
    """(label, unit, fmt, suffix) of an obs/drv ref, from the dictionary only."""
    kind, body, period = REF_RE.match(ref).groups()
    if kind == "obs":
        m = metrics[body]
        label, unit, fmt = f"{m.name} {period}", m.unit, ".1f"
    else:
        fn, args = parse_drv(body)
        m = metrics[next(a for a in args if a in metrics)]
        n = args[-1] if fn in ("ma", "diff", "pctile") and len(args) > 1 else None
        if fn == "yoy":
            label, unit, fmt = f"year-on-year change of {m.name} {period}", "%", ".1f"
        elif fn == "single":
            label, unit, fmt = f"single-period flow of {m.name} {period}", m.unit, ".1f"
        elif fn == "ma":
            label, unit, fmt = f"{n}-period average of {m.name} to {period}", m.unit, ".1f"
        elif fn == "diff":
            label, unit, fmt = f"change in {m.name} over {n} period(s) to {period}", ("pp" if m.unit == "%" else m.unit), "+.1f"
        elif fn == "deflator_yoy":
            label, unit, fmt = f"implied GDP deflator YoY {period} (nominal vs real GDP growth)", "%", ".1f"
        else:
            label, unit, fmt = f"{fn} of {m.name} {period}", m.unit, ".1f"
    if unit.startswith("CNY 100m"):
        fmt = fmt.replace(".1f", ",.0f")
    suffix = "%" if unit == "%" else " pp" if unit == "pp" else "" if unit.startswith("index") or unit == "m2" else f" {unit}"
    return label, unit, fmt, suffix


def _entry(ref: str, point, metrics: dict, frame: pd.DataFrame | None) -> dict:
    label, unit, fmt, suffix = _unit_info(ref, metrics)
    value = round(float(point.value), 4)
    kind, body, period = REF_RE.match(ref).groups()
    e = {"ref": ref, "kind": kind, "label": label, "period": period, "unit": unit, "value": value,
         "fmt": fmt, "suffix": suffix, "display": f"{value:{fmt}}{suffix}"}
    if kind == "obs" and frame is not None:
        row = frame[(frame.metric_id == body) & (frame.reference_period == period)]
        if not row.empty:
            e["available_at"] = iso_utc(available_at(row.iloc[0].to_dict()))
    return e


# ---------------------------------------------------------------- pieces
def _guard_public(paths: Paths) -> None:
    if any(part.lower() == "private" for part in Path(paths.obs_dir).parts):
        raise ContextError("the Copilot context is built from public observations only (never data/private)")


def _judgment_as_of(case_dir: Path, when: pd.Timestamp) -> tuple[dict, dict | None, str, bool]:
    """(standing judgment, latest analyst update before `when` or None, source file, replay-carried).

    The judgment in force at `when`: the baseline plus the updates dated at or before it. A replay
    sandbox baseline is flagged `replay: true` and carries the live 2026-10-04 judgment, which was
    written after the replayed release: its prose is withheld and the carry is disclosed."""
    base_path, update_paths = case_files(case_dir)
    base = load_yaml(base_path)
    state = {k: base[k] for k in ("probability", "conviction", "status", "last_update_direction")} | {"as_of": str(base["as_of"])}
    src, last_update = base_path.name, None
    for p in update_paths:
        u = load_yaml(p)
        if utc_naive(u["as_of"]) <= when:
            state = {k: u[k] for k in ("probability", "conviction", "status", "last_update_direction")} | {"as_of": str(u["as_of"])}
            src, last_update = p.name, {"file": p.name, **u}
    return state, last_update, src, bool(base.get("replay"))


def _analyst_prior(case_dir: Path, when: pd.Timestamp, last_update: dict | None) -> dict:
    """The analyst's own words per hypothesis, only if they predate `when` (never in a replay)."""
    base_path, _ = case_files(case_dir)
    base = load_yaml(base_path)
    if base.get("replay"):
        return {}
    doc = last_update if last_update and last_update.get("hypothesis_assessment") else base
    if utc_naive(doc["as_of"]) > when:
        return {}
    return {h: mask_figures(t) for h, t in (doc.get("hypothesis_assessment") or {}).items()}


def _tally(results: dict, mine: list) -> dict:
    return {"supports": sum(results[t.id].effect == "supports" for t in mine),
            "challenges": sum(results[t.id].effect == "challenges" for t in mine),
            "insufficient_data": sum(results[t.id].outcome == "insufficient_data" for t in mine)}


def _new_observations(obs, metrics, prior, now) -> list[dict]:
    a, b = store_as_of(obs, prior), store_as_of(obs, now)
    old = {(r.metric_id, r.reference_period): r.value for r in a.itertuples()}
    out = []
    for r in b.itertuples():
        k = (r.metric_id, r.reference_period)
        if (k not in old or old[k] != r.value) and r.metric_id in metrics and metrics[r.metric_id].redistribution == "public":
            out.append({"metric_id": r.metric_id, "period": r.reference_period, "revised_from": None if k not in old else float(old[k])})
    return sorted(out, key=lambda x: (x["metric_id"], x["period"]))


def _expectation(exp_dir: Path | None, release: ReleaseSpec, d: Deriver) -> dict | None:
    """The analyst's frozen Expectation Note, only if it was committed once, before the release.
    An uncommitted, edited or post-release note is excluded and the reason is recorded."""
    if exp_dir is None or not Path(exp_dir).exists():
        return None
    for f in sorted(Path(exp_dir).glob("*.yaml")):
        if f.name.startswith("_"):
            continue
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if doc.get("kind") != "expectation_note" or doc.get("release") != release.name:
            continue
        commits = records.git_commits(f)
        t = checks.commit_time(commits[-1]) if commits else None
        if not commits:
            return {"status": "excluded", "file": f.name, "reason": "not committed: an expectation counts only if committed before the release"}
        if len(commits) > 1 or t is None or t >= release_time(release.release_at):
            return {"status": "excluded", "file": f.name, "reason": "edited after its first commit or committed after the release"}
        items = []
        for it in doc.get("expectations") or []:
            ref, lo_hi = it["ref"], it.get("range") or [None, None]
            pt = d.resolve(ref)
            item = {"ref": ref, "direction_vs_prior": it.get("direction_vs_prior"), "range": lo_hi, "note": mask_figures(it.get("note", ""))}
            if pt is not None and None not in lo_hi:
                v = float(pt.value)
                item["vs_expectation"] = "above" if v > lo_hi[1] else "below" if v < lo_hi[0] else "inside"
            else:
                item["vs_expectation"] = "not_set"
            items.append(item)
        return {"status": "frozen", "file": f.name, "committed_at": t.isoformat() + "Z", "items": items,
                "scenarios": [{k: mask_figures(v) for k, v in sc.items()} for sc in doc.get("scenarios") or [] if isinstance(sc, dict)]}
    return None


def _open_needs(copilot_dir: Path | None, when: pd.Timestamp) -> list[dict]:
    """Research Needs the analyst kept alive in the most recent decided run (v0: no persistent queue, Phase E)."""
    if copilot_dir is None:
        return []
    return records.open_research_needs(Path(copilot_dir), when)


# ---------------------------------------------------------------- the builder
def build_context(paths: Paths, release: ReleaseSpec, as_of: str, prior_as_of: str | None = None, *,
                  copilot_dir: Path | None = None, expectation_dir: Path | None = None) -> dict:
    _guard_public(paths)
    now = utc_naive(as_of)
    prior = utc_naive(prior_as_of) if prior_as_of else release_time(release.release_at) - pd.Timedelta(minutes=BEFORE_MINUTES)
    if prior >= now:
        raise ContextError(f"as_of ({iso_utc(now)}) is not after the state before the release ({iso_utc(prior)}): the release has not happened yet at as_of")
    metrics = load_dictionary(paths.dictionary)
    obs = load_observations(paths.obs_dir)
    case, _, errs = effective_case(paths.case_dir)
    if errs:
        raise ContextError(f"the case in force is not valid: {errs[:2]}")

    before, term_before = evaluate(obs, metrics, case, iso_utc(prior))
    after, term_after = evaluate(obs, metrics, case, iso_utc(now))
    flips, marginal = diff_results(before, after)
    d = Deriver(store_as_of(obs, iso_utc(now)), metrics)
    frame = d.obs
    tests = load_tests(case["evidence_tests"])
    new_obs = _new_observations(obs, metrics, iso_utc(prior), iso_utc(now))
    if not new_obs:
        raise ContextError("no observation became available between prior_as_of and as_of: nothing to interpret")

    # ---- evidence allowlist: only refs that resolve at as_of ------------------------------------------
    refs: list[str] = []

    def add(ref: str) -> None:
        if ref not in refs:
            refs.append(ref)

    release_metrics = sorted({o["metric_id"] for o in new_obs})
    for o in new_obs:
        add(f"obs:{o['metric_id']}@{o['period']}")
        p = pd.Period(o["period"], freq=metrics[o["metric_id"]].frequency)
        add(f"obs:{o['metric_id']}@{p - 1}")
    for mid in release_metrics:
        latest = max(pd.Period(o["period"], freq=metrics[mid].frequency) for o in new_obs if o["metric_id"] == mid)
        for n in FEATURE_LAGS:
            add(f"drv:diff({mid},{n})@{latest}")
        add(f"drv:ma({mid},3)@{latest}")
    for t in tests:
        for res in (before[t.id], after[t.id]):
            for r in res.refs:
                add(r)
        if t.rule == "change" and t.indicator in metrics and after[t.id].latest_period:
            add(f"drv:diff({t.indicator},{t.n})@{after[t.id].latest_period}")

    allow: list[dict] = []
    for ref in refs:
        mids = [a for a in re.findall(r"[a-z0-9_]+", ref.split("@")[0]) if a in metrics]
        if not mids or any(metrics[m].redistribution != "public" for m in mids):
            continue                                            # licensed or unknown series never enter a context
        try:
            pt = d.resolve(ref)
        except (KeyError, ValueError, StopIteration):
            pt = None
        if pt is not None and pd.notna(pt.value):
            allow.append(_entry(ref, pt, metrics, frame))
    allow += [{"ref": f"test:{t.id}", "kind": "test", "label": t.description, "hypothesis": t.hypothesis} for t in tests]
    if len(allow) > MAX_ALLOWLIST:
        raise ContextError(f"allowlist has {len(allow)} entries (> {MAX_ALLOWLIST}); a context must stay bounded")
    by_ref = {e["ref"]: e for e in allow}

    # ---- hypotheses: definitions, test state, code-owned mechanical direction -----------------------
    state, last_update, judgment_src, replay_carried = _judgment_as_of(paths.case_dir, now)
    prior_text = _analyst_prior(paths.case_dir, now, last_update)
    hyps = {}
    for h in HYPOTHESES:
        spec = (case.get("hypotheses") or {}).get(h) or {}
        mine = [t for t in tests if t.hypothesis == h]
        hf = [f for f in flips if f["hypothesis"] == h]
        net = sum(EFFECT[f["effect_to"]] - EFFECT[f["effect_from"]] for f in hf)
        hyps[h] = {
            "name": spec.get("name"), "claim": spec.get("claim"),
            "analyst_prior": prior_text.get(h),
            "mechanical_delta": "supports" if net > 0 else "challenges" if net < 0 else "unchanged",
            "tests_prior": _tally(before, mine), "tests_now": _tally(after, mine),
            "flips": [{k: f[k] for k in ("test", "from", "to", "effect_from", "effect_to", "period_from", "period_to")} for f in hf],
            "tests": [{"id": t.id, "description": t.description, "window": t.window, "threshold_basis": t.threshold_basis,
                       "outcome_prior": before[t.id].outcome, "outcome_now": after[t.id].outcome,
                       "effect_now": after[t.id].effect, "latest_period": after[t.id].latest_period,
                       "refs_now": [r for r in after[t.id].refs if r in by_ref]} for t in mine],
        }

    # ---- schedule: what the model may name as "next data", from the release calendar ----------------------
    cal = ingest.load_calendar(paths.calendar)
    upcoming: dict[str, set] = {}
    for (mid, per), (rel, _) in cal.items():
        t = release_time(rel)
        if now < t <= now + pd.Timedelta(days=FORWARD_DAYS) and mid in metrics:
            upcoming.setdefault(iso_utc(t), set()).add((mid, per))
    next_releases = [{"release_at": k, "metrics": sorted(m for m, _ in v), "periods": sorted({p for _, p in v})}
                     for k, v in sorted(upcoming.items())]
    horizon = case.get("horizon") or {}
    forward = set(period_tokens(" ".join(str(horizon.get(k, "")) for k in ("definition_of_sustainable", "terminal_release"))))
    forward |= {p for nr in next_releases for p in nr["periods"]}

    ctx = {
        "version": CONTEXT_VERSION,
        "release": {"release_id": release.release_id, "name": release.name, "period": release.period,
                    "release_at": release.release_at, "metrics": release.metrics},
        "as_of": iso_utc(now), "prior_as_of": iso_utc(prior),
        "mode": "replay" if replay_carried else "live",
        "replay_disclosure": (
            "REPLAY. The standing judgment below is the 2026-10-04 baseline carried into the sandbox: it was written after the replayed "
            "release and the hypotheses were designed after seeing 2026 data (framework contamination, strategy §10.2). The analyst's "
            "prose is withheld. This run tests interpretation under the given framework, not the framework's predictive power, and it "
            "is not live evidence." if replay_carried else None),
        "standing_thesis": {
            "question": case.get("question"), "statement": case.get("statement"),
            "definition_of_sustainable": horizon.get("definition_of_sustainable"),
            "judgment": state, "judgment_source": judgment_src, "read_only": True},
        "previous_update": None if last_update is None else {
            "file": last_update["file"], "release": last_update.get("release"), "as_of": str(last_update["as_of"]),
            "does_this_change_the_thesis": mask_figures(last_update.get("does_this_change_the_thesis"))},
        "hypotheses": hyps,
        "terminal": {"before": term_before, "after": term_after, "owner": "code"},
        "new_observations": [{**o, "ref": f"obs:{o['metric_id']}@{o['period']}"} for o in new_obs],
        "unavailable_tests": sorted(t.id for t in tests if after[t.id].outcome == "insufficient_data"),
        "expectation": _expectation(expectation_dir, release, d),
        "open_research_needs": _open_needs(copilot_dir, now),
        "next_releases": next_releases,
        "forward_periods": sorted(forward),
        "allowlist": allow,
    }
    ctx["sha256"] = context_hash(ctx)
    return ctx


def canonical(ctx: dict) -> str:
    body = {k: v for k, v in ctx.items() if k != "sha256"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def context_hash(ctx: dict) -> str:
    return hashlib.sha256(canonical(ctx).encode("utf-8")).hexdigest()


def allowed_refs(ctx: dict) -> set[str]:
    return {e["ref"] for e in ctx["allowlist"]}
