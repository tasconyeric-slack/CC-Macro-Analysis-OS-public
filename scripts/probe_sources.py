#!/usr/bin/env python3
"""Probe whether each public source used by `cnmacro refresh-public` is reachable from
this machine. Prints one line per endpoint and writes a JSON report.

Used by the scheduled refresh workflow, so the reachability of official hosts from
GitHub-hosted runners is measured, not assumed.

Usage: python scripts/probe_sources.py [--out probe.json]
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129 Safari/537.36"}
ENDPOINTS = {
    "NBS data portal (indicator tree)":
        "https://data.stats.gov.cn/dg/website/publicrelease/web/external/new/queryIndexTreeAsync?pid=&code=1",
    "NBS release agenda":
        "https://data.stats.gov.cn/dg/website/publicrelease/web/external/queryAgendas?startDate=2026/10/01%2000:00:00&endDate=2026/10/31%2023:59:59",
    "NBS press releases (www.stats.gov.cn)": "https://www.stats.gov.cn/sj/zxfb/",
    "PBOC statistics index": "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html",
    "GACC English bulletin index": "http://english.customs.gov.cn/statics/report/monthly.html",
    "MOF budget releases": "https://gks.mof.gov.cn/tongjishuju/",
    "FRED CSV": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GS10&cosd=2026-01-01&coed=2026-12-31",
}


# FRED stalls on browser-like user agents but answers Python's default one (see ingest.DEFAULT_UA)
PLAIN_UA_HOSTS = ("fred.stlouisfed.org",)


def probe(url: str, timeout: int = 30) -> dict:
    t0 = time.time()
    headers = {} if any(h in url for h in PLAIN_UA_HOSTS) else UA
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            body = r.read(4096)
            return {"ok": True, "status": r.status, "bytes": len(body), "seconds": round(time.time() - t0, 1)}
    except urllib.error.HTTPError as ex:
        return {"ok": False, "status": ex.code, "error": str(ex.reason)[:120], "seconds": round(time.time() - t0, 1)}
    except Exception as ex:
        return {"ok": False, "status": None, "error": f"{type(ex).__name__}: {ex}"[:160],
                "seconds": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    a = ap.parse_args()
    report = {"probed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "results": {}}
    for name, url in ENDPOINTS.items():
        r = probe(url)
        report["results"][name] = {"url": url, **r}
        print(f"{'OK  ' if r['ok'] else 'FAIL'} {r.get('status')!s:>4} {r['seconds']:>5}s  {name}"
              + ("" if r["ok"] else f"  ({r.get('error')})"))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
