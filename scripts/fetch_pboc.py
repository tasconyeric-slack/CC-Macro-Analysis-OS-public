#!/usr/bin/env python3
"""Fetch PBOC public statistics tables into the inbox CSV format (docs/specs/data-spec.md §5).

Source: PBOC 调查统计司 统计数据 pages (one page per year and section), which link
HTML versions of each table under /diaochatongjisi/attachDir/. Tables used:

  社会融资规模存量统计表        -> cn_tsf_stock_yoy (published growth rate, %)
  社会融资规模增量统计表        -> cn_tsf_govbond_flow (政府债券 column, CNY 100m, monthly flow)
  金融机构人民币信贷收支表      -> cn_loans_hh_mlt_ytd, cn_loans_corp_mlt_ytd
                                  (balance change since the prior December, CNY 100m)

The loan metrics are derived from published balances, not taken from PBOC's
reported increments; each such row carries a limitation saying so.

Usage:  python scripts/fetch_pboc.py [--start 2019] [--out data/private/inbox/pboc.csv]
Then:   python -m cnmacro ingest-inbox data/private/inbox/pboc.csv
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

BASE = "https://www.pbc.gov.cn"
INDEX = BASE + "/diaochatongjisi/116219/116319/index.html"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129 Safari/537.36"}
SECTIONS = {"社会融资规模": "tsf", "金融机构信贷收支统计": "credit"}
TABLES = {"tsf": ["社会融资规模存量统计表", "社会融资规模增量统计表"], "credit": ["金融机构人民币信贷收支表"]}


def fetch(url: str) -> str:
    last = None
    for i in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
            for enc in ("utf-8", "gb18030"):
                try:
                    return b.decode(enc)
                except UnicodeDecodeError:
                    pass
        except Exception as ex:
            last = ex
            time.sleep(2 ** i)
    raise RuntimeError(f"GET failed: {url} ({last})")


def clean(s: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).replace("\xa0", " ").strip()


def table_rows(page: str) -> list[list[str]]:
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        cells = [clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        if any(cells):
            rows.append(cells)
    return rows


def year_sections(start: int) -> dict[tuple[int, str], str]:
    """{(year, section_key): section index URL} parsed from the statistics index page."""
    page = fetch(INDEX)
    out = {}
    # Each year block: "<year>年统计数据" followed by its section links.
    blocks = re.split(r"(\d{4})年统计数据", page)
    for i in range(1, len(blocks) - 1, 2):
        year = int(blocks[i])
        if year < start - 1:
            continue
        for href, text in re.findall(r"""<a[^>]+href=["']([^"']+)["'][^>]*>(.*?)</a>""", blocks[i + 1], re.S):
            key = SECTIONS.get(clean(text))
            if key and (year, key) not in out:
                out[(year, key)] = href if href.startswith("http") else BASE + href
    return out


def table_links(section_url: str, names: list[str]) -> dict[str, str]:
    page = fetch(section_url)
    out = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        label = clean(tr)
        hrefs = [h for h in re.findall(r"""href=["']([^"']+)["']""", tr) if h.lower().endswith((".htm", ".html")) and "attachDir" in h]
        for n in names:
            # exact table name at the start of the row (excludes 存款类金融机构… and 地区…)
            if label.startswith(n) and hrefs and n not in out:
                out[n] = hrefs[0] if hrefs[0].startswith("http") else BASE + hrefs[0]
    return out


def num(s: str) -> float | None:
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def month_header(rows: list[list[str]]) -> list[str]:
    """Periods like 2026.01 / 2026.1 from the header row, normalised to YYYY-MM."""
    for r in rows:
        ps = [c for c in r if re.fullmatch(r"\d{4}\.\d{1,2}", c)]
        if len(ps) >= 3:
            return [f"{p[:4]}-{int(p.split('.')[1]):02d}" for p in ps]
    return []


def parse_stock(rows):
    periods = month_header(rows)
    for r in rows:
        if r and r[0].startswith("社会融资规模存量") and "统计表" not in r[0]:
            vals = r[1:]
            out = {}
            for k, p in enumerate(periods):
                if 2 * k + 1 < len(vals):
                    g = num(vals[2 * k + 1])
                    if g is not None:
                        out[p] = g
            return out
    return {}


def parse_flow(rows):
    header = next((r for r in rows if r and r[0].startswith("社会融资规模增量") and "统计表" not in r[0]), None)
    if not header:
        return {}
    idx = next((i for i, c in enumerate(header) if c.startswith("政府债券")), None)
    if idx is None:
        return {}
    out = {}
    for r in rows:
        if r and re.fullmatch(r"\d{4}\.\d{1,2}", r[0]) and idx + 1 < len(r):
            v = num(r[idx + 1])
            if v is not None:
                # first block only: some years repeat the months as shares of total (%)
                out.setdefault(f"{r[0][:4]}-{int(r[0].split('.')[1]):02d}", v)
    return out


def parse_credit(rows):
    """Balances of household and corporate medium/long-term loans, {period: value}."""
    periods = month_header(rows)
    hh, corp, section = {}, {}, None
    for r in rows:
        label = r[0] if r else ""
        if "住户贷款" in label:
            section = "hh"
        # 企（事）业单位贷款 from 2023; 非金融企业及机关团体贷款 in earlier tables
        elif any(k in label for k in ("企（事）业单位贷款", "企(事)业单位贷款", "非金融企业及机关团体贷款")):
            section = "corp"
        elif "非银行业金融机构贷款" in label or "境外贷款" in label:
            section = None
        elif section and "中长期贷款" in label:
            target = hh if section == "hh" else corp
            for p, c in zip(periods, r[1:]):
                v = num(c)
                if v is not None:
                    target[p] = v
            section = None
    return hh, corp


def ytd_from_balances(bal: dict[str, float]) -> dict[str, float]:
    out = {}
    for p, v in bal.items():
        dec = f"{int(p[:4]) - 1}-12"
        if dec in bal:
            out[p] = round(v - bal[dec], 2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=2019)
    ap.add_argument("--out", default=f"data/private/inbox/pboc_{date.today():%Y%m%d}.csv")
    a = ap.parse_args()

    secs = year_sections(a.start)
    stock, flow, hh_bal, corp_bal, src = {}, {}, {}, {}, {}
    for (year, key), url in sorted(secs.items()):
        for name, link in table_links(url, TABLES[key]).items():
            rows = table_rows(fetch(link))
            if name == "社会融资规模存量统计表":
                got = parse_stock(rows); stock.update(got)
            elif name == "社会融资规模增量统计表":
                got = parse_flow(rows); flow.update(got)
            else:
                h, c = parse_credit(rows); hh_bal.update(h); corp_bal.update(c); got = h
            src[(year, name)] = link
            print(f"{year} {name}: {len(got)} periods  {link}")

    derived = ("derived: month-end balance minus prior-December balance from the PBOC RMB credit table; "
               "may differ from PBOC-reported increments where loans were reclassified or written off")
    series = {
        "cn_tsf_stock_yoy": (stock, "社会融资规模存量统计表:社会融资规模存量增速", ""),
        "cn_tsf_govbond_flow": (flow, "社会融资规模增量统计表:政府债券", ""),
        "cn_loans_hh_mlt_ytd": (ytd_from_balances(hh_bal), "金融机构人民币信贷收支表:住户中长期贷款余额较上年末变动", derived),
        "cn_loans_corp_mlt_ytd": (ytd_from_balances(corp_bal), "金融机构人民币信贷收支表:企(事)业单位中长期贷款余额较上年末变动", derived),
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric_id", "reference_period", "value", "release_date", "source", "source_code", "limitation"])
        for mid, (vals, code, note) in series.items():
            for p, v in sorted(vals.items()):
                if int(p[:4]) >= a.start:
                    w.writerow([mid, p, v, "", "PBOC", f"pboc:{code}", note])
            n = sum(1 for p in vals if int(p[:4]) >= a.start)
            last = max((p for p in vals), default=None)
            print(f"{mid}: {n} rows, latest {last}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
