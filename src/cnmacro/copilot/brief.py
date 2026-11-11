"""Research Brief: an evidence-bound AI read of one genuine release together with the news, policy and official
items collected around it (Issue #69 W6; strategy §5.2, §8; Issues #52 and #6).

    release facts (Context Builder, unchanged)  +  research-input bundle (official / first-party / media items)
        -> Draft (what changed and why)  ->  Challenge (counter-evidence, competing reading, what to watch next)
        -> the same hard gates as the Release Copilot, plus source rules  ->  Run Record
        -> a named person reviews (accept / edit / reject)  ->  public export of the reviewed text only

What it adds to the Release Copilot: source-linked items (`src:<event_id>`) the model may cite next to `obs:` /
`drv:` / `test:` refs, a counter-evidence list, and a "what's next" list pinned to the release calendar. What it
keeps: code owns every number and date, the model writes placeholders, a failed gate discards the run, every
outcome is a Run Record, and nothing here writes the case, an analyst update or the site.

A brief is never a signed thesis update. It has no direction hint, no probability and no conviction; a reviewed
brief is "AI-assisted interpretation reviewed by <person>", which is shown next to, never instead of, the
analyst's signed judgment. Without a model credential the brief degrades to the deterministic evidence pack.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from .. import ingest
from ..store import load_dictionary, utc_naive
from . import contract, records, runner
from .context import ContextError, build_context, canonical, context_hash, mask_figures
from .llm import ModelUnavailable, cost_usd

BRIEF_PROMPT_VERSION = "research-brief-prompt/1"
BRIEF_SCHEMA_VERSION = "research-brief-schema/1"
BRIEF_CONTEXT_VERSION = "research-brief-context/1"
EXPORT_VERSION = "research-brief-public/1"

MAX_SOURCES = 12
EXCERPT_CHARS = 160
KIND_ORDER = ("official_release", "first_party_policy", "media_report")
KIND_LABEL = {"official_release": ("official release", "官方发布"),
              "first_party_policy": ("first-party policy", "官方政策"),
              "media_report": ("media report (a lead, not an official figure)", "媒体报道（线索，非官方数据）")}
TRIAGE_ORDER = ("research_needed", "monitor")
SECTIONS = ("executive_delta", "hypothesis_impact", "competing_explanation", "counter_evidence", "does_not_prove", "whats_next")
UNSCHEDULED = "unscheduled"
# A reviewer is a person. Automation and models can draft a brief, never review it.
NOT_A_PERSON = re.compile(r"bot|automation|github-actions|claude|codex|copilot|agent|deepseek|gpt|llm|model", re.I)


def briefs_dir(root: Path = Path(".")) -> Path:
    return Path(root) / "research/cases/cn-nominal/copilot/briefs"


# ================================================================ context: release facts + source-linked inputs
def _source_entry(item: dict, allow_refs: set[str]) -> dict:
    title = str(item.get("title") or "").strip()
    published = str(item.get("published_at") or "")
    return {
        "ref": f"src:{item['event_id']}", "kind": "source", "evidence_kind": item["evidence_kind"],
        "publisher": item.get("publisher"), "published_at": published, "url": item.get("source_url"),
        "title": mask_figures(title), "excerpt": mask_figures(str(item.get("excerpt") or "")[:EXCERPT_CHARS]),
        "hypotheses": list(item.get("hypotheses") or []), "triage": item.get("triage"),
        "observation_refs": [r for r in item.get("observation_refs") or [] if r in allow_refs],
        "label": KIND_LABEL[item["evidence_kind"]][0],
        # the rendered citation: who said it, when, and the headline as published (a quotation, linked, never a value of ours)
        "display": f"{item.get('publisher')} ({published[:10]}): {title}",
    }


def select_sources(bundle: dict, as_of: str, allow_refs: set[str], limit: int = MAX_SOURCES) -> list[dict]:
    """Bundle items that existed at `as_of`, triaged as relevant, not a repetition, most material first."""
    when = utc_naive(as_of)
    keep = []
    for it in bundle.get("items") or []:
        if it.get("evidence_kind") not in KIND_ORDER or it.get("triage") not in TRIAGE_ORDER or it.get("repetition_of"):
            continue
        if not it.get("event_id") or not it.get("source_url") or not it.get("available_at"):
            continue
        if utc_naive(it["available_at"]) > when or (it.get("published_at") and utc_naive(it["published_at"]) > when):
            continue                                            # point in time: what was knowable at as_of
        keep.append(it)
    keep.sort(key=lambda i: (KIND_ORDER.index(i["evidence_kind"]), TRIAGE_ORDER.index(i["triage"]),
                             -utc_naive(i.get("published_at") or i["available_at"]).value, i["event_id"]))
    out, seen = [], set()
    for it in keep:
        if it["event_id"] in seen:
            continue
        seen.add(it["event_id"])
        out.append(_source_entry(it, allow_refs))
        if len(out) >= limit:
            break
    return out


def load_bundle(path: Path) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("kind") != "research_input_bundle":
        raise ContextError(f"{path} is not a research input bundle")
    return doc


def build_brief_context(paths, release, as_of: str, prior_as_of: str | None = None, *, bundle_path: Path | None,
                        copilot_dir: Path | None = None, expectation_dir: Path | None = None,
                        max_sources: int = MAX_SOURCES) -> dict:
    """The Release Copilot's context (unchanged code path) plus the source items knowable at as_of."""
    ctx = build_context(paths, release, as_of, prior_as_of, copilot_dir=copilot_dir, expectation_dir=expectation_dir)
    allow = {e["ref"] for e in ctx["allowlist"]}
    bundle = load_bundle(bundle_path) if bundle_path else None
    sources = select_sources(bundle, ctx["as_of"], allow, max_sources) if bundle else []
    ctx["version"] = BRIEF_CONTEXT_VERSION
    ctx["sources"] = {
        "bundle": None if bundle is None else {"bundle_id": bundle.get("bundle_id"), "as_of": bundle.get("as_of"),
                                                "generated_by": bundle.get("generated_by"), "file": Path(bundle_path).name},
        "rules": ("A `src:` ref cites an item by its publisher, date and link. Official releases and first-party policy may "
                  "support a claim; a media report is a lead, never an official figure, and cannot be the only support of a claim. "
                  "Headlines and excerpts are shown with figures masked; quantities come only from obs/drv placeholders."),
        "count": len(sources)}
    ctx["allowlist"] = ctx["allowlist"] + sources
    ctx["sha256"] = context_hash(ctx)
    return ctx


def official_refs(ctx: dict) -> set[str]:
    """Refs that can carry a claim on their own: observations, derived values, tests, official and first-party items."""
    return {e["ref"] for e in ctx["allowlist"] if e["kind"] != "source" or e["evidence_kind"] != "media_report"}


# ================================================================ prompts
BRIEF_RULES = """
SOURCES. Besides obs/drv/test refs the allowlist holds `src:` items: official releases, first-party policy texts and \
media reports collected up to `as_of`, each with publisher, date, link, and a headline and excerpt whose figures are masked \
as [figure]. You may cite a `src:` ref in evidence_refs and as a placeholder, e.g. {src:event_abc}; code renders it as \
"publisher (date): headline". A media report is a lead, not an official figure: never let a claim rest on media reports \
alone, and never restate a figure from a headline (the number gate applies to every field). The brief has no thesis \
direction: you explain and challenge, the analyst decides."""

CHALLENGE_TASK = """TASK 2 of 2 — CHALLENGE. You have not seen the analyst's view and you are not the author of the DRAFT below. \
Assume the DRAFT is wrong somewhere. Give the strongest competing explanation, the evidence in the context that cuts \
against the DRAFT, what the facts do NOT establish, and what to watch next.

Return this object (all keys required, no others):
{
  "competing_explanation": {
    "claim": "...", "why_plausible": "...",
    "discriminating_observation": "...",   // which next data would best tell the two readings apart
    "evidence_refs": ["..."],              // at least one; include every placeholder used in the three fields above
    "background_knowledge": []             // 0 to 3 strings of general background; no digits, no placeholders, not evidence
  },
  "counter_evidence": [                    // 1 to 3: facts in the context that cut against the DRAFT
    {"against": "X1",                      // a DRAFT executive_delta id (X1..X5) or a hypothesis label (H0..H4)
     "claim": "...",                       // numbers only as {placeholders}
     "evidence_refs": ["..."]}             // at least one, not media reports alone
  ],
  "does_not_prove": ["..."],               // 1 to 4 conclusions the evidence cannot support
  "whats_next": [                          // 1 to 3, highest information value first
    {"watch": "...",                       // which release, series or document
     "release_at": "...",                  // copy a release_at from next_releases exactly, or "unscheduled"
     "hypothesis": "H2",
     "would_support": "...", "would_challenge": "...",
     "evidence_refs": []}                  // refs used in this item's text (may be empty)
  ]
}"""


def explain_messages(ctx: dict) -> tuple[str, str]:
    from . import prompts
    return prompts.SYSTEM + "\n" + BRIEF_RULES, f"CONTEXT (JSON):\n{canonical(ctx)}\n\n{prompts.DRAFT_TASK}"


def challenge_messages(ctx: dict, draft: dict) -> tuple[str, str]:
    from . import prompts
    return prompts.SYSTEM + "\n" + BRIEF_RULES, (
        f"CONTEXT (JSON):\n{canonical(ctx)}\n\nDRAFT (already validated; a model's reading, not a fact):\n"
        f"{json.dumps(draft, sort_keys=True, separators=(',', ':'), ensure_ascii=False)}\n\n{CHALLENGE_TASK}")


# ================================================================ gates
def _media_only(c: contract.Checker, path: str, refs: list[str], strong: set[str]) -> None:
    if refs and not any(r in strong for r in refs):
        c.err("missing_evidence", path, "a claim cannot rest on media reports alone: cite an observation, a test or an official item")


def validate_explain(raw, ctx: dict) -> list[contract.Violation]:
    """The Release Copilot's Draft gates, plus: no claim may rest on media reports alone."""
    errs = contract.validate_draft(raw, ctx)
    if not isinstance(raw, dict):
        return errs
    c, strong = contract.Checker(ctx), official_refs(ctx)
    for key, field in (("executive_delta", "evidence_refs"), ("hypothesis_impact", "evidence_refs"), ("preliminary_implications", "evidence_refs")):
        for i, x in enumerate(raw.get(key) or []):
            if isinstance(x, dict) and isinstance(x.get(field), list):
                _media_only(c, f"$.{key}[{i}].{field}", [r for r in x[field] if isinstance(r, str)], strong)
    return errs + c.errs


def validate_brief_challenge(raw, ctx: dict, draft: dict | None = None) -> list[contract.Violation]:
    c, strong = contract.Checker(ctx), official_refs(ctx)
    c.keys("$", raw, {"competing_explanation", "counter_evidence", "does_not_prove", "whats_next"})
    if not isinstance(raw, dict):
        return c.errs
    ce = raw.get("competing_explanation")
    if c.keys("$.competing_explanation", ce, {"claim", "why_plausible", "discriminating_observation", "evidence_refs", "background_knowledge"}):
        declared = c.refs("$.competing_explanation.evidence_refs", ce["evidence_refs"])
        _media_only(c, "$.competing_explanation.evidence_refs", declared, strong)
        for k in ("claim", "why_plausible", "discriminating_observation"):
            c.text(f"$.competing_explanation.{k}", ce[k], declared=declared)
        bk = ce["background_knowledge"]
        if not isinstance(bk, list) or len(bk) > 3:
            c.err("schema", "$.competing_explanation.background_knowledge", "a list of at most 3 strings (may be empty)")
        else:
            for i, s in enumerate(bk):
                c.text(f"$.competing_explanation.background_knowledge[{i}]", s, placeholders=False)
    targets = set(contract.DISPLAY_ORDER) | {x.get("id") for x in (draft or {}).get("executive_delta", []) if isinstance(x, dict)}
    counter = raw.get("counter_evidence")
    if not isinstance(counter, list) or not 1 <= len(counter) <= 3:
        c.err("schema", "$.counter_evidence", "between 1 and 3 items required: name what cuts against the draft")
    else:
        for i, x in enumerate(counter):
            p = f"$.counter_evidence[{i}]"
            if c.keys(p, x, {"against", "claim", "evidence_refs"}):
                if not isinstance(x["against"], str) or x["against"] not in targets:
                    c.err("schema", f"{p}.against", f"{x['against']!r} is neither a draft item id nor H0-H4")
                declared = c.refs(f"{p}.evidence_refs", x["evidence_refs"])
                _media_only(c, f"{p}.evidence_refs", declared, strong)
                c.text(f"{p}.claim", x["claim"], declared=declared)
    dnp = raw.get("does_not_prove")
    if not isinstance(dnp, list) or not 1 <= len(dnp) <= 4:
        c.err("schema", "$.does_not_prove", "between 1 and 4 items required")
    else:
        for i, s in enumerate(dnp):
            c.text(f"$.does_not_prove[{i}]", s)
    scheduled = {nr["release_at"] for nr in ctx.get("next_releases") or []}
    nxt = raw.get("whats_next")
    if not isinstance(nxt, list) or not 1 <= len(nxt) <= 3:
        c.err("schema", "$.whats_next", "between 1 and 3 items required")
    else:
        for i, n in enumerate(nxt):
            p = f"$.whats_next[{i}]"
            if c.keys(p, n, {"watch", "release_at", "hypothesis", "would_support", "would_challenge", "evidence_refs"}):
                c.enum(f"{p}.hypothesis", n["hypothesis"], contract.DISPLAY_ORDER)
                if not isinstance(n["release_at"], str):
                    c.err("schema", f"{p}.release_at", "must be a string: a scheduled release_at or 'unscheduled'")
                elif n["release_at"] != UNSCHEDULED and n["release_at"] not in scheduled:
                    c.err("as_of_violation", f"{p}.release_at",
                          f"{n['release_at']!r} is not a scheduled release in the context: dates are code-owned (copy one, or say {UNSCHEDULED!r})")
                declared = c.refs(f"{p}.evidence_refs", n["evidence_refs"], minimum=0)
                for k in ("watch", "would_support", "would_challenge"):
                    c.text(f"{p}.{k}", n[k], declared=declared)
    return c.errs


# ================================================================ assembly, rendering, the deterministic fallback
def assemble(ctx: dict, draft: dict, challenge: dict) -> dict:
    impact = sorted(draft["hypothesis_impact"], key=lambda h: contract.DISPLAY_ORDER.index(h["hypothesis"]))
    schedule = {nr["release_at"]: nr for nr in ctx.get("next_releases") or []}
    return {
        "release_id": ctx["release"]["release_id"], "as_of": ctx["as_of"],
        "executive_delta": [{**x, "vs_expectation": contract.vs_expectation(x, ctx)} for x in draft["executive_delta"]],
        "hypothesis_impact": [{"hypothesis": h["hypothesis"], "mechanical_delta": ctx["hypotheses"][h["hypothesis"]]["mechanical_delta"],
                               **{k: v for k, v in h.items() if k != "hypothesis"}} for h in impact],
        "preliminary_implications": draft["preliminary_implications"],
        "competing_explanation": challenge["competing_explanation"],
        "counter_evidence": challenge["counter_evidence"],
        "does_not_prove": challenge["does_not_prove"],
        "whats_next": [{**n, "scheduled_metrics": (schedule.get(n["release_at"]) or {}).get("metrics", [])} for n in challenge["whats_next"]],
    }


def cited_sources(result: dict, ctx: dict) -> list[dict]:
    """Every `src:` item the brief cites, with its link: the reader can open each one."""
    text = json.dumps(result, ensure_ascii=False)
    out = []
    for e in ctx["allowlist"]:
        if e["kind"] == "source" and (f"\"{e['ref']}\"" in text or "{" + e["ref"] + "}" in text):
            out.append({k: e[k] for k in ("ref", "evidence_kind", "label", "publisher", "published_at", "url", "display")})
    return out


def evidence_pack(ctx: dict, dictionary: dict | None = None) -> dict:
    """What a reader sees when no model ran or no person reviewed: code-computed facts and links, no interpretation."""
    by_ref = {e["ref"]: e for e in ctx["allowlist"]}
    facts = []
    for o in ctx["new_observations"]:
        mid, per = o["metric_id"], o["period"]
        now = by_ref.get(o["ref"])
        if now is None:
            continue
        m = (dictionary or {}).get(mid)
        freq = getattr(m, "frequency", "M") if m else "M"
        prev_ref = f"obs:{mid}@{pd.Period(per, freq=freq) - 1}"
        chg = by_ref.get(f"drv:diff({mid},1)@{per}")
        facts.append({"ref": o["ref"], "metric_id": mid, "name": getattr(m, "name", mid) if m else mid,
                      "name_zh": getattr(m, "name_zh", None) if m else None, "period": per, "value": now["display"],
                      "previous": (by_ref.get(prev_ref) or {}).get("display"), "change": (chg or {}).get("display"),
                      "revised_from": o["revised_from"]})
    return {
        "release": ctx["release"]["name"], "as_of": ctx["as_of"], "context_sha256": ctx["sha256"],
        "facts": facts,
        "mechanical_delta": {h: v["mechanical_delta"] for h, v in ctx["hypotheses"].items()},
        "test_flips": [{**f, "hypothesis": h} for h, v in ctx["hypotheses"].items() for f in v["flips"]],
        "sources": [{k: e[k] for k in ("ref", "evidence_kind", "label", "publisher", "published_at", "url", "display")}
                    for e in ctx["allowlist"] if e["kind"] == "source"],
        "next_releases": ctx.get("next_releases") or [],
        "standing_judgment": ctx["standing_thesis"]["judgment"],
        "generated_by": "deterministic:cnmacro.copilot.brief.evidence_pack",
    }


def render_markdown(rendered: dict, ctx: dict, sources: list[dict]) -> str:
    """Reading order: What changed -> Why -> Divergence -> Counter-evidence -> Competing reading -> Not proven -> Next -> Sources."""
    r, o = rendered, []
    o += [f"# {ctx['release']['name']} — Research Brief (as of {ctx['as_of']})", "",
          "> AI-assisted interpretation. Every figure is filled in by code from the cited source; this is not the analyst's signed judgment.", ""]
    o += ["## What changed"] + [f"- **{x['id']}** [{x['lens']}, {x['materiality']}] {x['template']}" for x in r["executive_delta"]] + [""]
    o += ["## Why it matters"] + [f"- **{h['hypothesis']}** mechanical *{h['mechanical_delta']}* · AI *{h['ai_assessment']}*. {h['rationale_template']}"
                                  for h in r["hypothesis_impact"]]
    o += [f"- implication ({p['hypothesis']}): {p['template']}" for p in r["preliminary_implications"]]
    divs = [h for h in r["hypothesis_impact"] if h["divergence"]]
    o += ["", "## Where the AI disagrees with the mechanical tests"]
    o += [f"- **{h['hypothesis']}**: {h['divergence_reason']}" for h in divs] or ["- none"]
    o += ["", "## Counter-evidence"] + [f"- against {x['against']}: {x['claim']}" for x in r["counter_evidence"]]
    ce = r["competing_explanation"]
    o += ["", "## Strongest competing reading", ce["claim"], f"*Why plausible:* {ce['why_plausible']}",
          f"*What would tell them apart:* {ce['discriminating_observation']}"]
    o += [f"*Background (not evidence):* {b}" for b in ce["background_knowledge"]]
    o += ["", "## What this does not prove"] + [f"- {s}" for s in r["does_not_prove"]]
    o += ["", "## What to watch next"] + [f"- ({n['hypothesis']}) {n['watch']} — release: {n['release_at']}; supports if: {n['would_support']}; "
                                          f"challenges if: {n['would_challenge']}" for n in r["whats_next"]]
    o += ["", "## Sources cited"] + [f"- [{s['label']}] {s['display']} <{s['url']}>" for s in sources] or ["- (observations and tests only)"]
    return "\n".join(o) + "\n"


def render_pack_markdown(pack: dict) -> str:
    o = [f"# {pack['release']} — Evidence pack (as of {pack['as_of']})", "",
         "> Deterministic facts and links only. No model interpretation is included.", "", "## What changed"]
    o += [f"- {f['name']} {f['period']}: {f['value']} (previous {f['previous'] or 'n/a'}; change {f['change'] or 'n/a'})" for f in pack["facts"]]
    o += ["", "## Mechanical test direction"] + [f"- {h}: {d}" for h, d in pack["mechanical_delta"].items()]
    o += ["", "## Sources"] + [f"- [{s['label']}] {s['display']} <{s['url']}>" for s in pack["sources"]] or ["- none"]
    o += ["", "## Next scheduled releases"] + [f"- {nr['release_at']}: {', '.join(nr['metrics'])}" for nr in pack["next_releases"]]
    return "\n".join(o) + "\n"


# ================================================================ the run
def run_brief(client, ctx: dict, root: Path, *, unavailable: ModelUnavailable | None = None,
              knowledge_cutoff: str | None = None, review_id: str | None = None, dictionary: dict | None = None,
              log=print) -> tuple[dict, Path]:
    """Explain -> validate -> Challenge -> validate -> assemble -> render -> Run Record. Fail closed, no retry."""
    run_at = ingest.now_iso()
    run_id = records.new_run_id(run_at, ctx["sha256"])
    kind = "unavailable" if client is None else "model_run" if client.genuine else "fixture"
    record = {
        "record_version": "research-brief-run-record/1", "artifact": "research_brief", "run_id": run_id, "run_at": run_at,
        "kind": kind, "genuine_model_run": kind == "model_run",
        "evidence_class": {"fixture": "fixture (synthetic, not evidence)", "unavailable": "none (no model ran)"}.get(kind, "live_shadow"),
        "release": ctx["release"], "as_of": ctx["as_of"], "prior_as_of": ctx["prior_as_of"], "mode": ctx["mode"],
        "review_id": review_id,
        "model": (client.identity() if client else {"provider": None}) | {"knowledge_cutoff": knowledge_cutoff},
        "contamination": runner.contamination(ctx, knowledge_cutoff),
        "versions": {"prompt": BRIEF_PROMPT_VERSION, "schema": BRIEF_SCHEMA_VERSION, "context": BRIEF_CONTEXT_VERSION,
                     "code_commit": runner._git("rev-parse", "HEAD"), "code_dirty": bool(runner._git("status", "--porcelain", "--", "src"))},
        "context": {"sha256": ctx["sha256"], "file": "context.json", "evidence_allowlist": sorted(e["ref"] for e in ctx["allowlist"])},
        "signed_thesis_update": False,
        "publication": {"public": False, "reason": "unreviewed: only a brief a named person accepted or edited is exported"},
        "evidence_pack": evidence_pack(ctx, dictionary),
        "passes": [], "result": None, "rendered": None, "sources": [],
    }
    errors: list = []

    def finish(status: str, copilot: str) -> tuple[dict, Path]:
        record["status"], record["copilot"] = status, copilot
        passes = record["passes"]
        reported = [p["usage"] for p in passes if isinstance(p.get("usage"), dict) and
                    all(type(p["usage"].get(k)) is int and p["usage"][k] >= 0 for k in ("input_tokens", "output_tokens"))]
        u_in = sum(u["input_tokens"] for u in reported) if reported else None
        u_out = sum(u["output_tokens"] for u in reported) if reported else None
        record["usage"] = {"input_tokens": u_in, "output_tokens": u_out,
                           "cost_usd": cost_usd(getattr(client, "model", ""), {}) if client and client.genuine else None,
                           "latency_ms": sum(p.get("latency_ms") or 0 for p in passes)}
        counts = contract.gate_counts([v for _, v in errors])
        record["validation"] = {"ok": status == "validated", "gate_failures": counts,
                                "hard_gate_failures": {g: counts[g] for g in contract.HARD_GATES},
                                "errors": [{"pass": p, **v.as_dict()} for p, v in errors]}
        record["finished_at"] = ingest.now_iso()
        d = records.write_run(root, record, ctx)
        log(f"brief {run_id}: {status} (copilot: {copilot}) -> {d}")
        return record, d

    if client is None:
        record["unavailable"] = {"kind": unavailable.kind if unavailable else "unknown", "detail": unavailable.detail if unavailable else ""}
        return finish("model_unavailable", "unavailable")
    try:
        s1, u1 = explain_messages(ctx)
        p1, draft, e1 = runner._pass("explain", client, s1, u1, validate_explain, ctx)
        record["passes"].append(p1)
        errors += [("explain", v) for v in e1]
        if e1:
            return finish("validation_failed", "ok")
        s2, u2 = challenge_messages(ctx, draft)
        p2, challenge, e2 = runner._pass("challenge", client, s2, u2, lambda raw, c: validate_brief_challenge(raw, c, draft), ctx)
        record["passes"].append(p2)
        errors += [("challenge", v) for v in e2]
        if e2:
            return finish("validation_failed", "ok")
    except ModelUnavailable as e:
        record["passes"].append(e.pass_record)
        record["unavailable"] = {"kind": e.kind, "detail": e.detail[:500]}
        return finish("model_error", "unavailable")
    try:
        result = assemble(ctx, draft, challenge)
        record["rendered"] = contract.render(result, ctx)
        record["result"] = result
        record["sources"] = cited_sources(result, ctx)
    except (contract.RenderError, KeyError) as e:
        errors.append(("render", contract.Violation("invalid_evidence_ref", "$", f"rendering refused: {e}")))
        record["rendered"] = None
        return finish("validation_failed", "ok")
    return finish("validated", "ok")


# ================================================================ review and public export
def review(d: Path, action: str, *, reviewer: str, reason: str = "", final_markdown: str | None = None) -> Path:
    """A named person accepts, edits or rejects a validated brief (append-only, chained after the reveal)."""
    rec, ctx = records.load_run(d)
    if rec.get("artifact") != "research_brief":
        raise records.RecordError("not a research brief run")
    if rec["status"] != "validated":
        raise records.RecordError(f"only a validated brief can be reviewed (this run is {rec['status']})")
    if action not in ("accept", "edit", "reject"):
        raise records.RecordError("action must be accept, edit or reject")
    if not reviewer.strip() or NOT_A_PERSON.search(reviewer):
        raise records.RecordError("a brief is reviewed by a named person, not by automation or a model")
    if action in ("edit", "reject") and not reason.strip():
        raise records.RecordError(f"a reason is required to {action}")
    original = render_markdown(rec["rendered"], ctx, rec.get("sources") or [])
    if action == "edit" and not (final_markdown or "").strip():
        raise records.RecordError("edit needs the final text")
    have = [e["kind"] for e in records.events(d)]
    if "revealed" not in have:
        records.append_event(d, "revealed", {} if "blind_take" in have else {"waived_blind_take": "brief reviewed without a blind take"})
    payload = {"artifact": "research_brief", "action": action, "reviewer": reviewer.strip(), "reason": reason.strip(),
               "final_markdown": final_markdown if action == "edit" else None,
               "edit_diff": records.edit_diff(original, final_markdown) if action == "edit" else None,
               "signed_thesis_update": False}
    return records.append_event(d, "decision", payload)


def export_public(d: Path) -> dict:
    """The only shape a page may show. Unreviewed or rejected: the deterministic evidence pack, no model text."""
    rec, ctx = records.load_run(d)
    if rec.get("artifact") != "research_brief":
        raise records.RecordError("not a research brief run")
    decision = next((e for e in records.events(d) if e["kind"] == "decision"), None)
    reviewed = (rec["status"] == "validated" and rec["kind"] == "model_run" and decision is not None
                and decision.get("action") in ("accept", "edit"))
    base = {"kind": "research_brief", "version": EXPORT_VERSION, "run_id": rec["run_id"], "release": rec["release"],
            "as_of": rec["as_of"], "context_sha256": rec["context"]["sha256"], "signed_thesis_update": False,
            "evidence_pack": rec["evidence_pack"],
            "standing_judgment_note": {"en": "The analyst's signed judgment is unchanged by this brief.",
                                       "zh": "本简报不改变分析师已签署的研究判断。"}}
    if not reviewed:
        why = ("a fixture is synthetic and is never published" if rec["kind"] == "fixture" else
               "no model ran" if rec["status"] in ("model_unavailable", "model_error") else
               "the model output failed a hard gate" if rec["status"] == "validation_failed" else
               "rejected by the reviewer" if decision else "awaiting review")
        return base | {"status": "evidence_only", "reason": why, "brief": None,
                       "label": {"en": "Evidence pack: code-computed facts and source links; no AI interpretation shown.",
                                 "zh": "证据包：代码计算的数据与来源链接，不展示 AI 解读。"}}
    return base | {
        "status": "reviewed_ai_interpretation",
        "label": {"en": f"AI-assisted interpretation, reviewed by {decision['reviewer']}. Not a signed thesis update.",
                  "zh": f"AI 辅助解读，经 {decision['reviewer']} 审阅；不是已签署的研究判断更新。"},
        "reviewer": decision["reviewer"], "reviewed_at": decision["at"], "review_action": decision["action"],
        "brief": rec["rendered"] if decision["action"] == "accept" else None,
        "brief_markdown": decision["final_markdown"] if decision["action"] == "edit" else render_markdown(rec["rendered"], ctx, rec["sources"]),
        "sources": rec["sources"],
        "model": {k: rec["model"].get(k) for k in ("provider", "requested_id")},
    }


def load_dictionary_for(paths) -> dict:
    try:
        return load_dictionary(paths.dictionary)
    except Exception:          # the pack is a convenience; a broken dictionary must not block a run record
        return {}
