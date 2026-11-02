"""One Copilot run: Draft -> validate -> Challenge -> validate -> assemble -> render -> Run Record.

Fail closed and stop early: a failed Draft never reaches the Challenge, a failed Challenge discards the
whole run, and a failed run renders nothing. There is no retry or repair loop: a violation is a recorded
failure (so hard-gate counts stay honest) and the analyst may start a new run. Every outcome, including a
model outage or the absence of a credential, is written as a Run Record; none of it touches the
deterministic pipeline or any analyst-owned file.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd

from .. import ingest
from ..store import release_time
from . import CONTEXT_VERSION, PROMPT_VERSION, RECORD_VERSION, SCHEMA_VERSION
from . import contract, prompts, records
from .llm import ModelUnavailable, cost_usd


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def contamination(ctx: dict, knowledge_cutoff: str | None) -> dict:
    after = None
    if knowledge_cutoff:
        after = bool(release_time(ctx["release"]["release_at"]) > pd.Period(knowledge_cutoff, "M").end_time)
    return {"model_knowledge_cutoff": knowledge_cutoff, "cutoff_source": "supplied by the operator" if knowledge_cutoff else None,
            "release_after_cutoff": after,
            "probe": "not run (strategy §10.3 step 3 belongs to Phase C)",
            "note": ("a live run is uncontaminated by construction" if ctx["mode"] == "live" else
                     "a replay is only as clean as the model's knowledge cutoff; without a probe it cannot be called uncontaminated")}


def _pass(name: str, client, system: str, user: str, validator, ctx: dict) -> tuple[dict, object, list]:
    """(pass record, parsed object or None, violations). A ModelUnavailable propagates with the pass record attached."""
    rec = {"name": name, "prompt_sha256": prompts.prompt_sha256(system, user)}
    try:
        reply = client.call(system, user)
    except ModelUnavailable as e:
        rec |= {"raw_response": e.raw, "error": {"kind": e.kind, "detail": e.detail}, "latency_ms": e.latency_ms,
                "validation": {"ok": False, "errors": []}, **e.response_meta}
        e.pass_record = rec
        raise
    rec |= {"raw_response": reply.raw, "usage": reply.usage, "latency_ms": reply.latency_ms, "stop_reason": reply.stop_reason,
            "request_id": reply.request_id, "attempts": reply.attempts, "served_model": reply.served_model,
            "message_id": reply.message_id}
    try:
        parsed = contract.parse_json(reply.text)
        errs = validator(parsed, ctx)
    except ValueError as e:                       # not JSON at all
        parsed, errs = None, [contract.Violation("schema", "$", f"the answer is not a single JSON object ({e})")]
    rec["parsed"] = parsed
    rec["validation"] = {"ok": not errs, "errors": [v.as_dict() for v in errs]}
    return rec, parsed, errs


def run_release(client, ctx: dict, copilot_dir: Path, *, unavailable: ModelUnavailable | None = None,
                knowledge_cutoff: str | None = None, extra: dict | None = None, log=print) -> tuple[dict, Path]:
    """Run both passes (or record why not) and persist the Run Record. Returns (record, run directory)."""
    run_at = ingest.now_iso()
    run_id = records.new_run_id(run_at, ctx["sha256"])
    mode = ctx["mode"]
    kind = "unavailable" if client is None else "model_run" if client.genuine else "fixture"
    record = {
        "record_version": RECORD_VERSION, "run_id": run_id, "run_at": run_at, "kind": kind,
        "genuine_model_run": kind == "model_run",
        "evidence_class": {"fixture": "fixture (synthetic, not evidence)", "unavailable": "none (no model ran)"}.get(
            kind, "live_shadow" if mode == "live" else "replay_exploratory (no pre-run human labels: not eval-eligible)"),
        "release": ctx["release"], "as_of": ctx["as_of"], "prior_as_of": ctx["prior_as_of"], "mode": mode,
        "model": (client.identity() if client else {"provider": None}) | {"knowledge_cutoff": knowledge_cutoff},
        "contamination": contamination(ctx, knowledge_cutoff),
        "versions": {"prompt": PROMPT_VERSION, "schema": SCHEMA_VERSION, "context": CONTEXT_VERSION, "record": RECORD_VERSION,
                     "code_commit": _git("rev-parse", "HEAD"), "code_dirty": bool(_git("status", "--porcelain", "--", "src"))},
        "context": {"sha256": ctx["sha256"], "file": "context.json", "evidence_allowlist": sorted(e["ref"] for e in ctx["allowlist"])},
        "publication": {"public": False, "reason": "Shadow: no Copilot output is shown on the site; the analyst decision is the only publishable artifact"},
        "passes": [], "result": None, "rendered": None, **(extra or {}),
    }
    errors: list = []

    def finish(status: str, copilot: str) -> tuple[dict, Path]:
        record["status"], record["copilot"] = status, copilot
        passes = record["passes"]
        reported = [p["usage"] for p in passes if isinstance(p.get("usage"), dict) and
                    all(type(p["usage"].get(k)) is int and p["usage"][k] >= 0 for k in ("input_tokens", "output_tokens"))]
        usage_in = sum(p["input_tokens"] for p in reported) if reported else None
        usage_out = sum(p["output_tokens"] for p in reported) if reported else None
        record["usage"] = {"input_tokens": usage_in, "output_tokens": usage_out,
                           "cost_usd": cost_usd(getattr(client, "model", ""), {"input_tokens": usage_in, "output_tokens": usage_out}) if client and client.genuine else None,
                           "latency_ms": sum(p.get("latency_ms") or 0 for p in passes)}
        counts = contract.gate_counts([v for _, v in errors])
        record["validation"] = {"ok": status == "validated", "gate_failures": counts,
                                "hard_gate_failures": {g: counts[g] for g in contract.HARD_GATES},
                                "errors": [{"pass": p, **v.as_dict()} for p, v in errors]}
        record["finished_at"] = ingest.now_iso()
        d = records.write_run(copilot_dir, record, ctx)
        log(f"run {run_id}: {status} (copilot: {copilot}) -> {d}")
        return record, d

    if client is None:
        record["unavailable"] = {"kind": unavailable.kind if unavailable else "unknown", "detail": unavailable.detail if unavailable else ""}
        return finish("model_unavailable", "unavailable")
    try:
        sys1, usr1 = prompts.draft_messages(ctx)
        p1, draft, errs1 = _pass("draft", client, sys1, usr1, contract.validate_draft, ctx)
        record["passes"].append(p1)
        errors += [("draft", v) for v in errs1]
        if errs1:
            return finish("validation_failed", "ok")
        sys2, usr2 = prompts.challenge_messages(ctx, draft)
        p2, challenge, errs2 = _pass("challenge", client, sys2, usr2, contract.validate_challenge, ctx)
        record["passes"].append(p2)
        errors += [("challenge", v) for v in errs2]
        if errs2:
            return finish("validation_failed", "ok")
    except ModelUnavailable as e:
        record["passes"].append(e.pass_record)
        record["unavailable"] = {"kind": e.kind, "detail": e.detail[:500]}
        return finish("model_error", "unavailable")
    try:
        result = contract.assemble(ctx, draft, challenge)
        record["rendered"] = contract.render(result, ctx)
        record["result"] = result
    except (contract.RenderError, KeyError) as e:
        errors.append(("render", contract.Violation("invalid_evidence_ref", "$", f"rendering refused: {e}")))
        record["rendered"] = None
        return finish("validation_failed", "ok")
    return finish("validated", "ok")


def summarize(record: dict) -> dict:
    """What the CLI prints after a run: status and accounting, never the model's content (the blind take comes first)."""
    return {"run_id": record["run_id"], "status": record["status"], "copilot": record["copilot"], "kind": record["kind"],
            "mode": record["mode"], "release": record["release"]["name"], "as_of": record["as_of"],
            "context_sha256": record["context"]["sha256"], "usage": record["usage"],
            "hard_gate_failures": record["validation"]["hard_gate_failures"],
            "content": "withheld until your blind take is recorded: copilot blind-take, then copilot show"}


def dumps(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)
