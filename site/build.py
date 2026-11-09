"""Build the static, bilingual portfolio site from tracked, public artifacts only.

    python site/build.py               -> site/dist/          (public demo build)
    python site/build.py --preview     -> site/dist-preview/  (SYNTHETIC data, layout only, never published)

Reads: data/dictionary, data/demo/observations, research/cases/cn-nominal/*.
Never reads data/private. Numbers come from claims and observations, never typed here.

Output layout (all static; no server, no function, no locale routing on a host):
    index.html            locale selector: stored choice, else browser language, else English
    {en,zh}/<page>.html   the six pages in each language, built from ONE research state
    <page>.html           legacy V1.0 flat URLs: tiny redirects to the right locale, hash kept
    static/               shared CSS, JS, favicon and Open Graph images

Two layers are kept apart on every page:
  - analyst judgment: probability, confidence, status, from the preregistered baseline and
    append-only updates (changed only by a person, or a status by a preregistered rule);
  - automatic evidence state: observations, test outcomes and the terminal check as of the
    latest data refresh.

Language never forks the research: the model below is computed once, and each locale only
chooses words for it (site/views.py, site/i18n/*.yaml).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import markdown
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "site"))

import localization as L  # noqa: E402
from charts import line_chart  # noqa: E402
from cnmacro.claims import load_claims  # noqa: E402
from cnmacro.derive import REF_RE, Deriver, parse_drv  # noqa: E402
from cnmacro.evidence import load_tests  # noqa: E402
from cnmacro.refresh import evaluate, previous_evidence_as_of  # noqa: E402
from cnmacro.store import as_of, load_dictionary, load_observations, release_time, utc_naive  # noqa: E402
from cnmacro.thesis import case_files, effective_case, fold, load_yaml  # noqa: E402
from views import View, pick, validate_policy_events  # noqa: E402
from portal import CATEGORY_METRICS, portal_context  # noqa: E402
from data_portal import build_data_portal, data_context, public_history, write_data_assets  # noqa: E402

SITE = yaml.safe_load((ROOT / "site/site.yaml").read_text(encoding="utf-8"))
SITE_URL = SITE["url"].rstrip("/")
HYP_ORDER = ["H1", "H2", "H3", "H4", "H0"]
PAGES = ["index", "daily", "data", "policy", "memo", "evidence", "updates", "charts", "method"] + [f"data-{c}" for c in CATEGORY_METRICS]
PRIMARY_PAGES = ["index", "daily", "data", "policy", "memo"]
REF_LINES = {"%": 0.0}


def page_file(stem: str) -> str:
    return f"{stem}.html"


def page_url(loc: str, stem: str) -> str:
    """Absolute URL used in canonical / hreflang / Open Graph (identical on every host that serves the build)."""
    return f"{SITE_URL}/{loc}/" if stem == "index" else f"{SITE_URL}/{loc}/{stem}.html"


def git(*args) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def first_commit(path: Path, audit: dict) -> dict:
    """First commit of an immutable file: from git history, else from the eval report's audit
    manifest (for hosts that build from a shallow clone)."""
    try:
        rel = path.resolve().relative_to(ROOT).as_posix()   # the audit manifest's keys are git paths
    except ValueError:
        return {"sha": None, "short": None, "at": None}
    a = audit.get(rel)
    if a and a.get("origin"):            # first committed in the origin repository (origin_history.json)
        return {"sha": a["sha"], "short": a["sha"][:7], "at": a["at"]}
    # in a shallow clone git log would name the graft commit, so only the manifest is trusted there
    out = "" if git("rev-parse", "--is-shallow-repository") == "true" else git("log", "--diff-filter=A", "--format=%H|%cI", "--", rel)
    if out:
        sha, at = out.splitlines()[-1].split("|")
        return {"sha": sha, "short": sha[:7], "at": at}
    a = audit.get(rel)
    if a:
        return {"sha": a["sha"], "short": a["sha"][:7], "at": a["at"]}
    return {"sha": None, "short": None, "at": None}


# ---------------------------------------------------------------- synthetic preview
def synthetic_observations(metrics) -> "object":
    """Random-walk placeholder series so the layout can be reviewed without real data.
    Output is watermarked SYNTHETIC on every page and written outside site/dist."""
    import pandas as pd
    rng = random.Random(7)
    rows = []
    for m in metrics.values():
        n = 30 if m.frequency == "M" else 12
        start = pd.Period("2024-04", "M") if m.frequency == "M" else pd.Period("2023Q4", "Q")
        level = {"%": 0.0, "index (50 = no change)": 49.5}.get(m.unit, 100.0)
        for i in range(n):
            level += rng.gauss(0.05, 0.4 if m.unit != "CNY 100m" else 3)
            p = start + i
            rows.append({"metric_id": m.metric_id, "reference_period": str(p), "value": round(level, 2),
                         "release_date": "", "release_date_basis": "unknown",
                         "retrieved_at": "2026-10-01T00:00:00+00:00", "source": "SYNTHETIC", "source_code": "",
                         "source_class": "public", "consensus": float("nan"), "quality_flag": "ok",
                         "limitation": "synthetic preview", "_file": "synthetic"})
    return pd.DataFrame(rows)


def test_metrics(t) -> set[str]:
    if "(" not in t.indicator:
        return {t.indicator}
    _, args = parse_drv(t.indicator)
    return set(args)


def load_optional(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.exists() else {}


# ---------------------------------------------------------------- provenance (language-neutral)
def obs_row(store, metric_id: str, period: str):
    sub = store[(store.metric_id == metric_id) & (store.reference_period == period)]
    return sub.iloc[-1] if len(sub) else None


def latest_release(rows) -> str | None:
    dated = [r for r in rows if r is not None and r["release_date"]]
    return max((r["release_date"] for r in dated), key=release_time) if dated else None


def claim_sources(claim, store, d: Deriver) -> tuple[list[dict], list[dict]]:
    """(provenance groups, technical lineage) for one claim. Groups are what a reader sees by default
    (institution, metric, period, release date); lineage is the full obs:/drv: trace with codes."""
    groups: dict[tuple, dict] = {}
    lineage = []
    for ref in claim.all_refs():
        kind, body, period = REF_RE.match(ref).groups()
        if kind == "obs":
            key, meta = ("obs", body), {"kind": "obs", "metric_id": body}
        else:
            fn, args = parse_drv(body)
            key, meta = ("drv", f"{fn}({','.join(args)})"), {"kind": "drv", "fn": fn, "args": args}
        g = groups.setdefault(key, {**meta, "periods": [], "refs": []})
        if period not in g["periods"]:
            g["periods"].append(period)
        g["refs"].append(ref)
        try:
            pt = d.resolve(ref)
        except (KeyError, ValueError):
            pt = None
        entry = {"ref": ref, "value": None if pt is None else round(pt.value, 4), "inputs": list(pt.inputs) if pt else []}
        if kind == "obs":
            row = obs_row(store, body, period)
            if row is not None:
                entry.update(source=row["source"], source_code=row["source_code"] or None,
                             release_date=row["release_date"] or None, release_basis=row["release_date_basis"],
                             retrieved_at=row["retrieved_at"])
        lineage.append(entry)
    out = []
    for g in groups.values():
        g["periods"] = sorted(g["periods"], reverse=True)
        latest = g["periods"][0]
        if g["kind"] == "obs":
            rows = [obs_row(store, g["metric_id"], latest)]
            mids = [g["metric_id"]]
        else:
            ref = next(r for r in g["refs"] if r.endswith("@" + latest))
            pt = d.resolve(ref)
            inputs = [REF_RE.match(i).groups() for i in (pt.inputs if pt else [])]
            rows = [obs_row(store, b, p) for _, b, p in inputs]
            mids = sorted({b for _, b, _ in inputs})
        srcs = sorted({r["source"] for r in rows if r is not None})
        retrieved = max((r["retrieved_at"] for r in rows if r is not None), default="")
        out.append({k: v for k, v in g.items() if k != "refs"} | {
            "sources": srcs, "released": latest_release(rows), "retrieved": retrieved[:10], "metrics": mids})
    return out, lineage


# ---------------------------------------------------------------- model (language-neutral)
def build_model(cfg) -> dict:
    case_dir, preview = Path(cfg.case_dir), cfg.preview
    # Supplemental metrics are private research diagnostics: the public site never lists them.
    metrics = {k: m for k, m in load_dictionary(cfg.dictionary).items() if m.tier != "supplemental"}
    obs = synthetic_observations(metrics) if preview else load_observations(cfg.obs_dir)
    now = datetime.now(timezone.utc)
    eval_path = case_dir / "eval/latest.json"
    eval_report = json.loads(eval_path.read_text(encoding="utf-8")) if eval_path.exists() else None
    audit = (eval_report or {}).get("audit", {})
    # files carried over from the origin repository: their first commit is the origin's, not this repo's snapshot
    origin_path = case_dir / "origin_history.json"
    origin = json.loads(origin_path.read_text(encoding="utf-8")).get("files", {}) if origin_path.exists() else {}
    audit = {**audit, **{k: {"sha": v["sha"], "at": v["at"], "origin": True} for k, v in origin.items()}}

    case = yaml.safe_load((case_dir / "case.yaml").read_text(encoding="utf-8"))
    baseline, amendments, updates, refreshes, state, history = None, [], [], [], None, []
    if list((case_dir / "preregistered").glob("*-baseline.yaml")):
        base_path, upd_paths = case_files(case_dir)
        baseline = load_yaml(base_path)
        baseline["_file"], baseline["_commit"] = base_path.name, first_commit(base_path, audit)
        case, amendments, _ = effective_case(case_dir)  # frozen case + preregistered amendments
        for a in amendments:
            a["_commit"] = first_commit(case_dir / "preregistered" / a["_file"], audit)
        for p in upd_paths:
            u = load_yaml(p)
            u["_file"], u["_commit"] = p.name, first_commit(p, audit)
            updates.append(u)
        for p in sorted((case_dir / "refreshes").glob("*.json")):
            r = json.loads(p.read_text(encoding="utf-8"))
            r["_file"], r["_commit"] = p.name, first_commit(p, audit)
            refreshes.append(r)
        state, history, _ = fold(case_dir)
    draft = None
    if not baseline and (case_dir / "baseline_draft.yaml").exists():
        draft = yaml.safe_load((case_dir / "baseline_draft.yaml").read_text(encoding="utf-8"))

    # ---- the research layers around the frozen artifacts (all optional: a replay sandbox has none)
    presentation = load_optional(case_dir / "presentation.yaml")
    frozen_zh = load_optional(case_dir / "frozen_zh.yaml")
    policy = load_optional(case_dir / "policy_events.yaml")
    sources = load_optional(Path(cfg.dictionary).parent / "sources.yaml") or load_optional(ROOT / "data/dictionary/sources.yaml")
    bad = validate_policy_events(policy)
    if bad:
        raise SystemExit("policy_events.yaml is invalid:\n  " + "\n  ".join(bad))

    # ---- automatic evidence state: as of the latest data refresh (or the latest data held)
    held = max((utc_naive(t) for t in obs["retrieved_at"]), default=None)
    if baseline and not preview:
        ev_as_of = max([previous_evidence_as_of(case_dir)] + ([held.isoformat() + "Z"] if held is not None else []),
                       key=utc_naive)
    else:
        ev_as_of = now.replace(microsecond=0).isoformat()
    ev_obs = as_of(obs, ev_as_of)
    d = Deriver(ev_obs, metrics)
    results_now, terminal_now = evaluate(obs, metrics, case, ev_as_of)
    results_now = {k: v.__dict__ for k, v in results_now.items()}
    base_results = (baseline or {}).get("test_results", {})
    tests = load_tests(case["evidence_tests"])
    test_rows = [{**t.__dict__, "result": results_now.get(t.id, {}), "at_baseline": base_results.get(t.id, {}),
                  "metrics": sorted(test_metrics(t))} for t in tests]
    flips_since_baseline = [t for t in test_rows if t["at_baseline"] and
                            t["at_baseline"].get("outcome") != t["result"].get("outcome")]

    # ---- latest judgment document (baseline or the last analyst/terminal update)
    judgment_doc = updates[-1] if updates else baseline

    # ---- claims: render with public data only; refs missing from the public store are withheld
    claims_path = case_dir / "claims.jsonl"
    claims = load_claims(claims_path) if claims_path.exists() else []
    rendered = {}
    for c in claims:
        store = as_of(obs, c.as_of)
        dc, withheld = Deriver(store, metrics), set()
        for r in c.all_refs():
            try:
                if dc.resolve(r) is None:
                    withheld.add(r)
            except (KeyError, ValueError):
                withheld.add(r)
        prov, lineage = claim_sources(c, store, dc)
        rendered[c.id] = {"id": c.id, "type": c.type, "stance": c.stance, "hypotheses": c.hypotheses,
                          "text": {loc: c.render(withheld, loc) for loc in L.LOCALES},
                          "refs": c.all_refs(), "withheld": bool(withheld), "source": c.source,
                          "supports": c.supports, "as_of": c.as_of,
                          "prov": prov, "lineage": lineage}

    hyp = []
    for h in HYP_ORDER:
        rows = [t for t in test_rows if t["hypothesis"] == h]
        hyp.append({
            "id": h, **case["hypotheses"][h],
            "tests": rows,
            "supports": sum(1 for t in rows if t["result"].get("effect") == "supports"),
            "challenges": sum(1 for t in rows if t["result"].get("effect") == "challenges"),
            "pending": sum(1 for t in rows if t["result"].get("outcome") in (None, "insufficient_data")),
            "assessment": (baseline or {}).get("hypothesis_assessment", {}).get(h),
            "claims_for": [v["id"] for v in rendered.values() if h in v["hypotheses"] and v["stance"] == "for"],
            "claims_against": [v["id"] for v in rendered.values() if h in v["hypotheses"] and v["stance"] == "against"],
        })

    # ---- charts (as of the evidence state)
    charts, by_h, freshness = [], {h: [] for h in HYP_ORDER}, []
    for m in metrics.values():
        s = d.series_for(m.metric_id).dropna()
        sub = ev_obs[ev_obs.metric_id == m.metric_id]
        pts = [(str(p), float(v)) for p, v in s.items()][-36 if m.frequency == "M" else -16:]
        ref = 50.0 if m.unit.startswith("index") else REF_LINES.get(m.unit)
        latest = sub[sub.reference_period == pts[-1][0]] if pts else sub.iloc[0:0]
        rel = latest["release_date"].iloc[0] if len(latest) and latest["release_date"].iloc[0] else None
        chart = {
            "m": m, "id": f"ch-{m.metric_id}", "pts": pts, "ref": ref,
            "first": pts[0][0] if pts else None,
            "latest": pts[-1][0] if pts else None, "latest_release": rel,
            "sources": sorted(set(sub["source"])) or [m.source_primary],
            "retrieved": max(sub["retrieved_at"]) if len(sub) else None,
            "n": len(pts),
        }
        charts.append(chart)
        by_h[m.hypotheses[0]].append(chart)
        if pts and m.tier == "core":
            freshness.append(chart)
    latest_rel = max((c for c in charts if c["latest_release"]), key=lambda c: utc_naive(c["latest_release"]),
                     default=None)

    case_target = case["target"]
    defl_id = case_target.split(":", 1)[1].rsplit("@", 1)[0] if case_target.startswith("drv:") else case_target
    defl = d.series_for(defl_id).dropna()
    defl_pts = [(str(p), float(v)) for p, v in defl.items()][-16:]

    # ---- next releases and what they will test
    calendar = yaml.safe_load(Path(cfg.calendar).read_text(encoding="utf-8")).get("releases", []) if Path(cfg.calendar).exists() else []
    upcoming = sorted((r for r in calendar if utc_naive(r["release"]) > utc_naive(ev_as_of)),
                      key=lambda r: utc_naive(r["release"]))
    next_releases = []
    for r in upcoming[:5]:
        ids = set(r["metrics"])
        next_releases.append({**r, "tests": [t for t in test_rows if ids & set(t["metrics"])]})

    # ---- audit timeline (oldest first)
    audit_items = []
    if baseline:
        audit_items.append({"kind": "baseline", "when": baseline["_commit"].get("at") or baseline["as_of"], "doc": baseline})
        audit_items += [{"kind": "amendment", "when": a["_commit"].get("at") or str(a.get("date")), "doc": a} for a in amendments]
        audit_items += [{"kind": "refresh", "when": r["as_of"], "doc": r} for r in refreshes]
        audit_items += [{"kind": "update", "when": u["as_of"], "doc": u} for u in updates]
        audit_items.sort(key=lambda x: utc_naive(x["when"]))

    # ---- "latest data refresh": the newest refresh record, else the newest data pull
    refresh_at = refreshes[-1]["as_of"] if refreshes else (held.isoformat() + "Z" if held is not None else None)

    judgment_file = judgment_doc["_file"] if judgment_doc else None
    return {
        "preview": preview, "banner": cfg.banner, "draft": draft, "case": case, "metrics": metrics,
        "baseline": baseline, "amendments": amendments, "updates": updates, "refreshes": refreshes,
        "judgment_doc": judgment_doc, "judgment_file": judgment_file, "state": state, "history": history,
        "hypotheses": hyp, "charts": charts, "charts_by_h": by_h, "freshness": freshness, "latest_release": latest_rel,
        "target_pts": defl_pts, "claims": rendered,
        "eval": eval_report, "tests": test_rows,
        "evidence_as_of": ev_as_of, "refresh_at": refresh_at, "terminal_now": terminal_now,
        "flips_since_baseline": flips_since_baseline,
        "next_releases": next_releases, "audit_items": audit_items,
        "presentation": presentation, "frozen_zh": frozen_zh, "policy": policy, "sources": sources,
        "view_current": (presentation.get("applies_to") == judgment_file) if presentation else None,
        "built_at": now.replace(microsecond=0).isoformat(), "commit": git("rev-parse", "--short", "HEAD"),
        "case_dir": case_dir,
        "observations": ev_obs, "observation_history": public_history(obs, metrics), "release_calendar": calendar,
        "data_portal": build_data_portal(obs, metrics, test_rows, ev_as_of),
    }


# ---------------------------------------------------------------- per-locale context
def memo_html(model: dict, v: View, env_md: Environment) -> tuple[Markup | None, list[dict]]:
    """The Deep Dive in one language. Claims are cited as numbered references; the list of what was
    cited (with human-readable provenance, technical lineage on request) follows the article."""
    path = Path(model["case_dir"]) / f"memo.{v.loc}.md.j2"
    if not path.exists():
        return None, []
    used: list[str] = []

    def c(cid):
        cl = v.claim(cid)
        if not cl:
            return f"[missing claim {cid}]"
        if cid not in used:
            used.append(cid)
        n = used.index(cid) + 1
        return f'{cl["text"]}<sup class="cite"><a href="#ref-{n}" id="cite-{cid}" title="{cl["type_label"]}">[{n}]</a></sup>'

    state = dict(model["state"] or {"probability": (model["draft"] or {}).get("probability"),
                                    "conviction": (model["draft"] or {}).get("conviction", "–"), "status": "PROPOSED"})
    state["probability_pct"] = L.pct(state.get("probability"))
    state["confidence_label"] = v.confidence(state.get("conviction"))
    state["status_label"] = v.status(state.get("status"))
    tpl = env_md.from_string(path.read_text(encoding="utf-8"))
    html = Markup(markdown.markdown(
        tpl.render(c=c, case=v.case(), baseline=model["baseline"], state=state, t=v.t,
                   scenario_matrix=Markup(v.scenario_table_html()), asof=v.date(model["evidence_as_of"])),
        extensions=["tables"]))
    return html, [dict(v.claim(cid), n=i + 1) for i, cid in enumerate(used)]


def chart_card(model: dict, v: View, ch: dict) -> dict:
    m = ch["m"]
    label = v.t("chart.aria", name=v.metric_name(m.metric_id))
    svg = Markup(line_chart(ch["pts"], m.unit, ch["ref"], ch["id"], label=label,
                            empty=v.t("chart.not_enough"))) if ch["pts"] else None
    return {
        "id": m.metric_id, "chart_id": ch["id"], "svg": svg, "name": v.metric_name(m.metric_id),
        "name_alt": m.name if v.loc == "zh" else (m.name_zh or ""),
        "unit": v.unit(m.unit), "tier": m.tier, "tier_label": v.t(f"tier.{m.tier}"), "hypotheses": m.hypotheses,
        "period": f"{v.period(ch['first'])} – {v.period(ch['latest'])}" if ch["pts"] else v.t("chart.no_data"),
        "latest": ch["latest"], "latest_release": ch["latest_release"],
        "sources": [v.source_name(s) for s in ch["sources"]], "source_codes": [m.source_code] if m.source_code else [],
        "retrieved": ch["retrieved"], "role": v.metric_role(m.metric_id),
    }


def eval_view(model: dict, v: View) -> dict | None:
    e = model["eval"]
    if not e:
        return None
    mname = v.metric_name
    checks = []
    for c in e["checks"]:
        details = []
        for dtl in c.get("details", []):
            loc_text = L.localize_eval_detail(dtl, v.t, mname) if v.loc == "zh" else None
            details.append({"text": loc_text or dtl, "raw": loc_text is None and v.loc == "zh"})
        checks.append({**c, "label": v.t(f"eval.name.{c['id']}"), "what": v.t(f"eval.what.{c['id']}"), "details": details})
    fails = [c for c in e["checks"] if c["status"] == "fail"]
    warns = [c for c in e["checks"] if c["status"] == "warn"]
    return {**e, "checks": checks, "fails": len(fails), "warns": len(warns)}


def context(model: dict, v: View, stem: str, env_md: Environment) -> dict:
    loc, t = v.loc, v.t
    other = "zh" if loc == "en" else "en"
    case = v.case()
    state, draft, baseline = model["state"], model["draft"], model["baseline"]
    hyps = []
    for h in model["hypotheses"]:
        hyps.append({
            "id": h["id"], **v.hypothesis_text(h["id"], h), "state": v.view_state(h["id"]),
            "assessment": v.assessment(h["id"], h["assessment"]) if h["assessment"] else None,
            "tests": [v.test_row(r) for r in h["tests"]],
            "supports": h["supports"], "challenges": h["challenges"], "pending": h["pending"],
            "claims_for": [v.claim(c) for c in h["claims_for"]], "claims_against": [v.claim(c) for c in h["claims_against"]],
        })
    ctx = {
        "loc": loc, "t": t, "v": v, "page": stem, "other": other, "case": case, "hypotheses": hyps,
        "baseline": baseline, "draft": draft, "state": state, "preview": model["preview"], "banner": model["banner"],
        "updates": model["updates"], "refreshes": model["refreshes"],
        "judgment_doc": model["judgment_doc"],
        "status_label": v.status(state["status"] if state else ("PROPOSED" if draft else "DRAFT")),
        "confidence_label": v.confidence(state["conviction"] if state else (draft or {}).get("conviction")),
        "direction_label": v.direction(state["last_update_direction"]) if state else "–",
        "prob": L.pct((state or draft or {}).get("probability")),
        "evidence_as_of": model["evidence_as_of"], "refresh_at": model["refresh_at"],
        "terminal_now": model["terminal_now"], "terminal_label": v.status(model["terminal_now"]["status"]),
        "flips_since_baseline": model["flips_since_baseline"],
        "latest_release": model["latest_release"], "view_current": model["view_current"],
        "built_at": model["built_at"], "commit": model["commit"],
        "tests": [v.test_row(r) for r in model["tests"]],
    }
    ctx["amendments"] = [{**a, "title_l": v.frozen(a.get("title"), "documents", a["_file"], "title", what=f"{a['_file']} title")}
                         for a in model["amendments"]]
    ctx["other_claims"] = [v.claim(cid) for cid, c in model["claims"].items() if c["stance"] == "context"]
    cv = v.p.get("current_view") or {}
    ctx["current_view"] = {k: pick(cv.get(k), loc) for k in ("headline", "body", "policy")}
    ctx["top_for"], ctx["top_against"] = v.curated("top_evidence_for"), v.curated("top_evidence_against")
    ctx["policy"] = v.policy()
    ctx["rules"] = v.rules()
    ctx["scenarios"] = v.scenarios()
    ctx["limitations"] = v.limitations()
    ctx["sources_status"] = v.sources_status()
    ctx["eval"] = eval_view(model, v)
    ctx["metrics_table"] = [{"name": v.metric_name(m.metric_id), "alt": m.name if loc == "zh" else (m.name_zh or ""),
                             "tier": t(f"tier.{m.tier}"), "hypotheses": m.hypotheses, "role": v.metric_role(m.metric_id),
                             "source": v.source_name(m.source_primary)} for m in model["metrics"].values()]
    ctx["n_core"] = sum(1 for m in model["metrics"].values() if m.tier == "core")
    ctx["n_diag"] = sum(1 for m in model["metrics"].values() if m.tier == "diagnostic")
    ctx["n_tests"] = len(model["tests"])
    ctx["next_releases"] = [{"label": v.release_label(r), "release": r["release"],
                             "tests": [v.test_row(x) for x in r["tests"]]} for r in model["next_releases"]]
    ctx["freshness_latest"] = ({"name": v.metric_name(model["latest_release"]["m"].metric_id),
                                "period": v.period(model["latest_release"]["latest"], long=True),
                                "released": model["latest_release"]["latest_release"]}
                               if model["latest_release"] else None)
    pts = model["target_pts"]
    ctx["target_chart"] = Markup(line_chart(pts, "%", 0.0, "ch-target", width=1000, height=280,
                                            label=t("chart.aria", name=t("home.target_title")),
                                            empty=t("chart.not_enough"))) if len(pts) >= 2 else None
    ctx["charts_by_h"] = {h: [chart_card(model, v, ch) for ch in chs] for h, chs in model["charts_by_h"].items()}
    # audit timeline, localized where the immutable documents are English-only
    items = []
    for it in model["audit_items"]:
        d = dict(it["doc"])
        if it["kind"] == "baseline":
            d["rationale_l"] = v.frozen(d.get("rationale"), "documents", d["_file"], "rationale", what="baseline rationale")
            cb = d.get("committed_before")
            d["committed_release"] = v.release_name(cb["release"]) if cb else None
        elif it["kind"] == "amendment":
            for k in ("title", "reason", "effect"):
                d[k + "_l"] = v.frozen(d.get(k), "documents", d["_file"], k, what=f"{d['_file']} {k}")
            d["effective_release"] = v.release_name(d["effective_before"]["release"])
        elif it["kind"] == "update":
            # analyst updates are written in English; a Chinese text is `<field>_zh`. Without one the Chinese page
            # shows the English original, marked lang="en" (never silently mixed), and the build reports it.
            pc = d.get("probability_change") or {}
            for out_key, en_text, zh_text in (("does_this_change_the_thesis", d.get("does_this_change_the_thesis"), d.get("does_this_change_the_thesis_zh")),
                                              ("reasoning", pc.get("reasoning"), pc.get("reasoning_zh"))):
                fallback = loc == "zh" and bool(en_text) and not zh_text
                if fallback:
                    v.need(f"{d['_file']} {out_key}", en_text)
                d[out_key + "_l"] = zh_text if (loc == "zh" and zh_text) else en_text
                d[out_key + "_fb"] = fallback
            d["release_l"] = v.release_name(d["release"])
        items.append({"kind": it["kind"], "doc": d})
    ctx["audit_items"] = items
    ctx["portal"] = portal_context(model, v)
    if stem == "policy":
        from official_inbox import policy_inbox
        ctx["official_inbox"] = policy_inbox(model, loc)
        from policy_comparisons import comparison_view
        ctx["policy_comparisons"] = comparison_view(model, loc)
    if stem.startswith("data-"):
        ctx["category"] = next(c for c in ctx["portal"]["categories"] if c["id"] == stem[5:])
        ctx["data_explorer"] = data_context(model, v, stem[5:])
    if stem == "data":
        ctx["data_explorer"] = data_context(model, v)
    ctx["memo"], ctx["memo_refs"] = memo_html(model, v, env_md) if stem == "memo" else (None, [])
    return ctx


def meta(v: View, stem: str) -> dict:
    loc, t = v.loc, v.t
    key_stem = "data" if stem.startswith("data-") else stem
    title_key = f"page.{key_stem}.title"
    title = t("site.title") if stem == "index" else f"{t(title_key)} · {t('site.title')}"
    return {
        "title": title, "description": t(f"page.{key_stem}.description"), "canonical": page_url(loc, stem),
        "alternates": [(L.HREFLANG[l], page_url(l, stem)) for l in L.LOCALES] + [("x-default", f"{SITE_URL}/")],
        "og_image": f"{SITE_URL}/static/og-{loc}.png", "og_image_alt": t("site.og_alt"),
        "og_locale": L.OG_LOCALE[loc], "og_alternate": [L.OG_LOCALE[x] for x in L.LOCALES if x != loc],
        "site_name": t("site.name"),
    }


# ---------------------------------------------------------------- render
def make_env(loc: str) -> Environment:
    env = Environment(loader=FileSystemLoader(ROOT / "site/templates"), autoescape=select_autoescape(["html"]))
    env.filters["pct"] = L.pct
    env.filters["when"] = lambda v: L.fmt_when(v, loc)
    env.filters["date"] = lambda v: L.fmt_date(v, loc)
    env.filters["period"] = lambda v: L.fmt_period(v, loc)
    env.filters["num"] = lambda v: "–" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.2f}"
    env.filters["short"] = lambda s: (s or "")[:7]
    # label punctuation is the language's own: "Why: text" / "原因：文字" (no space after a full-width colon)
    env.filters["colon"] = lambda s: f"{s}：" if loc == "zh" else f"{s}: "
    env.filters["labelb"] = lambda s: Markup(f"<strong>{escape(s)}：</strong>" if loc == "zh" else f"<strong>{escape(s)}:</strong> ")
    env.globals["colon_s"] = "：" if loc == "zh" else ": "
    return env


def render_site(model: dict, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "site/static", out / "static")
    write_data_assets(model["data_portal"], out)
    # browsers ask for /favicon.ico at the root before they read any <link>
    if (out / "static/favicon.ico").exists():
        shutil.copy(out / "static/favicon.ico", out / "favicon.ico")
    missing: dict[str, list[str]] = {}
    for loc in L.LOCALES:
        env, env_md = make_env(loc), Environment()
        v = View(model, loc)
        (out / loc).mkdir()
        for stem in PAGES:
            ctx = context(model, v, stem, env_md)
            ctx["meta"] = meta(v, stem)
            ctx["asset"] = "../static/"
            ctx["lang_base"] = {l: f"../{l}/{page_file(stem)}" for l in L.LOCALES}
            ctx["nav"] = [(page_file(s), v.t(f"nav.{s}"), s == stem or (s == "data" and stem.startswith("data-"))) for s in PRIMARY_PAGES]
            ctx["footer_nav"] = [(page_file(s), v.t(f"nav.{s}")) for s in ["memo", "evidence", "updates", "charts", "method"]]
            html = env.get_template("data-category.html" if stem.startswith("data-") else page_file(stem)).render(**ctx)
            (out / loc / page_file(stem)).write_text(html, encoding="utf-8")
        missing[loc] = sorted(set(v.missing))
    # the root selector and the legacy V1.0 flat URLs
    t_en, t_zh = L.Translator("en"), L.Translator("zh")
    env = make_env("en")
    root_ctx = {"site_url": SITE_URL, "t_en": t_en, "t_zh": t_zh, "asset": "static/",
                "alternates": [(L.HREFLANG[l], page_url(l, "index")) for l in L.LOCALES] + [("x-default", f"{SITE_URL}/")],
                "canonical": f"{SITE_URL}/", "og_image": f"{SITE_URL}/static/og-en.png"}
    (out / "index.html").write_text(env.get_template("root.html").render(**root_ctx, stem=None), encoding="utf-8")
    for stem in PAGES[1:]:
        legacy = {**root_ctx, "canonical": page_url("en", stem), "stem": stem}
        (out / page_file(stem)).write_text(env.get_template("legacy.html").render(**legacy), encoding="utf-8")
    return missing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="synthetic data, layout review only")
    ap.add_argument("--case-dir", default=str(ROOT / "research/cases/cn-nominal"))
    ap.add_argument("--obs-dir", default=str(ROOT / "data/demo/observations"))
    ap.add_argument("--calendar", default=str(ROOT / "data/dictionary/release_calendar.yaml"))
    ap.add_argument("--dictionary", default=str(ROOT / "data/dictionary/metrics.yaml"))
    ap.add_argument("--out")
    ap.add_argument("--banner", help="a notice shown on every page (e.g. for a replay build)")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else ROOT / ("site/dist-preview" if a.preview else "site/dist")
    if out.exists():
        shutil.rmtree(out)
    model = build_model(a)
    missing = render_site(model, out)
    n = sum(1 for _ in out.rglob("*.html"))
    print(f"built {n} pages ({len(L.LOCALES)} locales x {len(PAGES)} + selector + {len(PAGES) - 1} legacy redirects) -> {out}")
    for loc, items in missing.items():
        if items and model["presentation"]:
            print(f"warning: {len(items)} text(s) fell back to English on the {loc} pages: {items[:5]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
