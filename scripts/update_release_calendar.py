#!/usr/bin/env python3
"""Refresh the China release calendar from official sources.

  nbs           NBS release agenda (queryAgendas): scheduled dates and times, appended to
                data/dictionary/release_calendar.yaml when not already there.
  publications  Releases already published by PBOC (金融统计数据报告), GACC (preliminary trade
                table and monthly country bulletin) and MOF (财政收支情况), with the date or time
                printed on the official page, written to data/dictionary/official_publications.yaml.

PBOC, GACC and MOF dates are recorded only after publication: none of them is scheduled here,
because no exact upcoming date was verifiable from an official page when this was written
(the 2026 GACC timetable on www.customs.gov.cn refuses automated requests).

New NBS entries carry `display_metrics` only, so the refresh scheduler and its freshness check
(which read `metrics`) behave exactly as before.

Usage:  python scripts/update_release_calendar.py nbs [--start 2026-09-01] [--end 2027-03-31]
        python scripts/update_release_calendar.py publications [--year 2026]
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from cnmacro import ingest  # noqa: E402

CALENDAR = ROOT / "data/dictionary/release_calendar.yaml"
PUBLICATIONS = ROOT / "data/dictionary/official_publications.yaml"
EN = {"cpi": "CPI", "ppi": "PPI", "pmi": "PMI", "economy": "national economic performance",
      "ip": "industrial production", "retail": "retail sales", "fai": "fixed-asset investment",
      "property": "property development and sales", "homes": "home prices (70 cities)",
      "energy": "energy production", "profits": "industrial profits", "income": "household income",
      "capacity": "capacity utilization", "industry_va": "value added by industry"}


def period_of(fb: str, rule: str) -> str | None:
    if rule == "prev_quarter" and int(fb[5:7]) not in (1, 4, 7, 10):
        return None
    return ingest._agenda_period(fb, rule)


def entry_text(e: dict) -> str:
    """One calendar entry in the file's hand-written style (comments above it survive)."""
    return (f'  - name: "{e["name"]}"\n    period: "{e["period"]}"\n    release: "{e["release"]}"\n'
            f'    metrics: []\n    display_metrics: [{", ".join(e["display_metrics"])}]\n'
            f'    url: {e["url"]}\n    verified_on: "{e["verified_on"]}"\n')


def nbs(start: str, end: str) -> int:
    doc = yaml.safe_load(CALENDAR.read_text(encoding="utf-8"))
    held = doc.get("releases", [])
    have = [(str(e["release"]), set(ingest.release_kinds(e["name"])), set(e["metrics"]) | set(e.get("display_metrics", [])))
            for e in held]
    url = (ingest.AGENDA_URL + "?startDate=" + start.replace("-", "/") + "%2000:00:00&endDate="
           + end.replace("-", "/") + "%2023:59:59")
    added = []
    for fb, title in ingest.nbs_agenda(start, end):
        kinds = ingest.release_kinds(title)
        if not kinds:
            continue  # releases outside the macro set (e.g. cultural industries) stay off the calendar
        kind = ingest.KIND[kinds[0]]
        period = period_of(fb, kind[4])
        if not period:
            continue
        at = fb.replace(" ", "T") + "+08:00"
        shown = kind[5]
        if any(t == at and (kind[0] in k or set(shown) & m) for t, k, m in have):
            continue  # the same release is already on the calendar (one event, one entry)
        zh = re.sub(r"[（(][^（）()]*[)）]", "", title).strip()
        entry = {"name": f"{period} {EN[kind[0]]} ({zh})", "period": period, "release": at,
                 "metrics": [], "display_metrics": shown, "url": url, "verified_on": date.today().isoformat()}
        added.append(entry)
        have.append((at, {kind[0]}, set(shown)))
    if added:
        text = CALENDAR.read_text(encoding="utf-8").rstrip("\n") + "\n"
        text += f"  # NBS release agenda (queryAgendas) {start}..{end}, checked {date.today().isoformat()}.\n"
        text += "".join(entry_text(e) for e in added)
        CALENDAR.write_text(text, encoding="utf-8")
    print(f"NBS agenda: {len(added)} new entries")
    return 0


def pboc(year: int) -> list[dict]:
    import fetch_pboc as p
    out = []
    for page in range(1, 30):
        url = p.BASE + "/goutongjiaoliu/113456/113469/" + ("index.html" if page == 1 else f"11040-{page}.html")
        html = p.fetch(url)
        dates = re.findall(r"(20\d\d)-\d\d-\d\d", html)
        for href, title, day in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{4,80})</a>\s*(?:</[^>]+>\s*)*<[^>]+>\s*'
                                           r'(20\d\d-\d\d-\d\d)', html):
            m = re.fullmatch(r"(20\d\d)年(\d{1,2}月|一季度|上半年|前三季度|)金融统计数据报告", title.strip())
            if not m:
                continue
            y, mon = int(m.group(1)), {"一季度": 3, "上半年": 6, "前三季度": 9, "": 12}.get(m.group(2)) or int(m.group(2)[:-1])
            out.append({"source": "PBOC", "kind": "pboc", "title_zh": title.strip(), "period": f"{y}-{mon:02d}",
                        "published": day, "url": p.BASE + href})
        if dates and max(int(d) for d in dates) < year:
            break
    return out


def gacc(year: int) -> list[dict]:
    import fetch_gacc_us as g
    out = []

    def timely(period: str, day: str) -> bool:  # a much later page date is a re-upload, not the release
        y, mon = int(period[:4]), int(period[5:])
        return (date.fromisoformat(day) - date(y + (mon == 12), mon % 12 + 1, 1)).days <= g.MAX_RELEASE_LAG_DAYS

    index = g.fetch(g.BASE + "/statics/report/preliminary.html")
    rows = [r for r in re.findall(r"<tr[^>]*>(.*?)</tr>", index, re.S | re.I)
            if g.clean(r).startswith("(1) China's Total Export & Import Values (in USD)")]
    for href in re.findall(r"href=['\"]?([^'\" >]+)", rows[0] if rows else ""):
        page = g.fetch(href)
        title = g.clean((re.search(r"<title>(.*?)</title>", page, re.S) or [None, ""])[1])
        m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w* (20\d\d)", title)
        day = g.page_date(page)
        period = f"{m.group(2)}-{g.MONTHS.index(m.group(1)) + 1:02d}" if m else ""
        if m and day and int(m.group(2)) == year and timely(period, day):
            out.append({"source": "GACC", "kind": "gacc_flash", "title_en": title,
                        "period": period, "published": day, "url": href})
    for month, href in sorted(g.country_table_links(year).items()):
        day = g.page_date(g.fetch(href))
        if day and timely(f"{year}-{month:02d}", day):
            out.append({"source": "GACC", "kind": "gacc_bulletin", "title_en": f"Monthly bulletin, table (2), {g.MONTHS[month - 1]} {year}",
                        "period": f"{year}-{month:02d}", "published": day, "url": href})
    return out


def mof(year: int) -> list[dict]:
    import fetch_pboc as p  # a plain GET with retries; the MOF site needs nothing more
    base = "http://gks.mof.gov.cn/tongjishuju/"
    out = []
    for href, title in re.findall(r'<a href="\./([^"]+\.htm)"\s+title="([^"]+)"', p.fetch(base)):
        m = re.fullmatch(rf"{year}年(?:1-(\d+)月|(一季度|上半年|前三季度))财政收支情况", title)
        if not m:
            continue
        mon = int(m.group(1)) if m.group(1) else {"一季度": 3, "上半年": 6, "前三季度": 9}[m.group(2)]
        page = p.fetch(base + href)
        stamp = re.search(r'<meta name="PubDate" content="(20\d\d-\d\d-\d\d)(?: (\d\d:\d\d))?', page)
        if stamp:
            out.append({"source": "MOF", "kind": "mof", "title_zh": title, "period": f"{year}-{mon:02d}",
                        "published": stamp.group(1) + (f"T{stamp.group(2)}:00+08:00" if stamp.group(2) else ""),
                        "url": base + href})
    return out


def publications(year: int) -> int:
    old = yaml.safe_load(PUBLICATIONS.read_text(encoding="utf-8")) if PUBLICATIONS.exists() else {}
    held = {r["url"]: r for r in (old or {}).get("publications", [])}
    for name, collect in (("PBOC", pboc), ("GACC", gacc), ("MOF", mof)):
        try:
            found = collect(year)
        except Exception as ex:  # one unreachable site never discards the others' records
            print(f"{name}: unreachable ({type(ex).__name__}: {ex}); kept recorded entries")
            continue
        for r in found:
            held.setdefault(r["url"], {**r, "verified_on": date.today().isoformat()})
        print(f"{name}: {len(found)} published releases found")
    rows = sorted(held.values(), key=lambda r: (r["published"][:10], r["source"], r["kind"]))
    head = ("# Official China releases already published, with the date (or time) printed on the official\n"
            "# page. Written by scripts/update_release_calendar.py; never a forecast of a future date.\n")
    PUBLICATIONS.write_text(head + yaml.safe_dump({"publications": rows}, allow_unicode=True, sort_keys=False, width=200),
                            encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("nbs")
    a.add_argument("--start", default=f"{date.today().year}-{date.today().month:02d}-01")
    a.add_argument("--end", default=f"{date.today().year + 1}-03-31")
    b = sub.add_parser("publications")
    b.add_argument("--year", type=int, default=date.today().year)
    args = ap.parse_args()
    return nbs(args.start, args.end) if args.cmd == "nbs" else publications(args.year)


if __name__ == "__main__":
    raise SystemExit(main())
