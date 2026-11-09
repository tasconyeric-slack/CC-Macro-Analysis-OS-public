"""A deterministic daily desk over public, point-in-time research artifacts."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import localization as L

from cnmacro.claims import Binding, Claim, validate_claim
from cnmacro.derive import Deriver
from cnmacro.store import utc_naive
from cnmacro.events.store import load_public_items, load_source_status

KPI_IDS = ("cn_rgdp_yoy", "cn_cpi_yoy", "cn_core_cpi_yoy", "cn_ppi_yoy",
           "cn_pmi_mfg", "cn_pmi_new_orders")


def build_calendar(model, now=None):
    clock = pd.Timestamp(now or model["built_at"])
    clock = clock.tz_localize("UTC") if clock.tzinfo is None else clock
    today = clock.tz_convert("Asia/Shanghai").date()
    obs = model["observations"]
    entries = []
    for release in model["release_calendar"]:
        at = pd.Timestamp(release["release"])
        mids = release["metrics"]
        complete = all(not obs[(obs.metric_id == mid) &
                               (obs.reference_period == release["period"])].empty for mid in mids)
        status = ("released" if at <= clock and complete else "pending" if at <= clock
                  else "today" if at.tz_convert("Asia/Shanghai").date() == today else "scheduled")
        entries.append({**release, "status": status,
                        "anchor": "release-" + release["period"] + "-" + mids[0]})
    return sorted(entries, key=lambda item: utc_naive(item["release"]))


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
            "releases": releases, "calendar": build_calendar(model), "events": events,
            "announcements": announcements, "source_status": sources}


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
    calendar = [{**item, "label": v.release_name(item["name"])} for item in desk["calendar"]]
    for item in calendar:
        related = next((r for r in releases if r["period"] == item["period"] and r["published_at"] and
                        any(value["metric_id"] in item["metrics"] for value in r["values"])), None)
        item["related_id"] = related["item_id"] if related else None
    pending = [item for item in calendar if item["status"] in ("pending", "today", "scheduled")]
    calendar = pending + sorted((item for item in calendar if item["status"] == "released"),
                                key=lambda item: utc_naive(item["release"]), reverse=True)
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
            "no_release_today": not any(item["published_at"] and
                pd.Timestamp(item["published_at"]).tz_convert("Asia/Shanghai").date() ==
                pd.Timestamp(desk["built_at"]).tz_convert("Asia/Shanghai").date() for item in releases)}


def write_desk(desk, out: Path):
    public = {key: value for key, value in desk.items() if key != "claims"}
    (out / "data").mkdir(exist_ok=True)
    (out / "data/briefing.json").write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
