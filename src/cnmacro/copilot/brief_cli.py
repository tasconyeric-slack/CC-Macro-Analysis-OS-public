"""`python -m cnmacro copilot brief ...`: the Research Brief (see brief.py).

    pack     deterministic evidence pack for a release (facts, test direction, source links); no model call
    context  build and print the bounded brief context; no model call
    run      Explain + Challenge, gates, Run Record (no credential: recorded as copilot unavailable, exit 3)
    show     print a validated brief (records that it was revealed)
    review   a named person accepts, edits or rejects it (append-only)
    export   the public JSON a page may show: reviewed text, or the evidence pack only
    list     brief Run Records

Exit codes of `run`: 0 validated, 2 validation failed, 3 model unavailable, 4 no context.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import ingest
from ..refresh import Paths
from . import brief, records
from .context import ContextError, default_prior, iso_utc, resolve_release

ROOT = Path(".")
INPUTS = Path("research/cases/cn-nominal/inputs")


def _p(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _bundle(a) -> Path | None:
    if a.bundle == "none":
        return None
    if a.bundle:
        return Path(a.bundle)
    found = sorted((ROOT / INPUTS).glob("*.json"))
    return found[-1] if found else None


def _context(a) -> tuple[dict, Paths]:
    paths = Paths.default(ROOT)
    rel = resolve_release(paths.calendar, a.release)
    as_of = iso_utc(a.as_of) if a.as_of else iso_utc(ingest.now_iso())
    prior = iso_utc(a.prior_as_of) if a.prior_as_of else default_prior(rel.release_at)
    from . import ops
    ctx = brief.build_brief_context(paths, rel, as_of, prior, bundle_path=_bundle(a), copilot_dir=ops.copilot_dir(ROOT),
                                    expectation_dir=ops.expectation_dir(ROOT))
    return ctx, paths


def _root(a) -> Path:
    return Path(a.records) if getattr(a, "records", None) else brief.briefs_dir(ROOT)


def cmd_pack(a) -> int:
    try:
        ctx, paths = _context(a)
    except ContextError as e:
        _p({"status": "no_context", "detail": str(e)})
        return 4
    pack = brief.evidence_pack(ctx, brief.load_dictionary_for(paths))
    if a.markdown:
        print(brief.render_pack_markdown(pack))
    else:
        _p(pack)
    return 0


def cmd_context(a) -> int:
    try:
        ctx, _ = _context(a)
    except ContextError as e:
        _p({"status": "no_context", "detail": str(e)})
        return 4
    if a.out:
        Path(a.out).write_text(json.dumps(ctx, indent=2, ensure_ascii=False), encoding="utf-8")
    _p({"status": "built", "sha256": ctx["sha256"], "as_of": ctx["as_of"], "prior_as_of": ctx["prior_as_of"],
        "allowlist": len(ctx["allowlist"]), "sources": [e["ref"] for e in ctx["allowlist"] if e["kind"] == "source"],
        "new_observations": [o["ref"] for o in ctx["new_observations"]], "out": a.out})
    return 0


def cmd_run(a) -> int:
    from .cli import _client
    try:
        ctx, paths = _context(a)
    except ContextError as e:
        _p({"status": "no_context", "copilot": "skipped", "detail": str(e)})
        return 4
    client, unavailable = _client(a)
    rec, d = brief.run_brief(client, ctx, _root(a), unavailable=unavailable, knowledge_cutoff=a.knowledge_cutoff,
                             review_id=a.review_id, dictionary=brief.load_dictionary_for(paths),
                             log=lambda *x: print(*x, file=sys.stderr))
    _p({"run_id": rec["run_id"], "status": rec["status"], "copilot": rec["copilot"], "kind": rec["kind"], "dir": d.as_posix(),
        "release": rec["release"]["name"], "as_of": rec["as_of"], "sources_cited": len(rec["sources"]),
        "hard_gate_failures": rec["validation"]["hard_gate_failures"],
        "next": "copilot brief show, then copilot brief review --action accept|edit|reject --reviewer <your name>"
                if rec["status"] == "validated" else "the evidence pack is in the record; `copilot brief export` publishes it without AI text"})
    return {"validated": 0, "validation_failed": 2, "model_error": 3, "model_unavailable": 3}[rec["status"]]


def cmd_show(a) -> int:
    d = records.find_run(_root(a), a.run_id)
    rec, ctx = records.load_run(d)
    if rec["status"] != "validated":
        print(brief.render_pack_markdown(rec["evidence_pack"]))
        return 2
    if "revealed" not in [e["kind"] for e in records.events(d)]:
        records.append_event(d, "revealed", {"waived_blind_take": a.waive_blind_take or "brief shown without a blind take"}
                             if "blind_take" not in [e["kind"] for e in records.events(d)] else {})
    print(brief.render_markdown(rec["rendered"], ctx, rec["sources"]))
    return 0


def cmd_review(a) -> int:
    d = records.find_run(_root(a), a.run_id)
    final = Path(a.file).read_text(encoding="utf-8") if a.file else None
    out = brief.review(d, a.action, reviewer=a.reviewer, reason=a.reason or "", final_markdown=final)
    _p({"recorded": out.as_posix(), "note": "a reviewed brief is AI-assisted interpretation, never a signed thesis update"})
    return 0


def cmd_export(a) -> int:
    d = records.find_run(_root(a), a.run_id)
    doc = brief.export_public(d)
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding="utf-8")
        _p({"status": doc["status"], "out": a.out})
    else:
        print(text)
    return 0


def cmd_list(a) -> int:
    rows = []
    for sub in ("runs", "samples"):
        for p in sorted((_root(a) / sub).glob("*/record.json")):
            r = json.loads(p.read_text(encoding="utf-8"))
            rows.append({"run_id": r["run_id"], "where": sub, "kind": r["kind"], "status": r["status"], "release": r["release"]["name"],
                         "events": [e["kind"] for e in records.events(p.parent)]})
    _p(rows)
    return 0


def register(cs, guarded, model) -> None:
    p = cs.add_parser("brief", help="Research Brief: release facts + source-linked news/policy -> Explain + Challenge -> reviewed export")
    bs = p.add_subparsers(dest="brief_cmd", required=True)

    def live(s):
        s.add_argument("--release", required=True, help="a release_calendar.yaml name, e.g. \"2026-10 PPI\"")
        s.add_argument("--as-of", help="information-set time (default: now)")
        s.add_argument("--prior-as-of", help="state before the release (default: release time minus 60 minutes)")
        s.add_argument("--bundle", help="research input bundle JSON (default: the newest under research/cases/cn-nominal/inputs; 'none' for facts only)")

    def rid(s):
        s.add_argument("--run-id", required=True)
        s.add_argument("--records", help="briefs directory (default: research/cases/cn-nominal/copilot/briefs)")

    s = bs.add_parser("pack"); live(s); s.add_argument("--markdown", action="store_true"); s.set_defaults(f=guarded(cmd_pack))
    s = bs.add_parser("context"); live(s); s.add_argument("--out"); s.set_defaults(f=guarded(cmd_context))
    s = bs.add_parser("run"); live(s); model(s); s.add_argument("--records"); s.add_argument("--review-id", help="the thesis review this brief accompanies (e.g. 2026-11-09T0223Z)")
    s.set_defaults(f=guarded(cmd_run))
    s = bs.add_parser("show"); rid(s); s.add_argument("--waive-blind-take", metavar="REASON"); s.set_defaults(f=guarded(cmd_show))
    s = bs.add_parser("review"); rid(s); s.add_argument("--action", required=True, choices=("accept", "edit", "reject"))
    s.add_argument("--reviewer", required=True, help="the person reviewing (automation and models are refused)")
    s.add_argument("--reason"); s.add_argument("--file", help="with --action edit: the final Markdown"); s.set_defaults(f=guarded(cmd_review))
    s = bs.add_parser("export"); rid(s); s.add_argument("--out"); s.set_defaults(f=guarded(cmd_export))
    s = bs.add_parser("list"); s.add_argument("--records"); s.set_defaults(f=guarded(cmd_list))
