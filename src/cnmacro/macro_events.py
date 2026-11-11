"""China macro occurrences from the news and policy intake already collected (news_feed / news_rank groups,
the official event store). Deterministic: no model call, no new source, no crawler.

Each occurrence is something that happened, with its source and first publication time:
  - `figures`: numbers *as reported* in the text (indicator, value, unit, basis, period, exact span). A media
    figure stays a reported figure; it never becomes or replaces an Observation.
  - `action`: a policy action (issuer, action, amount / rate, effective date, exact span).
Official confirmation is not required to show an attributed report; it only raises confidence.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from .events.grouping import triage as rule_triage
from .events.store import BEIJING, load_grouped_public_items, stamp
from .news_feed import CHINA, FOREIGN, classify

# (key, indicator pattern, short zh, short en, {basis: metric_id}); more specific patterns first.
INDICATORS = [
    ("core_cpi", r"核心CPI", "核心CPI", "Core CPI", {"yoy": "cn_core_cpi_yoy", "mom": "cn_core_cpi_mom"}),
    ("cpi", r"CPI|居民消费价格(?:指数)?", "CPI", "CPI", {"yoy": "cn_cpi_yoy", "mom": "cn_cpi_mom"}),
    ("ppi_in", r"工业生产者购进价格", "PPI购进", "PPI input", {}),
    ("ppi", r"PPI|工业生产者出厂价格(?:指数)?", "PPI", "PPI", {"yoy": "cn_ppi_yoy", "mom": "cn_ppi_mom"}),
    ("pmi_nonmfg", r"非制造业商务活动指数", "非制造业PMI", "Non-mfg PMI", {"level": "cn_pmi_nonmfg"}),
    ("pmi", r"制造业(?:PMI|采购经理指数(?:（PMI）)?)", "制造业PMI", "Mfg PMI", {"level": "cn_pmi_mfg"}),
    ("trade", r"进出口(?:总值|总额)?", "进出口", "Total trade", {}),
    ("exports", r"出口(?:总值|额)?", "出口", "Exports", {"yoy:USD": "cn_exports_usd_yoy"}),
    ("imports", r"进口(?:总值|额)?", "进口", "Imports", {"yoy:USD": "cn_imports_usd_yoy"}),
    ("m2", r"广义货币\(M2\)|广义货币（M2）|M2", "M2", "M2", {"yoy": "cn_m2_yoy"}),
    ("m1", r"狭义货币\(M1\)|狭义货币（M1）|M1", "M1", "M1", {"yoy": "cn_m1_yoy"}),
    ("tsf", r"社会融资规模存量|社融存量", "社融存量", "TSF stock", {"yoy": "cn_tsf_stock_yoy"}),
    ("loans", r"人民币贷款余额", "贷款余额", "RMB loans", {}),
    ("retail", r"社会消费品零售总额|社零", "社零", "Retail sales", {"yoy": "cn_retail_sales_yoy"}),
    ("ip", r"规模以上工业增加值", "工业增加值", "Industrial output", {"yoy": "cn_ip_yoy"}),
    ("fai", r"固定资产投资(?:（不含农户）)?", "固定资产投资", "Fixed-asset investment", {}),
    ("property_inv", r"房地产开发投资", "房地产投资", "Property investment", {}),
    ("profits", r"规模以上工业企业(?:实现)?利润(?:总额)?|工业企业利润", "工业利润", "Industrial profits",
     {"ytd": "cn_ind_profit_ytd_yoy"}),
    ("gdp", r"国内生产总值|GDP", "GDP", "GDP", {"yoy": "cn_rgdp_yoy"}),
    ("unemployment", r"城镇调查失业率", "失业率", "Jobless rate", {"level": "cn_unemployment"}),
    ("revenue", r"一般公共预算收入", "财政收入", "Budget revenue", {"ytd": "cn_budget_rev_ytd_yoy"}),
    ("spending", r"一般公共预算支出", "财政支出", "Budget spending", {"ytd": "cn_budget_exp_ytd_yoy"}),
]
IND = {k[0]: k for k in INDICATORS}
IND_RX = re.compile("|".join(f"(?P<{k}>{rx})" for k, rx, *_ in INDICATORS))
LEVEL = {"pmi", "pmi_nonmfg", "unemployment"}
TRADE = {"trade", "exports", "imports"}
NUMBER = re.compile(r"(?P<verb>增长|上涨|上升|下降|下跌|回落|持平|增|涨|降|跌|为)?\s*(?P<v>-?\d+(?:\.\d+)?)\s*%"
                    r"(?:[，,]?\s*前值\s*(?P<prev>-?\d+(?:\.\d+)?)\s*%)?")
NEGATIVE = ("下降", "下跌", "回落", "降", "跌")
OUTSIDE = re.compile(r"美国|美联储|美股|日本|欧元区|欧洲|英国|德国|法国|墨西哥|巴西|韩国|印度|俄罗斯|加拿大|澳大利亚|拉美"
                     r"|自治区|省|海南|西藏|香港|台湾|离岛|乘联|商会|协会|研究院|上海|北京市|深圳|广州|重庆|天津|杭州")
MONTH = re.compile(r"(?:(?P<y>20\d\d)年)?(?:(?P<ytd>1[—–-]|前)(?P<n>\d{1,2})个?月|(?P<q>前三季度|上半年|一季度)|(?P<m>\d{1,2})月份?)")

ISSUERS = [("PBOC", r"中国人民银行|人民银行|央行", "人民银行", "PBoC"),
           ("TARIFF", r"国务院关税税则委员会|关税税则委员会", "关税税则委员会", "Tariff Commission"),
           ("STATE", r"国务院(?:常务会议)?|中共中央|中央政治局", "国务院", "State Council"),
           ("MOF", r"财政部", "财政部", "MOF"), ("NDRC", r"国家发展改革委|国家发改委|发展改革委", "发改委", "NDRC"),
           ("MOFCOM", r"商务部", "商务部", "MOFCOM"), ("NFRA", r"金融监管总局|国家金融监督管理总局", "金融监管总局", "NFRA"),
           ("CSRC", r"证监会", "证监会", "CSRC"), ("SAFE", r"国家外汇管理局|外汇局", "外汇局", "SAFE")]
ACTIONS = [
    ("rrr_cut", r"下调.{0,12}存款准备金率|降准", "下调准备金率", "RRR cut"),
    ("rrr_hike", r"上调.{0,12}存款准备金率", "上调准备金率", "Reserve ratio raised"),
    ("rate_cut", r"下调.{0,15}(?:利率|LPR)|降息", "下调利率", "Rate cut"),
    ("rate_hike", r"上调.{0,15}利率", "上调利率", "Rate raised"),
    ("liquidity", r"(?:开展|进行|实施).{0,20}(?:逆回购|MLF|中期借贷便利|国债买卖)", "公开市场操作", "Liquidity operation"),
    ("tariff", r"(?:暂停实施|继续暂停|加征|调整|下调|上调|取消).{0,16}关税", "关税措施", "Tariff measure"),
    ("facility", r"(?:设立|实施|加力实施|增加).{0,16}(?:再贷款|工具|便利)", "结构性工具", "Lending facility"),
    ("bond", r"发行.{0,20}(?:国债|特别国债|专项债|地方政府债|主权债券)", "发行债券", "Bond issuance"),
    ("document", r"印发|出台|发布.{0,12}(?:通知|意见|办法|方案|规定|公告)", "政策文件", "Policy document"),
    ("meeting", r"国务院常务会议|政治局会议|中央经济工作会议|中央财经委员会", "重要会议", "Policy meeting"),
]
AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(万亿元|亿元|亿美元)")
RATE = re.compile(r"(\d+(?:\.\d+)?)\s*(个百分点|基点|%)")
EFFECTIVE = re.compile(r"自(?:(20\d\d)年)?(\d{1,2})月(\d{1,2})日起")
# a stated intention or possibility is a policy signal, not an announced action
INTENT = re.compile(r"将|拟|计划|考虑|可能|有望|预计|适时|择机|空间|运用|是否|或将|预期|呼吁|建议|若|如果|继续实施好|研究")
DECIDED = re.compile(r"决定|宣布|批准|自(?:20\d\d年)?\d{1,2}月\d{1,2}日起|即日起|发布公告|印发|出台")
# a scheduled issuance ('财政部将于11月16日当周发行') is announced, not intended
SCHEDULED = re.compile(r"将于(?:20\d\d年)?\d{1,2}月\d{1,2}日")
# a Chinese issuer's bond sold in Hong Kong or abroad is still a China policy action; the venue is not the issuer
VENUE = re.compile(r"(?:财政部|人民银行|央行).{0,24}(?:在|于).{0,12}发行")
ROUNDUP = re.compile(r"要闻|早餐|汇总|晚报|早报|盘前|收评|午评|一周|周报|看点")
OFFICIAL_HOST = re.compile(r"(^|\.)gov\.cn$")
SENTENCE = re.compile(r"[^。；;!?！？\n]+")


def _period(match, published) -> tuple[str | None, bool]:
    """(YYYY-MM, year-to-date?) of a period phrase, the year taken from the text or the publication date."""
    at = stamp(published).astimezone(BEIJING)
    if match.group("q"):
        month, ytd = {"一季度": 3, "上半年": 6, "前三季度": 9}[match.group("q")], True
    else:
        month, ytd = int(match.group("n") or match.group("m")), bool(match.group("ytd"))
    if not 1 <= month <= 12:
        return None, False
    year = int(match.group("y")) if match.group("y") else at.year - (month > at.month)
    return f"{year}-{month:02d}", ytd


def extract_figures(text: str, published_at: str) -> list[dict]:
    """China macro figures as written: one per indicator mention with a percentage after it."""
    if not text or not published_at:
        return []
    out, period, ytd = [], None, False
    same_basis = bool(re.search(r"同比[（(]下同[)）]|均为同比", text))
    for sent in SENTENCE.findall(text):
        if OUTSIDE.search(sent):
            continue
        marks = list(MONTH.finditer(sent))
        hits = list(IND_RX.finditer(sent))
        for i, hit in enumerate(hits):
            key = hit.lastgroup
            before = [m for m in marks if m.start() < hit.start()]
            if before:
                period, ytd = _period(before[-1], published_at)
            stop = hits[i + 1].start() if i + 1 < len(hits) else len(sent)
            gap = sent[hit.end():stop]
            num = NUMBER.search(gap)
            if not num or not period:
                continue
            lead = sent[max(0, hit.start() - 1):hit.start()]
            if key in TRADE and lead and lead not in "，,：: 月）)计中国":
                continue  # 原油进口 / 乘用车出口: a product line, not the aggregate
            if key in TRADE and sent[max(0, hit.start() - 2):hit.start()] == "累计":
                continue
            head = gap[:num.start()]
            if re.search(r"余额|亿元|万吨", head) and key not in ("m2", "m1", "tsf", "loans", "retail", "trade", "exports",
                                                                 "imports", "fai", "property_inv", "profits", "revenue", "spending"):
                continue
            basis = ("level" if key in LEVEL else "mom" if "环比" in head or "比上月" in head else
                     "yoy" if re.search(r"同比|比上年", head) or same_basis or key in ("m2", "m1", "tsf") else None)
            if basis is None:
                continue
            if ytd and basis == "yoy":
                basis = "ytd"
            ctx = sent[max(0, hit.start() - 12):hit.end() + num.end()]
            currency = "USD" if "美元" in ctx else "CNY" if re.search(r"人民币|万亿元|亿元", ctx) else None
            value = float(num.group("v"))
            if num.group("verb") in NEGATIVE and value > 0:
                value = -value
            mapping = IND[key][4]
            metric = mapping.get(f"{basis}:{currency}") or mapping.get(basis)
            out.append({"indicator": key, "value": value, "unit": "index" if key.startswith("pmi") else "%",
                        "basis": basis, "currency": currency if key in TRADE else None, "period": period,
                        "previous": float(num.group("prev")) if num.group("prev") else None,
                        "metric_id": metric, "span": (sent[hit.start():hit.end() + num.end()]).strip()})
    seen, unique = set(), []
    for f in out:
        k = (f["indicator"], f["basis"], f["currency"], f["period"])
        if k not in seen:
            seen.add(k)
            unique.append(f)
    return unique


def extract_action(text: str) -> dict | None:
    """The first China policy action in the text: issuer, action, amount or rate, effective date."""
    for sent in SENTENCE.findall(text or ""):
        abroad = bool(OUTSIDE.search(sent)) and not re.search(r"对美|美加征", sent)
        for kind, rx, zh, en in ACTIONS:
            m = re.search(rx, sent)
            if not m:
                continue
            venue = VENUE.search(sent)
            if abroad and not (kind == "bond" and venue and OUTSIDE.search(sent).start() > venue.start()):
                continue  # '美国财政部…发行' is foreign; '财政部…在香港发行' is a Chinese issuer abroad
            if INTENT.search(sent) and not DECIDED.search(sent) and not (kind == "bond" and SCHEDULED.search(sent)):
                continue  # '将灵活运用降准降息' is a signal, not a cut
            # the issuer named closest before the action acts ('经国务院批准，财政部将…发行' is MOF's issuance)
            named = [(hit.start(), -i, (code, z, e)) for i, (code, irx, z, e) in enumerate(ISSUERS)
                     for hit in re.finditer(irx, sent)]  # at one position the more specific (earlier listed) wins
            before = [n for n in named if n[0] < m.start()]
            issuer = (max(before, key=lambda n: n[:2]) if before else
                      min(named, key=lambda n: (n[0], -n[1])) if named else (0, 0, None))[2]
            if issuer is None and kind in ("document", "bond", "facility", "liquidity"):
                continue  # a document or bond with no named Chinese issuer is not a policy action we can attribute
            tail = sent[m.start():]
            amount, rate, eff = AMOUNT.search(tail), RATE.search(tail), EFFECTIVE.search(sent)
            for later in SENTENCE.findall(text)[1:]:  # the same action restated with its size or start date
                hit = re.search(rx, later)
                if hit:
                    amount = amount or AMOUNT.search(later[hit.start():])
                    rate = rate or RATE.search(later[hit.start():])
                    eff = eff or EFFECTIVE.search(later)
            return {"kind": kind, "action_zh": zh, "action_en": en,
                    "issuer": issuer[0] if issuer else None, "issuer_zh": issuer[1] if issuer else None,
                    "issuer_en": issuer[2] if issuer else None,
                    "amount": f"{amount.group(1)}{amount.group(2)}" if amount else None,
                    "rate": f"{rate.group(1)}{rate.group(2)}" if rate else None,
                    "effective": (f"{eff.group(2)}月{eff.group(3)}日" if eff else None),
                    "span": sent.strip()[:120]}
    return None


# ---------------------------------------------------------------- the occurrence index
def _items(news_dir: Path) -> dict[str, dict]:
    items = {}
    for p in sorted((news_dir / "archive").glob("*.json")):
        for it in json.loads(p.read_text(encoding="utf-8")):
            items.setdefault(it["item_id"], it)
    latest = news_dir / "latest.json"
    if latest.exists():
        for it in json.loads(latest.read_text(encoding="utf-8")).get("items", []):
            items.setdefault(it["item_id"], it)
    return items


def _china(title: str, body: str) -> bool:
    return not FOREIGN.search(title) and not (classify(body) == "global" and not CHINA.search(body))


def _hypotheses(title: str, summary: str, item_id: str) -> list[str]:
    from .research_inputs import _rules  # the same loaded H0-H4 rules the research bundle uses
    info = rule_triage({"title_zh": title, "summary_zh": summary, "item_id": item_id, "kind": "media"}, _rules())
    if info["triage"] == "irrelevant":
        return []
    return sorted({h["hypothesis"] for h in info["hypotheses"]})


def read_members(members) -> tuple[list[dict], dict | None]:
    """Reported figures (deduplicated across outlets, first-party first) and the first policy action
    stated in a group's own texts. Each figure keeps its outlet, URL and publication time."""
    figures, action = [], None
    for m in members:
        text = m["title_zh"] + "。" + (m.get("summary_zh") or "")
        for f in extract_figures(text, m["published_at"]):
            f.update({"publisher": m["publisher"], "url": m["canonical_url"], "published_at": m["published_at"],
                      "official": m.get("source_tier") == "T1" and bool(OFFICIAL_HOST.search(urlsplit(m["canonical_url"]).hostname or ""))})
            figures.append(f)
        lead = (SENTENCE.findall(m.get("summary_zh") or "") or [""])[0]
        found = extract_action(m["title_zh"] + "。" + lead)
        if action is None:
            action = found
        elif found and found["kind"] == action["kind"]:  # another outlet's text may give the size or start date
            action = {**action, **{k: found[k] for k in ("amount", "rate", "effective") if not action[k] and found[k]}}
    figures.sort(key=lambda f: (not f["official"], f["published_at"]))
    seen, unique = set(), []
    for f in figures:  # the same reading reported by several outlets is one figure, first-party first
        k = (f["indicator"], f["basis"], f["currency"], f["period"], f["value"])
        if k not in seen:
            seen.add(k)
            unique.append(f)
    return unique, action


def _occurrence(oid, title, summary, url, publisher, published, first_seen, official, members, topic, title_en=None):
    unique, action = read_members(members)
    hs = _hypotheses(title, summary, oid)
    kind = "data" if unique else "policy" if action else "news"
    at = stamp(published).astimezone(BEIJING)
    precise = "T" in str(published) and not str(published).endswith("T00:00:00+08:00")
    return {"occurrence_id": oid, "kind": kind, "title_zh": title, "title_en": title_en, "summary_zh": summary,
            "topic": topic, "publisher": publisher, "publishers": sorted({m["publisher"] for m in members} | {publisher}),
            "official": official, "url": url, "source_urls": sorted({m["canonical_url"] for m in members} | {url}),
            "reports": [{"publisher": m["publisher"], "url": m["canonical_url"]}
                        for m in sorted(members, key=lambda m: (m.get("source_tier") != "T1", stamp(m["published_at"])))],
            "published_at": at.isoformat(), "date": at.date().isoformat(), "time": at.strftime("%H:%M") if precise else "",
            "first_seen_at": first_seen, "figures": unique[:8], "action": action, "hypotheses": hs,
            "metric_ids": sorted({f["metric_id"] for f in unique if f["metric_id"]}
                                 | {mid for m in members for mid in m.get("metric_ids", [])})}


def build_occurrences(news_dir: Path, events_dir: Path | None, as_of: str) -> list[dict]:
    """News event groups and official intake items as China macro occurrences, available by `as_of`.
    One group is one occurrence (news_rank already joins same-occurrence reports); official intake items
    whose URL a news group already holds are folded into it, never shown twice."""
    news_dir, cutoff = Path(news_dir), stamp(as_of)
    items, out, held_urls = _items(news_dir), [], set()
    latest = news_dir / "latest.json"
    feed = json.loads(latest.read_text(encoding="utf-8")) if latest.exists() else {}
    for ev in feed.get("events", []):
        members = [items[i] for i in ev.get("items", []) if i in items and stamp(items[i]["first_seen_at"]) <= cutoff
                   and items[i].get("published_at")]
        if not members:
            continue
        # Group metadata describes every member, including ones collected after as_of. Use it only when every
        # member was available by then; otherwise rebuild from the eligible members (as research_inputs does).
        whole = len(members) == len(ev.get("items", []))
        g = ev if whole else {}
        rep = next((m for m in members if m["canonical_url"] == g.get("url")),
                   min(members, key=lambda m: (m.get("source_tier") != "T1", stamp(m["published_at"]))))
        title, summary = g.get("title_zh") or rep["title_zh"], g.get("summary_zh") or rep.get("summary_zh") or ""
        if ROUNDUP.search(title) or not _china(title, title + " " + summary):
            continue
        published = rep["published_at"]  # the reported occurrence's own time, not an earlier related member
        url = g.get("url") or rep["canonical_url"]
        first_party = bool(g.get("official")) if whole else rep.get("source_tier") == "T1"
        official = first_party and bool(OFFICIAL_HOST.search(urlsplit(url).hostname or ""))
        occ = _occurrence(ev["event_id"], title, summary, url,
                          g.get("publisher") or rep["publisher"], published,
                          min(m["first_seen_at"] for m in members), official, members, ev.get("topic"),
                          (g.get("ai") or {}).get("title_en") if feed.get("ai_display") else None)
        held_urls.update(occ["source_urls"])
        out.append(occ)
    grouped = {i for ev in feed.get("events", []) for i in ev.get("items", [])}
    rest: dict[str, list[dict]] = {}
    for it in items.values():  # archived items whose group has left the live window keep their own grouping
        if it["item_id"] not in grouped and it.get("published_at") and stamp(it["first_seen_at"]) <= cutoff:
            rest.setdefault(it.get("event_id") or it.get("event_group_id") or it["item_id"], []).append(it)
    for gid, members in rest.items():
        members.sort(key=lambda m: (m.get("source_tier") != "T1", stamp(m["published_at"])))
        rep = members[0]
        title, summary = rep["title_zh"], rep.get("summary_zh") or ""
        if ROUNDUP.search(title) or not _china(title, title + " " + summary):
            continue
        host = urlsplit(rep["canonical_url"]).hostname or ""
        occ = _occurrence(gid, title, summary, rep["canonical_url"], rep["publisher"],
                          min((m["published_at"] for m in members), key=lambda v: stamp(v)),
                          min(m["first_seen_at"] for m in members),
                          rep.get("source_tier") == "T1" and bool(OFFICIAL_HOST.search(host)), members, rep.get("topic"))
        held_urls.update(occ["source_urls"])
        out.append(occ)
    if events_dir and Path(events_dir).exists():
        for r in load_grouped_public_items(Path(events_dir), as_of=as_of):
            if r["canonical_url"] in held_urls or not r.get("published_at"):
                continue
            title, summary = r.get("title_zh") or "", r.get("summary_zh") or ""
            if not _china(title, title + " " + summary):
                continue
            member = {**r, "source_tier": "T1", "metric_ids": r.get("metric_ids", [])}
            occ = _occurrence(r["item_id"], title, summary, r["canonical_url"], r["publisher"], r["published_at"],
                              r["first_seen_at"], True, [member], r.get("topic") or classify(title + summary))
            occ["hypotheses"] = sorted(set(occ["hypotheses"]) | set(r.get("hypotheses", [])))
            out.append(occ)
    return sorted(out, key=lambda o: stamp(o["published_at"]), reverse=True)


# An institution's own release page, already collected by the hourly intake, records that the release came out.
RELEASE_PAGES = [
    ("PBOC", "pboc", "中国人民银行",
     re.compile(r"(?P<y>20\d\d)年(?:(?P<m>\d{1,2})月|(?P<q>一季度|上半年|前三季度))?金融统计数据报告")),
    ("MOF", "mof", "财政部",
     re.compile(r"(?P<y>20\d\d)年(?:1[-—–](?P<m>\d{1,2})月|(?P<q>一季度|上半年|前三季度))?财政收支情况")),
]


def official_releases(occurrences) -> list[dict]:
    """PBoC and MOF releases the intake has seen on the institution's own site, dated by that page, so the
    calendar records them as published without a manual calendar run. Never a forecast of a future date."""
    out = []
    for occ in occurrences:
        if not occ["official"]:
            continue
        for source, kind, publisher, rx in RELEASE_PAGES:
            m = rx.fullmatch((occ["title_zh"] or "").strip())
            if not m or occ["publisher"] != publisher:
                continue
            month = int(m.group("m")) if m.group("m") else {"一季度": 3, "上半年": 6, "前三季度": 9, None: 12}[m.group("q")]
            if not 1 <= month <= 12:
                continue
            out.append({"source": source, "kind": kind, "title_zh": occ["title_zh"], "period": f"{m.group('y')}-{month:02d}",
                        "published": occ["date"] + (f"T{occ['time']}:00+08:00" if occ["time"] else ""),
                        "url": occ["url"], "occurrence_id": occ["occurrence_id"]})
    return out


def material(occ: dict) -> bool:
    """Worth a dated calendar entry: a reported China figure, a policy action, or first-party news on the thesis."""
    action = occ["action"]
    # a State Council / Politburo meeting reaches the calendar from a first-party page; a document needs a thesis
    # link as well; a media notice of either stays in the feed
    acts = bool(action and (action["kind"] != "document" or (occ["official"] and occ["hypotheses"]))
                and (action["kind"] != "meeting" or occ["official"]))
    return bool(occ["figures"] or acts or (occ["official"] and occ["hypotheses"]))
