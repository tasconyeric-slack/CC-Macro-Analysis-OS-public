"""Ingestion into the observation CSV contract (docs/specs/data-spec.md §3).

Runs in Private Research Mode on the researcher's machine (network access).
Public sources write to data/demo/observations/; licensed sources to
data/private/observations/. Wind is reached through the officially installed Wind
skill by cnmacro.wind (`refresh-private`), which writes the same contract.
"""
from __future__ import annotations

import csv
import email.utils
import io
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import yaml

from .store import OBS_COLUMNS

PUBLIC_SOURCES = {"NBS", "PBOC", "MOF", "GACC", "FRED", "SAFE"}
UA = {"User-Agent": "Mozilla/5.0 (research; cc-macro-analysis-os)"}
# FRED stalls (read timeout) on unrecognised User-Agents, including both a
# browser-like and a custom tool UA, but answers Python's default urllib UA
# in <1s (observed 2026-10-04). FRED requests therefore send no custom UA.
DEFAULT_UA: dict = {}


# retrieved_at must be true time. If the local clock is wrong (seen on the
# researcher's PC: 12h slow), sync_clock() measures the offset from a server's
# HTTP Date header and now_iso() applies it.
_CLOCK_OFFSET = timedelta(0)


def sync_clock(url: str = "https://data.stats.gov.cn/", tolerance_s: int = 120, timeout: int = 20) -> float:
    """Measure local clock error against an HTTP Date header; returns offset in seconds."""
    global _CLOCK_OFFSET
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA, method="HEAD"), timeout=timeout) as r:
            server = email.utils.parsedate_to_datetime(r.headers["Date"])
    except Exception:
        return 0.0  # no network reference; keep the local clock
    off = server - datetime.now(timezone.utc)
    if abs(off.total_seconds()) > tolerance_s:
        _CLOCK_OFFSET = off
        print(f"warning: local clock is off by {off.total_seconds() / 3600:+.2f} h; retrieved_at uses server time")
    return off.total_seconds()


def now_iso() -> str:
    return (datetime.now(timezone.utc) + _CLOCK_OFFSET).replace(microsecond=0).isoformat()


def load_calendar(path: str | Path = "data/dictionary/release_calendar.yaml") -> dict:
    """{(metric_id, period): (release_datetime, url)} from verified official calendar entries."""
    p = Path(path)
    if not p.exists():
        return {}
    out = {}
    for e in yaml.safe_load(p.read_text(encoding="utf-8")).get("releases", []):
        for mid in e["metrics"]:
            out[(mid, e["period"])] = (e["release"], e.get("url", ""))
    return out


def row(metric_id, period, value, source, source_code, source_class, *, retrieved_at, calendar,
        limitation_if_unknown) -> dict:
    rel = calendar.get((metric_id, period))
    return {
        "metric_id": metric_id, "reference_period": period, "value": value,
        "release_date": rel[0] if rel else "",  # keep the official time when the calendar has one
        "release_date_basis": "official_calendar" if rel else "unknown",
        "retrieved_at": retrieved_at, "source": source, "source_code": source_code,
        "source_class": source_class, "consensus": "", "quality_flag": "ok",
        "limitation": "" if rel else limitation_if_unknown,
    }


def append_rows(rows: list[dict], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OBS_COLUMNS)
        if new:
            w.writeheader()
        w.writerows(rows)
    return len(rows)


def _get(url: str, timeout: int = 60, retries: int = 3, headers: dict | None = None) -> bytes:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA if headers is None else headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as ex:  # network flakiness is common on these hosts
            last = ex
            time.sleep(2 ** i)
    raise RuntimeError(f"GET failed after {retries} tries: {url} ({last})")


# ---------------- FRED (public CSV, no key) ----------------
def fetch_fred(series_id: str, start: str = "2015-01-01", window_years: int = 4) -> list[tuple[str, float]]:
    """Fetch a FRED series in date windows (full-history requests time out)."""
    out = {}
    y0, y_end = int(start[:4]), date.today().year
    for y in range(y0, y_end + 1, window_years):
        cosd, coed = f"{y}-01-01", f"{min(y + window_years - 1, y_end)}-12-31"
        url = ("https://fred.stlouisfed.org/graph/fredgraph.csv?"
               + urllib.parse.urlencode({"id": series_id, "cosd": cosd, "coed": coed}))
        text = _get(url, headers=DEFAULT_UA).decode("utf-8")
        for r in csv.DictReader(io.StringIO(text)):
            d = r.get("observation_date") or r.get("DATE")
            v = r.get(series_id)
            if d and v not in (None, "", "."):
                out[d] = float(v)
    return sorted(out.items())


def fred_rows(metric, start: str, calendar: dict, got: str | None = None) -> list[dict]:
    if not metric.source_code:
        raise ValueError(f"{metric.metric_id}: no FRED source_code in dictionary")
    got = got or now_iso()
    rows = []
    for d, v in fetch_fred(metric.source_code, start):
        period = d[:7] if metric.frequency == "M" else d
        rows.append(row(metric.metric_id, period, v, "FRED", metric.source_code, "public",
                        retrieved_at=got, calendar=calendar,
                        limitation_if_unknown="FRED does not expose first-release dates; availability taken as retrieval time"))
    return rows


def ingest_fred(metric, out_dir: Path, start: str, calendar: dict) -> int:
    return append_rows(fred_rows(metric, start, calendar), out_dir / f"fred_{metric.metric_id}.csv")


# ---------------- NBS data portal (public) ----------------
# data.stats.gov.cn moved to a new portal in 2026 (/dg/website/). The old
# easyquery.htm endpoint now returns 403 (WAF "UrlACL") for every client.
# The new portal exposes JSON endpoints: an indicator tree, an indicator list per
# catalog, and a POST data query. Indicators are addressed by (catalog id,
# indicator id). NBS splits some series into base-period catalogs (CPI 2016-2020 /
# 2021-2025 / 2026-), so one metric can need several segments.
#
# Dictionary source_code: "nbs:<catalog_id>/<indicator_id>[@idx100]" with segments
# joined by "|". "@idx100" marks an index published as "same period last year =
# 100"; the ingester stores value - 100 so the unit is % YoY.
NBS2 = "https://data.stats.gov.cn/dg/website/publicrelease/web/external/"
NBS2_ROOTS = {"M": ("1", "fc982599aa684be7969d7b90b1bd0e84"), "Q": ("2", "a94b8b7365a94874968cabbe392cf679")}
NBS2_SUFFIX = {"M": "MM", "Q": "SS"}


def _nbs2_get(path: str) -> dict:
    return json.loads(_get(NBS2 + path).decode("utf-8"))["data"]


def nbs_tree(freq: str = "M", pid: str = "") -> list[dict]:
    """Children of a node in the NBS indicator tree (pid '' = root for that frequency)."""
    code, _ = NBS2_ROOTS[freq]
    return _nbs2_get(f"new/queryIndexTreeAsync?pid={pid}&code={code}")


def nbs_indicators(catalog_id: str) -> list[dict]:
    return _nbs2_get(f"new/queryIndicatorsByCid?cid={catalog_id}&dt=&name=")["list"]


def fetch_nbs(catalog_id: str, indicator_id: str, freq: str, start: str = "2019-01") -> list[tuple[str, float]]:
    """(period_code, value) for one indicator, national level, start..today.
    Period codes: 202608MM (month), 202603SS (Q3)."""
    sfx = NBS2_SUFFIX[freq]
    y0, today = int(start[:4]), date.today()
    if freq == "M":
        dts = f"{start[:4]}{start[5:7]}{sfx}-{today.year}{today.month:02d}{sfx}"
    else:
        dts = f"{y0}01{sfx}-{today.year}04{sfx}"
    body = {"cid": catalog_id, "indicatorIds": [indicator_id], "daCatalogId": "",
            "das": [{"text": "全国", "value": "000000000000"}], "showType": "1",
            "dts": [dts], "rootId": NBS2_ROOTS[freq][1]}
    last = None
    for i in range(3):
        try:
            req = urllib.request.Request(NBS2 + "stream/esData", data=json.dumps(body).encode("utf-8"),
                                         headers={**UA, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))["data"]
            break
        except Exception as ex:
            last = ex
            time.sleep(2 ** i)
    else:
        raise RuntimeError(f"NBS query failed: {catalog_id}/{indicator_id} ({last})")
    out = []
    for node in data:
        for v in node["values"]:
            if v.get("_id") == indicator_id and v.get("value") not in (None, ""):
                out.append((node["code"], float(v["value"])))
    return out


def nbs_period(code: str, freq: str) -> str:
    """202608MM -> 2026-08 ; 202603SS -> 2026Q3."""
    if freq == "M":
        return f"{code[:4]}-{code[4:6]}"
    return f"{code[:4]}Q{int(code[4:6])}"


def parse_nbs_code(source_code: str) -> list[tuple[str, str, bool]]:
    segs = []
    for seg in source_code.split("|"):
        seg = seg.strip()
        if not seg.startswith("nbs:"):
            raise ValueError(f"not an NBS portal code: {seg}")
        body, _, flag = seg[4:].partition("@")
        cid, iid = body.split("/")
        segs.append((cid, iid, flag == "idx100"))
    return segs


def ingest_nbs(metric, out_dir: Path, calendar: dict, start: str = "2019-01") -> int:
    return append_rows(nbs_rows(metric, calendar, start), out_dir / f"nbs_{metric.metric_id}.csv")


def nbs_rows(metric, calendar: dict, start: str = "2019-01", got: str | None = None) -> list[dict]:
    if not metric.source_code:
        raise ValueError(f"{metric.metric_id}: no NBS code in dictionary (discover with nbs-tree / nbs-indicators)")
    got = got or now_iso()
    vals: dict[str, float] = {}
    for cid, iid, idx100 in parse_nbs_code(metric.source_code):
        for code, v in fetch_nbs(cid, iid, metric.frequency, start):
            vals.setdefault(nbs_period(code, metric.frequency), round(v - 100, 6) if idx100 else v)
    # The portal also republishes other agencies' statistics (PBOC money supply, MOF
    # budget, customs trade). `source` stays the originating agency; the "nbs:" code
    # records the route.
    source = metric.source_primary
    via = "" if source == "NBS" else f"{source} statistic republished on the NBS data portal; "
    return [row(metric.metric_id, p, v, source, metric.source_code, "public", retrieved_at=got, calendar=calendar,
                limitation_if_unknown=f"{via}first-release date not recorded, availability taken as retrieval time")
            for p, v in sorted(vals.items())]


# ---------------- NBS press releases (www.stats.gov.cn, first print) ----------------
# The data portal above lags the 09:30 press release (on 2026-10-14 it still ended at August
# three hours after September CPI/PPI were published), so a refresh that reads only the portal
# finds nothing on release day. The press release carries the same numbers in a "主要数据"
# table: one row per series, columns 环比 / 同比 / 1-N月. This route reads that table, only for
# periods the store does not hold yet; the portal stays the route for history and revisions
# (when it catches up, an equal value is a no-op and a different one is kept as a vintage).
NBS_RELEASES = "https://www.stats.gov.cn/sj/zxfb/"
# release title keyword -> {metric_id: (table row label, column header keyword)}
NBS_RELEASE_TABLES = {
    "居民消费价格": {"cn_cpi_yoy": ("居民消费价格", "同比"),
                    "cn_core_cpi_yoy": ("不包括食品和能源", "同比")},
    "工业生产者出厂价格": {"cn_ppi_yoy": ("工业生产者出厂价格", "同比"),
                         "cn_ppi_mom": ("工业生产者出厂价格", "环比"),
                         "cn_ppi_producer_yoy": ("生产资料", "同比"),
                         "cn_ppi_consumer_yoy": ("生活资料", "同比")},
}
NBS_RELEASE_METRICS = {mid for spec in NBS_RELEASE_TABLES.values() for mid in spec}
_RELEASE_TITLE = re.compile(r"(\d{4})年(\d{1,2})月份?(" + "|".join(NBS_RELEASE_TABLES) + ")")


class _Cells(HTMLParser):
    """Text of every <td>/<th>, grouped by <tr>, in document order."""

    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th") and self.rows:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self.rows[-1].append("".join(self._cell))
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _label(s: str) -> str:
    """'其中：不包括食品和能源' / '一、工业生产者出厂价格' / '粮 食' -> bare label."""
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"^[一二三四五六七八九十]+、", "", s)
    return s.removeprefix("其中：").removeprefix("其中:")


def nbs_release_links(listing_html: str) -> list[tuple[str, str, str]]:
    """(period 'YYYY-MM', title keyword, absolute url) for CPI/PPI releases on a listing page."""
    out, seen = [], set()
    for href, title in re.findall(r"<a[^>]+href=\"([^\"]+)\"[^>]*title='([^']*)'", listing_html):
        m = _RELEASE_TITLE.search(title)
        url = urllib.parse.urljoin(NBS_RELEASES, href)
        if m and url not in seen:
            seen.add(url)
            out.append((f"{m.group(1)}-{int(m.group(2)):02d}", m.group(3), url))
    return out


def parse_nbs_release(page_html: str, keyword: str) -> tuple[dict[str, float], str | None]:
    """({metric_id: value}, release time 'YYYY-MM-DDTHH:MM:00+08:00' or None) from one release page.
    Raises if a mapped row or column is missing or ambiguous: a changed layout must fail loudly,
    never yield a wrong number."""
    p = _Cells()
    p.feed(page_html)
    heads = [i for i, r in enumerate(p.rows) if any("环比" in c for c in r) and any("同比" in c for c in r)]
    if not heads:
        raise ValueError(f"NBS release ({keyword}): no 环比/同比 table header")
    # the page carries the table more than once (desktop and mobile copies): read each, they must agree
    tables = []
    for h, end in zip(heads, heads[1:] + [len(p.rows)]):
        cols = [re.sub(r"\s+", "", c) for c in p.rows[h]]
        body = [r for r in p.rows[h + 1:end] if r]
        got = {}
        for mid, (label, col) in NBS_RELEASE_TABLES[keyword].items():
            # the year-to-date column is also labelled 同比 ("1-9月同比"); the monthly one is not prefixed
            ci = [i for i, c in enumerate(cols) if col in c and "月" not in c]
            hits = [r for r in body if _label(r[0]) == label]
            if len(ci) != 1 or len(hits) != 1 or len(hits[0]) != len(cols):
                raise ValueError(f"NBS release ({keyword}): cannot locate {mid} "
                                 f"(row '{label}' x{len(hits)}, column '{col}' x{len(ci)})")
            got[mid] = float(re.sub(r"\s+", "", hits[0][ci[0]]))
        tables.append(got)
    out = tables[0]
    if any(t != out for t in tables[1:]):
        raise ValueError(f"NBS release ({keyword}): the copies of the data table disagree: {tables}")
    t = re.search(r"(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2})", page_html)
    released = f"{t[1]}-{t[2]}-{t[3]}T{t[4]}:{t[5]}:00+08:00" if t else None
    return out, released


def nbs_release_rows(ms: list, held: dict, calendar: dict, got: str | None = None) -> list[dict]:
    """Rows for `ms` from the latest CPI/PPI press releases, only for periods newer than `held`
    ({metric_id: 'YYYY-MM' or None})."""
    got = got or now_iso()
    want = {m.metric_id: m for m in ms if m.metric_id in NBS_RELEASE_METRICS}
    if not want:
        return []
    links = nbs_release_links(_get(NBS_RELEASES).decode("utf-8"))
    if not links:  # the listing always shows the latest CPI/PPI releases; none found means the markup changed
        raise ValueError(f"no CPI/PPI release link recognised on {NBS_RELEASES}")
    rows = []
    for period, keyword, url in links:
        targets = [mid for mid in NBS_RELEASE_TABLES[keyword]
                   if mid in want and (not held.get(mid) or period > held[mid][:7])]
        if not targets:
            continue
        values, released = parse_nbs_release(_get(url).decode("utf-8"), keyword)
        for mid in targets:
            r = row(mid, period, values[mid], "NBS", url, "public", retrieved_at=got, calendar=calendar,
                    limitation_if_unknown="")
            if r["release_date_basis"] == "unknown" and released:
                r.update(release_date=released, release_date_basis="source_field")
            r["limitation"] = "; ".join(x for x in (
                "first print read from the NBS press release table (the data portal had not published this period yet)",
                r["limitation"] or ("" if released else "release time not found on the page")) if x)
            rows.append(r)
    return rows


def with_nbs_release(base, log=print):
    """Combine NBS CPI/PPI and GDP/activity first prints with the historical portal.

    Independent routes are fail-isolated. Press-release schema failures are
    surfaced in logs and freshness monitoring, not silently called current.
    """
    from .firstprint import ACTIVITY_METRICS, activity_release_rows

    def fetch(route_name, ms, held, metrics, calendar, got):
        selected = {m.metric_id for m in ms}
        if route_name != "nbs" or not (NBS_RELEASE_METRICS | ACTIVITY_METRICS) & selected:
            return base(route_name, ms, held, metrics, calendar, got)

        price, activity, portal = [], [], {}
        if selected & NBS_RELEASE_METRICS:
            try:
                price = nbs_release_rows(ms, held, calendar, got)
                log(f"source nbs (press release): {len(price)} row(s)")
            except Exception as ex:
                log(f"source nbs (press release): FAILED ({type(ex).__name__}: {ex})"[:350])
        if selected & ACTIVITY_METRICS:
            try:
                activity = activity_release_rows(ms, held, calendar, got)
                log(f"source nbs (GDP/activity first print): {len(activity)} row(s)")
            except Exception as ex:
                log(f"source nbs (GDP/activity first print): FAILED ({type(ex).__name__}: {ex})"[:350])
        try:
            portal = base(route_name, ms, held, metrics, calendar, got)
        except Exception as ex:
            if not (price or activity):
                raise
            log(f"source nbs (data portal): FAILED ({type(ex).__name__}: {ex}); keeping first prints"[:350])
        if price:
            portal["nbs_release.csv"] = price
        if activity:
            portal["nbs_activity_release.csv"] = activity
        return portal
    return fetch


# ---------------- NBS release agenda (official calendar) ----------------
# queryAgendas returns NBS's published release schedule (fb_time per release)
# from 2018 onward. Release names map to metrics and to the reference period
# they carry. Entries with names that map to nothing (including test entries
# such as "测试") are ignored.
AGENDA_URL = NBS2 + "queryAgendas"
AGENDA_MAP = [  # (name prefix after removing the time suffix, metrics, period rule)
    ("居民消费价格指数月度报告", ["cn_cpi_yoy", "cn_core_cpi_yoy"], "prev_month"),
    ("工业生产者价格指数月度报告", ["cn_ppi_yoy", "cn_ppi_mom", "cn_ppi_producer_yoy", "cn_ppi_consumer_yoy"], "prev_month"),
    ("采购经理指数月度报告", ["cn_pmi_output_price", "cn_pmi_new_orders", "cn_pmi_new_export_orders", "cn_pmi_mfg", "cn_pmi_nonmfg", "cn_pmi_services", "cn_pmi_construction", "cn_pmi_composite"], "pmi"),
    ("中国采购经理指数月度报告", ["cn_pmi_output_price", "cn_pmi_new_orders", "cn_pmi_new_export_orders", "cn_pmi_mfg", "cn_pmi_nonmfg", "cn_pmi_services", "cn_pmi_construction", "cn_pmi_composite"], "pmi"),
    ("规模以上工业生产月度报告", ["cn_ip_yoy"], "prev_month"),
    ("社会消费品零售总额月度报告", ["cn_retail_sales_yoy"], "prev_month"),
    ("房地产开发和销售情况月度报告", ["cn_property_sales_area_ytd_yoy"], "prev_month"),
    ("工业经济效益月度报告", ["cn_ind_profit_ytd_yoy"], "profit"),
    ("国民经济运行情况", ["cn_ngdp_q", "cn_rgdp_yoy"], "prev_quarter"),  # also "...新闻发布会"
]


# China release kinds shown on the public calendar: (kind, title keywords, short zh, short en,
# reference-period rule for NBS agenda titles, metrics displayed with the release).
# Display metrics never feed the refresh scheduler; that stays on AGENDA_MAP and `metrics`.
RELEASE_KINDS = [
    ("cpi", ("居民消费价格", "CPI"), "CPI", "CPI", "prev_month", ["cn_cpi_yoy", "cn_core_cpi_yoy"]),
    ("ppi", ("工业生产者价格", "PPI"), "PPI", "PPI", "prev_month", ["cn_ppi_yoy", "cn_ppi_mom"]),
    ("pmi", ("采购经理", "PMI"), "PMI", "PMI", "pmi", ["cn_pmi_mfg", "cn_pmi_nonmfg", "cn_pmi_new_orders"]),
    ("gdp", ("GDP",), "GDP", "GDP", "prev_quarter", ["cn_rgdp_yoy"]),
    ("economy", ("国民经济运行", "national economic performance", "activity"), "国民经济运行",
     "Economic activity", "prev_month", ["cn_unemployment"]),
    ("ip", ("规模以上工业生产", "industrial production"), "工业生产", "Industrial output", "prev_month", ["cn_ip_yoy"]),
    ("retail", ("社会消费品零售", "retail sales"), "社零", "Retail sales", "prev_month", ["cn_retail_sales_yoy"]),
    ("fai", ("固定资产投资", "fixed-asset investment"), "固定资产投资", "Fixed-asset investment", "prev_month", []),
    ("property", ("房地产开发", "property development"), "房地产", "Property", "prev_month",
     ["cn_property_sales_area_ytd_yoy"]),
    ("homes", ("商品住宅销售价格", "home prices"), "70城房价", "Home prices", "prev_month", []),
    ("energy", ("能源生产", "energy production"), "能源生产", "Energy output", "prev_month", []),
    ("profits", ("工业经济效益", "industrial profits"), "工业利润", "Industrial profits", "profit",
     ["cn_ind_profit_ytd_yoy"]),
    ("income", ("居民收支", "household income"), "居民收支", "Household income", "prev_quarter", []),
    ("capacity", ("产能利用率", "capacity utilization"), "产能利用率", "Capacity utilization", "prev_quarter", []),
    ("industry_va", ("主要行业增加值", "value added by industry"), "分行业增加值", "Value added by industry",
     "prev_quarter", []),
    ("pboc", ("金融统计数据", "financial statistics"), "金融统计", "Money & credit", None,
     ["cn_m2_yoy", "cn_m1_yoy", "cn_tsf_stock_yoy"]),
    ("gacc_flash", ("进出口", "trade (preliminary)"), "进出口初值", "Trade (preliminary)", None,
     ["cn_exports_usd_yoy", "cn_imports_usd_yoy"]),
    ("gacc_bulletin", ("海关统计月报", "customs monthly bulletin"), "海关统计月报", "Customs bulletin", None,
     ["cn_exports_us_ytd_yoy"]),
    ("mof", ("财政收支", "fiscal"), "财政收支", "Fiscal revenue & spending", None, ["cn_budget_rev_ytd_yoy", "cn_budget_exp_ytd_yoy"]),
]
KIND = {k[0]: k for k in RELEASE_KINDS}
NBS_SCHEDULE_URL = "https://www.stats.gov.cn/sj/fbrc/"


def release_kinds(title: str) -> list[str]:
    """Kinds named in a calendar or official title, in table order ('CPI and PPI' -> ['cpi', 'ppi'])."""
    low = title.lower()
    return [k for k, words, *_ in RELEASE_KINDS if any(w.lower() in low for w in words)]


def nbs_agenda(start: str, end: str) -> list[tuple[str, str]]:
    """[(fb_time 'YYYY-MM-DD HH:MM:SS', release name)] between start and end (YYYY-MM-DD), deduplicated."""
    q = urllib.parse.urlencode({"startDate": start.replace("-", "/") + " 00:00:00",
                                "endDate": end.replace("-", "/") + " 23:59:59"})
    data = json.loads(_get(AGENDA_URL + "?" + q).decode("utf-8"))["data"] or {}
    out = set()
    for items in data.values():
        for x in items:
            name = re.sub(r"[（(]\s*\d{1,2}:\d{2}\s*[)）]", "", x["content"]).strip()
            out.add((x["fb_time"], name))
    return sorted(out)


def _agenda_period(fb_time: str, rule: str) -> str | None:
    y, m, d = int(fb_time[:4]), int(fb_time[5:7]), int(fb_time[8:10])
    if rule == "pmi" and d >= 20:      # PMI is released on the last day of its own month
        return f"{y}-{m:02d}"
    if rule == "profit" and m == 2:    # Jan is never published alone; a February release
        return f"{y - 1}-12"            # carries December (e.g. 2020-02-03, delayed)
    if rule in ("prev_month", "pmi", "profit"):  # ...or early next month when a holiday intervenes
        return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
    if rule == "prev_quarter":
        if m not in (1, 4, 7, 10):
            return None                 # monthly activity briefings carry no GDP
        return f"{y - 1}Q4" if m == 1 else f"{y}Q{(m - 1) // 3}"
    return None


def agenda_calendar(start: str, end: str) -> tuple[dict, list[str]]:
    """{(metric_id, period): (release ISO datetime +08:00, url)} plus a list of conflicts skipped."""
    found: dict[tuple[str, str], set[str]] = {}
    for fb, name in nbs_agenda(start, end):
        for prefix, metrics, rule in AGENDA_MAP:
            if name.startswith(prefix):
                period = _agenda_period(fb, rule)
                if period:
                    for mid in metrics:
                        found.setdefault((mid, period), set()).add(fb)
                break
    cal, conflicts = {}, []
    for key, times in found.items():
        # Duplicate entries on the same day (e.g. 00:00 and 09:30 in 2023) agree on the
        # release date; keep the first real time. Different days are a genuine conflict.
        if len({t[:10] for t in times}) == 1:
            real = sorted(t for t in times if not t.endswith("00:00:00")) or sorted(times)
            cal[key] = (real[0].replace(" ", "T") + "+08:00", AGENDA_URL)
        else:
            conflicts.append(f"{key[0]}@{key[1]}: {sorted(times)}")
    return cal, sorted(conflicts)


# ---------------- Inbox CSV (manual / Wind MCP exports) ----------------
def ingest_inbox(src: Path, metrics: dict, calendar: dict) -> tuple[int, int]:
    """Normalise a one-time export (metric_id, reference_period, value, release_date, source, source_code
    [, limitation, quality_flag]).

    Rows from public sources go to data/demo/observations; everything else (Wind, manual
    without a public source) to data/private/observations. Returns (public_rows, private_rows).
    """
    pub, priv = inbox_rows(src, metrics, calendar)
    stem = src.stem
    if pub:
        append_rows(pub, Path("data/demo/observations") / f"inbox_{stem}.csv")
    if priv:
        append_rows(priv, Path("data/private/observations") / f"inbox_{stem}.csv")
    return len(pub), len(priv)


def inbox_rows(src: Path, metrics: dict, calendar: dict, got: str | None = None) -> tuple[list[dict], list[dict]]:
    """(public rows, private rows) from an inbox-format CSV."""
    got = got or now_iso()
    pub, priv = [], []
    with src.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            mid = r["metric_id"].strip()
            if mid not in metrics:
                raise ValueError(f"{src.name}: unknown metric_id {mid}")
            source = r.get("source", "").strip() or "manual"
            cls = "public" if source in PUBLIC_SOURCES else "private"
            rel = r.get("release_date", "").strip()
            out = row(mid, r["reference_period"].strip(), float(r["value"]), source,
                      r.get("source_code", "").strip(), cls, retrieved_at=got, calendar=calendar,
                      limitation_if_unknown=f"imported from {src.name}; first-release date not provided")
            if rel:
                out.update(release_date=rel, release_date_basis="source_field", limitation="")
            # optional columns: a derivation note and a quality flag from the exporter
            note = (r.get("limitation") or "").strip()
            if note:
                out["limitation"] = "; ".join(x for x in (note, out["limitation"]) if x)
            if (r.get("quality_flag") or "").strip():
                out["quality_flag"] = r["quality_flag"].strip()
            (pub if cls == "public" else priv).append(out)
    return pub, priv
