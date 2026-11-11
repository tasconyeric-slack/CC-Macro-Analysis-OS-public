"""Research input bundle: already-collected news, policy and official-release records, triaged for the
CN nominal-growth thesis (H0-H4). Deterministic; no model call, no new source, no typed figures.

    research/cases/cn-nominal/inputs/<YYYY-MM-DD>.json     one bundle per as_of date, written once

Inputs (read only, public):
    data/events            official intake: grouped occurrences, stage, excerpt-backed H0-H4 links
    data/news/latest.json  news feed: deterministic event groups (news_rank) and their member items
    data/news/archive      captured news items (first_seen_at / canonical URL)
    research/cases/cn-nominal/refreshes   which observations each refresh actually added

Selection orders by research materiality, never by heat: an official release that changed an
observation used by a preregistered evidence test, then first-party policy with an action, then
media leads. Media coverage of an occurrence already held first-hand is kept but marked
`repetition_of` (reporting repetition is not an economic change). Nothing here changes a thesis:
the bundle is an input for reports and the analyst draft (#52), and every item is a lead or a
pointer to verified evidence, not a judgment.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .events.grouping import RULES, triage as rule_triage
from .events.store import load_grouped_items, stamp
from .news_feed import CHINA, FOREIGN, TOPICS, classify
from .news_rank import TYPES

VERSION = 1
GENERATOR = "deterministic:cnmacro.research_inputs@1"
TRIAGES = ("research_needed", "monitor", "irrelevant")
EVIDENCE_KINDS = ("official_release", "first_party_policy", "media_report")
MECHANISM = {"H1": "prices / reflation breadth", "H2": "domestic demand and credit",
             "H3": "policy impulse and transmission", "H4": "external demand", "H0": "supply or cost push (competing)"}
HYP_ORDER = ("H1", "H2", "H3", "H4", "H0")
EXCERPT_CHARS = 160
# news_feed topic -> the hypothesis whose mechanism that topic carries (fallback for first-party items only)
TOPIC_HYP = {"prices": "H1", "growth": "H2", "property": "H2", "credit": "H3", "fiscal": "H3", "trade": "H4"}
ROUNDUP = re.compile(r"要闻|早餐|汇总|晚报|早报|盘前|收评|午评")
OFFICIAL_HOSTS = re.compile(r"(^|\.)(gov\.cn|stats\.gov\.cn|pbc\.gov\.cn|mof\.gov\.cn|mofcom\.gov\.cn|ndrc\.gov\.cn|customs\.gov\.cn|safe\.gov\.cn)$")


class BundleError(ValueError):
    pass


def iso_z(value) -> str:
    return stamp(value).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _excerpt(text: str | None) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:EXCERPT_CHARS] + ("…" if len(text) > EXCERPT_CHARS else "")


def _hyps(hs) -> list[str]:
    have = set(hs)
    return [h for h in HYP_ORDER if h in have]


def _mechanism(hs: list[str]) -> str | None:
    return " + ".join(MECHANISM[h] for h in hs) or None


def _test_metrics(case: dict) -> dict[str, list[str]]:
    """metric_id -> preregistered evidence tests that read it (from the case in force; read only)."""
    from .evidence import load_tests
    out: dict[str, list[str]] = {}
    for t in load_tests(case["evidence_tests"]):
        for mid in re.findall(r"[a-z][a-z0-9_]+", t.indicator):
            out.setdefault(mid, []).append(t.id)
    return out


def _refresh_refs(case_dir: Path, start, end) -> dict[str, list[dict]]:
    """metric_id -> observations a refresh record in the window actually added (with the record file)."""
    out: dict[str, list[dict]] = {}
    for p in sorted((case_dir / "refreshes").glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        if not (start <= stamp(r["as_of"]) <= end):
            continue
        for o in r.get("new_observations", []):
            out.setdefault(o["metric_id"], []).append({"ref": f"obs:{o['metric_id']}@{o['reference_period']}",
                                                       "refresh": p.name})
    return out


def _topic_metrics(text: str, metrics: set[str]) -> list[str]:
    topic = classify(text)
    return [m for m in (TOPICS[topic][3] if topic else []) if m in metrics]


# ---------------------------------------------------------------- candidates from each existing intake
def _official(events_dir: Path, start, end, as_of: str, metrics: set[str], test_metrics, refresh_refs) -> list[dict]:
    out = []
    for r in load_grouped_items(events_dir, as_of=as_of):
        if not r.get("published_at") or not (start <= stamp(r["published_at"]) <= end):
            continue
        hs = _hyps(r.get("hypotheses") or [])
        triage = r.get("triage") or ("monitor" if hs else "irrelevant")
        linked = [m for m in (r.get("metric_ids") or []) if m in metrics]
        if not linked and hs:
            linked = _topic_metrics(r["title_zh"] + " " + (r.get("summary_zh") or ""), metrics)
        is_release = r.get("kind") == "data_release"
        tests = sorted({t for m in linked for t in test_metrics.get(m, [])})
        obs = [x for m in linked for x in refresh_refs.get(m, [])]
        quote = next((h.get("quote_zh") for h in r.get("hypothesis_links") or [] if h.get("quote_zh")), None)
        if is_release and tests and obs:
            triage = "research_needed"
            why = ("Official first print that added observations read by preregistered evidence tests "
                   f"{', '.join(tests)}; compare with the prior reading before any thesis statement.")
        elif triage == "irrelevant" or not hs:
            triage, why = "irrelevant", r.get("triage_reason_en") or "No hypothesis rule matches a specific tool or observation."
        else:
            why = " ".join(dict.fromkeys(m["en"] for m in rule_triage(r, _rules())["mechanism"])) or r.get("triage_reason_en")
        out.append({
            "event_id": r.get("event_id") or r["item_id"], "title": r["title_zh"], "source_url": r["canonical_url"],
            "publisher": r["publisher"], "published_at": iso_z(r["published_at"]), "available_at": iso_z(r["first_seen_at"]),
            "hypotheses": hs if triage != "irrelevant" else [], "mechanism": _mechanism(hs) if triage != "irrelevant" else None,
            "why_relevant": why, "triage": triage, "linked_metrics": linked if triage != "irrelevant" else [],
            "excerpt": _excerpt(quote or r.get("summary_zh") or r["title_zh"]),
            "evidence_kind": "official_release" if is_release else "first_party_policy",
            "repetition_of": None,
            # pointers only: the bundle never carries a value; consumers resolve refs from the store
            "observation_refs": [x["ref"] for x in obs] if triage == "research_needed" else [],
            "refresh_records": sorted({x["refresh"] for x in obs}) if triage == "research_needed" else [],
            "tests": tests if triage == "research_needed" else [],
            "stage": r.get("stage"), "intake_triage": r.get("triage"), "source_status": r.get("status"),
            "coverage": len(r.get("member_item_ids") or [1]),
        })
    return out


_RULES_CACHE: dict = {}


def _rules() -> dict:
    if not _RULES_CACHE:
        _RULES_CACHE.update(yaml.safe_load(Path(RULES).read_text(encoding="utf-8")))
    return _RULES_CACHE


def _news_items(news_dir: Path) -> dict[str, dict]:
    items = {}
    for p in sorted((news_dir / "archive").glob("*.json")):
        for it in json.loads(p.read_text(encoding="utf-8")):
            items.setdefault(it["item_id"], it)
    latest = news_dir / "latest.json"
    if latest.exists():
        for it in json.loads(latest.read_text(encoding="utf-8")).get("items", []):
            items.setdefault(it["item_id"], it)
    return items


def _news(news_dir: Path, start, end, as_of, metrics: set[str], official_by_url: dict[str, str]) -> list[dict]:
    latest = news_dir / "latest.json"
    if not latest.exists():
        return []
    feed, items, out = json.loads(latest.read_text(encoding="utf-8")), _news_items(news_dir), []
    for ev in feed.get("events", []):
        members = [items[i] for i in ev.get("items", []) if i in items and stamp(items[i]["first_seen_at"]) <= as_of]
        members = [m for m in members if m.get("published_at") and start <= stamp(m["published_at"]) <= end]
        if not members:
            continue
        rep = next((m for m in members if m["canonical_url"] == ev.get("url")), members[0])
        body = (ev.get("title_zh") or rep["title_zh"]) + " " + (ev.get("summary_zh") or rep.get("summary_zh") or "")
        info = rule_triage({"title_zh": ev.get("title_zh") or rep["title_zh"], "summary_zh": ev.get("summary_zh") or rep.get("summary_zh"),
                            "item_id": rep["item_id"], "kind": "media"}, _rules())
        hs = _hyps(h["hypothesis"] for h in info["hypotheses"])
        host = urlsplit(ev.get("url") or rep["canonical_url"]).hostname or ""
        first_party = bool(ev.get("official")) and bool(OFFICIAL_HOSTS.search(host))
        foreign = bool(FOREIGN.search(ev.get("title_zh") or "")) or (classify(body) == "global" and not CHINA.search(body))
        title = ev.get("title_zh") or rep["title_zh"]
        actionable = bool(re.search(TYPES["data_release"], body) or re.search(TYPES["policy_action"], body))
        topic_hyp = TOPIC_HYP.get(classify(body))
        if first_party and not hs and topic_hyp and not foreign and not re.search(_rules()["irrelevant"]["pattern"], body):
            hs = [topic_hyp]
            info = {**info, "triage": "monitor", "mechanism": [{"en": f"Topic rule only ({classify(body)}): "
                    + MECHANISM[topic_hyp] + "; no hypothesis-rule excerpt, read the first-party text."}]}
        if foreign or not hs or info["triage"] == "irrelevant":
            triage = "irrelevant"
            why = ("Foreign or global-market item with no China nominal-growth mechanism in the text." if foreign
                   else info["reason_en"])
        elif not first_party and (ROUNDUP.search(title) or not CHINA.search(title) or not actionable):
            triage = "irrelevant"
            why = ("Composite news roundup: discovery only, not a research input." if ROUNDUP.search(title) else
                   "Media item outside China or without a datum or policy action: background, not a research input.")
        else:
            # media is a lead, not verified evidence: at most monitor until the first-party text is held
            triage = info["triage"] if first_party else "monitor"
            why = " ".join(dict.fromkeys(m["en"] for m in info["mechanism"]))
        url = ev.get("url") or rep["canonical_url"]
        repetition = official_by_url.get(url)
        out.append({
            "event_id": ev["event_id"], "title": ev.get("title_zh") or rep["title_zh"], "source_url": url,
            "publisher": ev.get("publisher") or rep["publisher"],
            "published_at": iso_z(min(stamp(m["published_at"]) for m in members)),
            "available_at": iso_z(min(stamp(m["first_seen_at"]) for m in members)),
            "hypotheses": hs if triage != "irrelevant" else [], "mechanism": _mechanism(hs) if triage != "irrelevant" else None,
            "why_relevant": (f"Reporting of an occurrence already held first-hand ({repetition}); no additional economic change."
                             if repetition else why),
            "triage": triage,
            "linked_metrics": [m for m in rep.get("metric_ids", []) if m in metrics] if triage != "irrelevant" else [],
            "excerpt": _excerpt(ev.get("summary_zh") or rep.get("summary_zh") or rep["title_zh"]),
            "evidence_kind": ("official_release" if str(ev["event_id"]).startswith("release-") else "first_party_policy")
                             if first_party else "media_report",
            "repetition_of": repetition,
            "observation_refs": [], "refresh_records": [], "tests": [],
            "stage": None, "intake_triage": None, "source_status": "news_feed",
            "coverage": len(ev.get("publishers") or [rep["publisher"]]),
        })
    return out


# ---------------------------------------------------------------- the bundle
ORDER = {"research_needed": 0, "monitor": 1, "irrelevant": 2}
KIND_ORDER = {"official_release": 0, "first_party_policy": 1, "media_report": 2}


def build_bundle(root: Path, as_of: str, window_days: int = 7) -> dict:
    root = Path(root)
    case_dir, events_dir, news_dir = root / "research/cases/cn-nominal", root / "data/events", root / "data/news"
    if any(p.lower() == "private" for d in (events_dir, news_dir) for p in d.parts):
        raise BundleError("research inputs are built from public intake only")
    from .store import load_dictionary
    from .thesis import effective_case
    end = stamp(as_of)
    start = end - timedelta(days=window_days)
    metrics = {k for k, m in load_dictionary(root / "data/dictionary/metrics.yaml").items() if m.redistribution == "public"}
    case, _, errs = effective_case(case_dir)
    if errs:
        raise BundleError(f"case in force invalid: {errs[:2]}")
    official = _official(events_dir, start, end, iso_z(end), metrics, _test_metrics(case), _refresh_refs(case_dir, start, end))
    by_url = {o["source_url"]: o["event_id"] for o in official}
    news = _news(news_dir, start, end, end, metrics, by_url)
    held = {o["event_id"]: o for o in official}
    for x in news:      # a copy carries the original's reading, so a reader never sees two verdicts for one occurrence
        if x["repetition_of"]:
            o = held[x["repetition_of"]]
            x.update({k: o[k] for k in ("hypotheses", "mechanism", "triage", "linked_metrics", "evidence_kind")})
    items = official + news
    items.sort(key=lambda x: (x["repetition_of"] is not None, ORDER[x["triage"]], KIND_ORDER[x["evidence_kind"]],
                              -stamp(x["published_at"]).timestamp(), x["event_id"]))
    counts = {"considered": len(items), **{t: sum(1 for x in items if x["triage"] == t and not x["repetition_of"]) for t in TRIAGES},
              "repetition": sum(1 for x in items if x["repetition_of"])}
    inputs = {str(p.relative_to(root)): _sha(p) for p in
              [events_dir / "events.jsonl", events_dir / "reviews.jsonl", *sorted((events_dir / "inbox").glob("*.jsonl")),
               news_dir / "latest.json", *sorted((news_dir / "archive").glob("*.json"))] if p.exists()}
    bundle = {"kind": "research_input_bundle", "version": VERSION, "bundle_id": iso_z(end)[:10], "as_of": iso_z(end),
              "window": {"start": iso_z(start), "end": iso_z(end)}, "generated_by": GENERATOR,
              "case": "cn-nominal", "items": items, "counts": counts, "inputs_sha256": inputs,
              "note": "Candidate research inputs only. Triage is rule-based; no item is an analyst judgment or changes the thesis."}
    errs = validate_bundle(bundle, metrics)
    if errs:
        raise BundleError("; ".join(errs[:5]))
    return bundle


def validate_bundle(b: dict, metrics: set[str] | None = None) -> list[str]:
    errs = []
    if b.get("kind") != "research_input_bundle" or b.get("version") != VERSION:
        errs.append("not a research_input_bundle v1")
    as_of = stamp(b["as_of"])
    for x in b.get("items", []):
        w = x.get("event_id")
        if x.get("triage") not in TRIAGES:
            errs.append(f"{w}: bad triage")
        if x.get("evidence_kind") not in EVIDENCE_KINDS:
            errs.append(f"{w}: bad evidence_kind")
        if not str(x.get("source_url", "")).startswith("https://"):
            errs.append(f"{w}: source_url must be https")
        if stamp(x["available_at"]) > as_of:
            errs.append(f"{w}: available after the bundle as_of")
        if any(h not in MECHANISM for h in x.get("hypotheses", [])):
            errs.append(f"{w}: unknown hypothesis")
        if metrics is not None and any(m not in metrics for m in x.get("linked_metrics", [])):
            errs.append(f"{w}: unknown or non-public metric")
        if x.get("triage") != "irrelevant" and not x.get("hypotheses"):
            errs.append(f"{w}: a relevant item must name a hypothesis")
    return errs


def bundle_path(case_dir: Path, bundle_id: str) -> Path:
    return Path(case_dir) / "inputs" / f"{bundle_id}.json"


def write_bundle(case_dir: Path, bundle: dict) -> Path:
    p = bundle_path(case_dir, bundle["bundle_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "x", encoding="utf-8", newline="\n") as f:          # "x": a bundle is written once
        f.write(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n")
    return p


# ---------------------------------------------------------------- stable read-only loader (#52 / #57)
def load_bundle(path: Path) -> dict:
    b = json.loads(Path(path).read_text(encoding="utf-8"))
    errs = validate_bundle(b)
    if errs:
        raise BundleError(f"{path}: " + "; ".join(errs[:3]))
    return b


def latest_bundle(case_dir: Path, as_of: str) -> dict | None:
    """The newest bundle whose as_of is at or before `as_of`, with only the items available by then."""
    when, best = stamp(as_of), None
    for p in sorted((Path(case_dir) / "inputs").glob("*.json")):
        b = load_bundle(p)
        if stamp(b["as_of"]) <= when and (best is None or stamp(b["as_of"]) > stamp(best["as_of"])):
            best = b
    if best is None:
        return None
    return {**best, "items": [x for x in best["items"] if stamp(x["available_at"]) <= when]}


def material_items(bundle: dict | None) -> list[dict]:
    """What a report or analyst draft should read: relevant, and not a repetition of something held."""
    return [x for x in (bundle or {}).get("items", []) if x["triage"] != "irrelevant" and not x["repetition_of"]]


# ---------------------------------------------------------------- CLI
def _cmd_build(a) -> int:
    b = build_bundle(Path(a.root), a.as_of, a.window_days)
    summary = {"bundle_id": b["bundle_id"], "as_of": b["as_of"], "window": b["window"], "counts": b["counts"],
               "material": [{k: x[k] for k in ("event_id", "triage", "evidence_kind", "hypotheses", "linked_metrics", "source_url")}
                            for x in material_items(b)]}
    if not a.dry_run:
        try:
            summary["written"] = str(write_bundle(Path(a.root) / "research/cases/cn-nominal", b))
        except FileExistsError:
            print(json.dumps({"status": "refused", "detail": f"bundle {b['bundle_id']} exists; bundles are written once"}))
            return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def register(sub) -> None:
    p = sub.add_parser("research-inputs", help="build a hypothesis-linked research input bundle from existing intake")
    s = p.add_subparsers(dest="ri_cmd", required=True)
    b = s.add_parser("build")
    b.add_argument("--as-of", required=True)
    b.add_argument("--window-days", type=int, default=7)
    b.add_argument("--root", default=".")
    b.add_argument("--dry-run", action="store_true")
    b.set_defaults(f=_cmd_build)
