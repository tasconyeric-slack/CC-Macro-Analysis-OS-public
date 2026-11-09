#!/usr/bin/env python3
"""Step A probe for the market-data task: call each candidate Tushare endpoint once from a GitHub
runner (the token exists only there) and probe the public official pages used for cross-checks.

Writes a JSON report with endpoint, parameters (never the token), fields, row count, date range,
whether the account's points allow it, and a sample of the latest row. Nothing here is ingested.

    python scripts/probe_market_sources.py --out market-probe.json --summary "$GITHUB_STEP_SUMMARY" \
        --response-dir probe-responses
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cnmacro import tushare_client as ts  # noqa: E402

BEIJING = timezone(timedelta(hours=8))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129 Safari/537.36"}

# Public pages for the two cross-checks. The first round discovers which of these a runner can
# read and what shape they have; the comparison logic is written against what actually comes back.
PUBLIC_PROBES = {
    "CFETS central parity JSON": "https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/fx/ccpr.json",
    "CFETS central parity history": ("https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew"
                                     "?startDate={d0}&endDate={d1}&currency=USD/CNY&pageNum=1&pageSize=15"),
    "CFETS central parity page": "https://www.chinamoney.com.cn/chinese/bkccpr/",
    "ChinaBond yield curve page": "https://yield.chinabond.com.cn/cbweb-mn/yield_main?locale=zh_CN",
    "ChinaBond latest curve JSON": "https://yield.chinabond.com.cn/cbweb-czb-web/czb/queryGjqxInfo?locale=cn_ZH",
    "ChinaBond PBC curve list": "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/more?locale=cn_ZH",
    "ChinaBond home": "https://www.chinabond.com.cn/",
}


def today() -> datetime:
    return datetime.now(BEIJING)


def ymd(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def date_key(row: dict) -> str | None:
    for k in ("trade_date", "date"):
        if k in row and row[k]:
            return k
    return None


def run(name, api, params, fields=None, *, limit=None, note=""):
    """One Tushare call, summarised. Never raises."""
    t0 = time.time()
    out = {"name": name, "api": api, "params": params, "fields_requested": fields, "note": note}
    try:
        rows = ts.call(api, params, fields)
    except ts.TushareError as exc:
        out.update(ok=False, kind=exc.kind, error=str(exc)[:300], seconds=round(time.time() - t0, 1),
                   permitted={"not_permitted": False}.get(exc.kind, None))
        return out, []
    out.update(ok=True, kind="ok", rows=len(rows), seconds=round(time.time() - t0, 1), permitted=True)
    if rows:
        out["columns"] = list(rows[0].keys())
        k = date_key(rows[0])
        if k:
            dates = sorted(str(r[k]) for r in rows if r.get(k))
            out.update(first_date=dates[0], last_date=dates[-1])
            newest = max(rows, key=lambda r: str(r.get(k) or ""))
            out["latest_row"] = newest
        out["truncated"] = bool(limit and len(rows) >= limit)
    return out, rows


def tushare_probe(report):
    results = report["tushare"]
    end = ymd(today())
    start = "20180101"

    def add(*args, **kw):
        out, rows = run(*args, **kw)
        results.append(out)
        return rows

    # curve_term is documented as a number; fall back to the string form if a numeric query is empty
    for term in (1, 10):
        rows = add(f"yc_cb 1001.CB term {term}Y (maturity)", "yc_cb",
                   {"ts_code": "1001.CB", "curve_type": "0", "curve_term": term, "start_date": start, "end_date": end},
                   limit=2000)
        if not rows and results[-1].get("ok"):
            add(f"yc_cb 1001.CB term {term}Y (string term)", "yc_cb",
                {"ts_code": "1001.CB", "curve_type": "0", "curve_term": f"{term}.0", "start_date": start, "end_date": end},
                limit=2000)
    add("shibor ON/3M", "shibor", {"start_date": start, "end_date": end}, ["date", "on", "3m"], limit=2000)
    add("shibor_quote (DR007 search)", "shibor_quote", {"start_date": ymd(today() - timedelta(days=10)), "end_date": end},
        note="looking for any interbank repo fixing; shibor_quote is bank-by-bank SHIBOR quotes")
    add("repo_daily GC007.SH (exchange repo, NOT DR007)", "repo_daily",
        {"ts_code": "204007.SH", "start_date": ymd(today() - timedelta(days=30)), "end_date": end},
        note="exchange-traded treasury repo; recorded only to document that it is not the interbank DR007 fixing")

    basic = add("fx_obasic FXCM", "fx_obasic", {"exchange": "FXCM"}, ["ts_code", "name", "classify", "exchange"])
    cny = sorted(r["ts_code"] for r in basic if re.search(r"CN[YH]", r.get("ts_code", "")))
    results[-1]["cny_codes"] = cny
    for code in sorted({"USDCNH.FXCM"} | {c for c in cny if c.startswith("USDCN")}):
        add(f"fx_daily {code}", "fx_daily", {"ts_code": code, "start_date": start, "end_date": end}, limit=4000)

    add("index_daily 000300.SH", "index_daily", {"ts_code": "000300.SH", "start_date": start, "end_date": end}, limit=10000)

    add("index_classify SW2021 L1", "index_classify", {"level": "L1", "src": "SW2021"})
    for code, label in (("801050.SI", "nonferrous metals"), ("801120.SI", "food & beverage")):
        add(f"sw_daily {code} {label}", "sw_daily", {"ts_code": code, "start_date": start, "end_date": end}, limit=4000)

    for fut, label in (("CU.SHF", "copper"), ("RB.SHF", "rebar"), ("I.DCE", "iron ore")):
        mapping = add(f"fut_mapping {fut} {label}", "fut_mapping",
                      {"ts_code": fut, "start_date": ymd(today() - timedelta(days=45)), "end_date": end}, limit=5000)
        if mapping:
            newest = max(mapping, key=lambda r: r["trade_date"])
            add(f"fut_daily {newest['mapping_ts_code']} ({label} main)", "fut_daily",
                {"ts_code": newest["mapping_ts_code"], "start_date": ymd(today() - timedelta(days=45)), "end_date": end},
                limit=2000)
        add(f"fut_daily {fut} direct ({label}, continuous code)", "fut_daily",
            {"ts_code": fut, "start_date": ymd(today() - timedelta(days=15)), "end_date": end},
            limit=2000, note="whether the continuous code is accepted directly by fut_daily")

    add("us_tycr 1Y/10Y", "us_tycr", {"start_date": start, "end_date": end}, ["date", "y1", "y10"], limit=2000)


def public_probe(report, response_dir):
    d1 = today().date()
    d0 = d1 - timedelta(days=14)
    for name, url in PUBLIC_PROBES.items():
        url = url.format(d0=d0.isoformat(), d1=d1.isoformat())
        t0 = time.time()
        row = {"name": name, "url": url}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                body = r.read(2_000_000)
                text = body.decode("utf-8", errors="replace")
                row.update(ok=True, status=r.status, bytes=len(body), content_type=r.headers.get("Content-Type"),
                           final_url=r.url, sha256=hashlib.sha256(body).hexdigest(),
                           snippet=" ".join(text[:400].split()))
                try:
                    json.loads(text)
                    row["json"] = True
                except ValueError:
                    row["json"] = False
                if response_dir:
                    target = Path(response_dir) / (re.sub(r"\W+", "_", name).strip("_") + ".bin")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(body[:300_000])
                    row["response_file"] = target.name
        except Exception as exc:  # noqa: BLE001 - a probe reports every failure, it never raises
            row.update(ok=False, status=getattr(exc, "code", None), error=f"{type(exc).__name__}: {exc}"[:200])
        row["seconds"] = round(time.time() - t0, 1)
        report["public"].append(row)
        print(f"{'OK  ' if row['ok'] else 'FAIL'} {row.get('status')!s:>4} {row['seconds']:>5}s  {name}")


def summary_markdown(report):
    lines = ["## Market source probe", "", f"Probed at `{report['probed_at']}`. Token present: **{report['token_present']}** "
             "(value never printed or stored).", "", "### Tushare", "",
             "| Probe | Result | Rows | Date range | Truncated | Note |", "|---|---|---:|---|---|---|"]
    for r in report["tushare"]:
        rng = f"{r.get('first_date', '')} .. {r.get('last_date', '')}" if r.get("first_date") else ""
        res = "ok" if r["ok"] else f"{r['kind']}: {r.get('error', '')}"
        lines.append(f"| {r['name']} | {res.replace('|', '/')} | {r.get('rows', '')} | {rng} | {r.get('truncated', '')} | "
                     f"{(r.get('note') or '').replace('|', '/')} |")
    lines += ["", "### Public cross-check pages", "", "| Page | HTTP | Bytes | JSON | Snippet |", "|---|---:|---:|---|---|"]
    for r in report["public"]:
        lines.append(f"| {r['name']} | {r.get('status')} | {r.get('bytes', '')} | {r.get('json', '')} | "
                     f"{(r.get('snippet') or r.get('error') or '')[:120].replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="market-probe.json")
    ap.add_argument("--summary")
    ap.add_argument("--response-dir")
    ap.add_argument("--skip-tushare", action="store_true")
    a = ap.parse_args()
    report = {"probed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
              "token_present": bool(ts.token_from_env()), "tushare": [], "public": []}
    if report["token_present"] and not a.skip_tushare:
        tushare_probe(report)
    else:
        print("TUSHARE_TOKEN is not available in this run; Tushare probes skipped (reported, not failed).")
    public_probe(report, a.response_dir)
    text = json.dumps(report, indent=2, ensure_ascii=False, default=str)
    token = ts.token_from_env()
    if token and token in text:  # belt and braces: the report must never contain the credential
        raise SystemExit("refusing to write a report that contains the token")
    Path(a.out).write_text(text, encoding="utf-8")
    if a.summary:
        with open(a.summary, "a", encoding="utf-8") as f:
            f.write(summary_markdown(report))
    for r in report["tushare"]:
        print(f"{'OK  ' if r['ok'] else 'FAIL'} {r['name']}" + ("" if r["ok"] else f"  [{r['kind']}] {r.get('error', '')}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
