#!/usr/bin/env python3
"""Probe whether each public source used by `cnmacro refresh-public` is reachable from
this machine. Prints one line per endpoint and writes a JSON report.

Used by the scheduled refresh workflow, so the reachability of official hosts from
GitHub-hosted runners is measured, not assumed.

Usage: python scripts/probe_sources.py [--out probe.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

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

# Opt-in diagnostics for the event intake; refresh-public's existing probes stay unchanged.
EVENT_ENDPOINTS = {
    "NBS November release agenda": (
        "https://data.stats.gov.cn/dg/website/publicrelease/web/external/queryAgendas?startDate=2026/11/01%2000:00:00&endDate=2026/11/30%2023:59:59", "agenda"),
    "NBS PMI indicator metadata": (
        "https://data.stats.gov.cn/dg/website/publicrelease/web/external/new/queryIndicatorsByCid?cid=93ffbb1aa85740d3aa2618371508b606&dt=&name=", "metadata"),
    "NBS latest releases RSS": ("https://www.stats.gov.cn/sj/zxfb/rss.xml", "rss"),
    "PBOC news releases": ("https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html", "pbc"),
    "gov.cn policy library (monetary policy)": (
        "https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary&q=" + urllib.parse.quote("货币政策"), "gov"),
    "gov.cn policy library (fiscal)": (
        "https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary&q=" + urllib.parse.quote("财政"), "gov"),
    "MOF fiscal revenue and spending": (
        "https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/quanguocaizhengshouzhiqingkuang/", "dated_links"),
    "NDRC press releases": ("https://www.ndrc.gov.cn/xwdt/xwfb/", "dated_links"),
}


class ArticleLinks(HTMLParser):
    """Count dated document links, excluding navigation and duplicate anchors."""

    def __init__(self, base: str, kind: str):
        super().__init__()
        self.base, self.kind = base, kind
        self.href, self.parts, self.items = None, [], {}

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.parts = []

    def handle_data(self, data):
        if self.href:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag != "a" or not self.href:
            return
        url = urllib.parse.urljoin(self.base, self.href)
        title = " ".join("".join(self.parts).split())
        pattern = r"/113469/(\d{14})\d*/index\.html" if self.kind == "pbc" else r"(?:/t|/)(\d{8})[_/]"
        match = re.search(pattern, url)
        if title and match and urllib.parse.urlsplit(url).hostname == urllib.parse.urlsplit(self.base).hostname:
            stamp = match[1]
            try:
                date = datetime.strptime(stamp, "%Y%m%d%H%M%S" if self.kind == "pbc" else "%Y%m%d")
                published = date.isoformat() + "+08:00" if self.kind == "pbc" else date.date().isoformat()
                self.items[url] = {"title": title, "url": url, "published": published,
                                   "time_precision": "second" if self.kind == "pbc" else "date"}
            except ValueError:
                pass
        self.href = None


def event_items(body: bytes, url: str, kind: str) -> list[dict]:
    """Probe shapes only, not an ingestion parser or a publication approval."""
    if kind in ("metadata", "agenda"):
        payload = json.loads(body)["data"]
        if kind == "metadata":
            return payload["list"]
        return [item for day in payload.values() for item in day]
    if kind == "rss":
        root = ET.fromstring(body)
        if root.tag.lower() != "rss":
            raise ValueError("expected RSS document")
        return [{"title": i.findtext("title"), "url": i.findtext("link"),
                 "published": i.findtext("pubDate"), "guid": i.findtext("guid")}
                for i in root.findall("./channel/item")]
    if kind == "gov":
        payload = json.loads(body)
        rows = payload.get("searchVO", {}).get("result")
        if not isinstance(rows, list):
            raise ValueError("expected searchVO.result list")
        return [{"title": re.sub(r"<[^>]+>", "", str(i.get("title", ""))),
                 "url": i.get("url"), "published": i.get("pubTime"),
                 "publisher": i.get("puborg")}
                for i in rows]
    text = body.decode("utf-8", errors="replace")
    parser = ArticleLinks(url, kind)
    parser.feed(text)
    return list(parser.items.values())


# FRED stalls on browser-like user agents but answers Python's default one (see ingest.DEFAULT_UA)
PLAIN_UA_HOSTS = ("fred.stlouisfed.org",)


def probe(url: str, timeout: int = 30, kind: str | None = None, response_dir: str | None = None) -> dict:
    t0 = time.time()
    headers = {} if any(h in url for h in PLAIN_UA_HOSTS) else dict(UA)
    if kind == "gov":
        headers.update({"Referer": "https://sousuo.www.gov.cn/", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            body = r.read(4_000_001 if kind else 4096)
            result = {"ok": True, "status": r.status, "bytes": len(body),
                      "seconds": round(time.time() - t0, 1)}
            if kind:
                result.update({"final_url": r.url, "sha256": hashlib.sha256(body).hexdigest(),
                               "content_type": r.headers.get("Content-Type")})
                if response_dir:
                    target = Path(response_dir) / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".bin")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(body)
                    result["response_file"] = target.as_posix()
                try:
                    if len(body) > 4_000_000:
                        raise ValueError("response exceeds probe limit")
                    items = event_items(body, r.url, kind)
                    result.update({"item_count": len(items), "samples": items[:3], "content_ok": bool(items)})
                    if kind in ("metadata", "agenda"):
                        result["items"] = items
                    if not items:
                        result["error"] = "no document items matched; empty feed or changed/WAF response"
                except (ValueError, ET.ParseError, AttributeError, TypeError, KeyError) as ex:
                    result.update({"content_ok": False, "item_count": None, "error": str(ex)[:160]})
            return result
    except urllib.error.HTTPError as ex:
        return {"ok": False, "status": ex.code, "error": str(ex.reason)[:120], "seconds": round(time.time() - t0, 1)}
    except Exception as ex:
        return {"ok": False, "status": None, "error": f"{type(ex).__name__}: {ex}"[:160],
                "seconds": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--events", action="store_true", help="Also probe authorized event sources and count items")
    ap.add_argument("--summary", help="Append a Markdown table to the GitHub run summary")
    ap.add_argument("--response-dir", help="Save official event responses as diagnostic fixtures")
    a = ap.parse_args()
    report = {"probed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "results": {}}
    endpoints = {name: (url, None) for name, url in ENDPOINTS.items()}
    if a.events:
        endpoints.update(EVENT_ENDPOINTS)
    for name, (url, kind) in endpoints.items():
        r = probe(url, kind=kind, response_dir=a.response_dir)
        report["results"][name] = {"url": url, **r}
        print(f"{'OK  ' if r['ok'] else 'FAIL'} {r.get('status')!s:>4} {r['seconds']:>5}s  {name}"
              + (f"  items={r.get('item_count')}" if kind else "")
              + (f"  ({r['error']})" if r.get("error") else ""))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
    if a.summary:
        lines = ["## Official source probe", "", f"Probed at `{report['probed_at']}`.", "",
                 "HTTP success and parsed content are separate; zero/missing items are not intake success.", "",
                 "| Source | HTTP | Seconds | Items | Content |", "|---|---:|---:|---:|---|"]
        for name, row in report["results"].items():
            detail = row.get("error", "ok" if row.get("content_ok") else "reachability only")
            lines.append(f"| {name} | {row['status']} | {row['seconds']} | {row.get('item_count', '—')} | {detail.replace('|', '/')} |")
        with Path(a.summary).open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
