"""NBS/PBOC/gov.cn readers. No model, observation writes or automatic approval."""
from __future__ import annotations

import email.utils
import hashlib
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

from cnmacro.ingest import NBS_RELEASE_TABLES
from .store import BEIJING, append, load_source_status, raw_items, stamp

MAX_BYTES = 16_000_000
SOURCES = {
    "nbs": ("https://www.stats.gov.cn/sj/zxfb/rss.xml", "NBS"),
    "pboc": ("https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html", "PBOC"),
    "gov_monetary": ("https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary&q=" + urllib.parse.quote("货币政策"), "gov.cn"),
    "gov_fiscal": ("https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary&q=" + urllib.parse.quote("财政"), "gov.cn"),
}
HOSTS = {"www.stats.gov.cn", "www.pbc.gov.cn", "www.gov.cn"}


def canonical_url(value: str) -> str:
    url = urllib.parse.urlsplit(value.strip())
    if url.scheme not in {"http", "https"} or url.hostname not in HOSTS or url.username or url.password:
        raise ValueError("item URL is outside authorized official publishers")
    query = [(k, v) for k, v in urllib.parse.parse_qsl(url.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"spm", "from", "share"}]
    return urllib.parse.urlunsplit(("https", url.hostname, url.path, urllib.parse.urlencode(query), ""))


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain(value: str) -> str:
    parser = PlainText()
    parser.feed(value or "")
    parser.close()
    return " ".join(" ".join(parser.parts).split())


def publication(value: str | None) -> tuple[str | None, str]:
    if not value:
        return None, "unknown"
    text = re.sub(r"^(\d{4})\.(\d{2})\.(\d{2})", r"\1-\2-\3", value.strip())
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return datetime.strptime(text, "%Y-%m-%d").date().isoformat(), "date"
        try:
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            result = email.utils.parsedate_to_datetime(value)
        if result.tzinfo is None:
            result = result.replace(tzinfo=BEIJING)
        return result.isoformat(), "second"
    except (ValueError, TypeError, OverflowError):
        return None, "unknown"


def metric_ids(title: str) -> list[str]:
    ids = {mid for keyword, mapping in NBS_RELEASE_TABLES.items() if keyword in title for mid in mapping}
    extra = {"采购经理指数": ["cn_pmi_new_orders", "cn_pmi_output_price", "cn_pmi_new_export_orders"],
             "工业企业利润": ["cn_ind_profit_ytd_yoy"], "工业增加值": ["cn_ip_yoy"],
             "社会消费品零售": ["cn_retail_sales_yoy"], "房地产市场": ["cn_property_sales_area_ytd_yoy"],
             "国内生产总值": ["cn_ngdp_q", "cn_rgdp_yoy"]}
    for keyword, mids in extra.items():
        if keyword in title:
            ids.update(mids)
    return sorted(ids)


def item(source: str, title: str, url: str, published: str | None, excerpt: str, now: str) -> dict:
    title, excerpt, url = plain(title), plain(excerpt)[:300], canonical_url(url)
    if not title:
        raise ValueError("missing item title")
    published_at, precision = publication(published)
    digest = hashlib.sha256(json.dumps([title, url, published_at, excerpt], ensure_ascii=False).encode()).hexdigest()
    mids = metric_ids(title) if source == "nbs" else []
    # For date-only sources archive after the entire publication day +48h.
    archive_anchor = stamp(published_at) + (timedelta(days=1) if precision == "date" else timedelta()) if published_at else None
    return {"item_id": "item_" + hashlib.sha256((url + digest).encode()).hexdigest()[:24],
            "source": source, "kind": "data_release" if mids else ("policy" if source.startswith("gov_") else "announcement"),
            "publisher": SOURCES[source][1], "canonical_url": url, "title_zh": title, "title_en": None,
            "summary_zh": excerpt, "summary_en": None, "published_at": published_at,
            "publication_precision": precision, "first_seen_at": now, "retrieved_at": now,
            "source_hash": digest, "metric_ids": mids, "hypotheses": [], "tier": "EVENT",
            "status": "raw_candidate", "archived": bool(archive_anchor and stamp(now) - archive_anchor > timedelta(hours=48)),
            "quarantined": not bool(published_at)}


def parse_nbs(body: bytes, now: str) -> list[dict]:
    root = ET.fromstring(body)
    if root.tag.lower() != "rss":
        raise ValueError("NBS did not return RSS")
    return [item("nbs", node.findtext("title") or "", node.findtext("link") or "",
                 node.findtext("pubDate") or node.findtext("pubTime"), node.findtext("description") or "", now)
            for node in root.findall("./channel/item")]


class PBOCList(HTMLParser):
    def __init__(self):
        super().__init__()
        self.entries, self.pending, self.href, self.parts, self.row = [], None, None, [], []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row, self.pending = [], None
        if tag == "a":
            self.href, self.parts = dict(attrs).get("href"), []

    def handle_data(self, data):
        self.row.append(data)
        if self.href:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            if re.search(r"/113469/[^/]+/index\.html", self.href):
                self.pending = (urllib.parse.urljoin(SOURCES["pboc"][0], self.href), "".join(self.parts))
            self.href = None
        if tag == "tr" and self.pending:
            self.entries.append((*self.pending, "".join(self.row)))
            self.pending = None


def parse_pboc(body: bytes, now: str) -> list[dict]:
    parser = PBOCList()
    parser.feed(body.decode("utf-8"))
    result = []
    for url, title, row in parser.entries:
        match = re.search(r"/113469/(\d{14})\d*/", url)
        published = None
        if match:
            try:
                published = datetime.strptime(match[1], "%Y%m%d%H%M%S").replace(tzinfo=BEIJING).isoformat()
            except ValueError:
                pass
        if not published:
            day = re.search(r"\d{4}-\d{2}-\d{2}", row)
            published = day[0] if day else None
        result.append(item("pboc", title, url, published, "", now))
    return result


def parse_gov(body: bytes, now: str, source: str) -> list[dict]:
    search = json.loads(body)["searchVO"]
    rows = search.get("result")
    if not isinstance(rows, list) and isinstance(search.get("catMap"), dict):
        rows = [i for category in search["catMap"].values() for i in category.get("listVO", [])]
    if not isinstance(rows, list):
        raise ValueError("gov.cn result shape changed")
    result = []
    for row in rows:
        published = row.get("pubtimeStr") or row.get("pubTime")
        # The display date is authoritative precision; do not turn a date into an exact clock time.
        result.append(item(source, row.get("title", ""), row.get("url", ""), published,
                           row.get("summary", ""), now))
    return result


def fetch(url: str) -> bytes:
    headers = {"User-Agent": "Mozilla/5.0 (CC Macro official-source reader)"}
    if "sousuo.www.gov.cn" in url:
        headers["Referer"] = "https://sousuo.www.gov.cn/"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45) as response:
        if urllib.parse.urlsplit(response.url).hostname != urllib.parse.urlsplit(url).hostname:
            raise ValueError("source redirected outside the requested official host")
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("official response exceeds 16MB limit")
    return body


def intake(events_dir: Path, *, now: str | None = None, dry_run=False, include_gov=False, reader=fetch) -> dict:
    now = now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    stamp(now)
    known = {r["item_id"] for r in raw_items(events_dir)}
    cursor_path = events_dir / "cursors.json"
    cursors = json.loads(cursor_path.read_text(encoding="utf-8")) if cursor_path.exists() else {}
    prior = {r["source"]: r for r in load_source_status(events_dir, as_of=now)}
    summary = {"retrieved_at": now, "new_items": 0, "sources": []}
    additions, outcomes = [], []
    for source, (url, publisher) in SOURCES.items():
        if source.startswith("gov_") and not include_gov:
            continue
        outcome = {"source": source, "url": url, "publisher": publisher, "retrieved_at": now}
        try:
            body = reader(url)
            if len(body) > MAX_BYTES:
                raise ValueError("official response exceeds 16MB limit")
            records = parse_nbs(body, now) if source == "nbs" else parse_pboc(body, now) if source == "pboc" else parse_gov(body, now, source)
            if not records:
                raise ValueError("no official items parsed; empty/WAF/changed response")
            new = []
            for record in records:
                if record["item_id"] not in known:
                    new.append(record)
                    known.add(record["item_id"])
            additions.extend(new)
            outcome.update(ok=True, parsed=len(records), new_items=len(new), response_hash=hashlib.sha256(body).hexdigest())
            dated = [r for r in records if r["published_at"]]
            latest = max(dated, key=lambda r: stamp(r["published_at"]), default=None)
            new_cursor = {"last_seen_id": latest["item_id"] if latest else None,
                          "last_seen_publication": latest["published_at"] if latest else None,
                          "items_hash": hashlib.sha256("\n".join(sorted(r["item_id"] for r in records)).encode()).hexdigest()}
            # Re-scan the retained source list every run: cursors do not exclude older backfill.
            cursors[source] = new_cursor
        except Exception as error:
            outcome.update(ok=False, new_items=0, error=f"{type(error).__name__}: {error}"[:300])
        summary["sources"].append(outcome)
        previous = {k: v for k, v in prior.get(source, {}).items() if k not in {"retrieved_at", "new_items", "response_hash"}}
        current = {k: v for k, v in outcome.items() if k not in {"retrieved_at", "new_items", "response_hash"}}
        if previous != current or outcome["new_items"]:
            outcomes.append(outcome)
    summary["new_items"] = len(additions)
    if not dry_run:
        append(events_dir / "inbox" / (stamp(now).strftime("%Y-%m") + ".jsonl"), additions)
        append(events_dir / "source_status.jsonl", outcomes)
        if cursors and (not cursor_path.exists() or json.loads(cursor_path.read_text(encoding="utf-8")) != cursors):
            cursor_path.parent.mkdir(parents=True, exist_ok=True)
            cursor_path.write_text(json.dumps(cursors, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary
