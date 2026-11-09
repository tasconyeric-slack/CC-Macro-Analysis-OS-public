"""Command line for the research workflow (see skills/china-macro-research/SKILL.md).

    python -m cnmacro check [--public]
    python -m cnmacro evaluate --as-of 2026-10-13T20:00
    python -m cnmacro fill-claims
    python -m cnmacro preregister --as-of 2026-10-13T20:00
    python -m cnmacro update --as-of 2026-10-14T12:00 --release "September CPI/PPI"
    python -m cnmacro refresh-private --provider wind [--plan]   # local only: named provider(s) -> private observations -> private eval
    python -m cnmacro diagnose-private [--anchor PROVIDER_RUNID | --snapshot RUN_ID]  # local only: one verified anchor -> private diagnostics + report
    python -m cnmacro wind-runtime [--pin]            # verify (or deliberately re-pin) the installed Wind skill; no network
    python -m cnmacro copilot preflight|context|run|replay|blind-take|show|decide|verify|runs   # Release Copilot v0 (shadow); see src/cnmacro/copilot/cli.py
    python -m cnmacro ingest-fred | ingest-nbs [--metric id] | ingest-inbox FILE | nbs-tree [--freq M|Q] [PID] | nbs-indicators CID | nbs-agenda --start --end
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Callable

import yaml

from . import checks, ingest, normalize
from .claims import load_claims, save_claims
from .derive import Deriver
from .evidence import evaluate_test, load_tests, terminal_decision, window_is_open
from .normalize import as_of_routed
from .store import load_dictionary, load_observations, utc_naive
from .thesis import case_files, effective_case, fold

CASE = Path("research/cases/cn-nominal")
DICT = Path("data/dictionary/metrics.yaml")
DEMO_OBS = Path("data/demo/observations")
PRIVATE_OBS = Path("data/private/observations")
WIND_RUNTIME = Path("data/dictionary/wind_runtime.yaml")


def obs_dirs(public_only: bool) -> list[Path]:
    return [DEMO_OBS] if public_only else [DEMO_OBS, PRIVATE_OBS]


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return ""


def load_case() -> dict:
    return yaml.safe_load((CASE / "case.yaml").read_text(encoding="utf-8"))


def run_tests(obs, metrics, case, when) -> dict:
    d = Deriver(as_of_routed(obs, metrics, when), metrics)
    return {t.id: evaluate_test(t, d) for t in load_tests(case["evidence_tests"])}


def evaluate_case(obs, metrics, case, when) -> tuple[dict, str, bool]:
    """(test results, terminal decision, window open) for a case definition as of `when`."""
    d = Deriver(as_of_routed(obs, metrics, when), metrics)
    res = {t.id: evaluate_test(t, d) for t in load_tests(case["evidence_tests"])}
    is_open = window_is_open(case.get("horizon", {}), d, when)
    return res, terminal_decision(case["terminal_rules"], res, is_open), is_open


def case_in_force() -> dict:
    """The preregistered case plus amendments once a baseline exists; the draft before."""
    try:
        return effective_case(CASE)[0]
    except FileNotFoundError:
        return load_case()


def run_checks(metrics, obs, public_only: bool) -> list:
    """The eval gate (E0-E5) over an observation frame. One engine for public and private modes."""
    claims_path = CASE / "claims.jsonl"
    claims = load_claims(claims_path) if claims_path.exists() else []
    return checks.run_all(obs, metrics, claims, CASE, public_only=public_only, dictionary=DICT)


def cmd_check(a) -> int:
    metrics = load_dictionary(DICT)
    obs = load_observations(*obs_dirs(a.public))
    results = run_checks(metrics, obs, a.public)
    checks.write_report(results, CASE / "eval" / ("latest.json" if a.public else "latest-private.json"),
                        "public" if a.public else "private", CASE)
    for c in results:
        print(f"[{c.status.upper():4}] {c.id} {c.name}")
        for dmsg in c.details[:8]:
            print(f"        - {dmsg}")
        if len(c.details) > 8:
            print(f"        ... {len(c.details) - 8} more")
    return 1 if any(c.status == "fail" for c in results) else 0


def cmd_evaluate(a) -> int:
    metrics, case = load_dictionary(DICT), case_in_force()
    obs = load_observations(*obs_dirs(a.public))
    res, terminal, _ = evaluate_case(obs, metrics, case, a.as_of)
    for r in res.values():
        print(f"{r.id:8} {r.hypothesis}  {r.outcome:18} {r.effect:10} observed={r.observed} @ {r.latest_period}")
    print("terminal:", terminal)
    return 0


def cmd_fill_claims(a) -> int:
    metrics = load_dictionary(DICT)
    obs = load_observations(*obs_dirs(a.public))
    path = CASE / "claims.jsonl"
    claims = load_claims(path)
    missing = 0
    for c in claims:
        d = Deriver(as_of_routed(obs, metrics, c.as_of), metrics)
        for name, b in c.values.items():
            pt = d.resolve(b.ref)
            if pt is None:
                missing += 1
                print(f"{c.id}.{name}: {b.ref} not available as of {c.as_of}")
            elif b.recorded is None or a.overwrite:
                b.recorded = round(pt.value, 4)
    save_claims(claims, path)
    print(f"filled {len(claims)} claims; {missing} unresolved")
    return 1 if missing else 0


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


def cmd_preregister(a) -> int:
    pre = CASE / "preregistered"
    if list(pre.glob("*-baseline.yaml")):
        print("A baseline already exists; baselines are immutable. Use `update`.")
        return 1
    draft = yaml.safe_load((CASE / "baseline_draft.yaml").read_text(encoding="utf-8"))
    metrics, case = load_dictionary(DICT), load_case()
    obs = load_observations(*obs_dirs(False))
    res, terminal, _ = evaluate_case(obs, metrics, case, a.as_of)
    cal = yaml.safe_load(Path("data/dictionary/release_calendar.yaml").read_text(encoding="utf-8"))["releases"]
    upcoming = sorted((r for r in cal if utc_naive(r["release"]) > utc_naive(a.as_of)),
                      key=lambda r: utc_naive(r["release"]))
    baseline = {
        "kind": "baseline",
        "as_of": a.as_of,
        "committed_before": {"release": upcoming[0]["name"], "at": upcoming[0]["release"]} if upcoming else None,
        "probability": draft["probability"], "conviction": draft["conviction"],
        "status": "ACTIVE", "last_update_direction": "UNCHANGED",
        "rationale": draft["rationale"],
        "hypothesis_assessment": draft.get("hypothesis_assessment", {}),
        "key_claims": draft.get("key_claims", []),
        "test_results": {k: asdict(v) for k, v in res.items()},
        "terminal_status_at_baseline": terminal,
        "claims_sha256": _sha256(CASE / "claims.jsonl"),
        "case": case,
    }
    pre.mkdir(parents=True, exist_ok=True)
    out = pre / f"{a.as_of[:10]}-baseline.yaml"
    out.write_text(yaml.safe_dump(baseline, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"wrote {out}. Run `check`, then commit it before {baseline['committed_before']}.")
    return 0


def cmd_update(a) -> int:
    metrics = load_dictionary(DICT)
    base_path, updates = case_files(CASE)
    state, history, _ = fold(CASE)
    prev_doc = yaml.safe_load((updates[-1] if updates else base_path).read_text(encoding="utf-8"))
    frozen_case = case_in_force()  # frozen case + preregistered amendments
    obs = load_observations(*obs_dirs(False))
    res, terminal, _ = evaluate_case(obs, metrics, frozen_case, a.as_of)
    prev_res = prev_doc.get("test_results", {})
    flipped = [{"test": k, "from": prev_res.get(k, {}).get("outcome"), "to": r.outcome}
               for k, r in res.items() if prev_res.get(k, {}).get("outcome") != r.outcome]
    slug = re.sub(r"[^a-z0-9]+", "-", a.release.lower()).strip("-")
    out = CASE / "updates" / f"{a.as_of[:10]}-{slug}.yaml"
    if out.exists() and checks.git_history(out):
        print(f"{out} is committed and immutable.")
        return 1
    doc = {
        "kind": "update", "baseline": base_path.name, "as_of": a.as_of, "release": a.release,
        "previous_state": {k: state[k] for k in ("probability", "conviction", "status", "last_update_direction")},
        "test_results": {k: asdict(v) for k, v in res.items()},
        "flipped_tests": flipped,
        "terminal_check": terminal,
        "new_claims": [],
        "does_this_change_the_thesis": "TODO: one paragraph, citing claim ids.",
        "does_this_change_the_thesis_zh": "TODO: the same paragraph in Chinese (the Chinese site shows it; without it the page falls back to English and says so).",
        "probability": state["probability"], "conviction": state["conviction"],
        "status": state["status"], "last_update_direction": "UNCHANGED",
        "probability_change": None, "terminal_rule_fired": None,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"scaffolded {out}; {len(flipped)} test(s) changed outcome.")
    return 0


def cmd_refresh_public(a) -> int:
    from .refresh import Paths, fetch_live, refresh_public
    ingest.sync_clock(timeout=10)
    paths = Paths.default()
    if a.no_build:
        paths.site_out = None
    # NBS first prints (CPI/PPI and GDP/activity) precede updates on its historical data portal.
    fetcher = ingest.with_nbs_release(lambda *args: fetch_live(*args, paths.root))
    r = refresh_public(paths, now=a.now, fetcher=fetcher, force_all=a.all, dry_run=a.dry_run,
                       use_agenda=not a.no_agenda)
    # Operational freshness is computed after research-engine execution so that
    # the frozen engine and preregistered thesis state remain byte-identical.
    from .firstprint import official_release_freshness
    from .refresh import full_calendar
    from .store import load_observations, utc_naive
    calendar, _ = full_calendar(paths, utc_naive(r.as_of), use_agenda=not a.no_agenda)
    freshness = official_release_freshness(r.due, load_observations(paths.obs_dir),
                                           calendar, utc_naive(r.as_of))
    summary = {"status": r.status, "as_of": r.as_of, "new_rows": r.new_rows, "record": r.record,
               "terminal_update": r.terminal_update, "flipped": [f["test"] for f in r.flipped],
               "sources": r.sources, "eval": r.eval_status, "freshness": freshness}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if a.summary:
        Path(a.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    if r.status == "eval_failed":
        return 1
    if any(not s.get("ok") for s in r.sources.values()) and a.strict:
        return 2
    return 0


def _wind_failure(f) -> int:
    print(json.dumps({"status": "failed", "error": f.code, "message": f.detail, "details": f.details},
                     indent=2, ensure_ascii=False))
    return 1


def cmd_wind_runtime(a) -> int:
    """Compare the installed Wind skill with the pinned runtime contract. Local files only: no Wind call."""
    from . import wind
    runtime = wind.load_runtime(WIND_RUNTIME)
    try:
        reading = wind.read_runtime(wind.locate_skill_dir(), runtime)
    except wind.WindFailure as f:
        return _wind_failure(f)
    diffs = wind.runtime_differences(reading, runtime)
    status = "match" if not diffs else "drift"
    if diffs and a.pin:
        wind.pin_runtime(WIND_RUNTIME, reading)
        status, diffs = "pinned", []
        print(f"re-pinned {WIND_RUNTIME}; review the diff and commit it. Every later run is checked against it.", file=sys.stderr)
    print(json.dumps({"status": status, "installed_version": reading.version, "pinned_version": runtime.version,
                      "files": sorted(runtime.files), "differences": diffs}, indent=2, ensure_ascii=False))
    return 0 if not diffs else 1


def private_eval(metrics, now: str) -> dict:
    """The existing private eval path over public + private observations. Read-only: it writes no
    tracked file, changes no thesis state and builds nothing."""
    obs = load_observations(*obs_dirs(False))
    results = run_checks(metrics, obs, public_only=False)
    tests, terminal, _ = evaluate_case(obs, metrics, case_in_force(), now)
    overall = "fail" if any(c.status == "fail" for c in results) else "warn" if any(c.status == "warn" for c in results) else "pass"
    return {"overall": overall, "checks": {c.id: c.status for c in results},
            "details": {c.id: c.details for c in results if c.details},
            "terminal": terminal, "tests": {k: r.outcome for k, r in tests.items()}}


# ---------------------------------------------------------------- refresh-private: select, sequence and report adapters
@dataclass(frozen=True)
class Adapter:
    """One provider `refresh-private` can run. This table is the whole registry: no discovery, no plug-in loader.
    An adapter does its own runtime check, budget, atomic publication and manifest; the command only selects,
    sequences and reports. `default` adapters run when no --provider is named, so only a free one should be; an adapter
    that spends paid credits is opt-in and runs only when it is named."""
    plan: Callable[[dict], dict]        # (metrics) -> {"status": "plan", ...}; verifies what it can, makes no provider call
    refresh: Callable[[dict], dict]     # (metrics) -> {"status": "refreshed" | "failed", ...}; fetches and publishes
    default: bool = False


def _failed(code: str, message: str = "", **extra) -> dict:
    return {"status": "failed", "error": code, "message": message, **extra}


def _wind_plan(metrics: dict) -> dict:
    from . import wind
    runtime = wind.load_runtime(WIND_RUNTIME)
    try:
        plan = wind.plan_groups(metrics, runtime)
        reading = wind.verify_runtime(wind.locate_skill_dir(), runtime, "plan")
    except ValueError as e:
        return _failed("WIND_CONTRACT_INVALID", str(e), details=[])
    except wind.WindFailure as f:
        return _failed(f.code, f.detail, details=f.details)
    return {"status": "plan", "runtime_version": reading.version, "runtime": "match", "calls": len(plan),
            "max_calls": runtime.call_budget,
            "groups": [{"group": g.name, "tool": g.tool, "metrics": list(g.metric_ids)} for g in plan]}


def _wind_refresh(metrics: dict) -> dict:
    from . import wind
    out = wind.run_refresh(metrics, wind.load_runtime(WIND_RUNTIME))
    raw_dir = (wind.RUNS_DIR / out.run_id).as_posix()
    if out.status != "published":
        return {"status": "failed", "run_id": out.run_id, "error": out.error["code"], "group": out.error.get("group"),
                "calls": out.calls, "published": False, "raw_dir": raw_dir}
    return {"status": "refreshed", "run_id": out.run_id, "calls": out.calls, "metrics": out.metrics,
            "private_rows": out.rows, "runtime_version": normalize.runtime_version(out.manifest),
            "snapshot": out.manifest["publication"]["file"], "raw_dir": raw_dir}


# Wind spends paid credits, so it is opt-in: it runs only when named (`--provider wind`).
ADAPTERS: dict[str, Adapter] = {"wind": Adapter(plan=_wind_plan, refresh=_wind_refresh, default=False)}


def _default_providers(metrics: dict) -> list[str]:
    """What runs with no --provider: default adapters that have a route active now, or a candidate route marked
    `collect`, whose access permits automated retrieval. (No record is future-dated, so the last record is in force.)"""
    out = []
    for name, adapter in ADAPTERS.items():
        if adapter.default and any(
                r.provider == name and (r.collect or (m.route_history and m.route_history[-1].active == name))
                and r.access.permits("automated_retrieval") for m in metrics.values() for r in m.sources):
            out.append(name)
    return out


def _refuse(code: str, message: str) -> int:
    print(json.dumps({"status": "failed", "error": code, "message": message, "available": sorted(ADAPTERS)},
                     indent=2, ensure_ascii=False))
    return 1


def _print_results(results: list[dict], ok: str) -> None:
    """One provider prints as itself; several print under `providers`."""
    if len(results) == 1:
        print(json.dumps(results[0], indent=2, ensure_ascii=False))
        return
    failed = [r for r in results if r["status"] == "failed"]
    status = "failed" if len(failed) == len(results) else "partial" if failed else ok
    print(json.dumps({"status": status, "providers": results}, indent=2, ensure_ascii=False))


def cmd_refresh_private(a) -> int:
    """Local only. For each selected provider (`--provider P ...`): verify its runtime, fetch its routes, validate the
    whole batch and publish immutably; then run the private eval once over public + private observations.

    With no `--provider`, only default adapters run (none is: Wind spends paid credits and runs only when named).
    One provider failing publishes nothing for it and leaves the others untouched.

    Not here, by design: no public site build, no tracked refresh record, no thesis or probability change,
    no write into data/demo, and no GitHub Actions."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(json.dumps({"status": "failed", "error": "PRIVATE_REFRESH_IS_LOCAL_ONLY",
                          "message": "refresh-private needs a local provider runtime, key and private data; it never runs in CI"}, indent=2))
        return 1
    metrics = load_dictionary(DICT)
    named = list(dict.fromkeys(a.provider or []))
    unknown = [p for p in named if p not in ADAPTERS]
    if unknown:
        return _refuse("UNKNOWN_PROVIDER", f"no adapter for: {', '.join(unknown)}")
    selected = named or _default_providers(metrics)
    if not selected:
        return _refuse("NO_PROVIDER_SELECTED", "no provider runs by default; name one: refresh-private --provider "
                       + "|".join(sorted(ADAPTERS)) + " (Wind spends paid credits, so it runs only when named)")
    if a.plan:
        results = [{"provider": p, **ADAPTERS[p].plan(metrics)} for p in selected]
        _print_results(results, "plan")
        return 1 if any(r["status"] == "failed" for r in results) else 0
    ingest.sync_clock(timeout=10)
    results = [{"provider": p, **ADAPTERS[p].refresh(metrics)} for p in selected]
    published = [r for r in results if r["status"] == "refreshed"]
    ev = None
    if published:
        now = ingest.now_iso()
        try:
            ev = private_eval(metrics, now)
        except Exception as e:                  # the snapshots are already published; say so, and report the eval honestly
            ev = {"overall": "error", "checks": {}, "details": {}, "terminal": None, "tests": {}, "error": type(e).__name__}
        for r in published:
            r.update(eval=ev["overall"], checks=ev["checks"])
            (Path(r["raw_dir"]) / "summary.json").write_text(
                json.dumps({**r, "evaluated_at": now, "eval_detail": ev}, indent=2, ensure_ascii=False), encoding="utf-8")
    _print_results(results, "refreshed")
    if any(r["status"] == "failed" for r in results):
        return 1
    return 2 if ev and ev["overall"] in ("fail", "error") else 0


def cmd_diagnose_private(a) -> int:
    """Local only. Diagnose one immutable, verified private anchor (default: the newest eligible) with the frozen
    signal contract. Acquisition stays in refresh-private; this makes no provider call and changes no tracked file,
    thesis state or public output. Prints classes, never values."""
    from . import diagnose, signals
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(json.dumps({"status": "failed", "error": "PRIVATE_DIAGNOSIS_IS_LOCAL_ONLY",
                          "message": "diagnose-private reads licensed private data; it never runs in CI"}, indent=2))
        return 1
    metrics = load_dictionary(DICT)
    try:
        contract = signals.load_signal_contract(signals.SIGNALS_CONTRACT, metrics)
        summary = diagnose.run(".", metrics, contract, case_in_force(), anchor=a.anchor, snapshot=a.snapshot)
    except ValueError as e:
        print(json.dumps({"status": "failed", "error": "SIGNAL_CONTRACT_INVALID", "message": str(e)}, indent=2, ensure_ascii=False))
        return 1
    except diagnose.DiagnoseFailure as f:
        print(json.dumps({"status": "failed", "error": f.code, "message": f.detail}, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def replay_site_complete(pages: list[str]) -> bool:
    """The replayed site has the same six pages in each language (plus the root selector)."""
    per = {loc: {p.split("/", 1)[1] for p in pages if p.startswith(loc + "/")} for loc in ("en", "zh")}
    return len(per["en"]) == 6 and per["en"] == per["zh"] and "index.html" in pages


def cmd_replay(a) -> int:
    from .replay import replay
    rep = replay(a.release_at, Path(a.out), data_cutoff=a.data_cutoff)
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    ok = (rep["refresh"]["status"] == "refreshed" and rep["refresh"]["flipped"] and rep["refresh"]["record"]
          and rep["rerun"]["status"] == "no_new_data" and replay_site_complete(rep["site_pages"]))
    return 0 if ok else 1


def cmd_ingest_fred(a) -> int:
    ingest.sync_clock()
    metrics = load_dictionary(DICT)
    cal = ingest.load_calendar()
    for m in metrics.values():
        if m.source_primary == "FRED" and (not a.metric or m.metric_id == a.metric):
            print(m.metric_id, ingest.ingest_fred(m, DEMO_OBS, a.start, cal), "rows")
    return 0


def cmd_ingest_nbs(a) -> int:
    ingest.sync_clock()
    metrics = load_dictionary(DICT)
    cal = ingest.load_calendar()
    if a.agenda:
        # official release dates from the NBS agenda; verified yaml entries take precedence
        agenda, conflicts = ingest.agenda_calendar(f"{a.start[:4]}-01-01", date.today().isoformat())
        for c in conflicts:
            print(f"agenda conflict skipped: {c}")
        cal = {**agenda, **cal}
    for m in metrics.values():
        if (m.source_primary == "NBS" or (m.source_code or "").startswith("nbs:")) and (not a.metric or m.metric_id == a.metric):
            if (m.source_code or '').startswith('nbs-release:'):
                print(f"skip {m.metric_id}: use scripts/fetch_price_releases.py for official release tables")
                continue
            if not m.source_code:
                print(f"skip {m.metric_id}: no NBS code yet")
                continue
            print(m.metric_id, ingest.ingest_nbs(m, DEMO_OBS, cal, a.start), "rows")
    return 0


def cmd_ingest_inbox(a) -> int:
    ingest.sync_clock()
    pub, priv = ingest.ingest_inbox(Path(a.file), load_dictionary(DICT), ingest.load_calendar())
    print(f"public rows: {pub} -> data/demo/observations ; private rows: {priv} -> data/private/observations")
    return 0


def cmd_nbs_agenda(a) -> int:
    for fb, name in ingest.nbs_agenda(a.start, a.end):
        mapped = next(((m, ingest._agenda_period(fb, r)) for p, m, r in ingest.AGENDA_MAP if name.startswith(p)), None)
        print(fb, name, "->", f"{mapped[1]} {','.join(mapped[0])}" if mapped and mapped[1] else "-")
    return 0


def cmd_nbs_tree(a) -> int:
    for n in ingest.nbs_tree(a.freq, a.pid):
        print(n["_id"], n["name"].strip(), "(leaf)" if n.get("isLeaf") else "")
    return 0


def cmd_nbs_indicators(a) -> int:
    for n in ingest.nbs_indicators(a.cid):
        print(n["_id"], n["i_showname"].strip(), "|", n.get("dp_name"), "|", n.get("du_name"))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="cnmacro")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("check"); s.add_argument("--public", action="store_true"); s.set_defaults(f=cmd_check)
    s = sub.add_parser("evaluate"); s.add_argument("--as-of", required=True); s.add_argument("--public", action="store_true"); s.set_defaults(f=cmd_evaluate)
    s = sub.add_parser("fill-claims"); s.add_argument("--public", action="store_true"); s.add_argument("--overwrite", action="store_true"); s.set_defaults(f=cmd_fill_claims)
    s = sub.add_parser("preregister"); s.add_argument("--as-of", required=True); s.set_defaults(f=cmd_preregister)
    s = sub.add_parser("update"); s.add_argument("--as-of", required=True); s.add_argument("--release", required=True); s.set_defaults(f=cmd_update)
    s = sub.add_parser("refresh-public", help="fetch due public data, append new rows, re-test, eval, rebuild site")
    s.add_argument("--now", help="override the clock (ISO time); for replays and tests")
    s.add_argument("--all", action="store_true", help="fetch every public route, not only metrics that are due")
    s.add_argument("--dry-run", action="store_true", help="fetch and diff, write nothing")
    s.add_argument("--no-agenda", action="store_true", help="do not extend the calendar from the NBS agenda")
    s.add_argument("--no-build", action="store_true")
    s.add_argument("--strict", action="store_true", help="exit 2 if any source failed")
    s.add_argument("--summary", help="write the JSON summary here")
    s.set_defaults(f=cmd_refresh_public)
    s = sub.add_parser("refresh-private", help="LOCAL ONLY: fetch the named provider(s), publish private snapshots, run the private eval")
    s.add_argument("--provider", action="extend", nargs="+", metavar="P",
                   help="provider(s) to run, in order; Wind spends paid credits, so it runs only when named (--provider wind)")
    s.add_argument("--plan", action="store_true", help="verify each provider's runtime and show its call plan; make no provider call, write nothing")
    s.set_defaults(f=cmd_refresh_private)
    s = sub.add_parser("diagnose-private", help="LOCAL ONLY: deterministic private diagnostics and report for one verified anchor")
    s.add_argument("--anchor", help="<provider>_<run_id> of a verified active publication; default: the newest eligible anchor")
    s.add_argument("--snapshot", help="alias for a Wind anchor: the run id of wind_<run_id>.csv")
    s.set_defaults(f=cmd_diagnose_private)
    s = sub.add_parser("wind-runtime", help="compare the installed Wind skill with the pinned runtime contract (no network)")
    s.add_argument("--pin", action="store_true", help="rewrite the contract to match the installed skill (review and commit the diff)")
    s.set_defaults(f=cmd_wind_runtime)
    s = sub.add_parser("replay", help="sandbox replay of a past official release through the refresh path")
    s.add_argument("--release-at", default="2026-08-09", help="Beijing date (or time) of a past release")
    s.add_argument("--out", default="site/replay")
    s.add_argument("--data-cutoff", default="2026-10-04T23:59:59Z")
    s.set_defaults(f=cmd_replay)
    s = sub.add_parser("ingest-fred"); s.add_argument("--metric"); s.add_argument("--start", default="2015-01-01"); s.set_defaults(f=cmd_ingest_fred)
    s = sub.add_parser("ingest-nbs"); s.add_argument("--metric"); s.add_argument("--start", default="2019-01"); s.add_argument("--agenda", action="store_true", help="fill release_date from the NBS release agenda"); s.set_defaults(f=cmd_ingest_nbs)
    s = sub.add_parser("nbs-agenda"); s.add_argument("--start", required=True); s.add_argument("--end", required=True); s.set_defaults(f=cmd_nbs_agenda)
    s = sub.add_parser("ingest-inbox"); s.add_argument("file"); s.set_defaults(f=cmd_ingest_inbox)
    s = sub.add_parser("nbs-tree"); s.add_argument("--freq", default="M", choices=["M", "Q"]); s.add_argument("pid", nargs="?", default=""); s.set_defaults(f=cmd_nbs_tree)
    s = sub.add_parser("nbs-indicators"); s.add_argument("cid"); s.set_defaults(f=cmd_nbs_indicators)
    from .copilot import cli as copilot_cli          # imported here only: refresh / replay never import the Copilot
    copilot_cli.register(sub)
    from .events import cli as events_cli
    events_cli.register(sub)
    from . import policy_cli
    policy_cli.register(sub)
    a = p.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
