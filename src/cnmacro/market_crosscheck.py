"""Cross-checks of the Tushare market series against public official pages.

  * ChinaBond 10Y (and 1Y) government yield: the "国债及其他债券收益率曲线" page of the China Central
    Depository & Clearing Co. (yield.chinabond.com.cn). Tushare yc_cb carries the same curve, so the
    tolerance is tight.
  * CFETS USD/CNY central parity (chinamoney.com.cn). The parity is a morning reference rate and the
    stored Tushare series is the FXCM offshore close, so the two are different quantities by design:
    the tolerance is wide enough for the normal spot-to-fixing distance and a gap beyond it is a
    reported signal, never an overwrite.

A gap beyond tolerance is returned as status "gap" and surfaced in the run log and summary. Nothing
here writes into the observation store. If the Tushare value for the official date is not stored yet
(yc_cb updates at 20:00 Beijing time) the result is "pending", not a failure.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import date, timedelta

CHINABOND_URL = "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/more?locale=cn_ZH"
CFETS_URL = ("https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew"
             "?startDate={start}&endDate={end}&currency=USD/CNY&pageNum=1&pageSize=15")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129 Safari/537.36"}

# metric -> (official source, tolerance, unit of tolerance)
CHECKS = {
    "mk_cn_gov_10y": {"official": "ChinaBond", "tolerance": 0.01, "mode": "abs", "term": 10,
                   "label": "ChinaBond 10Y treasury curve"},
    "mk_cn_gov_1y": {"official": "ChinaBond", "tolerance": 0.01, "mode": "abs", "term": 1,
                  "label": "ChinaBond 1Y treasury curve"},
    "mk_usdcnh": {"official": "CFETS", "tolerance": 0.005, "mode": "rel",
                  "label": "CFETS USD/CNY central parity (reference rate, not a close)"},
}


def get(url: str, timeout: int = 40) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read(2_000_000)


def parse_chinabond(page: str) -> tuple[str, dict[int, float]]:
    """(curve date, {term in years: yield %}) from the first treasury-curve row of the page."""
    table = re.search(r'id="gjqxData".*?</table>', page, re.S)
    if not table:
        raise ValueError("ChinaBond page: curve table not found")
    html = re.sub(r"<!--.*?-->", "", table.group(0), flags=re.S)
    head = re.search(r"<th[^>]*>\s*(\d{4}-\d{2}-\d{2})", html)
    terms = [m for m in re.findall(r"<th[^>]*>\s*(\d+)\s*(年|月)", html)]
    rows = [re.findall(r"<td[^>]*>(.*?)</td>", r, re.S) for r in re.findall(r"<tr>(.*?)</tr>", html, re.S)[1:]]
    if not head or not terms or not rows:
        raise ValueError("ChinaBond page: unexpected table shape")
    label, *cells = rows[0]
    if "国债" not in label or "收益率" not in label:
        raise ValueError(f"ChinaBond page: first row is not the treasury curve ({label.strip()!r})")
    out = {}
    for (n, unit), cell in zip(terms, cells):
        text = cell.strip()
        if unit == "年" and text:
            out[int(n)] = float(text)
    return head.group(1), out


def parse_cfets(body: str) -> dict[str, float]:
    """{date: USD/CNY central parity} from the CcprHisNew JSON."""
    doc = json.loads(body)
    head = doc["data"]["head"]
    if "USD/CNY" not in head:
        raise ValueError("CFETS response: USD/CNY column missing")
    i = head.index("USD/CNY")
    # `values` holds only the requested currency when one is given; fall back to the column index otherwise
    return {r["date"]: float(r["values"][0 if len(r["values"]) == 1 else i]) for r in doc["records"] if r["values"]}


def compare(metric_id: str, official_date: str, official_value: float, stored: dict[str, float]) -> dict:
    cfg = CHECKS[metric_id]
    result = {"metric_id": metric_id, "official_source": cfg["official"], "label": cfg["label"],
              "date": official_date, "official_value": official_value, "tolerance": cfg["tolerance"],
              "tolerance_mode": cfg["mode"]}
    mine = stored.get(official_date)
    if mine is None:
        return {**result, "status": "pending", "tushare_value": None, "difference": None,
                "note": "Tushare value for the official date is not stored yet; not a failure"}
    diff = mine - official_value
    gap = abs(diff) / official_value if cfg["mode"] == "rel" else abs(diff)
    return {**result, "status": "ok" if gap <= cfg["tolerance"] else "gap", "tushare_value": mine,
            "difference": round(diff, 6), "gap_measure": round(gap, 6)}


def run_crosschecks(stored: dict[str, dict[str, float]], *, fetch=get, today: date | None = None, log=print) -> list[dict]:
    """Run both cross-checks against the stored series ({metric_id: {date: value}}); never raises."""
    today = today or date.today()
    results: list[dict] = []
    try:
        curve_date, curve = parse_chinabond(fetch(CHINABOND_URL).decode("utf-8"))
        for mid, cfg in CHECKS.items():
            if cfg["official"] == "ChinaBond" and cfg["term"] in curve:
                results.append(compare(mid, curve_date, curve[cfg["term"]], stored.get(mid, {})))
    except Exception as exc:  # noqa: BLE001 - an unreachable page is reported, never fatal
        for mid, cfg in CHECKS.items():
            if cfg["official"] == "ChinaBond":
                results.append({"metric_id": mid, "official_source": "ChinaBond", "label": cfg["label"],
                                "status": "unavailable", "note": f"{type(exc).__name__}: {exc}"[:200]})
    try:
        url = CFETS_URL.format(start=(today - timedelta(days=14)).isoformat(), end=today.isoformat())
        parity = parse_cfets(fetch(url).decode("utf-8"))
        latest = max(parity)
        results.append(compare("mk_usdcnh", latest, parity[latest], stored.get("mk_usdcnh", {})))
    except Exception as exc:  # noqa: BLE001
        results.append({"metric_id": "mk_usdcnh", "official_source": "CFETS", "label": CHECKS["mk_usdcnh"]["label"],
                        "status": "unavailable", "note": f"{type(exc).__name__}: {exc}"[:200]})
    for r in results:
        if r["status"] == "gap":
            log(f"::warning title=market cross-check gap::{r['metric_id']} {r['date']}: Tushare {r['tushare_value']} vs "
                f"{r['official_source']} {r['official_value']} (gap {r['gap_measure']} > {r['tolerance']}); nothing overwritten")
        elif r["status"] == "unavailable":
            log(f"::warning title=market cross-check unavailable::{r['metric_id']}: {r.get('note')}")
        else:
            log(f"cross-check {r['metric_id']} {r.get('date')}: {r['status']}")
    return results
