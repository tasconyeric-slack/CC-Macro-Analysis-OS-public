"""`diagnose-private`: one verified ACTIVE publication (the anchor) -> routed information set -> deterministic
diagnostics -> a private report.

    verified publications, any provider (manifest says published, file SHA256 matches)
        -> anchor: a verified active publication with a row on a route that is active at its own time T
        -> information set at T:  select_active(public + every verified private publication, T)   the route filter
                                  then store.as_of(., T)                                          ... BEFORE as_of
        -> public evidence state (preregistered tests on public observations only; read, never changed)
        -> signals.compute_signals
        -> data/private/signals/<run_id>.json
           data/private/research/<run_id>/PRIVATE_DIAGNOSTIC_REPORT.md

Local only and read-only towards everything tracked: no provider call, no thesis or probability change, no
public file, no site. Outputs are written once. The run id carries a hash of the contract, the anchor and the
information set, so the same inputs always give the same id; a rerun must reproduce the stored result exactly,
and a definition that changed without a version bump stops the run. A run also records `routes`: which route was
authoritative for each routed input at T. Candidate publications are loaded as history only, never as an anchor,
and a route-history record can never rewrite what a stored run used (ROUTE_HISTORY_RETROACTIVE).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from . import checks
from .derive import Deriver
from .evidence import evaluate_test, load_tests, terminal_decision, window_is_open
from .normalize import as_of_routed, select_active
from .signals import INSUFFICIENT, SignalContract, SignalResult, compute_signals
from .store import Metric, as_of, load_observation_files, load_observations, route_at, route_change_at, utc_naive

DEMO_OBS = Path("data/demo/observations")
PRIVATE_DIR = Path("data/private")
PRIVATE_OBS = PRIVATE_DIR / "observations"       # active publications
PRIVATE_CAND = PRIVATE_DIR / "candidates"        # candidate publications: history only, never an anchor
SIGNALS_DIR = Path("data/private/signals")
RESEARCH_DIR = Path("data/private/research")
REPORT_NAME = "PRIVATE_DIAGNOSTIC_REPORT.md"
SIGNALS_CONTRACT_FILE = "data/dictionary/private_signals.yaml"
DICTIONARY_FILE = "data/dictionary/metrics.yaml"
RUN_FIELDS = ("signals", "public_state", "previous_snapshot", "changes", "routes")   # what a rerun must reproduce
# Part of `previous_snapshot`, so part of what an earlier run stored: a stored run must still reproduce, so this text is frozen.
LEGACY_NOT_EVALUABLE = ("Only one genuine snapshot exists; no earlier snapshot was retrieved before this one. "
                        "Nothing is compared with reconstructed pseudo-vintages.")


class DiagnoseFailure(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@dataclass
class Snapshot:
    """The stored run's `snapshot` block (kept as it was, so earlier runs stay readable and reproducible)."""
    run_id: str
    file: str                 # repo-relative path
    sha256: str
    as_of: str                # the latest retrieved_at in the publication, UTC ISO
    rows: int


@dataclass
class Publication:
    """One verified provider publication file: `<provider>_<run_id>.csv` plus its run manifest."""
    provider: str
    run_id: str
    kind: str                 # observations | candidates
    file: str
    sha256: str
    as_of: str
    rows: int
    is_anchor: bool = False   # an active publication with a row on a route active at its own as_of
    frame: pd.DataFrame | None = field(default=None, repr=False, compare=False)

    @property
    def stem(self) -> str:
        return f"{self.provider}_{self.run_id}"

    @property
    def anchor_id(self) -> str:
        """Wind anchors keep their Phase 2 id (the bare run id); every other provider's is `<provider>_<run_id>`."""
        return self.run_id if self.provider == "wind" else self.stem

    def snapshot(self) -> Snapshot:
        return Snapshot(self.anchor_id, self.file, self.sha256, self.as_of, self.rows)

    def anchor(self) -> dict:
        return {"provider": self.provider, "run_id": self.run_id, "stem": self.stem, "file": self.file,
                "sha256": self.sha256, "as_of": self.as_of, "rows": self.rows}


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verified_publications(root: Path, metrics: dict[str, Metric]) -> tuple[list[Publication], list[str]]:
    """Every provider publication whose bytes still match its run manifest, from observations/ and candidates/,
    oldest first; and the problems with any that do not (those are never loaded, never anchors, and never count as a
    genuine earlier anchor). The manifest must record the file as the publication of THAT directory, so a candidate
    copied into observations/ is unverified."""
    known = {r.provider for m in metrics.values() for r in m.sources}
    routed = [k for k, v in metrics.items() if v.routed]
    good, bad = [], []
    for directory, kind in ((PRIVATE_OBS, "observations"), (PRIVATE_CAND, "candidates")):
        for f in sorted((root / directory).glob("*.csv")):
            provider, _, run_id = f.stem.partition("_")
            if provider not in known or not run_id:
                if (root / PRIVATE_DIR / provider / "runs").is_dir():
                    bad.append(f"{f.name}: no route for provider {provider} in the dictionary")
                continue                                  # not a provider publication (e.g. a manual inbox file)
            manifest = root / PRIVATE_DIR / provider / "runs" / run_id / "manifest.json"
            if not manifest.exists():
                bad.append(f"{f.name}: no run manifest")
                continue
            m = json.loads(manifest.read_text(encoding="utf-8"))
            pub = m.get("publication") or {}
            if m.get("status") != "published" or pub.get("status") != "published":
                bad.append(f"{f.name}: the run manifest does not record a published snapshot")
                continue
            rel = (directory / f.name).as_posix()
            entry = next((e for e in (pub, pub.get("candidates")) if e and e.get("file") == rel), None)
            if entry is None:
                bad.append(f"{f.name}: the run manifest does not record this file under {directory.as_posix()}/")
                continue
            digest = _sha256(f)
            if entry.get("sha256") != digest:
                bad.append(f"{f.name}: SHA256 differs from the run manifest; the snapshot is not the one published")
                continue
            df = pd.read_csv(f, dtype=str, keep_default_na=False)
            when = max(utc_naive(t) for t in df["retrieved_at"])
            p = Publication(provider, run_id, kind, rel, digest, when.isoformat() + "Z", len(df), frame=df)
            if kind == "observations":                    # a row on a route that was active at this file's own time
                p.is_anchor = not select_active(df[df["metric_id"].isin(routed)], metrics, when).empty
            good.append(p)
    good.sort(key=lambda p: (p.as_of, p.stem, p.kind))
    return good, bad


def public_state(obs: pd.DataFrame, metrics: dict[str, Metric], case: dict, when) -> tuple[dict, dict]:
    """The preregistered evidence state on public observations only, as of `when`: (TestResults, summary)."""
    pub = as_of(obs[obs["source_class"] == "public"], when)
    d = Deriver(pub, metrics)
    res = {t.id: evaluate_test(t, d) for t in load_tests(case["evidence_tests"])}
    is_open = window_is_open(case.get("horizon", {}), d, when)
    summary = {"evaluated_as_of": utc_naive(when).isoformat() + "Z", "source": "public observations only",
               "terminal_status": terminal_decision(case["terminal_rules"], res, is_open),
               "decision_window_open": is_open,
               "tests": {k: {"hypothesis": r.hypothesis, "outcome": r.outcome, "effect": r.effect,
                             "latest_period": r.latest_period} for k, r in res.items()}}
    return res, summary


def _canonical(x) -> str:
    return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def information_set_sha256(frame: pd.DataFrame) -> str:
    cols = ["metric_id", "reference_period", "value", "retrieved_at", "source_class"]
    rows = frame[cols].astype(str).copy()
    rows["file"] = [Path(str(f)).stem for f in frame.get("_file", pd.Series([""] * len(frame), index=frame.index))]
    return hashlib.sha256(rows.sort_values(cols + ["file"]).to_csv(index=False).encode()).hexdigest()


# ---------------------------------------------------------------- routes recorded in a run
def routed_inputs(metrics: dict[str, Metric], contract: SignalContract) -> list[str]:
    """The routed metrics the signal contract reads, sorted."""
    ids = {mid for d in contract.signals for mid in d.input_metrics().values()}
    return sorted(mid for mid in ids if mid in metrics and metrics[mid].routed)


ROUTE_KEYS = ("provider", "series_key", "equivalence", "effective_at")     # the route identity a run records and a rerun must reproduce
GENESIS_EQUIVALENCE = "EXACT"                                              # the incumbent Wind route was pinned as the canonical definition


def route_record(metric: Metric, when) -> dict:
    """The route authoritative for `metric` at `when`, as a run records it."""
    r, c = route_at(metric, when), route_change_at(metric, when)
    return {"provider": r.provider, "series_key": r.series_key, "equivalence": r.equivalence, "effective_at": c.effective_at}


def routes_at(metrics: dict[str, Metric], contract: SignalContract, when) -> dict[str, dict]:
    """For each routed input, the route authoritative at `when`: {provider, series_key, equivalence, effective_at}."""
    return {mid: route_record(metrics[mid], when) for mid in routed_inputs(metrics, contract)}


def genesis_routes(metrics: dict[str, Metric], contract: SignalContract) -> dict[str, dict]:
    """What a run stored before V1.2.1 (no `routes` field) implies: every input on its incumbent Wind route, EXACT,
    from genesis. The equivalence is the incumbent's by definition, not read back from the current dictionary,
    so editing it afterwards cannot make an old run look consistent."""
    out = {}
    for mid in routed_inputs(metrics, contract):
        wind = next((r for r in metrics[mid].sources if r.provider == "wind"), None)
        if wind is not None:
            out[mid] = {"provider": "wind", "series_key": wind.series_key, "equivalence": GENESIS_EQUIVALENCE,
                        "effective_at": "genesis"}
    return out


def check_route_history(root: Path, metrics: dict[str, Metric], contract: SignalContract) -> None:
    """Two guards, both before anything is written.

    * Cross-version append-only integrity (checks.route_history_audit): no earlier route-history record was edited,
      removed or reordered between Git versions of the dictionary, even where no stored run notices.
    * Retroactivity: for EVERY stored run, route_at(m, run.as_of) must equal the route the run recorded for m. A run
      without `routes` predates V1.2.1 and must equal the genesis state (all Wind). A route-history record can
      therefore never rewrite what a ResearchRun that already exists was built from."""
    violations, _ = checks.route_history_audit(root / DICTIONARY_FILE)
    if violations:
        raise DiagnoseFailure("ROUTE_HISTORY_REWRITTEN", "; ".join(violations))
    legacy = genesis_routes(metrics, contract)
    for f in sorted((root / SIGNALS_DIR).glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        recorded = doc.get("routes")
        recorded = legacy if recorded is None else recorded
        for mid, r in recorded.items():
            m = metrics.get(mid)
            if m is None or not m.routed:
                continue
            now = route_record(m, doc["as_of"])
            differs = [k for k in ROUTE_KEYS if now[k] != r.get(k)]
            if differs:                                  # the whole recorded identity, not provider and time alone
                raise DiagnoseFailure("ROUTE_HISTORY_RETROACTIVE",
                                      f"{f.name}: at its as_of {doc['as_of']} {mid} was routed as "
                                      + ", ".join(f"{k} {r.get(k)!r}" for k in ROUTE_KEYS) + "; the dictionary now says "
                                      + ", ".join(f"{k} {now[k]!r}" for k in ROUTE_KEYS)
                                      + f" (differs: {', '.join(differs)}); a route-history record may only be appended")


def diagnose_anchor(obs: pd.DataFrame, metrics, contract: SignalContract, case: dict, anchor: Publication) -> dict:
    """Signals and public state for one anchor, as of its own retrieval time. The route filter runs first, so the
    information set holds one provider per routed metric whatever was retrieved when."""
    frame = as_of_routed(obs, metrics, anchor.as_of)
    results, summary = public_state(obs, metrics, case, anchor.as_of)
    sigs = compute_signals(frame, metrics, contract, anchor.as_of, results)
    return {"frame": frame, "signals": sigs, "public_state": summary}


def _transitive_inputs(contract: SignalContract, signal_id: str) -> set[str]:
    d = contract.get(signal_id.split(".")[0])
    out = set(d.input_metrics().values())
    for up in d.input_signals():
        out |= _transitive_inputs(contract, up)
    return out


def compare(before: list[SignalResult], after: list[SignalResult], contract: SignalContract | None = None,
            routes_before: dict | None = None, routes_after: dict | None = None) -> list[dict]:
    """Class and numeric changes between two genuine anchors, signal by signal. A signal whose input route differs
    between the two is annotated, so a provider switch is never read as an economic change."""
    prev = {s.signal_id: s for s in before}
    out = []
    for s in after:
        p = prev.get(s.signal_id)
        if p is None:
            out.append({"signal_id": s.signal_id, "before": None, "after": s.status, "class_changed": True,
                        "numeric_change": {}, "note": "not computed for the previous snapshot"})
            continue
        if (p.signal_version, p.definition_sha256) != (s.signal_version, s.definition_sha256):
            out.append({"signal_id": s.signal_id, "before": p.status, "after": s.status, "class_changed": None,
                        "numeric_change": {}, "note": "definitions differ; not comparable"})
            continue
        num = {}
        for k, v in s.numeric_components.items():
            pv = p.numeric_components.get(k)
            if isinstance(v, (int, float)) and isinstance(pv, (int, float)):
                num[k] = round(v - pv, 6)
        entry = {"signal_id": s.signal_id, "before": p.status, "after": s.status,
                 "class_changed": p.status != s.status, "numeric_change": num, "note": ""}
        if contract is not None and routes_before is not None and routes_after is not None:
            moved = [{"metric_id": m, "before": routes_before[m]["provider"], "after": routes_after[m]["provider"]}
                     for m in sorted(_transitive_inputs(contract, s.signal_id))
                     if m in routes_before and m in routes_after
                     and (routes_before[m]["provider"], routes_before[m]["series_key"])
                     != (routes_after[m]["provider"], routes_after[m]["series_key"])]
            if moved:                                       # only when it happened, so unchanged runs reproduce
                entry["route_changes"] = moved
                entry["note"] = "input route changed: " + ", ".join(f"{x['metric_id']} {x['before']} -> {x['after']}" for x in moved)
        out.append(entry)
    return out


def _stored_definitions(root: Path) -> dict[tuple[str, int], tuple[str, str]]:
    """(signal_id, version) -> (definition hash, file) over every stored run."""
    seen: dict[tuple[str, int], tuple[str, str]] = {}
    for f in sorted((root / SIGNALS_DIR).glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        for s in doc.get("signals", []):
            base = s["signal_id"].split(".")[0]
            seen.setdefault((base, s["signal_version"]), (s["definition_sha256"], f.name))
    return seen


def check_versions(root: Path, contract: SignalContract) -> None:
    """A stored (signal_id, version) must keep its definition hash: change the definition, bump the version."""
    stored = _stored_definitions(root)
    for d in contract.signals:
        prior = stored.get((d.signal_id, d.version))
        if prior and prior[0] != d.sha256:
            raise DiagnoseFailure("SIGNAL_DEFINITION_CHANGED_WITHOUT_VERSION_BUMP",
                                  f"{d.signal_id} v{d.version} differs from the definition stored in {prior[1]}; "
                                  "give the changed definition a new version")


def _select_anchor(pubs: list[Publication], anchors: list[Publication], problems: list[str], ref: str) -> Publication:
    cur = next((a for a in anchors if a.stem == ref), None)
    if cur is not None:
        return cur
    named = [p for p in pubs if p.stem == ref]
    if named:                                              # verified, but not an anchor: say why
        why = ("a candidate publication is never an anchor" if all(p.kind == "candidates" for p in named)
               else "none of its rows is on a route that was active at its own time")
        raise DiagnoseFailure("ANCHOR_NOT_ELIGIBLE", f"{ref}: {why}")
    why = next((p for p in problems if p.startswith(f"{ref}.csv")), "no such published anchor")
    raise DiagnoseFailure("SNAPSHOT_NOT_VERIFIED", f"{ref}: {why}")


def run(root: Path | str, metrics: dict[str, Metric], contract: SignalContract, case: dict,
        anchor: str | None = None, snapshot: str | None = None) -> dict:
    """Diagnose one verified anchor (default: the newest). `anchor` is `<provider>_<run_id>`; `snapshot` is the Phase 2
    alias for a Wind run id. Returns a summary carrying classes, not values."""
    root = Path(root)
    pubs, problems = verified_publications(root, metrics)
    anchors = [p for p in pubs if p.is_anchor]
    ref = anchor or (f"wind_{snapshot}" if snapshot else None)
    if ref:
        cur = _select_anchor(pubs, anchors, problems, ref)
    else:
        if not anchors:
            raise DiagnoseFailure("NO_VERIFIED_SNAPSHOT", "run refresh-private first; " + "; ".join(problems))
        cur = anchors[-1]
    earlier = [a for a in anchors if a.as_of < cur.as_of]
    prev = earlier[-1] if earlier else None
    check_versions(root, contract)
    check_route_history(root, metrics, contract)

    obs = pd.concat([load_observations(root / DEMO_OBS), load_observation_files([root / p.file for p in pubs])],
                    ignore_index=True)
    now = diagnose_anchor(obs, metrics, contract, case, cur)
    routes = routes_at(metrics, contract, cur.as_of)
    ident = _canonical({"contract": contract.sha256, "snapshot": cur.sha256,
                        "information_set": information_set_sha256(now["frame"]), "public_state": now["public_state"]})
    run_id = f"{cur.anchor_id}-{hashlib.sha256(ident.encode()).hexdigest()[:10]}"
    for s in now["signals"]:
        s.run_id, s.as_of = run_id, cur.as_of

    if prev is not None:
        before = diagnose_anchor(obs, metrics, contract, case, prev)
        changes = compare(before["signals"], now["signals"], contract, routes_at(metrics, contract, prev.as_of), routes)
        previous = {**asdict(prev.snapshot()), "status": "COMPARED"}
    else:
        changes = []
        previous = {"status": "NOT_EVALUABLE",              # stored text of a field a rerun must reproduce: never reword it
                    "reason": LEGACY_NOT_EVALUABLE}

    private_files = sorted({Path(str(f)).name for f in now["frame"].loc[now["frame"]["source_class"] == "private", "_file"]})
    doc = {
        "kind": "private_diagnostic_run", "private_only": True, "run_id": run_id, "as_of": cur.as_of,
        "snapshot": asdict(cur.snapshot()),
        "anchor": cur.anchor(),
        "routes": routes,
        "contract": {"file": SIGNALS_CONTRACT_FILE, "contract_version": contract.contract_version, "sha256": contract.sha256},
        "information_set": {"rule": "store.as_of(select_active(public + every verified private publication, anchor as_of), "
                                    "anchor as_of): one route per routed metric, selected before as_of; private rows are "
                                    "available only from their own retrieved_at",
                            "private_files": private_files,
                            "rows": int(len(now["frame"])),
                            "private_rows": int((now["frame"]["source_class"] == "private").sum()),
                            "sha256": information_set_sha256(now["frame"])},
        "unverified_snapshots_ignored": problems,
        "public_state": now["public_state"],
        "signals": [asdict(s) for s in now["signals"]],
        "previous_snapshot": previous,
        "changes": changes,
    }
    out = root / SIGNALS_DIR / f"{run_id}.json"
    report = root / RESEARCH_DIR / run_id / REPORT_NAME
    text = json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=False, default=str)
    outcome = _write_once(out, text, doc, genesis_routes(metrics, contract))
    report_text = render_report(doc)
    if not report.exists():
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(report_text, encoding="utf-8")
    return {"status": outcome, "run_id": run_id, "anchor": cur.stem, "snapshot": cur.anchor_id, "as_of": cur.as_of,
            "previous_snapshot": prev.anchor_id if prev else None,
            "routes": {mid: r["provider"] for mid, r in routes.items()},
            "signals": {s.signal_id: s.status for s in now["signals"]},
            "insufficient": [s.signal_id for s in now["signals"] if s.status == INSUFFICIENT],
            "output": out.relative_to(root).as_posix(), "report": report.relative_to(root).as_posix()}


def _write_once(path: Path, text: str, doc: dict, legacy_routes: dict) -> str:
    """Create the run file, or prove an existing one is reproduced exactly. Never overwrite. A stored run with no
    `routes` field predates V1.2.1 and is compared as the genesis state (every input on its Wind route)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        stored = {k: old.get(k) for k in RUN_FIELDS}
        if "routes" not in old:
            stored["routes"] = legacy_routes
        if _canonical(stored) != _canonical(json.loads(json.dumps({k: doc[k] for k in RUN_FIELDS}, default=str))):
            raise DiagnoseFailure("NON_REPRODUCIBLE", f"{path.name} exists with different results for identical inputs and "
                                                      "definitions; a method changed without a version bump")
        return "reproduced"
    with open(path, "x", encoding="utf-8") as f:            # exclusive: an existing result is never replaced
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    return "diagnosed"


# ---------------------------------------------------------------- the report (deterministic template; no LLM)
SECTIONS = {"A": "Liquidity / financial conditions", "B": "Credit demand", "C": "Property pulse",
            "D": "Market confirmation"}
KIND = {"CONFIRMATORY": "deterministic", "CONTEXT_ONLY": "context", "COMPETING_EXPLANATION": "deterministic flag",
        "EXPERIMENTAL": "experimental"}


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:,.4f}".rstrip("0").rstrip(".") if abs(v) < 1e6 else f"{v:,.0f}"
    return str(v)


def _block(s: dict) -> list[str]:
    lines = [f"**{s['signal_id']}** · {s['title']} (v{s['signal_version']}, {s['research_role']}) — "
             f"**{s['status']}** · coverage {s['coverage_status']}"]
    for k, v in s["numeric_components"].items():
        lines.append(f"- {k}: {_fmt(v)}")
    for k in ("recent_window", "previous_window", "latest_month", "latest_date", "positive_components",
              "observed_days", "moves", "channels", "inputs", "responding_channels", "regime", "cities"):
        if k in s["components"]:
            lines.append(f"- {k}: {_fmt(s['components'][k])}")
    for dmsg in s["coverage_detail"]:
        lines.append(f"- coverage: {dmsg}")
    lines.append(f"- inputs: {len(s['input_observation_ids'])} observation(s)"
                 + (f"; signals {', '.join(s['input_signals'])}" if s["input_signals"] else ""))
    return lines + [""]


def render_report(doc: dict) -> str:
    sig = {s["signal_id"]: s for s in doc["signals"]}

    def st(sid: str) -> str:
        return sig[sid]["status"] if sid in sig else "missing"

    pub = doc["public_state"]
    prev = doc["previous_snapshot"]
    changed = [c for c in doc["changes"] if c["class_changed"]]
    if prev["status"] != "COMPARED":
        what_changed = "Cannot yet be evaluated: this is the first genuine anchor."
    elif changed:
        what_changed = f"{len(changed)} classification(s) changed: " + "; ".join(
            f"{c['signal_id']} {c['before']} → {c['after']}" for c in changed)
    else:
        what_changed = "No classification changed since the previous genuine anchor."
    flags = sig.get("R4_h0_competing_explanation", {}).get("components", {}).get("flags", {})
    L = [
        "# Private Macro Diagnostic", "",
        "> LOCAL ONLY. Contains licensed or private-route-derived values (private_only). Never commit, publish or paste into a "
        "public channel. Generated deterministically by `python -m cnmacro diagnose-private`; no number below "
        "was produced by a language model.", "",
        f"- run: `{doc['run_id']}`", f"- as of: {doc['as_of']} (the anchor's own retrieval time)",
        f"- anchor: `{doc['snapshot']['file']}` (provider {doc.get('anchor', {}).get('provider', 'wind')}; SHA256 verified against its run manifest)",
        f"- signal contract: `{doc['contract']['file']}` v{doc['contract']['contract_version']} "
        f"(sha256 {doc['contract']['sha256'][:12]}…)", "",
        "## Executive diagnostic", "",
        "| Question | Answer | Basis | Kind |", "|---|---|---|---|",
        f"| What changed? | {what_changed} | genuine snapshots only | deterministic |",
        f"| Is domestic demand confirming the nominal-growth turn? | {st('R1_domestic_demand_confirmation')} | "
        f"household {st('B1_household_credit_pulse')}, corporate {st('B2_corporate_credit_pulse')}, property "
        f"{st('C2_property_breadth')} | deterministic private layer; does not replace the preregistered H2 condition |",
        f"| Is policy transmission visible? | {st('R2_policy_transmission')} | DR007 {st('A1_dr007_liquidity_trend')}; "
        f"responses: corporate {st('B2_corporate_credit_pulse')}, household {st('B1_household_credit_pulse')}, property "
        f"{st('C2_property_breadth')} | deterministic, contemporaneous, not causal |",
        f"| Are markets confirming growth/reflation, or responding to liquidity? | {st('R3_market_confirmation')} | "
        f"regime {st('D1_market_regime')} | context only |",
        f"| Does H0 remain a credible competing explanation? | {st('R4_h0_competing_explanation')} | "
        + ", ".join(f"{k} {v}" for k, v in flags.items()) + " | deterministic flag; never falsifies the thesis |",
        f"| Preregistered thesis state | {pub['terminal_status']} | public tests as of {pub['evaluated_as_of']} | "
        "preregistered rules, unchanged by this report |", "",
        "Left to analyst judgment: whether any of this moves probability or conviction (it never does automatically), "
        "how to read MIXED or INSUFFICIENT_DATA results, and every causal interpretation.", "",
    ]
    for block, title in SECTIONS.items():
        L += [f"## {title}", ""]
        for s in doc["signals"]:
            if s["block"] == block:
                L += _block(s)
        if block == "C":
            L += ["Four-city high-frequency confirmation only; never national property sales, and city areas are never "
                  "added together.", ""]
        if block == "D":
            L += _block(sig["R3_market_confirmation"]) if "R3_market_confirmation" in sig else []
    L += ["## H0 competing explanations", ""]
    if "R4_h0_competing_explanation" in sig:
        r4 = sig["R4_h0_competing_explanation"]
        c = r4["components"]
        L += [f"**{r4['status']}** — elevates a competing explanation for analyst attention; only a preregistered terminal "
              "rule can falsify the thesis.", ""]
        for k, v in c["flags"].items():
            L.append(f"- {k}: **{v}**")
        L += [f"- public price evidence improving (≥2 of T-H1-01..03 true): {_fmt(c['price_improving'])}",
              f"- apparent nominal improvement (the price tests alone): {_fmt(c['nominal_improving'])}",
              f"- context, public external evidence improving (T-H4-01 and T-H4-02 true; never the nominal premise): "
              f"{_fmt(c['external_improving'])}",
              f"- H0 public context: " + ", ".join(f"{k} {(v or {}).get('outcome', 'n/a')}" for k, v in c["h0_public_context"].items())]
        L += [f"- coverage: {m}" for m in r4["coverage_detail"]] + [""]
    L += ["## H1–H4 relevance", "", "| Hypothesis | Signal | Mapping | Role | Status |", "|---|---|---|---|---|"]
    for h in ("H1", "H2", "H3", "H4", "H0"):
        rows: dict[str, list[dict]] = {}
        for s in doc["signals"]:
            if h in s["mapped_hypotheses"]:
                rows.setdefault(s["signal_id"].split(".")[0], []).append(s)
        for base, ss in rows.items():
            status = ss[0]["status"] if len(ss) == 1 else ", ".join(f"{x['signal_id'].split('.')[1]} {x['status']}" for x in ss)
            L.append(f"| {h} | {base} | {ss[0]['mapped_hypotheses'][h]} | {ss[0]['research_role']} | {status} |")
    L += ["", "No Phase 2 signal is a preregistered evidence test or an input to a terminal rule. H4 remains public-data "
          "driven.", "", "## What changed since previous genuine snapshot", ""]
    if prev["status"] != "COMPARED":
        L += [prev["reason"], ""]
    else:
        L += [f"Previous genuine snapshot: `{prev['file']}` (as of {prev['as_of']}). Both are diagnosed with the same "
              "definitions, each as of its own retrieval time.", "", "| Signal | Before | After | Numeric change |",
              "|---|---|---|---|"]
        for c in doc["changes"]:
            nums = ", ".join(f"{k} {v:+g}" for k, v in c["numeric_change"].items()) or c["note"] or "—"
            L.append(f"| {c['signal_id']} | {c['before']} | {c['after']} | {nums} |")
        L.append("")
    L += ["## What remains unresolved", ""]
    insufficient = [s for s in doc["signals"] if s["status"] == INSUFFICIENT]
    for s in insufficient:
        L.append(f"- {s['signal_id']}: INSUFFICIENT_DATA — " + ("; ".join(s["coverage_detail"]) or "no detail"))
    for s in doc["signals"]:
        if s["status"] != INSUFFICIENT and s["coverage_status"] == "PARTIAL":
            L.append(f"- {s['signal_id']}: partial coverage — " + "; ".join(s["coverage_detail"]))
    L += ["- Consensus (X1) stays EXPERIMENTAL until the release-time validation succeeds; no surprise is computed.",
          "- Lagged transmission (easing at t, response at t+1..t+3) needs genuine snapshots through time; it is not "
          "reconstructed from current-vintage history.", ""]
    L += ["## Data / as-of / coverage caveats", "",
          f"- Information set: {doc['information_set']['rows']} rows ({doc['information_set']['private_rows']} private) "
          f"from {', '.join(doc['information_set']['private_files']) or 'no private file'}; {doc['information_set']['rule']}.",
          "- Provider history inside a publication is current-vintage data: usable for a diagnosis today, never evidence that it "
          "was known earlier. No historical backtest is built from it."]
    for mid, r in (doc.get("routes") or {}).items():
        L.append(f"- route in force at the anchor's time: {mid} → {r['provider']} ({r['series_key']}), effective {r['effective_at']}")
    for p in doc["unverified_snapshots_ignored"]:
        L.append(f"- Ignored (not verified): {p}")
    seen = set()
    for s in doc["signals"]:
        for c in s["caveats"]:
            if c not in seen:
                seen.add(c)
                L.append(f"- {s['signal_id'].split('.')[0]}: {c}")
    return "\n".join(L) + "\n"
