"""Run Records: append-only, one directory per model run.

    <copilot_dir>/runs/<run_id>/record.json      the model run (written once)
                                context.json     exactly what the model was shown (written once)
                                events/NNNN-<kind>.json   analyst events, each written once, hash-chained

Nothing is ever rewritten: a file is created with exclusive mode and an existing one is an error. The
events chain by `prev_sha256` (record.json, then each event file), so a later edit to anything earlier is
detectable by `verify`. A run is genuine only if a real model call produced it; fixture runs are
rejected from `runs/` and live in `samples/`, so synthetic output can never enter the evaluation set.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import secrets
import subprocess
from pathlib import Path

import pandas as pd

from .. import ingest
from ..store import utc_naive

EVENT_KINDS = ("blind_take", "revealed", "decision")
ACTIONS = ("accept", "edit", "reject", "keep_unresolved")
SECTIONS = ("executive_delta", "hypothesis_impact", "competing_explanation", "does_not_prove",
            "research_needs", "draft_analyst_update")


class RecordError(ValueError):
    pass


def git_commits(path: Path) -> list[str]:
    """Commits that touched exactly this path, newest first. Deliberately no --follow: git's rename heuristic would lend
    a new file the history of a similar deleted or copied one, and "committed exactly once" must mean this path's own."""
    try:
        return subprocess.check_output(["git", "log", "--format=%H", "--", str(path)], text=True, stderr=subprocess.DEVNULL).split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True, default=str)


def _write_once(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8", newline="\n") as f:      # "x": never overwrite
        f.write(text)


def run_dir(root: Path, run_id: str, genuine: bool) -> Path:
    return Path(root) / ("runs" if genuine else "samples") / run_id


def find_run(root: Path, run_id: str) -> Path:
    for sub in ("runs", "samples"):
        p = Path(root) / sub / run_id
        if (p / "record.json").exists():
            return p
    raise RecordError(f"no run record {run_id!r} under {root}")


def new_run_id(run_at: str, context_sha: str) -> str:
    """Time, context and a random tail: two runs on one context can never collide, so a paid-for answer is never lost to a name clash."""
    return f"{utc_naive(run_at).strftime('%Y%m%dT%H%M%SZ')}-{context_sha[:8]}-{secrets.token_hex(2)}"


def write_run(root: Path, record: dict, context: dict) -> Path:
    """Persist a run. A fixture run goes to samples/ and nowhere else; every other kind (a real model run,
    a failed one, a recorded outage) goes to runs/. Synthetic output can therefore never enter the evaluation set."""
    d = run_dir(root, record["run_id"], record["kind"] != "fixture")
    if d.exists():
        raise RecordError(f"{d} exists; run records are append-only")
    _write_once(d / "context.json", _dump(context) + "\n")
    _write_once(d / "record.json", _dump(record) + "\n")
    return d


def load_run(d: Path) -> tuple[dict, dict]:
    d = Path(d)
    return (json.loads((d / "record.json").read_text(encoding="utf-8")),
            json.loads((d / "context.json").read_text(encoding="utf-8")))


def events(d: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((Path(d) / "events").glob("*.json"))]


def _chain_tip(d: Path) -> str:
    files = sorted((Path(d) / "events").glob("*.json"))
    return sha256_bytes((files[-1] if files else Path(d) / "record.json").read_bytes())


def append_event(d: Path, kind: str, payload: dict, at: str | None = None) -> Path:
    """Add one analyst event. Order is enforced: blind take, then reveal, then decision."""
    if kind not in EVENT_KINDS:
        raise RecordError(f"unknown event kind {kind!r}")
    have = [e["kind"] for e in events(d)]
    if kind in have:
        raise RecordError(f"a {kind} is already recorded for this run; events are append-only and never replaced")
    if kind == "revealed" and "blind_take" not in have and not payload.get("waived_blind_take"):
        raise RecordError("record the analyst's blind take before the Copilot output is shown "
                          "(or waive it explicitly with a reason: the run then counts as not blind)")
    if kind == "decision" and "revealed" not in have:
        raise RecordError("a decision needs the output to have been shown (`copilot show`) first")
    n = len(have) + 1
    doc = {"kind": kind, "at": at or ingest.now_iso(), "prev_sha256": _chain_tip(d), **payload}
    out = Path(d) / "events" / f"{n:04d}-{kind}.json"
    _write_once(out, _dump(doc) + "\n")
    return out


def edit_diff(before: str, after: str) -> str:
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), "copilot", "analyst", n=1))


def verify_chain(d: Path) -> list[str]:
    """Problems with the event chain and with git immutability (empty list = intact)."""
    d, errs, prev = Path(d), [], (Path(d) / "record.json")
    prev_sha = sha256_bytes(prev.read_bytes())
    for p in sorted((d / "events").glob("*.json")):
        ev = json.loads(p.read_text(encoding="utf-8"))
        if ev.get("prev_sha256") != prev_sha:
            errs.append(f"{p.name}: chain broken (an earlier file changed)")
        prev_sha = sha256_bytes(p.read_bytes())
    for p in [d / "record.json", d / "context.json", *sorted((d / "events").glob("*.json"))]:
        if len(git_commits(p)) > 1:
            errs.append(f"{p.name}: modified after its first commit")
    return errs


def open_research_needs(root: Path, when: pd.Timestamp) -> list[dict]:
    """Needs the analyst accepted, edited or kept unresolved in the most recent decided run before `when`.
    v0 has no persistent queue (strategy Phase E): nothing is tracked beyond that decision."""
    best = None
    for sub in ("runs",):
        for d in sorted((Path(root) / sub).glob("*/record.json")):
            dec = next((e for e in events(d.parent) if e["kind"] == "decision"), None)
            if dec and utc_naive(dec["at"]) <= when and (best is None or utc_naive(dec["at"]) > utc_naive(best[1]["at"])):
                best = (d.parent, dec)
    if best is None:
        return []
    rec, _ = load_run(best[0])
    action = ((best[1].get("sections") or {}).get("research_needs") or {}).get("action")
    if action not in ("accept", "edit", "keep_unresolved") or not rec.get("result"):
        return []
    return [{"question": n["question"], "hypothesis": n["hypothesis"], "from_run": rec["run_id"]}
            for n in rec["result"].get("research_needs", [])]


def decision_template(rec: dict) -> dict:
    """The skeleton the analyst fills in: one action per section, one verdict per divergence."""
    res = rec.get("result") or {}
    return {"thesis_decision": "unchanged | changed (then: published_update: updates/<file>.yaml)",
            "published_update": None,
            "sections": {s: {"action": "accept | edit | reject | keep_unresolved", "reason": "", "final_text": None}
                         for s in SECTIONS if res.get(s)},
            "divergences": {h["hypothesis"]: {"action": "accept | reject | keep_unresolved", "reason": ""}
                            for h in res.get("hypothesis_impact", []) if h.get("divergence")},
            "new_vs_blind_take": {x["id"]: None for x in res.get("executive_delta", [])}}


def validate_decision(doc: dict, rec: dict) -> list[str]:
    errs, res = [], rec.get("result") or {}
    td = doc.get("thesis_decision")
    if td not in ("unchanged", "changed"):
        errs.append("thesis_decision must be 'unchanged' or 'changed' (an explicit statement is required even when nothing changes)")
    if td == "changed" and not doc.get("published_update"):
        errs.append("a changed thesis must name the published update file (the analyst's own `cnmacro update`)")
    for s, v in (doc.get("sections") or {}).items():
        if s not in SECTIONS or not res.get(s):
            errs.append(f"unknown or empty section {s!r}")
        elif v.get("action") not in ACTIONS:
            errs.append(f"{s}: action must be one of {ACTIONS}")
        elif v["action"] in ("edit", "reject", "keep_unresolved") and not str(v.get("reason") or "").strip():
            errs.append(f"{s}: a reason is required for {v['action']}")
        elif v["action"] == "edit" and not str(v.get("final_text") or "").strip():
            errs.append(f"{s}: edit needs final_text (the diff is computed from it)")
    for h, v in (doc.get("divergences") or {}).items():
        if v.get("action") not in ("accept", "reject", "keep_unresolved"):
            errs.append(f"divergence {h}: action must be accept, reject or keep_unresolved")
    if not doc.get("sections"):
        errs.append("decide at least one section")
    return errs


def section_text(rendered: dict, section: str) -> str:
    return json.dumps(rendered.get(section), indent=2, ensure_ascii=False)


