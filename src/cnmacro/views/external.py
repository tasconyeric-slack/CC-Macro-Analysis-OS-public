"""EXTERNAL_VIEW records: sourced institutional views, never observations or evidence.

A record is one dated, linked view by one named institution on one hypothesis of the case
(optionally with one numeric forecast the source itself states). Records arrive as
append-only JSONL files under `data/external/views/` from a permitted provider (for example
a FinLens export once the Owner holds a token and redistribution permission) or by hand from
a publisher's public page. Nothing here fetches anything: there is no network adapter until a
provider contract can be verified.

Rules enforced here, so a bad record fails closed instead of reaching a page:
  * every view names its institution, links its source over https, and quotes its own short
    wording (no licensed full text: `quote` is capped);
  * point in time: a view is used only if published and retrieved at or before the cutoff;
  * `redistribution: private` records are kept out of any public output;
  * a forecast median is reported only when at least MIN_CONSENSUS distinct institutions
    gave a value for the same metric and period; below that the values are listed, never
    called a consensus.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

import yaml

from ..store import utc_naive

HYPOTHESES = ("H0", "H1", "H2", "H3", "H4")
STANCES = ("supports", "challenges", "mixed", "none")
INSTITUTION_TYPES = ("domestic_broker", "foreign_bank", "official", "other")
REDISTRIBUTION = ("public_link", "permitted", "private")
MAX_QUOTE = 280
MIN_CONSENSUS = 5
REQUIRED = ("view_id", "institution", "institution_type", "title", "published_at", "retrieved_at",
            "source_url", "via", "hypothesis", "stance", "quote", "redistribution")


def validate_external_view(rec: dict) -> list[str]:
    where = rec.get("view_id", "<no view_id>")
    errs = [f"{where}: missing {k}" for k in REQUIRED if rec.get(k) in (None, "")]
    if errs:
        return errs
    if rec.get("kind", "EXTERNAL_VIEW") != "EXTERNAL_VIEW":
        errs.append(f"{where}: kind must be EXTERNAL_VIEW")
    if rec["hypothesis"] not in HYPOTHESES:
        errs.append(f"{where}: hypothesis {rec['hypothesis']!r} not in {HYPOTHESES}")
    if rec["stance"] not in STANCES:
        errs.append(f"{where}: stance {rec['stance']!r} not in {STANCES}")
    if rec["institution_type"] not in INSTITUTION_TYPES:
        errs.append(f"{where}: institution_type {rec['institution_type']!r} not in {INSTITUTION_TYPES}")
    if rec["redistribution"] not in REDISTRIBUTION:
        errs.append(f"{where}: redistribution {rec['redistribution']!r} not in {REDISTRIBUTION}")
    if not str(rec["source_url"]).startswith("https://"):
        errs.append(f"{where}: source_url must be an https link to the source")
    if len(str(rec["quote"])) > MAX_QUOTE:
        errs.append(f"{where}: quote longer than {MAX_QUOTE} characters (no full text)")
    try:
        if utc_naive(rec["published_at"]) > utc_naive(rec["retrieved_at"]):
            errs.append(f"{where}: published_at is after retrieved_at")
    except (ValueError, TypeError):
        errs.append(f"{where}: published_at / retrieved_at must be ISO dates")
    fc = rec.get("forecast")
    if fc is not None:
        missing = [k for k in ("metric_id", "period", "value", "unit") if fc.get(k) in (None, "")]
        if missing:
            errs.append(f"{where}: forecast missing {', '.join(missing)} (only a stated number with period and unit)")
        elif not isinstance(fc["value"], (int, float)) or isinstance(fc["value"], bool):
            errs.append(f"{where}: forecast value must be a number")
    return errs


def load_external_views(directory: str | Path, as_of=None, *, public: bool = True) -> tuple[list[dict], list[str]]:
    """All valid views in `directory` usable at `as_of`, plus every validation error.

    A missing directory is not an error: it means no permitted source has been connected."""
    directory = Path(directory)
    views, errors, seen = [], [], set()
    if not directory.is_dir():
        return views, errors
    cutoff = utc_naive(as_of) if as_of is not None else None
    for path in sorted(directory.glob("*.jsonl")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"{path.name}:{n}: not JSON ({e.msg})")
                continue
            bad = validate_external_view(rec)
            if bad:
                errors += [f"{path.name}:{n}: {b}" for b in bad]
                continue
            if rec["view_id"] in seen:   # append-only: a changed view is a new view_id
                errors.append(f"{path.name}:{n}: duplicate view_id {rec['view_id']}")
                continue
            seen.add(rec["view_id"])
            if public and rec["redistribution"] == "private":
                continue
            if cutoff is not None and max(utc_naive(rec["published_at"]), utc_naive(rec["retrieved_at"])) > cutoff:
                continue
            views.append({**rec, "kind": "EXTERNAL_VIEW", "_file": path.name})
    return views, errors


def latest_per_institution(views: list[dict]) -> list[dict]:
    """The newest view per institution x hypothesis (ties: the later-retrieved one)."""
    best: dict[tuple, dict] = {}
    for v in views:
        key = (v["institution"], v["hypothesis"])
        rank = (utc_naive(v["published_at"]), utc_naive(v["retrieved_at"]))
        if key not in best or rank >= (utc_naive(best[key]["published_at"]), utc_naive(best[key]["retrieved_at"])):
            best[key] = v
    return sorted(best.values(), key=lambda v: (v["hypothesis"], v["institution"]))


def forecast_summary(views: list[dict]) -> list[dict]:
    """Per metric x period: each institution's latest stated value; a median only when n >= 5."""
    latest: dict[tuple, dict] = {}
    for v in views:
        fc = v.get("forecast")
        if not fc:
            continue
        key = (fc["metric_id"], str(fc["period"]), fc["unit"], v["institution"])
        if key not in latest or utc_naive(v["published_at"]) >= utc_naive(latest[key]["published_at"]):
            latest[key] = v
    groups: dict[tuple, list[dict]] = {}
    for (mid, period, unit, _), v in latest.items():
        groups.setdefault((mid, period, unit), []).append(v)
    out = []
    for (mid, period, unit), vs in sorted(groups.items()):
        values = [{"institution": v["institution"], "value": v["forecast"]["value"], "published_at": v["published_at"],
                   "source_url": v["source_url"], "view_id": v["view_id"]} for v in sorted(vs, key=lambda v: v["institution"])]
        n = len(values)
        nums = [x["value"] for x in values]
        out.append({"metric_id": mid, "period": period, "unit": unit, "n": n, "values": values,
                    "median": statistics.median(nums) if n >= MIN_CONSENSUS else None,
                    "range": [min(nums), max(nums)] if n >= MIN_CONSENSUS else None,
                    "consensus": n >= MIN_CONSENSUS})
    return out


def access_ledger(path: str | Path) -> list[dict]:
    """Dated record of the institutional-view sources checked and why each is not connected."""
    path = Path(path)
    if not path.is_file():
        return []
    return list((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("checks", []))
