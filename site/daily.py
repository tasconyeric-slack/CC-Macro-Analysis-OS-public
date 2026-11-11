"""A deterministic daily desk over public, point-in-time research artifacts."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import yaml
import localization as L

from cnmacro import ingest, macro_events
from cnmacro.claims import Binding, Claim, validate_claim
from cnmacro.derive import Deriver
from cnmacro.store import utc_naive
from cnmacro.events.store import load_grouped_public_items as load_public_items, load_source_status

KPI_IDS = ("cn_rgdp_yoy", "cn_cpi_yoy", "cn_core_cpi_yoy", "cn_ppi_yoy",
           "cn_pmi_mfg", "cn_pmi_new_orders")


ROOT = Path(__file__).resolve().parents[1]
PUBLICATIONS = ROOT / "data/dictionary/official_publications.yaml"
# reported indicator -> the release kind that publishes it (to fold coverage into the official release)
INDICATOR_KIND = {"cpi": "cpi", "core_cpi": "cpi", "ppi": "ppi", "ppi_in": "ppi", "pmi": "pmi", "pmi_nonmfg": "pmi",
                  "trade": "gacc_flash", "exports": "gacc_flash", "imports": "gacc_flash", "m2": "pboc", "m1": "pboc",
                  "tsf": "pboc", "loans": "pboc", "retail": "retail", "ip": "ip", "fai": "fai", "property_inv": "property",
                  "profits": "profits", "gdp": "gdp", "unemployment": "economy", "revenue": "mof", "spending": "mof"}
SOURCE_OF = {"国家统计局": "NBS", "中国人民银行": "PBOC", "人民银行": "PBOC", "海关总署": "GACC", "财政部": "MOF"}
# Where each institution lists its releases; used for a release whose date is not yet announced.
LISTINGS = {"pboc": "https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html",
            "gacc_flash": "http://english.customs.gov.cn/statics/report/preliminary.html",
            "mof": "http://gks.mof.gov.cn/tongjishuju/"}
PUBLISHER = {"NBS": ("国家统计局", "NBS"), "PBOC": ("人民银行", "PBoC"), "GACC": ("海关总署", "Customs"),
             "MOF": ("财政部", "MOF")}
SHORT_METRIC = {  # concise reading labels for calendar cards (zh, en)
    "cn_cpi_yoy": ("CPI同比", "CPI y/y"), "cn_core_cpi_yoy": ("核心CPI", "Core CPI"),
    "cn_ppi_yoy": ("PPI同比", "PPI y/y"), "cn_ppi_mom": ("PPI环比", "PPI m/m"),
    "cn_pmi_mfg": ("制造业PMI", "Mfg PMI"), "cn_pmi_nonmfg": ("非制造业", "Non-mfg"),
    "cn_pmi_new_orders": ("新订单", "New orders"), "cn_rgdp_yoy": ("GDP同比", "GDP y/y"),
    "cn_unemployment": ("失业率", "Jobless"), "cn_ip_yoy": ("工业增加值", "Ind. output"),
    "cn_retail_sales_yoy": ("社零同比", "Retail y/y"), "cn_property_sales_area_ytd_yoy": ("商品房销售面积", "Home sales area"),
    "cn_ind_profit_ytd_yoy": ("利润累计", "Profits YTD"), "cn_m2_yoy": ("M2", "M2"), "cn_m1_yoy": ("M1", "M1"),
    "cn_tsf_stock_yoy": ("社融存量", "TSF stock"), "cn_exports_usd_yoy": ("出口", "Exports"),
    "cn_imports_usd_yoy": ("进口", "Imports"), "cn_exports_us_ytd_yoy": ("对美出口累计", "To US YTD"),
    "cn_budget_rev_ytd_yoy": ("财政收入", "Revenue YTD"), "cn_budget_exp_ytd_yoy": ("财政支出", "Spending YTD")}


def official_publications(model, occurrences=()):
    """Releases already published by PBOC, GACC and MOF, each with its official page and date: the recorded
    list, plus PBoC / MOF release pages the hourly intake has collected since (one entry per release)."""
    if "official_publications" in model:
        held = list(model["official_publications"])
    elif PUBLICATIONS.exists():
        held = yaml.safe_load(PUBLICATIONS.read_text(encoding="utf-8")).get("publications", [])
    else:
        held = []
    have = {(p["source"], p["kind"], str(p["period"])) for p in held} | {p["url"] for p in held}
    for p in macro_events.official_releases(occurrences):
        if (p["source"], p["kind"], p["period"]) not in have and p["url"] not in have:
            held.append(p)
            have |= {(p["source"], p["kind"], p["period"]), p["url"]}
    return held


def _beijing_ts(value):
    at = pd.Timestamp(value)
    return at.tz_localize("Asia/Shanghai") if at.tzinfo is None else at.tz_convert("Asia/Shanghai")


def reading(model, mid, period):
    """Actual, previous and change for one metric and reference period, from the observation store.
    Only rates and indices are shown; a level without its own scale would mislead on a card."""
    m = model["metrics"].get(mid)
    if m is None or not (m.unit == "%" or m.unit.startswith("index")):
        return None
    obs = model["observations"]
    rows = obs[obs.metric_id == mid]
    held = rows[rows.reference_period == period]
    if held.empty:
        return None
    row = held.sort_values("retrieved_at").iloc[-1]
    earlier = rows[rows.reference_period < period]
    prior = earlier[earlier.reference_period == earlier.reference_period.max()].sort_values("retrieved_at")
    prev = prior.iloc[-1] if len(prior) else None
    code = str(row.source_code)
    return {"metric_id": mid, "period": period, "value": float(row.value), "unit": m.unit,
            "category": m.category, "previous": float(prev.value) if prev is not None else None,
            "previous_period": str(prev.reference_period) if prev is not None else None,
            "delta": round(float(row.value) - float(prev.value), 4) if prev is not None else None,
            "source_url": code if code.startswith("https://") else None}


def _release_items(model, occurrences=()):
    """Every dated China release: NBS scheduled entries and PBOC/GACC/MOF published ones."""
    for r in model["release_calendar"]:
        kinds = ingest.release_kinds(r["name"])
        headline = [mid for k in kinds for mid in ingest.KIND[k][5]]  # headline readings first
        yield {"source": r.get("source", "NBS"), "at": str(r["release"]), "period": str(r["period"]),
               "kinds": kinds, "metrics": list(r["metrics"]),
               "shown": list(dict.fromkeys(headline + list(r.get("display_metrics") or []) + list(r["metrics"]))),
               "url": r.get("url"), "published": False, "required": list(r.get("display_metrics") or []),
               "name": r["name"]}
    for p in official_publications(model, occurrences):
        yield {"source": p["source"], "at": str(p["published"]), "period": str(p["period"]), "kinds": [p["kind"]],
               "metrics": [], "shown": list(ingest.KIND[p["kind"]][5]), "url": p["url"], "published": True}


def build_calendar(model, now=None, occurrences=()):
    """One event per institution and release moment: releases NBS publishes together at 10:00 are
    one event, not seven. Past events carry the actual, previous and change held in the store."""
    clock = pd.Timestamp(now or model["built_at"])
    clock = clock.tz_localize("UTC") if clock.tzinfo is None else clock
    today = clock.tz_convert("Asia/Shanghai").date()
    obs = model["observations"]
    groups = {}
    for item in _release_items(model, occurrences):
        groups.setdefault((item["source"], item["at"]), []).append(item)
    events = []
    for (source, at), items in groups.items():
        dated_only = "T" not in at
        stamp = _beijing_ts(at)
        kinds = list(dict.fromkeys(k for item in items for k in item["kinds"]))
        values, seen = [], set()
        for item in items:
            for mid in item["shown"]:
                hit = reading(model, mid, item["period"]) if mid not in seen and stamp <= clock else None
                if hit:
                    values.append(hit)
                    seen.add(mid)
        heads = {ingest.KIND[k][5][0] for k in kinds if ingest.KIND[k][5]}  # one headline per release kind
        values.sort(key=lambda v: v["metric_id"] not in heads)
        complete = all(not obs[(obs.metric_id == mid) & (obs.reference_period == item["period"])].empty
                       for item in items for mid in (item["metrics"] or item.get("required", [])))
        published = any(item["published"] for item in items)
        status = ("released" if stamp <= clock and (complete or published) else "pending" if stamp <= clock
                  else "today" if stamp.date() == today else "scheduled")
        periods = sorted({item["period"] for item in items}, key=lambda p: ("Q" in p, p))
        mids = [mid for item in items for mid in (item["metrics"] or item["shown"])]
        official = next((v["source_url"] for v in values if v["source_url"]), None)
        page = next((item["url"] for item in items if item["published"]), None)
        date, time = stamp.date().isoformat(), "" if dated_only else stamp.strftime("%H:%M")
        events.append({"source": source, "name": next((x["name"] for x in items if x.get("name")), None),
                       "release": at, "date": date, "time": time,
                       "time_precision": "date" if dated_only else "minute", "period": periods[0],
                       "periods": periods, "kinds": kinds, "metrics": list(dict.fromkeys(mids)),
                       "status": status, "values": values[:6],
                       "url": page or official or ingest.NBS_SCHEDULE_URL,
                       "schedule_url": None if published else items[0]["url"],
                       "anchor": "cal-" + source.lower() + "-" + date + ("-" + time.replace(":", "") if time else "")})
    for e in events:
        e.update({"kind": "release", "reported": [], "coverage": [], "action": None, "hypotheses": [],
                  "occurrence_ids": []})
    for occ in occurrences:
        if not macro_events.material(occ):
            continue
        target = _release_for(occ, events)
        if target:
            _fold(target, occ)
            continue
        if stamp_after(occ["published_at"], clock):
            continue
        values = [hit for hit in (reading(model, f["metric_id"], f["period"]) for f in occ["figures"] if f["metric_id"])
                  if hit]
        events.append({"source": SOURCE_OF.get(occ["publisher"], "MEDIA" if not occ["official"] else "OFFICIAL"),
                       "release": occ["published_at"], "date": occ["date"], "time": occ["time"],
                       "time_precision": "minute" if occ["time"] else "date",
                       "period": next((f["period"] for f in occ["figures"]), None), "periods": [],
                       "kinds": [], "metrics": occ["metric_ids"], "status": "released",
                       "values": list({v["metric_id"]: v for v in values}.values())[:4], "url": occ["url"],
                       "schedule_url": None, "anchor": "cal-occ-" + re.sub(r"[^0-9a-zA-Z_-]", "", occ["occurrence_id"])[-24:],
                       "kind": occ["kind"], "title_zh": occ["title_zh"], "title_en": occ["title_en"],
                       "publisher": occ["publisher"], "official": occ["official"],
                       "reported": [f for f in occ["figures"] if not _canonical_match(f, values)][:6],
                       "coverage": [{"publisher": p, "url": u} for p, u in _coverage(occ)],
                       "action": occ["action"], "hypotheses": occ["hypotheses"], "occurrence_ids": [occ["occurrence_id"]]})
    return sorted(events, key=lambda e: (e["date"], e["time"] or "99:99", e["source"]))


def stamp_after(value, clock):
    return _beijing_ts(value) > clock


def _coverage(occ):
    """One link per outlet that reported the occurrence, first party first."""
    seen = {occ["publisher"]: occ["url"]}
    for r in occ.get("reports", []):
        seen.setdefault(r["publisher"], r["url"])
    return list(seen.items())[:6]


def _release_for(occ, events):
    """The official release this report covers: same indicator and period, published within three days
    of it; the same page; or the institution's own same-day material on its release day."""
    day = pd.Timestamp(occ["date"])
    best = None
    for e in events:
        if e.get("kind", "release") != "release":
            continue
        lag = (day - pd.Timestamp(e["date"])).days
        kinds = _covered(e["kinds"])
        same_page = occ["url"] == e["url"] or occ["url"] in (e.get("schedule_url") or "")
        covers = 0 <= lag <= 3 and any(macro_events_kind(f) in kinds and f["period"] in e["periods"]
                                         for f in occ["figures"])
        own = (lag == 0 and SOURCE_OF.get(occ["publisher"]) == e["source"] and not occ["action"]
               and (not occ["figures"] or covers or set(ingest.release_kinds(occ["title_zh"])) & kinds))
        named = lag == 0 and set(ingest.release_kinds(occ["title_zh"])) & kinds and SOURCE_OF.get(occ["publisher"]) == e["source"]
        if same_page or covers or own or named:
            score = (same_page, bool(covers), bool(named), len(kinds))
            if best is None or score > best[0]:
                best = (score, e)
    return best[1] if best else None


def _covered(kinds):
    """Release kinds an event publishes; the 10:00 national-economy release carries the activity series."""
    out = set(kinds)
    if "economy" in out or "gdp" in out:
        out |= {"ip", "retail", "fai", "property", "economy", "gdp"}
    return out


def macro_events_kind(figure):
    return INDICATOR_KIND.get(figure["indicator"])


def _canonical_match(figure, values):
    return any(v["metric_id"] == figure["metric_id"] and v["period"] == figure["period"]
               and abs(v["value"] - figure["value"]) < 1e-9 for v in values)


def _fold(event, occ):
    """Coverage of a release joins the release: one occurrence, many reports, canonical values first."""
    event["occurrence_ids"].append(occ["occurrence_id"])
    have = {c["publisher"] for c in event["coverage"]}
    for publisher, url in _coverage(occ):  # one link per outlet
        if publisher not in have and url != event["url"]:
            event["coverage"].append({"publisher": publisher, "url": url})
            have.add(publisher)
    keys = {(f["indicator"], f["basis"], f["currency"], f["period"]) for f in event["reported"]}
    for f in occ["figures"]:
        k = (f["indicator"], f["basis"], f["currency"], f["period"])
        if k in keys or _canonical_match(f, event["values"]) or macro_events_kind(f) not in _covered(event["kinds"]):
            continue
        if any(v["metric_id"] == f["metric_id"] and v["period"] == f["period"] for v in event["values"]):
            f = {**f, "differs_from_canonical": True}  # shown beside the canonical value, never replacing it
        event["reported"].append(f)
        keys.add(k)
    event["reported"].sort(key=lambda f: (not f["metric_id"], f["basis"] == "ytd", not f["official"]))
    event["reported"] = event["reported"][:6]
    event["hypotheses"] = sorted(set(event["hypotheses"]) | set(occ["hypotheses"]))


def undated_releases(model, occurrences=()):
    """The next PBOC, GACC and MOF releases: real, recurring, but without an announced date."""
    out = []
    for kind in LISTINGS:
        held = [p for p in official_publications(model, occurrences) if p["kind"] == kind]
        if not held:
            continue
        latest = max(held, key=lambda p: p["period"])
        nxt = str(pd.Period(latest["period"], "M") + 1)
        out.append({"source": latest["source"], "kinds": [kind], "period": nxt, "url": LISTINGS[kind],
                    "status": "tba", "metrics": list(ingest.KIND[kind][5])})
    return out


def source_url(model, source, code=""):
    if str(code).startswith("https://"):
        return str(code)
    return next((s["url"] for s in model["sources"].get("sources", [])
                 if s["id"] == source and s.get("url")), "https://www.stats.gov.cn/sj/zxfb/")


def build_desk(model, events_dir=None):
    obs, metrics = model["observations"], model["metrics"]
    history = model.get("observation_history", obs)
    kpis, claims = [], []
    for mid in KPI_IDS:
        m = metrics.get(mid)
        rows = obs[obs.metric_id == mid].sort_values("reference_period")
        latest = rows.iloc[-1] if len(rows) else None
        previous = rows.iloc[-2] if len(rows) > 1 else None
        item = {"metric_id": mid, "value": float(latest.value) if latest is not None else None,
                "unit": m.unit if m else "index (50 = no change)",
                "period": str(latest.reference_period) if latest is not None else None,
                "release_date": (latest.release_date or None) if latest is not None else None,
                "retrieved_at": latest.retrieved_at if latest is not None else None,
                "publisher": m.source_primary if m else "NBS",
                "canonical_url": source_url(model, m.source_primary if m else "NBS",
                                            latest.source_code if latest is not None else ""),
                "delta": float(latest.value - previous.value) if previous is not None else None,
                "ref": f"obs:{mid}@{latest.reference_period}" if latest is not None else None}
        kpis.append(item)
        if latest is not None and mid in ("cn_cpi_yoy", "cn_core_cpi_yoy", "cn_ppi_yoy", "cn_pmi_new_orders"):
            c = Claim(id="DESK-" + mid, type="FACT", stance="context", as_of=model["evidence_as_of"],
                      hypotheses=m.hypotheses,
                      text_en=f"{m.name} for {item['period']}: {{value}}.",
                      text_zh=f"{m.name_zh}（{L.fmt_period(item['period'], 'zh')}）：{{value}}。",
                      values={"value": Binding(ref=item["ref"], recorded=item["value"],
                                               suffix="%" if m.unit == "%" else "")})
            errors = validate_claim(c)
            if errors:
                raise ValueError("Invalid desk claim: " + "; ".join(errors))
            resolved = Deriver(obs, metrics).resolve(item["ref"])
            if resolved is None or abs(resolved.value - item["value"]) > 1e-9:
                raise ValueError("Desk claim does not match public observation: " + item["ref"])
            claims.append(c)
    target = model["case"]["target"]
    pts = model["target_pts"]
    if pts:
        inputs = [k for k in ("cn_ngdp_q", "cn_rgdp_yoy") if k in metrics]
        sub = obs[obs.metric_id.isin(inputs) & (obs.reference_period == pts[-1][0])]
        released = [r for r in sub.release_date if r]
        kpis.append({"metric_id": target, "ref": target + "@" + pts[-1][0],
                     "value": pts[-1][1], "period": pts[-1][0], "unit": "%", "publisher": "NBS",
                     "release_date": max(released, default=None) if len(released) == len(inputs) else None,
                     "retrieved_at": max(sub.retrieved_at, default=None),
                     "canonical_url": source_url(model, "NBS"),
                     "delta": pts[-1][1] - pts[-2][1] if len(pts) > 1 else None})

    groups = {}
    for refresh in model["refreshes"]:
        for row in refresh.get("new_observations", []):
            mid, period = row["metric_id"], row["reference_period"]
            if mid not in metrics:
                continue
            published = row.get("release_date") or None
            revision = row.get("quality_flag") == "revised"
            match = next((r for r in model["release_calendar"]
                          if r["period"] == period and mid in r["metrics"]), None)
            # Unknown revision dates remain unknown. A calendar is a schedule, not a source timestamp.
            label = match["name"] if match and published and not revision else None
            key = (published, period, label or row["source"], revision,
                   refresh["as_of"] if not published or revision else "")
            stamp = re.sub(r"[^0-9]", "", published or refresh["as_of"])
            group = groups.setdefault(key, {"item_id": "release-" + period + "-" + mid + "-" + stamp,
                "kind": "data_release", "tier": "FACT", "period": period,
                "published_at": published, "retrieved_at": refresh["as_of"],
                "publisher": row["source"], "name": label,
                "is_revision": revision, "values": [], "test_flips": [],
                "status": "verified", "canonical_url": source_url(model, row["source"])})
            rows = history[(history.metric_id == mid) & (history.reference_period == period)]
            rows = rows[rows.retrieved_at.map(utc_naive) <= utc_naive(refresh["as_of"])]
            if len(rows):
                code = rows.sort_values("retrieved_at").iloc[-1].source_code
                group["canonical_url"] = source_url(model, row["source"], code)
            group["values"].append({"metric_id": mid, "period": period, "value": row["value"],
                                     "unit": metrics[mid].unit, "ref": f"obs:{mid}@{period}"})
            group["retrieved_at"] = max(group["retrieved_at"], refresh["as_of"])
            for flip in refresh.get("flipped_tests", []):
                test_id = flip.get("test") if isinstance(flip, dict) else flip
                test = next((t for t in model["tests"] if t["id"] == test_id), None)
                if test and mid in test["metrics"] and flip not in group["test_flips"]:
                    group["test_flips"].append(flip)
    releases = sorted(groups.values(), key=lambda r: utc_naive(r["published_at"] or r["retrieved_at"]), reverse=True)
    events = load_public_items(events_dir, as_of=model["built_at"]) if events_dir else []
    occurrences = (macro_events.build_occurrences(ROOT / "data/news", events_dir, model["built_at"])
                   if events_dir else [])
    sources = load_source_status(events_dir, as_of=model["built_at"]) if events_dir else []
    announcements = []
    for item in events:
        related = next((r for r in releases if r["canonical_url"] == item["canonical_url"]), None)
        if related:
            related["official_item_id"] = item["item_id"]
            related["first_seen_at"] = item["first_seen_at"]
            related["event_id"] = item.get("event_id")
            item["attached_release_id"] = related["item_id"]
        else:
            announcements.append(item)
    analyst_updates = [u for u in model["updates"] if not str(u.get("author", "")).startswith("automation")]
    judgment = analyst_updates[-1] if analyst_updates else model["baseline"]
    return {"built_at": model["built_at"], "evidence_as_of": model["evidence_as_of"],
            "last_refresh": model["refresh_at"], "judgment_as_of": (judgment or {}).get("as_of"),
            "has_analyst_update": bool(analyst_updates), "kpis": kpis, "claims": claims,
            "releases": releases, "calendar": build_calendar(model, occurrences=occurrences),
            "calendar_tba": undated_releases(model, occurrences), "occurrences": occurrences,
            "events": events,
            "announcements": announcements, "source_status": sources}


BASIS = {"yoy": ("同比", "y/y"), "mom": ("环比", "m/m"), "ytd": ("累计同比", "YTD y/y"), "level": ("", "")}


def _short_title(text, n):
    text = re.sub(r"^[^：:]{2,12}[：:]", "", text or "").strip()  # drop a 'Speaker:' / 'Agency:' lead
    return text if len(text) <= n else text[:n - 1] + "…"


def calendar_view(item, v):
    """A calendar event in the reader's language: a short name for the month cell, the rest for its detail."""
    i = 0 if v.loc == "zh" else 1
    kinds = item["kinds"]
    names = [ingest.KIND[k][2 + i] for k in kinds]
    economy = "economy" in kinds
    reported = []
    for f in item.get("reported", []):
        ind = macro_events.IND[f["indicator"]]
        cur = {"USD": ("美元计", "USD"), "CNY": ("人民币计", "CNY")}.get(f["currency"], ("", ""))[i]
        name = " ".join(x for x in (ind[2 + i], BASIS[f["basis"]][i], f"({cur})" if cur else "") if x)
        reported.append({**f, "name": name if i else name.replace(" ", ""), "unit_label": "" if f["unit"] == "index" else "%"})
    action = item.get("action")
    if kinds or item.get("kind", "release") == "release":
        title = (("国民经济运行情况", "Economic activity")[i] if economy else " · ".join(names) if names
                 else v.release_name(item["name"]) if item.get("name") else item["source"])
        short, lang_zh = title, False
    else:  # an occurrence from the news / policy intake
        title = (item.get("title_en") if i else None) or item["title_zh"]
        lang_zh = not (i and item.get("title_en"))
        inds = list(dict.fromkeys(macro_events.IND[f["indicator"]][2 + i] for f in item.get("reported", [])))
        short = (" · ".join(inds[:2]) if inds and item["kind"] == "data" else
                 (action["issuer_zh"] or "") + action["action_zh"] if action and not i else
                 " ".join(x for x in (action["issuer_en"], action["action_en"]) if x) if action else
                 _short_title(title, 14 if not i or lang_zh else 32))
        lang_zh = lang_zh and not (action or (inds and item["kind"] == "data"))
    members = [n for k, n in zip(kinds, names) if k != "economy"] if economy else []
    period = L.fmt_period(item["period"], v.loc) if item.get("period") and kinds else ""
    values = []
    for val in item.get("values", []):
        index = not val["unit"] == "%"
        values.append({**val, "name": SHORT_METRIC.get(val["metric_id"], (None, None))[i] or v.metric_name(val["metric_id"]),
                       "full_name": v.metric_name(val["metric_id"]),
                       "unit_label": "" if index else v.unit(val["unit"]),
                       "delta_unit": (("点", "pts") if index else ("个百分点", "pp"))[i]})
    publisher = PUBLISHER.get(item["source"], (None, None))[i] or item.get("publisher") or item["source"]
    return {**item, "title": title, "short": short, "short_is_zh": lang_zh, "members": members, "values": values,
            "reported": reported,
            "label": ((period + title) if v.loc == "zh" else f"{period} {title}".strip()) if names else title,
            "publisher_name": publisher}


def desk_context(desk, v):
    def beijing(value):
        if not value:
            return None
        stamp = pd.Timestamp(value)
        stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp
        return stamp.tz_convert("Asia/Shanghai").isoformat()

    kpis = []
    for item in desk["kpis"]:
        mid = item["metric_id"]
        name = (v.t("desk.deflator") if mid.startswith("drv:") else
                v.metric_name(mid) if mid in v.m["metrics"] else v.t("desk.headline_pmi"))
        kpis.append({**item, "name": name, "unit_label": v.unit(item["unit"]),
                     "delta_unit": v.t("desk.pp" if item["unit"] == "%" else "desk.points"),
                     "retrieved_at": beijing(item["retrieved_at"]),
                     "publisher_name": v.source_name(item["publisher"])})
    releases = []
    for item in desk["releases"]:
        title = (v.release_name(item["name"]) if item["name"] else
                 v.t("desk.revision" if item["is_revision"] else "desk.received"))
        values = [{**value, "name": v.metric_name(value["metric_id"]),
                   "unit_label": v.unit(value["unit"])} for value in item["values"]]
        flips = []
        for flip in item["test_flips"]:
            test = next((test for test in v.m["tests"] if test["id"] == flip["test"]), None)
            if test:
                flips.append({"description": v.test_row(test)["description"], "hypothesis": test["hypothesis"]})
        releases.append({**item, "title": title, "values": values, "flip_labels": flips,
                         "retrieved_at": beijing(item["retrieved_at"]),
                         "publisher_name": v.source_name(item["publisher"])})
    calendar = [calendar_view(item, v) for item in desk["calendar"]]
    for item in calendar:
        related = next((r for r in releases if r["period"] == item["period"] and r["published_at"] and
                        any(value["metric_id"] in item["metrics"] for value in r["values"])), None)
        item["related_id"] = related["item_id"] if related else None
    pending = [item for item in calendar if item["status"] in ("pending", "today", "scheduled")]
    calendar = pending + sorted((item for item in calendar if item["status"] == "released"),
                                key=lambda item: (item["date"], item["time"]), reverse=True)
    announcements = [{**item, "title": item.get("title_" + v.loc) or item["title_zh"],
                       "original_language": v.loc == "en" and not item.get("title_en"),
                       "published_at": beijing(item["published_at"]),
                       "first_seen_at": beijing(item["first_seen_at"]),
                       "retrieved_at": beijing(item["retrieved_at"])} for item in desk["announcements"]]
    return {**desk, "kpis": kpis, "releases": releases, "announcements": announcements,
            "built_at": beijing(desk["built_at"]), "last_refresh": beijing(desk["last_refresh"]),
            "judgment_as_of": beijing(desk["judgment_as_of"]),
            "brief": [claim.render(locale=v.loc) for claim in desk["claims"]],
            "calendar": calendar, "upcoming": pending,
            "calendar_tba": [calendar_view(item, v) for item in desk.get("calendar_tba", [])],
            "no_release_today": not any(item["published_at"] and
                pd.Timestamp(beijing(item["published_at"])).date() ==
                pd.Timestamp(beijing(desk["built_at"])).date() for item in releases)}


def write_desk(desk, out: Path):
    public = {key: value for key, value in desk.items() if key != "claims"}
    (out / "data").mkdir(exist_ok=True)
    (out / "data/briefing.json").write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
