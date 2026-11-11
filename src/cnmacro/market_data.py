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
# The account is limited to roughly one call per interface per hour (observed 2026-11-10), so every series is read
# in ONE call per interface: history_start..today fits the row caps (shibor/us_tycr 2000, index_daily 10000).
YEARS_PER_CALL = 8
DATE_RATE_KINDS = ("shibor", "hibor", "us_tycr", "us_trycr")
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


# A refusal that another call in the same run cannot change: once seen for an interface, that interface is not
# called again in this run (a rate-limited retry would only spend the account's next allowance). A bad or missing
# token stops every interface.
STICKY_KINDS = (ts.RATE_LIMITED, ts.NOT_PERMITTED)
FATAL_KINDS = (ts.INVALID_TOKEN, ts.MISSING_TOKEN)


class Fetcher:
    """Runs the endpoint calls of one refresh. Identical queries are made once, and a rate-limit or permission
    refusal is remembered per interface so the run never sends a second request that is bound to be refused."""

    def __init__(self, call: Caller = ts.call):
        self._call, self._cache = call, {}
        self._refused: dict[str, ts.TushareError] = {}
        self._fatal: ts.TushareError | None = None
        self.requests: list[str] = []          # interfaces actually requested, in order (for the run summary)

    def rows(self, api: str, params: dict, fields: list[str] | None = None) -> list[dict]:
        key = (api, json.dumps(params, sort_keys=True), tuple(fields or ()))
        if key in self._cache:
            return self._cache[key]
        if self._fatal is not None:
            raise self._fatal
        if api in self._refused:
            raise self._refused[api]
        self.requests.append(api)
        try:
            self._cache[key] = self._call(api, params, fields)
        except ts.TushareError as exc:
            if exc.kind in FATAL_KINDS:
                self._fatal = exc
            elif exc.kind in STICKY_KINDS:
                self._refused[api] = exc
            raise
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
    if kind in DATE_RATE_KINDS:         # shibor, hibor, us_tycr, us_trycr: one `date` column, one column per tenor
        rows = _ranged(fetcher, kind, {}, start, end)
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


TRUNCATION_SLACK_DAYS = 14     # a backfill whose first row is later than history_start + this is reported as short


def request_starts(spec: dict, held: dict[str, dict[str, float]], end: date, *, backfill: bool = False) -> dict[str, date]:
    """First date to request for each fetched series. Series that share one interface query (the four SHIBOR
    tenors, both HIBOR tenors, UST 1Y and 10Y) get the earliest start of the group, so the group is still ONE
    request even when only one of its series has no stored history yet."""
    first = date.fromisoformat(spec["history_start"])
    recent = end - timedelta(days=spec["lookback_days"])
    own = {s["metric_id"]: first if (backfill or not held.get(s["metric_id"])) else recent
           for s in spec["series"] if s["kind"] != "derived"}
    group: dict[tuple, date] = {}
    for s in spec["series"]:
        if s["metric_id"] in own:
            key = query_key(s)
            group[key] = min(group.get(key, own[s["metric_id"]]), own[s["metric_id"]])
    return {s["metric_id"]: group[query_key(s)] for s in spec["series"] if s["metric_id"] in own}


def query_key(s: dict) -> tuple:
    """The parameters that decide which request a series needs (its field is read from the same reply)."""
    return (s["kind"], s.get("ts_code"), s.get("curve_type"), s.get("curve_term"))


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
    starts = request_starts(spec, held, end, backfill=backfill)
    for s in spec["series"]:
        mid = s["metric_id"]
        if mid not in metrics:
            summary["series"][mid] = {"status": "error", "reason": "not in metrics.yaml"}
            continue
        if s["kind"] == "derived":
            continue
        start = starts[mid]
        try:
            fetched[mid] = fetch_values(s, fetcher, start, end)
        except ts.TushareError as exc:
            status = "skipped" if exc.kind in (ts.NOT_PERMITTED, ts.MISSING_TOKEN) else "error"
            summary["series"][mid] = {"status": status, "reason": exc.kind, "interface": s["kind"],
                                      "detail": str(exc)[:200]}
            log(f"::warning title=market series skipped::{mid}: {exc.kind}")
            continue
        if not fetched[mid]:
            summary["series"][mid] = {"status": "empty", "reason": "endpoint returned no rows"}
            log(f"::warning title=market series empty::{mid}: endpoint returned no rows")
            continue
        if start == date.fromisoformat(spec["history_start"]):
            first = date.fromisoformat(min(fetched[mid]))
            if (first - start).days > TRUNCATION_SLACK_DAYS:
                # The interface returns newest rows first, so a row cap silently drops the oldest history.
                summary.setdefault("warnings", []).append(f"{mid}: history begins {first}, later than {start}")
                log(f"::warning title=market history short::{mid}: history begins {first} (asked from {start}); "
                    "the interface row cap may have truncated it")
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
    summary["requests"] = list(fetcher.requests)
    summary["failed"] = [s["metric_id"] for s in spec["series"]
                         if summary["series"].get(s["metric_id"], {}).get("status") != "ok"]
    log(f"market refresh: {summary['new_rows']} new row(s) across {len(appended)} series; "
        f"{sum(1 for v in summary['series'].values() if v['status'] == 'ok')}/{len(spec['series'])} series ok; "
        f"{len(fetcher.requests)} request(s) sent")
    if not dry_run:
        for fname, rows in appended.items():
            ingest.append_rows(rows, obs_dir / fname)
    return summary


CROSSCHECK_DIR = "data/market/crosschecks"


def incomplete(summary: dict) -> list[str]:
    """Configured series that did not come back ok (used by `market-refresh --require-all`)."""
    return list(summary.get("failed", [])) or [m for m, v in summary.get("series", {}).items() if v.get("status") != "ok"]


def run_market(root: Path | str = ".", *, crosscheck=None, **kwargs) -> dict:
    """Refresh, then cross-check against the official pages. A cross-check record is written (one new
    file per run that added data) so the page can say what was checked; gaps are reported, not fixed."""
    from . import market_crosscheck as xc
    root = Path(root)
    log = kwargs.get("log", print)
    summary = refresh_market(root, **kwargs)
    obs = load_observations(root / "data/demo/observations")
    active = {s["metric_id"] for s in load_spec(root)["series"]}
    needed = set(xc.CHECKS) | set(xc.MONTHLY_CHECKS) | {c["series"] for c in xc.MONTHLY_CHECKS.values()}
    stored = {mid: held_values(obs, mid) for mid in needed}
    results = (crosscheck or xc.run_crosschecks)(stored, log=log, active=active)
    summary["crosschecks"] = results
    summary["crosscheck_gaps"] = [r["metric_id"] for r in results if r["status"] == "gap"]
    if summary["new_rows"] and not summary["dry_run"]:
        stamp = datetime.fromisoformat(summary["retrieved_at"]).astimezone(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
        target = root / CROSSCHECK_DIR / f"{stamp}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"checked_at": summary["retrieved_at"], "results": results},
                                     indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
