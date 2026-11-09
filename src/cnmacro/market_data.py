"""Daily market series from Tushare, appended to the existing observation store with vintages.

    cnmacro market-refresh [--backfill] [--dry-run]

Fetch rules (data/dictionary/market_series.yaml):
  * a series with no stored rows is backfilled from `history_start`; otherwise the last
    `lookback_days` calendar days are re-read so a revised value becomes a new vintage;
  * only genuinely new information is appended (`refresh.new_rows`): a new trade date, or a
    changed value kept as a new vintage flagged `revised`;
  * a missing token, a non-permitted endpoint or any fetch error skips that series and is
    reported; the run never fails on data availability and never substitutes guessed values.

Reference period is the trade date (YYYY-MM-DD). Availability is the retrieval time: Tushare
does not give a publication time, so the point-in-time store never claims earlier knowledge.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import ingest, tushare_client as ts
from .store import load_dictionary, load_observations

SPEC = "data/dictionary/market_series.yaml"
FILE_PREFIX = "tushare_"
LIMITATION = "Tushare daily value; no publication time is given, so availability is taken as retrieval time"
YEARS_PER_CALL = 2          # keeps each call well under Tushare's row caps (yc_cb 2000, us_tycr 2000)
Caller = type(ts.call)


def load_spec(root: Path | str = ".") -> dict:
    spec = yaml.safe_load((Path(root) / SPEC).read_text(encoding="utf-8"))
    ids = [s["metric_id"] for s in spec["series"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate metric_id in market_series.yaml")
    return spec


def iso(d: str) -> str:
    """20261109 -> 2026-11-09 (already-ISO input is returned unchanged)."""
    d = str(d)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d.isdigit() else d[:10]


def compact(d: date | str) -> str:
    return str(d).replace("-", "")[:8]


def windows(start: date, end: date, years: int = YEARS_PER_CALL):
    cur = start
    while cur <= end:
        nxt = min(date(cur.year + years, cur.month, min(cur.day, 28)) - timedelta(days=1), end)
        yield cur, nxt
        cur = nxt + timedelta(days=1)


class Fetcher:
    """Runs the endpoint calls of one refresh; identical queries are made once."""

    def __init__(self, call: Caller = ts.call):
        self._call, self._cache = call, {}

    def rows(self, api: str, params: dict, fields: list[str] | None = None) -> list[dict]:
        key = (api, json.dumps(params, sort_keys=True), tuple(fields or ()))
        if key not in self._cache:
            self._cache[key] = self._call(api, params, fields)
        return self._cache[key]


def _ranged(fetcher, api, params, start, end, fields=None):
    out = []
    for a, b in windows(start, end):
        out += fetcher.rows(api, {**params, "start_date": compact(a), "end_date": compact(b)}, fields)
    return out


def fetch_values(spec: dict, fetcher: Fetcher, start: date, end: date) -> dict[str, float]:
    """{ISO trade date: value} for one non-derived series."""
    kind, field = spec["kind"], spec.get("field")
    if kind == "yc_cb":
        rows = _ranged(fetcher, "yc_cb", {"ts_code": spec["ts_code"], "curve_type": str(spec["curve_type"]),
                                         "curve_term": spec["curve_term"]}, start, end)
        return {iso(r["trade_date"]): float(r[field]) for r in rows if r.get(field) is not None}
    if kind == "shibor":
        rows = _ranged(fetcher, "shibor", {}, start, end)
        return {iso(r["date"]): float(r[field]) for r in rows if r.get(field) is not None}
    if kind == "us_tycr":
        rows = _ranged(fetcher, "us_tycr", {}, start, end)
        return {iso(r["date"]): float(r[field]) for r in rows if r.get(field) is not None}
    if kind == "fx_daily":
        rows = _ranged(fetcher, "fx_daily", {"ts_code": spec["ts_code"]}, start, end)
        a, b = spec["mid_of"]
        return {iso(r["trade_date"]): round((float(r[a]) + float(r[b])) / 2, 5)
                for r in rows if r.get(a) is not None and r.get(b) is not None}
    if kind in ("index_daily", "sw_daily"):
        rows = _ranged(fetcher, kind, {"ts_code": spec["ts_code"]}, start, end)
        return {iso(r["trade_date"]): float(r[field]) for r in rows if r.get(field) is not None}
    if kind == "fut_main":
        mapping = _ranged(fetcher, "fut_mapping", {"ts_code": spec["ts_code"]}, start, end)
        by_contract: dict[str, dict[str, str]] = {}
        for r in mapping:
            by_contract.setdefault(r["mapping_ts_code"], {})[iso(r["trade_date"])] = r["mapping_ts_code"]
        out: dict[str, float] = {}
        for contract, days in by_contract.items():
            lo, hi = min(days), max(days)
            rows = fetcher.rows("fut_daily", {"ts_code": contract, "start_date": compact(lo), "end_date": compact(hi)})
            for r in rows:
                d = iso(r["trade_date"])
                if d in days and r.get(field) is not None:
                    out[d] = float(r[field])
        return out
    raise ValueError(f"unknown market series kind {kind!r}")


def derive_minus(values: dict[str, dict[str, float]], held: dict[str, dict[str, float]], spec: dict) -> dict[str, float]:
    a, b = spec["minus"]
    va, vb = {**held.get(a, {}), **values.get(a, {})}, {**held.get(b, {}), **values.get(b, {})}
    touched = set(values.get(a, {})) | set(values.get(b, {}))
    return {d: round(va[d] - vb[d], spec.get("decimals", 4)) for d in sorted(touched) if d in va and d in vb}


def held_values(obs, metric_id: str) -> dict[str, float]:
    sub = obs[obs.metric_id == metric_id]
    if sub.empty:
        return {}
    last = sub.sort_values("retrieved_at").drop_duplicates("reference_period", keep="last")
    return {r.reference_period: float(r.value) for r in last.itertuples()}


def to_rows(metric_id: str, source_code: str, values: dict[str, float], got: str) -> list[dict]:
    return [ingest.row(metric_id, d, round(v, 6), "Tushare", source_code, "public",
                       retrieved_at=got, calendar={}, limitation_if_unknown=LIMITATION)
            for d, v in sorted(values.items())]


def refresh_market(root: Path | str = ".", *, call: Caller = ts.call, today: date | None = None, backfill: bool = False,
                   dry_run: bool = False, log=print, now: str | None = None) -> dict:
    """Fetch every configured series; returns a summary and (unless dry_run) appends the new rows."""
    from .refresh import new_rows       # imported here: refresh pulls in the whole evidence stack
    root = Path(root)
    spec = load_spec(root)
    metrics = load_dictionary(root / "data/dictionary/metrics.yaml")
    obs_dir = root / "data/demo/observations"
    obs = load_observations(obs_dir)
    got = now or ingest.now_iso()
    end = today or datetime.now(timezone(timedelta(hours=8))).date()
    summary = {"retrieved_at": got, "as_of": end.isoformat(), "token_present": bool(ts.token_from_env()),
               "series": {}, "new_rows": 0, "dry_run": dry_run}
    if not summary["token_present"] and call is ts.call:
        log(f"::notice title=market data::{ts.TOKEN_ENV} is not available; every Tushare series is skipped")
        summary["series"] = {s["metric_id"]: {"status": "skipped", "reason": ts.MISSING_TOKEN} for s in spec["series"]}
        return summary
    fetcher = Fetcher(call)
    fetched: dict[str, dict[str, float]] = {}
    appended: dict[str, list[dict]] = {}
    held = {s["metric_id"]: held_values(obs, s["metric_id"]) for s in spec["series"]}
    for s in spec["series"]:
        mid = s["metric_id"]
        if mid not in metrics:
            summary["series"][mid] = {"status": "error", "reason": "not in metrics.yaml"}
            continue
        if s["kind"] == "derived":
            continue
        full = backfill or not held[mid]
        start = date.fromisoformat(spec["history_start"]) if full else end - timedelta(days=spec["lookback_days"])
        try:
            fetched[mid] = fetch_values(s, fetcher, start, end)
        except ts.TushareError as exc:
            status = "skipped" if exc.kind in (ts.NOT_PERMITTED, ts.MISSING_TOKEN) else "error"
            summary["series"][mid] = {"status": status, "reason": exc.kind, "detail": str(exc)[:200]}
            log(f"::warning title=market series skipped::{mid}: {exc.kind}")
            continue
        if not fetched[mid]:
            summary["series"][mid] = {"status": "empty", "reason": "endpoint returned no rows"}
            log(f"::warning title=market series empty::{mid}: endpoint returned no rows")
    for s in spec["series"]:
        mid = s["metric_id"]
        if s["kind"] == "derived":
            if any(fetched.get(m) for m in s["minus"]):
                fetched[mid] = derive_minus(fetched, held, s)
            else:
                summary["series"][mid] = {"status": "skipped", "reason": "inputs unavailable"}
                continue
        if mid not in fetched or not fetched[mid]:
            continue
        code = metrics[mid].source_code
        fresh = new_rows(to_rows(mid, code, fetched[mid], got), obs)
        summary["series"][mid] = {"status": "ok", "fetched": len(fetched[mid]), "new": len(fresh),
                                  "latest": max(fetched[mid]), "history_start": min(fetched[mid])}
        if fresh:
            appended[f"{FILE_PREFIX}{mid}.csv"] = fresh
    summary["new_rows"] = sum(len(v) for v in appended.values())
    log(f"market refresh: {summary['new_rows']} new row(s) across {len(appended)} series; "
        f"{sum(1 for v in summary['series'].values() if v['status'] == 'ok')}/{len(spec['series'])} series ok")
    if not dry_run:
        for fname, rows in appended.items():
            ingest.append_rows(rows, obs_dir / fname)
    return summary


CROSSCHECK_DIR = "data/market/crosschecks"


def run_market(root: Path | str = ".", *, crosscheck=None, **kwargs) -> dict:
    """Refresh, then cross-check against the official pages. A cross-check record is written (one new
    file per run that added data) so the page can say what was checked; gaps are reported, not fixed."""
    from . import market_crosscheck as xc
    root = Path(root)
    log = kwargs.get("log", print)
    summary = refresh_market(root, **kwargs)
    obs = load_observations(root / "data/demo/observations")
    stored = {mid: held_values(obs, mid) for mid in xc.CHECKS}
    results = (crosscheck or xc.run_crosschecks)(stored, log=log)
    summary["crosschecks"] = results
    summary["crosscheck_gaps"] = [r["metric_id"] for r in results if r["status"] == "gap"]
    if summary["new_rows"] and not summary["dry_run"]:
        stamp = datetime.fromisoformat(summary["retrieved_at"]).astimezone(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
        target = root / CROSSCHECK_DIR / f"{stamp}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"checked_at": summary["retrieved_at"], "results": results},
                                     indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
