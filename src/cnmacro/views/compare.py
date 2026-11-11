"""Signed view vs. evidence since: which hypotheses has the evidence moved on, and has the
signed view kept up?

Inputs are committed, append-only artifacts only:
  * the signed view: the latest of the preregistered baseline and `updates/*.yaml`, with its
    per-hypothesis assessment and (when it carries them) the test results it was signed on;
  * the evidence: the refresh records in `refreshes/*.json` (their `test_results`);
  * the frozen Chinese renderings in `frozen_zh.yaml` for the zh text of immutable English.

Everything is a mechanical comparison of test outcomes. Direction uses the same rule as the
refresh record's `suggested_direction` (support for H0 counts against the thesis). The result
is a prompt for analyst review, never a judgment: it changes no probability, conviction,
status or test, and an AI is not involved.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ..refresh import EFFECT, suggested_direction
from ..store import utc_naive
from ..thesis import case_files, effective_case, load_yaml
from . import external as ext

ORDER = ("H1", "H2", "H3", "H4", "H0")
STATE_KEYS = ("probability", "conviction", "status", "last_update_direction")


def _load_optional_yaml(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.is_file() else {}


def signed_documents(case_dir: Path) -> list[dict]:
    """Baseline then updates, oldest first; each tagged with its file name."""
    base_path, update_paths = case_files(case_dir)
    docs = []
    for p in [base_path, *update_paths]:
        d = load_yaml(p)
        d["_file"] = p.name
        docs.append(d)
    return docs


def refresh_records(case_dir: Path) -> list[dict]:
    out = []
    for p in sorted((case_dir / "refreshes").glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        if "test_results" in r:
            r["_file"] = p.name
            out.append(r)
    return sorted(out, key=lambda r: utc_naive(r["as_of"]))


def _evidence_at_signing(doc: dict, refreshes: list[dict]) -> tuple[dict | None, str | None, str | None]:
    """The test results the signed view was signed on: its own if it carries them, otherwise
    the latest refresh at or before its as_of (never a later one)."""
    if doc.get("test_results"):
        return doc["test_results"], doc["_file"], str(doc["as_of"])
    signed = utc_naive(doc["as_of"])
    prior = [r for r in refreshes if utc_naive(r["as_of"]) <= signed]
    if prior:
        return prior[-1]["test_results"], prior[-1]["_file"], str(prior[-1]["as_of"])
    return None, None, None


def _tally(results: dict, ids: list[str]) -> dict:
    out = {"supports": 0, "challenges": 0, "insufficient": 0}
    for t in ids:
        r = results.get(t)
        if r is None or r.get("outcome") == "insufficient_data" or r.get("effect") not in ("supports", "challenges"):
            out["insufficient"] += 1
        else:
            out[r["effect"]] += 1
    return out


def _flips(then: dict, now: dict, ids: list[str]) -> list[dict]:
    flips = []
    for t in ids:
        a, b = then.get(t), now.get(t)
        if a is None or b is None or a.get("outcome") == b.get("outcome"):
            continue
        flips.append({"test": t, "hypothesis": b["hypothesis"], "from": a["outcome"], "to": b["outcome"],
                      "effect_from": a.get("effect", "none"), "effect_to": b.get("effect", "none"),
                      "observed_from": a.get("observed"), "observed_to": b.get("observed"),
                      "period_from": a.get("latest_period"), "period_to": b.get("latest_period"),
                      "refs_to": list(b.get("refs", []))})
    return flips


def _score(flips: list[dict]) -> int:
    return suggested_direction(flips)["score"]


def build_comparison(case_dir: str | Path, *, to_refresh: str | None = None,
                     external_dir: str | Path | None = None, access_file: str | Path | None = None,
                     public: bool = True, now: str | None = None) -> dict:
    """The comparison object (JSON-serialisable, one object for both locales)."""
    case_dir = Path(case_dir)
    case, _, _ = effective_case(case_dir)
    frozen_zh = _load_optional_yaml(case_dir / "frozen_zh.yaml")
    docs = signed_documents(case_dir)
    refreshes = refresh_records(case_dir)
    if to_refresh:
        refreshes_upto = [r for r in refreshes if r["_file"] <= to_refresh]
        if not refreshes_upto or refreshes_upto[-1]["_file"] != to_refresh:
            raise ValueError(f"no refresh record named {to_refresh}")
        refreshes = refreshes_upto
        # the signed view in force at the cutoff, never a later update (or its later results)
        cutoff = utc_naive(refreshes[-1]["as_of"])
        docs = [d for d in docs if utc_naive(d["as_of"]) <= cutoff]
        if not docs:
            raise ValueError(f"{to_refresh} precedes the first signed view")
    signed = docs[-1]

    then, then_src, then_as_of = _evidence_at_signing(signed, refreshes)
    after = [r for r in refreshes if utc_naive(r["as_of"]) > utc_naive(signed["as_of"])]
    if then is None and after:   # nothing at or before signing: compare from the first record after it
        then, then_src, then_as_of = after[0]["test_results"], after[0]["_file"], str(after[0]["as_of"])
    latest = after[-1] if after else None
    now_results = latest["test_results"] if latest else (then or {})
    now_src = latest["_file"] if latest else then_src
    now_as_of = str(latest["as_of"]) if latest else then_as_of
    then = then or {}

    tests = case.get("evidence_tests", [])
    zh_tests = frozen_zh.get("tests", {})
    by_h: dict[str, list[str]] = {h: [] for h in ORDER}
    desc = {}
    for t in tests:
        by_h.setdefault(t["hypothesis"], []).append(t["id"])
        desc[t["id"]] = {"en": t.get("description", ""), "zh": zh_tests.get(t["id"], t.get("description", ""))}

    zh_doc = frozen_zh.get("documents", {}).get(signed["_file"], {})
    assess_en = signed.get("hypothesis_assessment", {}) or {}
    assess_zh = zh_doc.get("hypothesis_assessment", {}) or {}
    names_zh = frozen_zh.get("hypotheses", {})

    hyps, all_flips = [], []
    for h in [x for x in ORDER if x in case.get("hypotheses", {})]:
        ids = by_h.get(h, [])
        flips = _flips(then, now_results, ids)
        for f in flips:
            f["description"] = desc.get(f["test"], {"en": "", "zh": ""})
        all_flips += flips
        score = _score(flips)
        hyps.append({
            "id": h,
            "name": {"en": case["hypotheses"][h].get("name", h), "zh": names_zh.get(h, {}).get("name", case["hypotheses"][h].get("name", h))},
            "signed_assessment": {"en": assess_en.get(h), "zh": assess_zh.get(h, assess_en.get(h))},
            "tests": len(ids),
            "at_signing": _tally(then, ids),
            "now": _tally(now_results, ids),
            "flips": flips,
            "score": score,
            # flips that cancel out are "mixed", not "unchanged": the evidence did move
            "drift": "toward_thesis" if score > 0 else "against_thesis" if score < 0 else "mixed" if flips else "unchanged",
        })

    overall = suggested_direction(all_flips)
    timeline = []
    for r in after:
        fl = _flips(then, r["test_results"], [t["id"] for t in tests])
        timeline.append({"refresh": r["_file"], "as_of": str(r["as_of"]), "flips_since_signing": len(fl),
                         "score_since_signing": _score(fl)})
    signed_at = utc_naive(signed["as_of"])
    age_days = (utc_naive(now_as_of) - signed_at).days if now_as_of else 0

    ext_dir = Path(external_dir) if external_dir else None
    views, view_errors = ext.load_external_views(ext_dir, now_as_of, public=public) if ext_dir else ([], [])
    latest_views = ext.latest_per_institution(views)
    for hyp in hyps:
        hv = [v for v in latest_views if v["hypothesis"] == hyp["id"]]
        hyp["external_views"] = [{k: v.get(k) for k in ("view_id", "institution", "institution_type", "title", "published_at",
                                                         "source_url", "via", "stance", "quote")} for v in hv]
        hyp["external_stances"] = {s: sum(v["stance"] == s for v in hv) for s in ext.STANCES}
    external = {
        "status": "connected" if views else "not_connected",
        "institutions": len({v["institution"] for v in views}),
        "documents": len({v["source_url"] for v in views}),
        "forecasts": ext.forecast_summary(views),
        "errors": view_errors,
        "access_checks": ext.access_ledger(access_file) if access_file else [],
        "note": {"en": "External views are shown beside the signed view; they never enter evidence tests, claims or probability.",
                 "zh": "机构观点仅与已签署观点并列展示，不进入证据检验、论断或概率。"},
    }

    return {
        "schema": 1,
        "kind": "view_comparison",
        "case_id": case.get("case_id"),
        "question": {"en": case.get("question"), "zh": case.get("question_zh", case.get("question"))},
        "generated_at": now or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "signed_view": {"file": signed["_file"], "kind": signed.get("kind", "update"), "as_of": str(signed["as_of"]),
                        **{k: signed.get(k) for k in STATE_KEYS}},
        "signed_history": [{"file": d["_file"], "as_of": str(d["as_of"]), **{k: d.get(k) for k in STATE_KEYS}} for d in docs],
        "evidence_at_signing": {"source": then_src, "as_of": then_as_of},
        "evidence_now": {"source": now_src, "as_of": now_as_of},
        "refreshes_since_signing": len(after),
        "signed_view_age_days": age_days,
        "hypotheses": hyps,
        "summary": {
            "flips": len(all_flips),
            "score": overall["score"],
            "direction": overall["direction"],
            "review_prompt": bool(all_flips),
            "moved": [h["id"] for h in hyps if h["flips"]],
        },
        "timeline": timeline,
        "external": external,
        "boundary": {"en": "Mechanical comparison of committed test outcomes. It is a prompt for analyst review, not a judgment; the signed probability, conviction and status change only through a signed update.",
                     "zh": "基于已提交检验结果的机械对比，仅提示分析师复核，不构成判断；已签署的概率、确信度与状态只能通过签署的更新改变。"},
    }


# ------------------------------------------------------------------ Markdown (review / PR use)
TEXT = {
    "title": {"en": "Signed view vs. evidence since", "zh": "已签署观点 vs 此后证据"},
    "signed": {"en": "Signed view", "zh": "已签署观点"},
    "prob": {"en": "probability", "zh": "概率"},
    "conv": {"en": "conviction", "zh": "确信度"},
    "since": {"en": "Evidence compared", "zh": "对比证据"},
    "refreshes": {"en": "refresh records since signing", "zh": "签署后的数据刷新记录"},
    "age": {"en": "days since signing", "zh": "距签署天数"},
    "summary": {"en": "Summary", "zh": "结论"},
    "hyp": {"en": "Hypothesis", "zh": "假设"},
    "then": {"en": "At signing (support/challenge/n.a.)", "zh": "签署时（支持/否定/不足）"},
    "now": {"en": "Now", "zh": "现在"},
    "drift": {"en": "Drift", "zh": "方向"},
    "assess": {"en": "Signed assessment", "zh": "签署时评估"},
    "flipped": {"en": "Tests that flipped since signing", "zh": "签署后发生翻转的检验"},
    "external": {"en": "Institutional views", "zh": "机构观点"},
    "none_flip": {"en": "No evidence test has flipped since the signed view.", "zh": "签署以来没有证据检验发生翻转。"},
    "not_connected": {"en": "No permitted institutional-view source is connected; none are shown. Sources checked:",
                      "zh": "尚未接入获准使用的机构观点来源，因此不展示任何机构观点。已核查的来源："},
}
DRIFT = {"toward_thesis": {"en": "toward thesis", "zh": "偏向命题"}, "against_thesis": {"en": "against thesis", "zh": "偏离命题"},
         "unchanged": {"en": "unchanged", "zh": "未变"}, "mixed": {"en": "mixed (flips offset)", "zh": "分化（翻转相互抵消）"}, "neutral": {"en": "neutral", "zh": "中性"}}


def _fmt(x) -> str:
    return "n/a" if x is None else (f"{x:g}" if isinstance(x, (int, float)) else str(x))


def render_markdown(c: dict, lang: str = "en") -> str:
    T = {k: v[lang] for k, v in TEXT.items()}
    s, sv = c["summary"], c["signed_view"]
    lines = [f"# {T['title']} · {c['case_id']}", "", f"> {c['question'][lang]}", "",
             f"**{T['signed']}:** `{sv['file']}` · {sv['as_of'][:10]} · {T['prob']} {_fmt(sv['probability'])} · "
             f"{T['conv']} {sv['conviction']} · {sv['status']}",
             f"**{T['since']}:** `{c['evidence_at_signing']['source']}` → `{c['evidence_now']['source']}` "
             f"({c['refreshes_since_signing']} {T['refreshes']}; {c['signed_view_age_days']} {T['age']})", "",
             f"## {T['summary']}", ""]
    if s["flips"]:
        moved = ", ".join(s["moved"])
        lines.append({"en": f"{s['flips']} evidence test(s) flipped since signing ({moved}); net mechanical direction: "
                            f"**{DRIFT[s['direction']]['en']}** (score {s['score']:+d}). The signed view has not been updated; "
                            "this is a candidate for analyst review, not a judgment.",
                      "zh": f"签署以来共有 {s['flips']} 项证据检验翻转（{moved}）；机械方向：**{DRIFT[s['direction']]['zh']}**"
                            f"（得分 {s['score']:+d}）。已签署观点尚未更新；这是提示分析师复核的候选，不构成判断。"}[lang])
    else:
        lines.append(T["none_flip"])
    lines += ["", f"| {T['hyp']} | {T['then']} | {T['now']} | {T['drift']} | {T['assess']} |", "|---|---|---|---|---|"]
    for h in c["hypotheses"]:
        a, n = h["at_signing"], h["now"]
        lines.append(f"| {h['id']} {h['name'][lang]} | {a['supports']}/{a['challenges']}/{a['insufficient']} | "
                     f"{n['supports']}/{n['challenges']}/{n['insufficient']} | {DRIFT[h['drift']][lang]} | "
                     f"{(h['signed_assessment'][lang] or '').replace('|', '/')} |")
    flips = [f for h in c["hypotheses"] for f in h["flips"]]
    if flips:
        lines += ["", f"## {T['flipped']}", ""]
        for f in flips:
            lines.append(f"- **{f['test']}** ({f['hypothesis']}) {f['description'][lang]} — "
                         f"{f['from']} @ {_fmt(f['period_from'])} ({_fmt(f['observed_from'])}) → "
                         f"{f['to']} @ {_fmt(f['period_to'])} ({_fmt(f['observed_to'])}); refs: "
                         + ", ".join(f"`{r}`" for r in f["refs_to"]))
    e = c["external"]
    lines += ["", f"## {T['external']}", ""]
    if e["status"] == "connected":
        for h in c["hypotheses"]:
            for v in h["external_views"]:
                lines.append(f"- {h['id']} · {v['institution']} · {v['published_at'][:10]} · {v['stance']} · "
                             f"[{v['title']}]({v['source_url']}) — “{v['quote']}”")
        for fc in e["forecasts"]:
            vals = "; ".join(f"{x['institution']} {_fmt(x['value'])}" for x in fc["values"])
            med = f" · median {_fmt(fc['median'])} (n={fc['n']})" if fc["consensus"] else f" · n={fc['n']} (< 5, no consensus)"
            lines.append(f"- {fc['metric_id']} {fc['period']} ({fc['unit']}): {vals}{med}")
    else:
        lines.append(T["not_connected"])
        for a in e["access_checks"]:
            lines.append(f"  - {a.get('checked_on')} · {a.get('source')}: {a.get('result', {}).get(lang) if isinstance(a.get('result'), dict) else a.get('result')}")
    lines += ["", f"_{c['boundary'][lang]}_", ""]
    return "\n".join(lines)
