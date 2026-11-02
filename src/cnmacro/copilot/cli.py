"""`python -m cnmacro copilot ...` (docs/runbooks/2026-10-14-live-1.md).

    preflight   readiness for a release, no model call
    context     build and print the bounded context for a release (no model call)
    run         build context, run Draft + Challenge, validate, write the Run Record
    replay      the same, on a historical release in a sandbox (production as-of path)
    blind-take  record the analyst's independent take (must precede `show`)
    show        reveal the validated Copilot read (direction hint only after a blind take)
    decide      record Accept / Edit / Reject / Keep unresolved per section
    verify      is a Run Record intact and reproducible?
    runs        list Run Records

Exit codes of `run` / `replay`: 0 validated, 2 validation failed (record written), 3 model unavailable (record
written; continue manually), 4 no delta / context could not be built (nothing to interpret). Nothing here
touches refresh, the case, the claims, the updates or the site.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

import yaml

from .. import ingest
from . import contract, ops, records, runner
from .context import ContextError, build_context, default_prior, iso_utc, resolve_release
from .llm import DEFAULT_MODEL, DeepSeekClient, FixtureClient, ModelUnavailable
from ..refresh import Paths

ROOT = Path(".")


def _p(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _err(*args) -> None:
    """Progress and replay logs go to stderr so stdout stays one JSON document."""
    print(*args, file=sys.stderr)


@contextlib.contextmanager
def _stdout_to_stderr():
    """The replay builds a site in a subprocess that inherits stdout; keep our stdout a single JSON document."""
    sys.stdout.flush()
    saved = os.dup(1)
    os.dup2(2, 1)
    try:
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)


def _guarded(fn):
    """A refused operation is a message and exit code 1, never a traceback."""
    def run(a) -> int:
        try:
            return fn(a)
        except (records.RecordError, ContextError, FileNotFoundError) as e:
            _p({"status": "refused", "detail": str(e)})
            return 1
    run.__name__ = fn.__name__
    return run


def _client(a):
    """(client, unavailable). A missing credential is an outcome to record, not a crash."""
    if getattr(a, "fixture", None):
        d = Path(a.fixture)
        files = [d / "draft.json"] + ([d / "challenge.json"] if (d / "challenge.json").exists() else [])
        return FixtureClient(files), None
    try:
        effort = None if a.effort == "none" else a.effort
        return DeepSeekClient(a.model, effort=effort, max_tokens=a.max_tokens), None
    except ModelUnavailable as e:
        return None, e


def _exit_code(rec: dict) -> int:
    return {"validated": 0, "validation_failed": 2, "model_error": 3, "model_unavailable": 3}[rec["status"]]


def cmd_preflight(a) -> int:
    rep = ops.preflight(ROOT, a.release, a.now)
    _p(rep)
    return 0 if rep["ready_for_release"] else 1


def _live_context(a):
    ingest.sync_clock(timeout=10)
    paths = Paths.default(ROOT)
    rel = resolve_release(paths.calendar, a.release)
    as_of = iso_utc(a.as_of) if a.as_of else iso_utc(ingest.now_iso())
    prior = iso_utc(a.prior_as_of) if a.prior_as_of else default_prior(rel.release_at)
    return build_context(paths, rel, as_of, prior, copilot_dir=ops.copilot_dir(ROOT), expectation_dir=ops.expectation_dir(ROOT))


def cmd_context(a) -> int:
    try:
        ctx = _live_context(a)
    except ContextError as e:
        _p({"status": "no_context", "detail": str(e)})
        return 4
    if a.out:
        Path(a.out).write_text(json.dumps(ctx, indent=2, ensure_ascii=False), encoding="utf-8")
    _p({"status": "built", "sha256": ctx["sha256"], "as_of": ctx["as_of"], "prior_as_of": ctx["prior_as_of"], "mode": ctx["mode"],
        "allowlist": len(ctx["allowlist"]), "new_observations": [o["ref"] for o in ctx["new_observations"]],
        "mechanical_delta": {h: v["mechanical_delta"] for h, v in ctx["hypotheses"].items()},
        "expectation": (ctx["expectation"] or {}).get("status"), "out": a.out})
    return 0


def cmd_run(a) -> int:
    try:
        ctx = _live_context(a)
    except ContextError as e:
        _p({"status": "no_context", "copilot": "skipped", "detail": str(e),
            "next": "no model call was made. If the release has passed, check that the refresh ingested it (runbook §4)."})
        return 4
    client, unavailable = _client(a)
    rec, _ = runner.run_release(client, ctx, ops.copilot_dir(ROOT), unavailable=unavailable, knowledge_cutoff=a.knowledge_cutoff, log=_err)
    _p(runner.summarize(rec))
    return _exit_code(rec)


def cmd_replay(a) -> int:
    try:
        with _stdout_to_stderr():
            ctx, extra, _ = ops.replay_context(a.release_at, Path(a.out), ROOT, a.data_cutoff, log=_err)
    except ContextError as e:
        _p({"status": "no_context", "detail": str(e)})
        return 4
    if a.context_only:                              # for a human labeller: exactly what the model would see, no model call, no record
        if a.context_out:
            Path(a.context_out).write_text(json.dumps(ctx, indent=2, ensure_ascii=False), encoding="utf-8")
        _p({"status": "context_only", "sha256": ctx["sha256"], "as_of": ctx["as_of"], "mode": ctx["mode"],
            "new_observations": [o["ref"] for o in ctx["new_observations"]],
            "mechanical_delta": {h: v["mechanical_delta"] for h, v in ctx["hypotheses"].items()}, "out": a.context_out})
        return 0
    client, unavailable = _client(a)
    root = Path(a.records) if a.records else ops.copilot_dir(ROOT)
    rec, _ = runner.run_release(client, ctx, root, unavailable=unavailable, knowledge_cutoff=a.knowledge_cutoff, extra=extra, log=_err)
    _p(runner.summarize(rec))
    return _exit_code(rec)


def _run_dir(a) -> Path:
    return records.find_run(ops.copilot_dir(ROOT) if not getattr(a, "records", None) else Path(a.records), a.run_id)


def cmd_blind_take(a) -> int:
    d = _run_dir(a)
    text = Path(a.file).read_text(encoding="utf-8") if a.file else a.text
    if not (text or "").strip():
        print("a blind take is required text (three lines: the most important change, which hypothesis it touches, the direction)", file=sys.stderr)
        return 1
    out = records.append_event(d, "blind_take", {"author": a.author, "text": text.strip()})
    _p({"recorded": out.as_posix(), "next": "commit this file now (git add/commit/push): its commit time is the evidence that it preceded the AI read; then `copilot show`"})
    return 0


def cmd_show(a) -> int:
    d = _run_dir(a)
    rec, ctx = records.load_run(d)
    if rec["status"] != "validated" or not rec.get("rendered"):
        _p({"shown": False, "status": rec["status"], "copilot": rec["copilot"],
            "reason": "only a run that passed every gate may be shown; a failed run has no publishable output",
            "errors": rec["validation"]["errors"][:12]})
        return 2
    have = [e["kind"] for e in records.events(d)]
    if "blind_take" not in have and not a.waive_blind_take:
        print("record your blind take first (`copilot blind-take`), or waive it with --waive-blind-take \"reason\" "
              "(the run is then recorded as not blind and excluded from the marginal-insight measure)", file=sys.stderr)
        return 1
    if "revealed" not in have:
        records.append_event(d, "revealed", {"waived_blind_take": a.waive_blind_take} if "blind_take" not in have else {})
    print(contract.render_markdown(rec["rendered"], ctx, show_hint=True))
    return 0


def cmd_decide(a) -> int:
    d = _run_dir(a)
    rec, _ = records.load_run(d)
    if a.template:
        print(yaml.safe_dump(records.decision_template(rec), sort_keys=False, allow_unicode=True))
        return 0
    doc = yaml.safe_load(Path(a.file).read_text(encoding="utf-8")) or {}
    errs = records.validate_decision(doc, rec)
    if errs:
        _p({"recorded": False, "errors": errs})
        return 1
    if doc["thesis_decision"] == "changed" and not Path(ROOT / "research/cases/cn-nominal" / str(doc["published_update"])).exists() \
            and not Path(doc["published_update"]).exists():
        _p({"recorded": False, "errors": [f"published_update {doc['published_update']!r} does not exist: write the update with `cnmacro update` first"]})
        return 1
    for s, v in (doc.get("sections") or {}).items():
        if v["action"] == "edit":
            v["edit_diff"] = records.edit_diff(records.section_text(rec["rendered"], s), str(v["final_text"]))
    out = records.append_event(d, "decision", {k: doc.get(k) for k in ("thesis_decision", "published_update", "sections", "divergences", "new_vs_blind_take")})
    _p({"recorded": out.as_posix(), "note": "this records the analyst's decision on the Copilot read. The thesis changes only through the analyst's own update file."})
    return 0


def cmd_verify(a) -> int:
    d = _run_dir(a)
    with _stdout_to_stderr():
        res = ops.verify_run(d, ROOT, rebuild=not a.no_rebuild)
    _p(res)
    return 0 if res["ok"] else 1


def cmd_runs(a) -> int:
    base = ops.copilot_dir(ROOT)
    rows = []
    for sub in ("runs", "samples"):
        for p in sorted((base / sub).glob("*/record.json")):
            r = json.loads(p.read_text(encoding="utf-8"))
            rows.append({"run_id": r["run_id"], "where": sub, "kind": r["kind"], "status": r["status"], "mode": r["mode"],
                         "release": r["release"]["name"], "events": [e["kind"] for e in records.events(p.parent)]})
    _p(rows)
    return 0


def register(sub) -> None:
    p = sub.add_parser("copilot", help="Release Copilot v0 (shadow): context, two-pass run, validation, Run Record, analyst decision")
    cs = p.add_subparsers(dest="copilot_cmd", required=True)

    def live(s):
        s.add_argument("--release", required=True, help="a release_calendar.yaml name, e.g. \"September 2026 CPI and PPI\"")
        s.add_argument("--as-of", help="information-set time (default: now)")
        s.add_argument("--prior-as-of", help="state before the release (default: release time minus 60 minutes)")

    def model(s):
        s.add_argument("--model", default=os.environ.get("CNMACRO_COPILOT_MODEL", DEFAULT_MODEL))
        s.add_argument("--effort", default=os.environ.get("CNMACRO_COPILOT_EFFORT", "high"), help="low|medium|high|xhigh|max|none (medium/xhigh map to high)")
        s.add_argument("--max-tokens", type=int, default=int(os.environ.get("CNMACRO_COPILOT_MAX_TOKENS", "24000")),
                       help="output cap per call; adaptive thinking counts against it")
        s.add_argument("--knowledge-cutoff", default=os.environ.get("CNMACRO_COPILOT_KNOWLEDGE_CUTOFF"),
                       help="YYYY-MM, from the vendor's documentation; recorded for the contamination screen")
        s.add_argument("--fixture", help="DIR with draft.json (+ challenge.json): synthetic responses, never a genuine run; written to samples/")

    s = cs.add_parser("preflight"); s.add_argument("--release", required=True); s.add_argument("--now"); s.set_defaults(f=_guarded(cmd_preflight))
    s = cs.add_parser("context"); live(s); s.add_argument("--out"); s.set_defaults(f=_guarded(cmd_context))
    s = cs.add_parser("run"); live(s); model(s); s.set_defaults(f=_guarded(cmd_run))
    s = cs.add_parser("replay"); s.add_argument("--release-at", default="2026-08-09", help="Beijing date of a past release")
    s.add_argument("--out", default="site/replay/copilot"); s.add_argument("--data-cutoff", default="2026-10-04T23:59:59Z")
    s.add_argument("--records", help="where to write the Run Record (default: the case's copilot/ directory)")
    s.add_argument("--context-only", action="store_true", help="build the replay context and stop: no model call, no record (for labelling)")
    s.add_argument("--context-out", help="with --context-only: write the full context JSON here"); model(s); s.set_defaults(f=_guarded(cmd_replay))
    def rid(s):
        s.add_argument("--run-id", required=True)
        s.add_argument("--records", help="copilot/ directory holding the run (default: the case's)")

    s = cs.add_parser("blind-take"); rid(s); s.add_argument("--author", default="analyst")
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--text"); g.add_argument("--file"); s.set_defaults(f=_guarded(cmd_blind_take))
    s = cs.add_parser("show"); rid(s); s.add_argument("--waive-blind-take", metavar="REASON"); s.set_defaults(f=_guarded(cmd_show))
    s = cs.add_parser("decide"); rid(s)
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--template", action="store_true"); g.add_argument("--file"); s.set_defaults(f=_guarded(cmd_decide))
    s = cs.add_parser("verify"); rid(s); s.add_argument("--no-rebuild", action="store_true"); s.set_defaults(f=_guarded(cmd_verify))
    s = cs.add_parser("runs"); s.set_defaults(f=_guarded(cmd_runs))
