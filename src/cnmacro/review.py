"""Release -> deterministic evidence -> draft analyst update -> explicit Approve / Edit / Reject -> signed update.

    reviews/<review_id>/draft.json      the draft (written once, by code: every value computed, nothing typed)
    reviews/<review_id>/decision.json   the analyst's decision (written once, chained to the draft's sha256)
    updates/<date>-<slug>.yaml          the signed thesis update, appended ONLY when the decision is approve/edit

A draft is built from one immutable refresh record (a genuine release that reached the public store), the judgment
in force when it was built, and the Copilot's deterministic Context Builder (`copilot.context.build_context`), so the
draft and a Copilot run see the same evidence. No model is called and no judgment is proposed: the draft states what
the preregistered tests did and that the mechanical tally alone does not move the probability. Only a person can
approve, and the signed update is dated when they decide (never back-dated to the release).

Without a decision the review stays `awaiting_analyst` and the site keeps showing the previous signed judgment.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd
import yaml

from . import ingest
from .evidence import load_tests
from .refresh import Paths, diff_results, evaluate
from .store import load_dictionary, load_observations, release_time, utc_naive
from .thesis import case_files, effective_case, fold, load_yaml, validate_update

VERSION = 1
ACTIONS = ("approve", "edit", "reject")
THESIS_SIDE = ("H1", "H2", "H3", "H4")       # the thesis legs; H0 is the competing explanation
COMPETING = "H0"
MAX_INPUTS = 5
ZH_CONVICTION = {"LOW": "低", "MEDIUM": "中", "HIGH": "高"}
ZH_STATUS = {"ACTIVE": "进行中", "CONFIRMED": "已确认", "FALSIFIED": "已证伪", "RETIRED": "已退役"}   # as site/i18n/zh.yaml
# A signer is a person. Automation, bots and coding agents can draft but never sign.
NOT_A_PERSON = re.compile(r"bot|automation|github-actions|claude|codex|copilot|agent|deepseek|gpt|llm", re.I)


class ReviewError(ValueError):
    pass


# ---------------------------------------------------------------- small helpers
def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n"


def _write_once(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8", newline="\n") as f:       # "x": an existing file is never replaced
        f.write(text)


def _iso(ts) -> str:
    return utc_naive(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt(v, unit: str) -> str:
    if v is None:
        return "–"
    suffix = "%" if unit == "%" else "" if unit.startswith("index") else f" {unit}"
    return f"{float(v):,.1f}{suffix}" if unit.startswith("CNY") else f"{float(v):.1f}{suffix}"


def review_dir(case_dir: Path) -> Path:
    return Path(case_dir) / "reviews"


def review_id_for(refresh_file: str) -> str:
    return Path(refresh_file).stem                                   # e.g. 2026-11-09T0223Z: one review per refresh


# ---------------------------------------------------------------- what counts as a release worth a review
def tested_metrics(case: dict) -> set[str]:
    out = set()
    for t in load_tests(case["evidence_tests"]):
        out |= set(re.findall(r"[a-z][a-z0-9_]+", t.indicator))
    return out


def eligible(record: dict, case: dict) -> bool:
    """A refresh deserves an analyst review when it brought a new reading of a series a preregistered test uses."""
    used = tested_metrics(case)
    return any(o["metric_id"] in used for o in record.get("new_observations", []))


def release_group(calendar: Path, record: dict):
    """The verified calendar entries the refresh delivered: an entry matches a new observation by metric and
    reference period, released at or before the refresh. Ingestion may lag the release (a print published before the
    previous refresh but fetched only now still belongs to its release), and several entries can share one release
    time (CPI and PPI)."""
    from .copilot.context import ReleaseSpec, slug
    rels = yaml.safe_load(Path(calendar).read_text(encoding="utf-8"))["releases"]
    hi = utc_naive(record["as_of"])
    got = {(o["metric_id"], str(o["reference_period"])) for o in record["new_observations"]}
    hits = [r for r in rels if release_time(r["release"]) <= hi
            and any((m, str(r["period"])) in got for m in r["metrics"])]
    if not hits:
        return None, []
    first = hits[0]
    metrics = sorted({m for r in hits for m in r["metrics"]})
    spec = ReleaseSpec(slug(first["name"]), first["name"], str(first["period"]), str(first["release"]), metrics)
    return spec, [{"name": r["name"], "period": str(r["period"]), "release_at": str(r["release"]),
                   "url": r.get("url"), "metrics": list(r["metrics"])} for r in hits]


# ---------------------------------------------------------------- judgment in force
def judgment_in_force(case_dir: Path) -> dict:
    base_path, upd = case_files(case_dir)
    path = upd[-1] if upd else base_path
    doc = load_yaml(path)
    state, _, _ = fold(case_dir)
    return {"file": path.name, "kind": "update" if upd else "baseline", "as_of": str(doc["as_of"]),
            "author": doc.get("author") or ("preregistered baseline" if not upd else None),
            **{k: state[k] for k in ("probability", "conviction", "status", "last_update_direction")},
            "terminal_rule_fired": doc.get("terminal_rule_fired"),
            "statement_en": (doc.get("does_this_change_the_thesis") if upd else doc.get("rationale")),
            "statement_zh": (doc.get("does_this_change_the_thesis_zh") if upd else None)}


# ---------------------------------------------------------------- optional research inputs (#56 bundle, read-only)
def research_inputs(case_dir: Path, as_of: str) -> dict | None:
    """The newest committed research-input bundle at or before as_of (contract: inputs/<date>.json, kind
    research_input_bundle). Only material, non-repeated items available by as_of are carried."""
    d = Path(case_dir) / "inputs"
    if not d.exists():
        return None
    best = None
    for p in sorted(d.glob("*.json")):
        try:
            b = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if b.get("kind") == "research_input_bundle" and b.get("as_of") and utc_naive(b["as_of"]) <= utc_naive(as_of):
            best = (p, b)
    if best is None:
        return None
    p, b = best
    keep = [i for i in b.get("items", []) if i.get("triage") in ("research_needed", "monitor")
            and not i.get("repetition_of") and i.get("available_at") and utc_naive(i["available_at"]) <= utc_naive(as_of)]
    keep.sort(key=lambda i: (i.get("triage") != "research_needed", i.get("available_at", "")))
    fields = ("event_id", "title", "source_url", "publisher", "published_at", "available_at", "hypotheses",
              "mechanism", "why_relevant", "triage", "linked_metrics", "evidence_kind")
    return {"file": p.name, "sha256": _sha(p.read_bytes()), "as_of": b["as_of"],
            "items": [{k: i.get(k) for k in fields} for i in keep[:MAX_INPUTS]]}


# ---------------------------------------------------------------- the draft
def _test_side(h: str, effect: str | None) -> str | None:
    """Does a test result support or contradict the thesis (H0 is the competing explanation)?"""
    if effect not in ("supports", "challenges"):
        return None
    pro = effect == "supports"
    return ("supporting" if pro else "contradicting") if h in THESIS_SIDE else ("contradicting" if pro else "supporting")


def build_draft(paths: Paths, refresh_file: str, created_at: str | None = None) -> dict:
    from .copilot.context import build_context
    case_dir = Path(paths.case_dir)
    rec_path = case_dir / "refreshes" / refresh_file
    raw = rec_path.read_bytes()
    record = json.loads(raw)
    case, _, errs = effective_case(case_dir)
    if errs:
        raise ReviewError(f"case in force is invalid: {errs[:2]}")
    if not eligible(record, case):
        raise ReviewError(f"{refresh_file}: no new reading of a tested series; nothing for the analyst to review")
    spec, group = release_group(paths.calendar, record)
    if spec is None:
        raise ReviewError(f"{refresh_file}: no verified calendar release inside this refresh window")
    created = created_at or ingest.now_iso()
    if utc_naive(created) < utc_naive(record["as_of"]):
        raise ReviewError("a draft cannot be created before the refresh it reads")

    prior = judgment_in_force(case_dir)
    ctx = build_context(paths, spec, record["as_of"], record["previous_evidence_as_of"])
    by_ref = {e["ref"]: e for e in ctx["allowlist"]}
    metrics = load_dictionary(paths.dictionary)

    # newly known facts: each new reading against the previous period, values from the store (code-rendered)
    facts = []
    for o in record["new_observations"]:
        m = metrics.get(o["metric_id"])
        if m is None:
            continue
        p = pd.Period(o["reference_period"], freq=m.frequency)
        prev = by_ref.get(f"obs:{o['metric_id']}@{p - 1}")
        val = float(o["value"])
        facts.append({"metric_id": o["metric_id"], "name": m.name, "name_zh": m.name_zh, "unit": m.unit,
                      "period": o["reference_period"], "value": val, "previous_period": str(p - 1),
                      "previous_value": prev["value"] if prev else None,
                      "change": round(val - prev["value"], 4) if prev else None,
                      "release_date": o.get("release_date"), "source": o.get("source"),
                      "quality_flag": o.get("quality_flag"), "ref": f"obs:{o['metric_id']}@{o['reference_period']}",
                      "tested": o["metric_id"] in tested_metrics(case)})

    # cumulative change since the judgment in force (the reader's "versus the previous reading")
    obs = load_observations(paths.obs_dir)
    then, _ = evaluate(obs, metrics, case, _iso(prior["as_of"]))
    now, term_now = evaluate(obs, metrics, case, record["as_of"])
    flips_since, _ = diff_results(then, now)

    tests = load_tests(case["evidence_tests"])
    supporting, contradicting = [], []
    for t in tests:
        r = now[t.id]
        side = _test_side(t.hypothesis, r.effect)
        row = {"test": t.id, "hypothesis": t.hypothesis, "description": t.description, "outcome": r.outcome,
               "effect": r.effect, "latest_period": r.latest_period, "observed": r.observed}
        (supporting if side == "supporting" else contradicting if side == "contradicting" else []).append(row)

    hyp = {h: {"name": (case["hypotheses"].get(h) or {}).get("name"),
               "mechanical_delta": v["mechanical_delta"], "tests_now": v["tests_now"], "tests_prior": v["tests_prior"],
               "flips": v["flips"]} for h, v in ctx["hypotheses"].items()}
    demand_pending = [t for t in tests if t.hypothesis == "H2" and now[t.id].outcome in ("false", "insufficient_data")]
    competing = {
        "hypothesis": COMPETING, "name": (case["hypotheses"].get(COMPETING) or {}).get("name"),
        "claim": (case["hypotheses"].get(COMPETING) or {}).get("claim"),
        "tests_now": ctx["hypotheses"][COMPETING]["tests_now"],
        "discriminating_tests": [{"test": t.id, "description": t.description, "outcome": now[t.id].outcome} for t in demand_pending],
    }
    watch = [{"release_at": nr["release_at"], "metrics": nr["metrics"], "periods": nr["periods"],
              "tests": sorted({t.id for t in tests if set(re.findall(r"[a-z][a-z0-9_]+", t.indicator)) & set(nr["metrics"])})}
             for nr in ctx["next_releases"]][:5]

    n_flip_rel = len(record.get("flipped_tests", []))
    draft = {
        "kind": "thesis_review_draft", "version": VERSION,
        "review_id": review_id_for(refresh_file), "created_at": _iso(created), "created_by": "deterministic:cnmacro.review",
        "status": "awaiting_analyst",
        "refresh_record": {"file": refresh_file, "sha256": _sha(raw), "as_of": record["as_of"],
                           "previous_evidence_as_of": record["previous_evidence_as_of"]},
        "release": {"name": spec.name, "release_at": spec.release_at, "period": spec.period, "entries": group},
        "context_sha256": ctx["sha256"],
        "previous_state": prior,
        "new_facts": facts,
        "test_changes_this_release": {"flipped": record.get("flipped_tests", []), "marginal": record.get("marginal_changes", [])},
        "flips_since_judgment": flips_since,
        "hypotheses": hyp,
        "supporting_evidence": supporting,
        "contradicting_evidence": contradicting,
        "competing_explanation": competing,
        "terminal": {"status": term_now["status"], "rule_fired": term_now.get("rule_fired"), "owner": "code"},
        "suggested_direction": record.get("suggested_direction"),
        "research_inputs": research_inputs(case_dir, record["as_of"]),
        "watch_next": watch,
        "proposal": {
            "thesis_change": "none_proposed",
            "why": "the draft is produced by code; it never proposes a probability, conviction or status change. "
                   "Only the analyst can, by choosing Edit.",
            **{k: prior[k] for k in ("probability", "conviction", "status")}, "last_update_direction": "UNCHANGED"},
    }
    draft["text"] = draft_text(draft, n_flip_rel)
    return draft


def draft_text(d: dict, n_flip_rel: int) -> dict:
    """The proposed update paragraph in both languages. Every figure is rendered here by code from the draft."""
    p = d["previous_state"]
    shown = sorted(d["new_facts"], key=lambda f: not f["tested"])[:6]     # tested series first
    rd = utc_naive(d["release"]["release_at"]).strftime("%Y-%m-%d")

    def facts(loc: str) -> str:
        parts = []
        for f in shown:
            name = (f["name_zh"] or f["name"]) if loc == "zh" else f["name"]
            prev = _fmt(f["previous_value"], f["unit"])
            tail = "" if f["previous_value"] is None else (f"（前值 {prev}）" if loc == "zh" else f" (prior {prev})")
            parts.append(f"{name} {f['period']} {_fmt(f['value'], f['unit'])}{tail}")
        return ("；" if loc == "zh" else "; ").join(parts)

    since = d["flips_since_judgment"]
    flips_en = ", ".join(f"{f['test']} {f['from']}→{f['to']}" for f in since) or "none"
    sup, con = len(d["supporting_evidence"]), len(d["contradicting_evidence"])
    pr = f"{round(p['probability'] * 100)}%"
    jdate = utc_naive(p["as_of"]).strftime("%Y-%m-%d")
    term = d["terminal"]["status"]
    en = (f"Release of {rd}: {facts('en')}. "
          f"{'No preregistered evidence test changed outcome on this release' if not n_flip_rel else f'{n_flip_rel} preregistered test(s) changed outcome on this release'}; "
          f"since the judgment in force ({p['file']}, {jdate}) the changes are: {flips_en}. "
          f"Across all tests, {sup} currently read in favour of the thesis and {con} against it (H0, the supply-led "
          f"explanation, counted against). Terminal status {term}. "
          f"Proposed: no change to the thesis; probability stays {pr}, conviction {p['conviction']}, status {p['status']}.")
    flips_zh = "、".join(f"{f['test']} {f['from']}→{f['to']}" for f in since) or "无"
    zh = (f"{rd} 发布：{facts('zh')}。"
          f"{'本次发布没有预注册证据检验改变结果' if not n_flip_rel else f'本次发布有 {n_flip_rel} 项预注册检验改变结果'}；"
          f"相对现行判断（{p['file']}，{jdate}），检验变化为：{flips_zh}。"
          f"全部检验中，目前 {sup} 项支持命题、{con} 项不支持（H0 供给主导解释计为不支持）。"
          f"终止状态：{ZH_STATUS.get(term, term)}。"
          f"建议：命题判断不变；概率维持 {pr}，信心{ZH_CONVICTION.get(p['conviction'], p['conviction'])}，"
          f"状态{ZH_STATUS.get(p['status'], p['status'])}。")
    return {"en": en, "zh": zh}


def write_draft(case_dir: Path, draft: dict) -> Path:
    out = review_dir(case_dir) / draft["review_id"] / "draft.json"
    if out.exists():
        raise ReviewError(f"{out} exists; drafts are written once")
    _write_once(out, _dump(draft))
    return out


# ---------------------------------------------------------------- reading reviews
def load_review(case_dir: Path, review_id: str) -> tuple[dict, dict | None]:
    d = review_dir(case_dir) / review_id
    if not (d / "draft.json").exists():
        raise ReviewError(f"no draft for review {review_id!r}")
    draft = json.loads((d / "draft.json").read_text(encoding="utf-8"))
    dec = json.loads((d / "decision.json").read_text(encoding="utf-8")) if (d / "decision.json").exists() else None
    return draft, dec


def status_of(draft: dict, decision: dict | None) -> str:
    if decision is None:
        return "awaiting_analyst"
    return {"approve": "approved", "edit": "edited", "reject": "rejected"}[decision["action"]]


def reviews(case_dir: Path) -> list[dict]:
    """Every review, oldest first, with its current status (for the site and the CLI)."""
    out = []
    root = review_dir(case_dir)
    if not root.exists():
        return out
    for p in sorted(root.glob("*/draft.json")):
        draft, dec = load_review(case_dir, p.parent.name)
        out.append({"review_id": draft["review_id"], "status": status_of(draft, dec), "draft": draft, "decision": dec})
    for older in out[:-1]:                       # a newer draft carries everything since the judgment in force
        if older["status"] == "awaiting_analyst":
            older["status"] = "superseded"
    return out


def verify(case_dir: Path, review_id: str) -> list[str]:
    """Problems with a review (empty = intact): the draft still matches its refresh record, the decision is chained
    to the exact draft, and a signed update exists exactly when the decision approved or edited."""
    draft, dec = load_review(case_dir, review_id)
    d, errs = review_dir(case_dir) / review_id, []
    rec = Path(case_dir) / "refreshes" / draft["refresh_record"]["file"]
    if not rec.exists() or _sha(rec.read_bytes()) != draft["refresh_record"]["sha256"]:
        errs.append("draft does not match its refresh record")
    if dec:
        if dec.get("draft_sha256") != _sha((d / "draft.json").read_bytes()):
            errs.append("decision is not chained to this draft (draft changed after the decision)")
        up = dec.get("published_update")
        if dec["action"] in ("approve", "edit") and not (up and (Path(case_dir) / "updates" / up).exists()):
            errs.append("approved decision without its signed update")
        if dec["action"] == "reject" and up:
            errs.append("a rejected draft must not publish an update")
    return errs


# ---------------------------------------------------------------- the decision
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def decide(case_dir: Path, review_id: str, action: str, signer: str, *, reason: str = "",
           at: str | None = None, via: str = "cli", edits: dict | None = None) -> tuple[Path, Path | None]:
    """Record an analyst decision and, for approve/edit, append the signed update. Refuses rather than guesses."""
    case_dir = Path(case_dir)
    if action not in ACTIONS:
        raise ReviewError(f"action must be one of {ACTIONS}")
    signer = (signer or "").strip()
    if not signer or NOT_A_PERSON.search(signer):
        raise ReviewError("a decision is signed by a named person; automation and agents cannot sign")
    draft, dec = load_review(case_dir, review_id)
    newest = reviews(case_dir)[-1]["review_id"]
    if newest != review_id:
        raise ReviewError(f"review {review_id} is superseded by {newest}, which carries every change since the judgment in force")
    if dec is not None:
        raise ReviewError(f"review {review_id} is already decided ({dec['action']} by {dec['signed_by']}); decisions are final")
    at = _iso(at or ingest.now_iso())
    if utc_naive(at) < utc_naive(draft["created_at"]):
        raise ReviewError("a decision cannot predate the draft it decides (no back-dating)")
    if verify(case_dir, review_id):
        raise ReviewError(f"review {review_id} is not intact: {verify(case_dir, review_id)}")
    prior = judgment_in_force(case_dir)
    if prior["file"] != draft["previous_state"]["file"]:
        raise ReviewError(f"the judgment changed since this draft ({draft['previous_state']['file']} -> {prior['file']}); "
                          "the draft is stale: reject it or build a new draft")
    if action in ("edit", "reject") and not reason.strip():
        raise ReviewError(f"{action} needs a reason")
    edits = edits or {}
    if action == "edit" and not (edits.get("text_en") or "").strip():
        raise ReviewError("edit needs the analyst's own text (text_en; text_zh recommended)")

    d = review_dir(case_dir) / review_id
    decision = {"kind": "thesis_review_decision", "version": VERSION, "review_id": review_id, "action": action,
                "signed_by": signer, "at": at, "via": via, "reason": reason.strip() or None,
                "draft_sha256": _sha((d / "draft.json").read_bytes()), "published_update": None}
    update_path, doc = None, None
    if action in ("approve", "edit"):
        doc = signed_update(case_dir, draft, decision, edits if action == "edit" else {})
        update_path = case_dir / "updates" / f"{at[:10]}-{_slug(draft['release']['name'])}.yaml"
        if update_path.exists():
            raise ReviewError(f"{update_path.name} exists; updates are append-only")
        state, _, _ = fold(case_dir)
        problems = validate_update(doc, state, update_path.name)
        if problems:
            raise ReviewError(f"the signed update would be invalid: {problems}")
        decision["published_update"] = update_path.name
        if action == "edit":
            import difflib
            decision["edit_diff"] = "".join(difflib.unified_diff(draft["text"]["en"].splitlines(True),
                                                                 edits["text_en"].splitlines(True), "draft", "analyst"))
    _write_once(d / "decision.json", _dump(decision))
    if doc is not None:
        _write_once(update_path, yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return d / "decision.json", update_path


def signed_update(case_dir: Path, draft: dict, decision: dict, edits: dict) -> dict:
    """The update document in the existing `updates/` convention (validated by thesis.validate_update)."""
    base_path, _ = case_files(case_dir)
    p = draft["previous_state"]
    rec = json.loads((Path(case_dir) / "refreshes" / draft["refresh_record"]["file"]).read_text(encoding="utf-8"))
    prob = float(edits.get("probability", p["probability"]))
    conviction = edits.get("conviction") or p["conviction"]
    direction = edits.get("direction") or ("UNCHANGED" if prob == p["probability"] else
                                           "STRENGTHENED" if prob > p["probability"] else "WEAKENED")
    pc = None
    if prob != float(p["probability"]):
        if not (edits.get("reasoning") or "").strip() or not edits.get("evidence"):
            raise ReviewError("a probability change needs reasoning and the evidence (test or claim ids) behind it")
        pc = {"previous": p["probability"], "new": prob, "evidence": list(edits["evidence"]),
              "hypotheses": list(edits.get("hypotheses") or sorted({x.split("-")[1] for x in edits["evidence"] if x.startswith("T-")})),
              "reasoning": edits["reasoning"].strip()}
        if (edits.get("reasoning_zh") or "").strip():
            pc["reasoning_zh"] = edits["reasoning_zh"].strip()
    text_en = (edits.get("text_en") or draft["text"]["en"]).strip()
    text_zh = (edits.get("text_zh") or ("" if edits.get("text_en") else draft["text"]["zh"])).strip()
    doc = {
        "kind": "update", "baseline": base_path.name, "as_of": decision["at"], "release": draft["release"]["name"],
        "author": decision["signed_by"],
        "signature": {"signed_by": decision["signed_by"], "signed_at": decision["at"], "action": decision["action"],
                      "via": decision["via"], "review_id": draft["review_id"], "draft_sha256": decision["draft_sha256"]},
        "evidence_as_of": draft["refresh_record"]["as_of"], "refresh_record": draft["refresh_record"]["file"],
        "previous_state": {k: p[k] for k in ("probability", "conviction", "status", "last_update_direction")},
        "previous_judgment_file": p["file"],
        "test_results": rec.get("test_results", {}),
        "flipped_tests": [{"test": f["test"], "from": f["from"], "to": f["to"]} for f in draft["flips_since_judgment"]],
        "terminal_check": draft["terminal"]["status"],
        "new_claims": [],
        "does_this_change_the_thesis": text_en,
        "probability": prob, "conviction": conviction, "status": p["status"], "last_update_direction": direction,
        "probability_change": pc,
        # a terminal status set by a preregistered rule keeps its provenance in every later update
        "terminal_rule_fired": p.get("terminal_rule_fired") if p["status"] in ("CONFIRMED", "FALSIFIED") else None,
    }
    if text_zh:
        doc["does_this_change_the_thesis_zh"] = text_zh
    return doc


# ---------------------------------------------------------------- latest eligible refresh (used by the refresh workflow)
def pending_refreshes(paths: Paths) -> list[str]:
    """Eligible refresh records newer than the judgment in force and than the newest review (the refresh workflow
    drafts only the newest of them: a draft carries every change since the judgment in force)."""
    case_dir = Path(paths.case_dir)
    case, _, _ = effective_case(case_dir)
    since = utc_naive(judgment_in_force(case_dir)["as_of"])
    done = reviews(case_dir)
    if done:
        since = max(since, utc_naive(done[-1]["draft"]["refresh_record"]["as_of"]))
    out = []
    for p in sorted((case_dir / "refreshes").glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        if utc_naive(r["as_of"]) > since and eligible(r, case) and not (review_dir(case_dir) / p.stem).exists():
            spec, _ = release_group(paths.calendar, r)
            if spec is not None:
                out.append(p.name)
    return out


# ---------------------------------------------------------------- CLI: python -m cnmacro review ...
def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def summary(r: dict) -> dict:
    d, dec = r["draft"], r["decision"]
    return {"review_id": r["review_id"], "status": r["status"], "release": d["release"]["name"],
            "release_at": d["release"]["release_at"], "draft_created_at": d["created_at"],
            "judgment_in_force": d["previous_state"]["file"],
            "decision": None if dec is None else {k: dec.get(k) for k in ("action", "signed_by", "at", "via", "published_update")}}


def decision_card(case_dir: Path, review_id: str) -> str:
    """The short decision surface the analyst reads before choosing Approve / Edit / Reject."""
    d, dec = load_review(case_dir, review_id)
    p = d["previous_state"]
    lines = [f"# Thesis review {review_id} — {status_of(d, dec)}",
             f"Release: {d['release']['name']} ({d['release']['release_at']})",
             f"Judgment in force: {p['file']} — probability {round(p['probability'] * 100)}%, {p['conviction']}, {p['status']}",
             "", "## Proposed update (EN)", d["text"]["en"], "", "## 建议更新（中文）", d["text"]["zh"], "",
             "## Competing explanation", f"{d['competing_explanation']['hypothesis']}: {d['competing_explanation']['claim']}",
             "Discriminating tests: " + ", ".join(f"{t['test']} ({t['outcome']})" for t in d["competing_explanation"]["discriminating_tests"]),
             "", "## Watch next"]
    lines += [f"- {w['release_at']}: {', '.join(w['metrics'])} → tests {', '.join(w['tests']) or '–'}" for w in d["watch_next"]]
    ri = d.get("research_inputs") or {}
    if ri.get("items"):
        lines += ["", f"## Research inputs ({ri['file']})"]
        lines += [f"- [{i['triage']}] {i['title']} — {i['publisher']} {i['source_url']} ({', '.join(i.get('hypotheses') or [])})" for i in ri["items"]]
    lines += ["", "Decide: Approve (publish as drafted: no thesis change) · Edit (your text, optional probability change) · Reject (no update; judgment stays)"]
    return "\n".join(lines)


def _cmd(a) -> int:
    paths = Paths.default()
    case_dir = Path(paths.case_dir)
    try:
        if a.review_cmd == "draft":
            files = [a.refresh] if a.refresh else pending_refreshes(paths)[-1:]
            if not files:
                _print({"status": "nothing_to_draft"})
                return 0
            out = write_draft(case_dir, build_draft(paths, files[0]))
            _print({"status": "drafted", "draft": str(out), "review_id": out.parent.name})
        elif a.review_cmd == "list":
            _print([summary(r) for r in reviews(case_dir)])
        elif a.review_cmd == "show":
            print(decision_card(case_dir, a.id))
        elif a.review_cmd == "verify":
            errs = verify(case_dir, a.id)
            _print({"review_id": a.id, "intact": not errs, "problems": errs})
            return 1 if errs else 0
        elif a.review_cmd == "decide":
            edits = yaml.safe_load(Path(a.edits).read_text(encoding="utf-8")) if a.edits else None
            dec, upd = decide(case_dir, a.id, a.action, a.signer, reason=a.reason or "", via=a.via, edits=edits)
            _print({"status": "decided", "decision": str(dec), "signed_update": str(upd) if upd else None})
    except (ReviewError, FileNotFoundError) as e:
        _print({"status": "refused", "detail": str(e)})
        return 1
    return 0


def register(sub) -> None:
    s = sub.add_parser("review", help="release -> draft analyst update -> explicit Approve / Edit / Reject -> signed update")
    rs = s.add_subparsers(dest="review_cmd", required=True)
    x = rs.add_parser("draft", help="draft a review for a refresh record (default: newest eligible refresh with no review)")
    x.add_argument("--refresh", help="refresh record file name, e.g. 2026-11-09T0223Z.json")
    rs.add_parser("list")
    x = rs.add_parser("show"); x.add_argument("--id", required=True)
    x = rs.add_parser("verify"); x.add_argument("--id", required=True)
    x = rs.add_parser("decide", help="ANALYST ONLY: record Approve / Edit / Reject (signed, dated now)")
    x.add_argument("--id", required=True)
    x.add_argument("--action", required=True, choices=ACTIONS)
    x.add_argument("--signer", required=True, help="the analyst's name or GitHub login")
    x.add_argument("--reason", default="")
    x.add_argument("--edits", help="YAML: text_en, text_zh, optional probability/conviction/reasoning/evidence")
    x.add_argument("--via", default="cli")
    s.set_defaults(f=_cmd)
