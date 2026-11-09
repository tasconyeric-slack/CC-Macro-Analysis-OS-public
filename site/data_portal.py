"""Public observation explorer. Values, vintages and differences are deterministic."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from markupsafe import Markup

from charts import line_chart
from cnmacro.derive import Deriver
from cnmacro.store import OBS_COLUMNS, as_of

CATEGORIES = ("growth", "prices", "pmi", "trade", "credit", "fiscal", "external")
DEFLATOR = "deflator"


def public_metrics(metrics):
    out = {mid: m for mid, m in metrics.items() if m.redistribution == "public" and m.tier != "supplemental"}
    for mid, m in out.items():
        if m.category not in CATEGORIES:
            raise ValueError(f"{mid}: public metric requires a valid category")
    return out


def public_history(obs, metrics):
    return obs[obs.metric_id.isin(public_metrics(metrics)) & (obs.source_class == "public")].copy()


def clean_row(row):
    return {k: None if pd.isna(row[k]) else row[k] for k in OBS_COLUMNS}


def build_data_portal(obs, metrics, tests, evidence_as_of):
    allowed = public_metrics(metrics)
    history = public_history(obs, metrics)
    current = as_of(history, evidence_as_of)
    series = {}
    for mid, m in allowed.items():
        vintages = [clean_row(r) for _, r in history[history.metric_id == mid].sort_values(["reference_period", "retrieved_at"]).iterrows()]
        points = []
        for _, r in current[current.metric_id == mid].sort_values("reference_period").iterrows():
            points.append({"period": r.reference_period, "value": float(r.value),
                           "release_date": r.release_date or None, "release_date_basis": r.release_date_basis,
                           "retrieved_at": r.retrieved_at, "source": r.source, "source_code": r.source_code,
                           "quality_flag": r.quality_flag, "limitation": r.limitation,
                           "ref": f"obs:{mid}@{r.reference_period}"})
        series[mid] = {"metric_id": mid, "category": m.category, "unit": m.unit, "frequency": m.frequency,
                       "points": points, "vintages": vintages, "as_of": evidence_as_of}
    if {"cn_ngdp_q", "cn_rgdp_yoy"} <= allowed.keys():
        points = []
        for period, pt in Deriver(current, allowed).deflator_yoy("cn_ngdp_q", "cn_rgdp_yoy").items():
            inputs = []
            for ref in pt.inputs:
                mid, per = ref[4:].split("@")
                inputs.extend(p for p in series[mid]["points"] if p["period"] == per)
            releases = [p["release_date"] for p in inputs if p["release_date"]]
            points.append({"period": str(period), "value": pt.value, "ref": pt.ref, "inputs": pt.inputs,
                           "release_date": max(releases) if len(releases) == len(inputs) else None,
                           "retrieved_at": max(p["retrieved_at"] for p in inputs), "source": "NBS",
                           "source_code": "", "quality_flag": "derived", "limitation": ""})
        series[DEFLATOR] = {"metric_id": DEFLATOR, "category": "prices", "unit": "%", "frequency": "Q",
                            "points": points, "vintages": [], "as_of": evidence_as_of, "derived": True}
    return {"series": series}


def write_data_assets(data, out):
    target = Path(out) / "data/series"
    target.mkdir(parents=True, exist_ok=True)
    for mid, item in data["series"].items():
        (target / f"{mid}.json").write_text(json.dumps(item, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        with (target / f"{mid}.csv").open("w", encoding="utf-8-sig", newline="") as f:
            columns = ["period", "value", "ref", "release_date", "retrieved_at"] if item.get("derived") else OBS_COLUMNS
            w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            w.writeheader()
            w.writerows(item["points"] if item.get("derived") else item["vintages"])


def source_url(point, metric, sources):
    code = str(point.get("source_code") or "")
    if code.startswith("https://") and urlparse(code).hostname:
        return code
    if point.get("source") == "FRED" and code and code.split("@")[0].replace("_", "").isalnum():
        return "https://fred.stlouisfed.org/series/" + code.split("@")[0]
    source = point.get("source") or (metric.source_primary if metric else "NBS")
    return next((s.get("url", "") for s in sources if s["id"] == source), "")


def changes(points, freq):
    if not points:
        return None, None
    latest = points[-1]
    p = pd.Period(latest["period"], freq=freq)
    values = {row["period"]: row["value"] for row in points}
    def delta(back):
        old = values.get(str(p - back))
        return latest["value"] - old if old is not None else None
    return delta(1), delta({"M": 12, "Q": 4, "D": 365}[freq])


def data_context(model, v, category=None):
    cards = []
    source_rows = model.get("sources", {}).get("sources", [])
    for mid, item in model["data_portal"]["series"].items():
        if category and item["category"] != category:
            continue
        m = model["metrics"].get(mid)
        derived = bool(item.get("derived"))
        name = v.t("data_explorer.deflator") if derived else v.metric_name(mid)
        pts = item["points"]
        latest = pts[-1] if pts else None
        prior, year = changes(pts, item["frequency"])
        unit = v.unit(item["unit"])
        diff_unit = v.t("data_explorer.pp") if item["unit"] == "%" else (v.t("data_explorer.points") if item["unit"].startswith("index") else unit)
        def delta_text(x):
            return f"{x:+,.2f} {diff_unit}" if x is not None else v.t("data_explorer.not_available")
        ranges = []
        if pts:
            last = pd.Period(pts[-1]["period"], freq=item["frequency"])
            for key, years in (("2y", 2), ("5y", 5), ("all", None)):
                cutoff = last - years * {"M": 12, "Q": 4, "D": 365}[item["frequency"]] + 1 if years else None
                selected = [p for p in pts if cutoff is None or pd.Period(p["period"], freq=item["frequency"]) >= cutoff]
                plots = []
                for size, width in (("wide", 640), ("compact", 360)):
                    chart_id = f"data-{mid}-{key}-{size}"
                    details = [v.t("data_explorer.tooltip", released=v.date(p.get("release_date")) if p.get("release_date") else v.t("data_explorer.unknown_release"),
                                   retrieved=v.date(p["retrieved_at"]), vintage=p["quality_flag"]) for p in selected]
                    plots.append({"size": size, "svg": Markup(line_chart([(p["period"], p["value"]) for p in selected], item["unit"],
                                      ref=50 if item["unit"].startswith("index") else (0 if item["unit"] == "%" else None),
                                      chart_id=chart_id, width=width, label=name, details=details))})
                ranges.append({"key": key, "plots": plots})
        used = [t for t in model["tests"] if (mid in t["metrics"] if not derived else "deflator_yoy" in t["indicator"])]
        cards.append({"id": mid, "category": item["category"], "name": name,
                      "role": v.t("data_explorer.deflator_note") if derived else v.metric_role(mid),
                      "unit": unit, "frequency": item["frequency"], "latest": latest,
                      "value": f"{latest['value']:,.2f}" if latest else "–", "previous_change": delta_text(prior), "year_change": delta_text(year),
                      "publisher": v.source_name(latest["source"]) if latest else v.source_name(m.source_primary if m else "NBS"),
                      "source_url": source_url(latest or {}, m, source_rows), "source_code": (latest or {}).get("source_code") or (m.source_code if m else ""),
                      "notes": m.caliber_notes if m else [], "ranges": ranges, "points": pts,
                      "thumbnail": Markup(line_chart([(p["period"], p["value"]) for p in pts[-24:]], item["unit"],
                                             chart_id=f"thumb-{mid}", width=320, height=110, label=name)) if pts else None,
                      "vintages": list(reversed(item["vintages"])), "tests": used, "derived": derived,
                      "json_url": f"../data/series/{mid}.json", "csv_url": f"../data/series/{mid}.csv"})
    return {"cards": cards, "available": sum(bool(c["latest"]) for c in cards), "gap_count": sum(not c["latest"] for c in cards)}
