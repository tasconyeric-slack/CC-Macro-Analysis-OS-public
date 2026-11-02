#!/usr/bin/env python3
"""Fetch China's exports to the United States, published YTD YoY (%), from the GACC
English monthly bulletin, table (2) "Imports and Exports by Country (Region) of
Origin/Destination", into the inbox CSV format (docs/specs/data-spec.md §5).

The table's "Percentage Change" columns are year-to-date changes as published by
GACC; they are taken as-is (metric cn_exports_us_ytd_yoy), never derived.

Year index pages: http://english.customs.gov.cn/statics/report/monthly<YEAR>.html
(the current year is monthly.html). The English site is reachable over plain HTTP;
its HTTPS certificate is self-signed.

Usage:  python scripts/fetch_gacc_us.py [--start 2019] [--out data/private/inbox/gacc_us.csv]
Then:   python -m cnmacro ingest-inbox data/private/inbox/gacc_us.csv
"""
from __future__ import annotations

import argparse
import csv
import html
import re
import time
import urllib.request
from datetime import date
from pathlib import Path

BASE = "http://english.customs.gov.cn"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129 Safari/537.36"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# A bulletin page date this many days after the reference month's end is treated as a
# later re-upload, not the publication date.
MAX_RELEASE_LAG_DAYS = 45


def fetch(url: str) -> str:
    last = None
    for i in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf-8", "ignore")
        except Exception as ex:
            last = ex
            time.sleep(2 ** i)
    raise RuntimeError(f"GET failed: {url} ({last})")


def clean(s: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).replace("\xa0", " ").strip()


def country_table_links(year: int) -> dict[int, str]:
    page = fetch(f"{BASE}/statics/report/monthly{'' if year == date.today().year else year}.html")
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        if "by Country" in clean(tr):
            out = {}
            for href, text in re.findall(r"<a[^>]+href=['\"]?([^'\" >]+)['\"]?[^>]*>(.*?)</a>", tr, re.S):
                t = clean(text).rstrip(".")
                if t[:3] in MONTHS:
                    out[MONTHS.index(t[:3]) + 1] = href
            return out
    return {}


def parse_us(page: str) -> tuple[float | None, str]:
    """(published YTD YoY % for exports to the United States, title)."""
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        cells = [clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        # some years pad rows with empty edge cells
        while cells and not cells[0]:
            cells.pop(0)
        while cells and not cells[-1]:
            cells.pop()
        if cells:
            rows.append(cells)
    title = rows[0][0] if rows else ""
    # Layouts: 10 cells = name | total m | total ytd | exports m | exports ytd | imports m |
    # imports ytd | %total | %exports | %imports ; 7 cells (Jan-Feb combined tables, YTD
    # only) = name | total | exports | imports | %total | %exports | %imports
    col = {10: 8, 7: 5}
    for r in rows:
        if r and r[0] == "United States":
            if len(r) not in col:
                raise ValueError(f"unexpected row width {len(r)}: {r}")
            try:
                return float(r[col[len(r)]].replace(",", "")), title
            except ValueError:
                return None, title
    return None, title


def page_date(page: str) -> str | None:
    m = re.search(r"(20\d\d)/(\d{2})/(\d{2})", clean(page))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=2019)
    ap.add_argument("--out", default="data/private/inbox/gacc_us.csv")
    a = ap.parse_args()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric_id", "reference_period", "value", "release_date", "source", "source_code", "limitation"])
        for year in range(a.start, date.today().year + 1):
            links = country_table_links(year)
            print(f"{year}: months linked {sorted(links)}")
            for month, url in sorted(links.items()):
                page = fetch(url)
                v, title = parse_us(page)
                if v is None:
                    print(f"  {year}-{month:02d}: no United States YTD change ({title[:60]})")
                    continue
                # title ends with ",<month>.<year>" or ",<year>.<month>"; check it names this month
                if not re.search(rf"\b0?{month}\.\s*{year}\b|\b{year}\.\s*0?{month}\b", title):
                    print(f"  {year}-{month:02d}: title does not match the month ({title[:80]}); skipped")
                    continue
                rel = page_date(page)
                note = "GACC English monthly bulletin table (2); published year-to-date % change, taken as-is"
                if rel:
                    end = date(year + (month == 12), month % 12 + 1, 1)
                    if (date.fromisoformat(rel) - end).days > MAX_RELEASE_LAG_DAYS:
                        note += f"; page dated {rel}, too late to be the publication date, so release_date left blank"
                        rel = ""
                else:
                    note += "; page carries no date"
                    rel = ""
                w.writerow(["cn_exports_us_ytd_yoy", f"{year}-{month:02d}", v, rel, "GACC", url, note])
                n += 1
    print(f"wrote {n} rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
