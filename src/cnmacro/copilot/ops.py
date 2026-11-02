"""Operations around a run: replay on the production path, verify a Run Record, preflight the release day.

None of this writes to the preregistered case, the observation store, claims, updates or the site. The
replay is `replay.replay` unchanged (a sandbox on the same `as_of` path as production) followed by the
same Context Builder and Copilot as a live release (strategy §10.1, D-05).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

from .. import checks, ingest, replay as replay_mod
from ..claims import load_claims
from ..refresh import Paths, due_metrics, full_calendar, held_latest, route
from ..store import load_dictionary, load_observations, release_time, utc_naive
from ..thesis import case_files, load_yaml
from . import contract, records
from .context import ContextError, ReleaseSpec, build_context, context_hash, resolve_release

CASE = Path("research/cases/cn-nominal")


def copilot_dir(root: Path = Path(".")) -> Path:
    return Path(root) / CASE / "copilot"


def expectation_dir(root: Path = Path(".")) -> Path:
    return Path(root) / CASE / "expectations"


# ---------------------------------------------------------------- replay on the production path
def sandbox_paths(sb: Path) -> Paths:
    sb = Path(sb)
    return Paths(root=sb, case_dir=sb / "case", obs_dir=sb / "observations", dictionary=sb / "dictionary.yaml",
                 calendar=sb / "calendar.yaml", site_out=None)


def replay_context(release_at: str, out: Path, root: Path = Path("."), data_cutoff: str = "2026-10-04T23:59:59Z",
                   log=print) -> tuple[dict, dict, dict]:
    """(context, extra record fields, replay report). The sandbox is replay.replay's, untouched."""
    out = Path(out)
    if out.exists() and (not (out / "replay-report.json").exists() or out.resolve() in (Path(root).resolve(), *Path(root).resolve().parents)):
        raise ContextError(f"{out} exists and is not a previous replay sandbox; replay.replay deletes its --out directory, so this is refused")
    rep = replay_mod.replay(release_at, out, root=Path(root), data_cutoff=data_cutoff, log=log)
    if rep["refresh"]["status"] != "refreshed":
        raise ContextError(f"the replay did not refresh ({rep['refresh']['status']}): nothing to interpret")
    arrived = [a.split("@") for a in rep["arrived"]]
    rel = ReleaseSpec(f"replay-{release_at}", f"replay of official release(s) on {release_at}",
                      ",".join(sorted({p for _, p in arrived})), release_at, sorted({m for m, _ in arrived}))
    ctx = build_context(sandbox_paths(out), rel, rep["after"], rep["before"])
    extra = {"replay": {"release_at": release_at, "data_cutoff": data_cutoff, "sandbox": str(out),
                        "refresh_record": rep["refresh"]["record"], "arrived": rep["arrived"],
                        "eval_eligible": False,
                        "eval_ineligible_reason": "no human labels were committed before this run (strategy §11.1); exploratory only"}}
    return ctx, extra, rep


# ---------------------------------------------------------------- verify
def rebuild_context(rec: dict, root: Path = Path(".")) -> dict:
    """The context rebuilt from the store (live) or from a fresh sandbox replay, for the same as_of."""
    if rec["mode"] == "replay":
        rp = rec["replay"]
        with tempfile.TemporaryDirectory() as tmp:
            ctx, _, _ = replay_context(rp["release_at"], Path(tmp) / "sb", root, rp["data_cutoff"], log=lambda *_: None)
        return ctx
    paths = Paths.default(root)
    return build_context(paths, ReleaseSpec(**rec["release"]), rec["as_of"], rec["prior_as_of"],
                         copilot_dir=copilot_dir(root), expectation_dir=expectation_dir(root))


def verify_run(d: Path, root: Path = Path("."), rebuild: bool = True) -> dict:
    """Is this Run Record intact and reproducible? Each line is a named check with a boolean."""
    rec, ctx = records.load_run(d)
    out: dict[str, object] = {}
    out["context_file_matches_recorded_hash"] = context_hash(ctx) == rec["context"]["sha256"]
    out["allowlist_matches_recorded_ids"] = sorted(e["ref"] for e in ctx["allowlist"]) == rec["context"]["evidence_allowlist"]
    if rebuild:
        try:
            out["context_rebuilds_to_same_hash"] = context_hash(rebuild_context(rec, root)) == rec["context"]["sha256"]
        except Exception as e:      # an honest "cannot say" is a failure of reproducibility, not a pass
            out["context_rebuilds_to_same_hash"] = f"not verified: {type(e).__name__}: {e}"
    errors_now = []
    for p in rec["passes"]:
        if p.get("parsed") is not None:
            v = contract.validate_draft if p["name"] == "draft" else contract.validate_challenge
            errors_now += [e.as_dict() for e in v(p["parsed"], ctx)]
    recorded = [{k: e[k] for k in ("gate", "path", "message")} for e in rec["validation"]["errors"] if e["pass"] in ("draft", "challenge")]
    out["validation_replays_to_same_outcome"] = errors_now == recorded
    if rec.get("result"):
        by = {p["name"]: p["parsed"] for p in rec["passes"]}
        again = contract.assemble(ctx, by["draft"], by["challenge"])
        out["result_is_the_assembly_of_the_validated_passes"] = again == rec["result"]
        out["rendering_replays_to_same_text"] = contract.render(again, ctx) == rec["rendered"]
        out["mechanical_delta_untouched"] = all(h["mechanical_delta"] == ctx["hypotheses"][h["hypothesis"]]["mechanical_delta"]
                                                for h in rec["result"]["hypothesis_impact"])
    problems = records.verify_chain(d)
    out["event_chain_and_git_immutability"] = problems or True
    out["ok"] = all(v is True for v in out.values())
    return out


# ---------------------------------------------------------------- preflight (release day readiness, no model call)
def preflight(root: Path, release_name: str, now: str | None = None) -> dict:
    root = Path(root)
    now_s = now or ingest.now_iso()
    t_now = utc_naive(now_s)
    items: list[dict] = []

    def add(cid: str, status: str, detail: str) -> None:
        items.append({"id": cid, "status": status, "detail": detail})

    add("python", "pass" if sys.version_info >= (3, 14) else "fail",
        f"{sys.version.split()[0]} (the project requires 3.14: pyproject.toml requires-python)")
    paths = Paths.default(root)
    try:
        rel = resolve_release(paths.calendar, release_name)
    except ContextError as e:
        add("calendar", "fail", str(e))
        return _report(release_name, now_s, items)
    t_rel = release_time(rel.release_at)
    raw = next(r for r in load_yaml_calendar(paths.calendar) if r["name"] == rel.name)
    hrs = (t_rel - t_now) / pd.Timedelta(hours=1)
    add("calendar", "pass" if raw.get("verified_on") else "warn",
        f"{rel.name}: {rel.release_at}; verified_on {raw.get('verified_on')}; {hrs:+.1f} h from now ({'pending' if hrs > 0 else 'released'})")
    metrics = load_dictionary(paths.dictionary)
    obs = load_observations(paths.obs_dir)
    cal, note = full_calendar(paths, t_now, use_agenda=False)
    rows, bad = [], []
    for mid in rel.metrics:
        m = metrics.get(mid)
        if m is None or m.redistribution != "public" or not route(m):
            bad.append(mid)
            continue
        held = held_latest(obs, m)
        rows.append(f"{mid}: held {held}, want {rel.period}{' (already in the store)' if held is not None and str(held) >= rel.period else ''}")
    add("refresh_routes", "fail" if bad else "pass",
        ("not fetchable by the public refresh: " + ", ".join(bad)) if bad else "every release metric has a public route; " + "; ".join(rows))
    due = due_metrics(metrics, obs, cal, t_now)
    add("refresh_due_now", "pass", f"{len(due)} metric(s) due at this clock ({note}): {sorted(due)[:8]}")
    refs = sorted((root / CASE / "refreshes").glob("*.json"))
    last = json.loads(refs[-1].read_text(encoding="utf-8"))["as_of"] if refs else None
    add("last_refresh_record", "pass" if last else "warn", f"{refs[-1].name if refs else 'none'} (as_of {last})")
    claims_path = root / CASE / "claims.jsonl"
    results = checks.run_all(obs, metrics, load_claims(claims_path), root / CASE, public_only=True)
    st = {c.id: c.status for c in results}
    add("eval_gate_E0_E5", "fail" if "fail" in st.values() else "pass", json.dumps(st))
    base_path, _ = case_files(root / CASE)
    commits = checks.git_history(base_path)
    add("baseline_frozen", "pass" if len(commits) == 1 else "fail" if len(commits) > 1 else "warn",
        f"{base_path.name}: {len(commits)} commit(s) in history (must be 1); sha256 "
        f"{records.sha256_bytes(base_path.read_bytes())[:16]}")
    exp = next((f for f in sorted(expectation_dir(root).glob("*.yaml")) if not f.name.startswith("_")
                and (load_yaml(f) or {}).get("release") == rel.name), None) if expectation_dir(root).exists() else None
    if exp is None:
        add("expectation_note", "warn",
            "none found: freeze one (docs/runbooks/2026-10-14-live-1.md §2) and commit it before the release; "
            "it cannot be created afterwards. Without it the Copilot runs with vs_expectation = not_set")
    else:
        c = records.git_commits(exp)
        t_c = checks.commit_time(c[-1]) if c else None
        ok = bool(c) and len(c) == 1 and t_c is not None and t_c < t_rel
        add("expectation_note", "pass" if ok else "warn",
            f"{exp.name}: {'frozen (one commit, before the release)' if ok else 'NOT frozen (uncommitted, edited, or committed after the release) and will be excluded from the context'}")
    key = bool(os.environ.get("DEEPSEEK_API_KEY"))
    add("copilot_credential", "pass" if key else "warn",
        "DEEPSEEK_API_KEY is set" if key else "DEEPSEEK_API_KEY is not set: `copilot: unavailable`. The refresh, the evidence record and manual publication are unaffected")
    cdir = copilot_dir(root)
    base = cdir if cdir.exists() else next(p for p in cdir.parents if p.exists())
    add("run_record_store", "pass" if os.access(base, os.W_OK) else "fail",
        f"{cdir.as_posix()} {'exists and ' if cdir.exists() else 'will be created; '}{base.as_posix()} is {'writable' if os.access(base, os.W_OK) else 'NOT writable'}")
    if hrs > 0:
        add("context_dry_run", "pass", "pre-release: no delta can exist yet. After the refresh ingests the release, `copilot context` shows the delta without a model call")
    else:
        try:
            ctx = build_context(paths, rel, now_s, None, copilot_dir=cdir, expectation_dir=expectation_dir(root))
            add("context_dry_run", "pass", f"{len(ctx['allowlist'])} allowlisted ids, {len(json.dumps(ctx))} bytes, "
                                           f"{len(ctx['new_observations'])} new observation(s), sha256 {ctx['sha256'][:12]}")
        except ContextError as e:
            add("context_dry_run", "warn", f"no delta: {e}. The release has passed: has the refresh ingested it? (runbook §4)")
    return _report(rel.name, now_s, items)


def load_yaml_calendar(p: Path) -> list[dict]:
    import yaml
    return yaml.safe_load(Path(p).read_text(encoding="utf-8"))["releases"]


def _report(release: str, now: str, items: list[dict]) -> dict:
    cred = next((i for i in items if i["id"] == "copilot_credential"), None)
    return {"release": release, "now": now, "ready_for_release": not any(i["status"] == "fail" for i in items),
            "copilot": "ready" if cred and cred["status"] == "pass" else "unavailable",
            "deterministic_pipeline_depends_on_copilot": False, "checks": items}
