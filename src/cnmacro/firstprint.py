"""Read official NBS first-print GDP and activity tables, before the history portal updates.

Only exact indicator labels and officially calendared release periods are accepted.
No article URLs or reported numeric values are hardcoded into production code.
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import datetime
from html.parser import HTMLParser

ACTIVITY_METRICS = frozenset({
    "cn_ngdp_q", "cn_rgdp_yoy", "cn_ip_yoy",
    "cn_retail_sales_yoy", "cn_property_sales_area_ytd_yoy",
})
LISTINGS = ("https://www.stats.gov.cn/sj/zxfb/",
            "https://www.stats.gov.cn/sj/zxfbhjd/")
LABELS = {
    "cn_ngdp_q": {"国内生产总值（亿元）"},
    "cn_rgdp_yoy": {"国内生产总值（亿元）"},
    "cn_ip_yoy": {"规模以上工业增加值"},
    "cn_retail_sales_yoy": {"社会消费品零售总额", "社会消费品零售总额（亿元）"},
    "cn_property_sales_area_ytd_yoy": {"新建商品房销售面积（万平方米）"},
}
# Five-column NBS release table: label, period value, period YoY, YTD value, YTD YoY
COLUMN = {"cn_ngdp_q": 1, "cn_rgdp_yoy": 2, "cn_ip_yoy": 2,
          "cn_retail_sales_yoy": 2, "cn_property_sales_area_ytd_yoy": 4}


def _compact(s):
    return re.sub(r"\s+", "", s).replace(",", "").replace("−", "-").replace("﹣", "-")


class _Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []
        self.href = None
        self.title = ""
        self.visible = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            d = dict(attrs)
            self.href = d.get("href")
            self.title = d.get("title") or ""
            self.visible = []

    def handle_data(self, data):
        if self.href is not None:
            self.visible.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            self.items.append((self.href, self.title or "".join(self.visible)))
            self.href = None


def release_links(index_url: str, html: str, day: str) -> list[str]:
    """Find same-day NBS articles in either official index, most relevant first."""
    p = _Anchors()
    p.feed(html)
    primary, secondary, seen = [], [], set()
    pattern = r"/sj/(?:zxfb|zxfbhjd)/20\d{4}/t" + day.replace("-", "") + r"_\d+\.html$"
    for href, title in p.items:
        url = urllib.parse.urljoin(index_url, href)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "www.stats.gov.cn" or not re.search(pattern, parsed.path):
            continue
        if url in seen:
            continue
        seen.add(url)
        if "经济运行" in title and any(x in title for x in ("季度", "半年", "全年", "月份")):
            primary.append(url)
        elif any(x in title for x in ("工业增加值", "社会消费品零售总额", "房地产市场基本情况")):
            secondary.append(url)
    return primary + secondary


def _number(text: str, quarter=False) -> float:
    s = _compact(text)
    if quarter:
        match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)(?:[（(](?:第?[一二三四1234]|Q[1-4])季度[）)])?", s)
        if not match:
            raise ValueError(f"not a single-quarter GDP cell: {s!r}")
        return float(match[1])
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", s):
        raise ValueError(f"invalid NBS table numeric cell: {s!r}")
    return float(s)


def parse_activity_table(page: str) -> dict[str, float]:
    """Exact labelled rows, explicit monthly vs YTD columns, duplicate-value check."""
    from . import ingest

    parser = ingest._Cells()
    parser.feed(page)
    values = {}
    for cells in parser.rows:
        if not cells:
            continue
        label = ingest._label(cells[0])
        for mid, names in LABELS.items():
            if label not in names:
                continue
            col = COLUMN[mid]
            if len(cells) <= col:
                # Dedicated property table: label, cumulative area, cumulative YoY.
                if mid == "cn_property_sales_area_ytd_yoy" and len(cells) == 3:
                    col = 2
                else:
                    continue
            number = _number(cells[col], quarter=mid in ("cn_ngdp_q", "cn_rgdp_yoy"))
            if mid in values and abs(values[mid] - number) > 1e-6:
                raise ValueError(f"contradictory duplicate official NBS values for {mid}")
            values[mid] = number
    return values


def activity_release_rows(ms: list, held: dict, calendar: dict, got: str) -> list[dict]:
    """Collect only missing officially-released periods, preserving source URL."""
    from . import ingest

    now = datetime.fromisoformat(got.replace("Z", "+00:00"))
    wanted = {}
    for m in ms:
        mid = m.metric_id
        if mid not in ACTIVITY_METRICS:
            continue
        eligible = sorted(
            (period, published[:10]) for (key, period), (published, _) in calendar.items()
            if key == mid and datetime.fromisoformat(published.replace("Z", "+00:00")) <= now
            and (not held.get(mid) or period > held[mid])
        )
        if eligible:
            wanted[mid] = eligible[-1]
    if not wanted:
        return []

    rows = []
    for day in sorted({d for _, d in wanted.values()}, reverse=True):
        urls = []
        for listing in LISTINGS:
            urls += release_links(listing, ingest._get(listing).decode("utf-8"), day)
        urls = list(dict.fromkeys(urls))
        if not urls:
            raise ValueError(f"NBS official activity release articles unavailable for {day}")
        values = {}
        for url in urls:
            extracted = parse_activity_table(ingest._get(url).decode("utf-8"))
            for mid, number in extracted.items():
                if mid in values and abs(values[mid][0] - number) > 1e-6:
                    raise ValueError(f"NBS same-day articles disagree for {mid} on {day}")
                values[mid] = (number, url)
        for mid, (period, expected_day) in wanted.items():
            if day != expected_day or mid not in values:
                continue
            value, url = values[mid]
            observation = ingest.row(mid, period, value, "NBS", url, "public",
                                     retrieved_at=got, calendar=calendar,
                                     limitation_if_unknown="first print time unverified")
            observation["limitation"] = "NBS official first print; portal revision may follow"
            rows.append(observation)
    return rows



def official_release_freshness(due: dict, obs, calendar: dict,
                               now, grace_minutes: int = 90) -> dict:
    """Operational monitoring only; no research engine or thesis-state mutation.

    Alert only on calendar-verified due periods. Estimated provider lags are
    not official deadlines and must never trigger a false stale alert.
    """
    from .store import utc_naive

    missing = []
    for mid, info in sorted(due.items()):
        period = info.get("expected")
        if not period or (mid, period) not in calendar:
            continue
        released_at, _ = calendar[(mid, period)]
        release_time = utc_naive(released_at)
        if release_time > now:
            continue
        if not obs[(obs.metric_id == mid) & (obs.reference_period == period)].empty:
            continue
        age = int((now - release_time).total_seconds() / 60)
        missing.append({"metric_id": mid, "expected_period": period,
                        "release_at": released_at, "age_minutes": age,
                        "overdue": age >= grace_minutes})
    state = ("SOURCE_STALE" if any(x["overdue"] for x in missing)
             else "RELEASE_PENDING_INGEST" if missing else "CURRENT")
    return {"status": state, "missing": missing, "grace_minutes": grace_minutes}
