"""NBS monthly CPI/PPI and manufacturing PMI table facts, with archived URL lineage.

No prose-number extraction, estimated contributions or inferred missing cells.
Transport failure and schema drift preserve the last valid public store.
"""
from __future__ import annotations

import re
import html
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from . import ingest
from .firstprint import _Anchors
from .refresh import new_rows
from .store import load_observations

BASE = 'https://www.stats.gov.cn/sj/zxfb/'
CPI = {'cn_cpi': '居民消费价格', 'cn_core_cpi': '不包括食品和能源',
       'cn_cpi_food': '食品', 'cn_cpi_pork': '猪肉', 'cn_cpi_fuel': '交通工具用燃料',
       'cn_cpi_services': '服务', 'cn_cpi_goods': '消费品'}
PPI = {'cn_ppi': '工业生产者出厂价格', 'cn_ppi_producer': '生产资料',
       'cn_ppi_consumer': '生活资料', 'cn_ppi_mining': '采掘',
       'cn_ppi_raw_materials': '原材料', 'cn_ppi_processing': '加工'}
PMI = {'cn_pmi_input_price':'主要原材料购进价格', 'cn_pmi_output_price':'出厂价格'}
PRICE_METRICS = frozenset({base+'_'+change for base in CPI | PPI for change in ('yoy','mom')} | PMI.keys())
LEGACY_METRICS = frozenset({'cn_cpi_yoy','cn_core_cpi_yoy','cn_ppi_yoy','cn_ppi_mom','cn_ppi_producer_yoy','cn_ppi_consumer_yoy','cn_pmi_output_price'})
NEW_PRICE_METRICS = PRICE_METRICS - LEGACY_METRICS
TITLE = re.compile(r'^(\d{4})年(\d{1,2})月份?(居民消费价格|工业生产者出厂价格|中国采购经理指数运行情况)')
MISSING = {'', '—', '–', '-', '…', '...', '　'}


def release_links(page, base=BASE):
    anchors = _Anchors(); anchors.feed(page)
    links = {}
    for href,title in anchors.items:
        match = TITLE.match(title.strip())
        url = urljoin(base,href)
        parsed = urlparse(url)
        if match and parsed.scheme=='https' and parsed.netloc=='www.stats.gov.cn' and re.fullmatch(r'/sj/zxfb/20\d{4}/t\d{8}_\d+\.html',parsed.path):
            links[url] = {'url':url,'title':title.strip(),'period':f'{match[1]}-{int(match[2]):02d}'}
    return list(links.values())


def fetch_release(url):
    """Read the same official article using the runner-verified cache variant if needed.

    The canonical article remains the observation's source_code. The summary records
    the actual transport URL. An HTTP 200 JavaScript challenge is never a data success.
    """
    failures = []
    # These routes were measured from GitHub runners against these same
    # public NBS articles. HTTP carries no credentials; identity remains HTTPS.
    cache_day = datetime.now(timezone.utc).strftime('%Y%m%d')
    for transport in (url,url+'?v=1',url+'?_='+cache_day,url.replace('https:','http:',1)):
        try:
            text = ingest._get(transport,timeout=20,retries=2).decode('utf-8')
            if '<table' in text.lower(): return text,transport
            failures.append('no table: '+transport)
        except Exception as exc: failures.append(str(exc))
    raise ValueError('Official NBS release transports failed: '+'; '.join(failures))


def _number(cell):
    cell = re.sub(r'\s+','',cell).replace('−','-').replace('﹣','-')
    if cell in MISSING: return None
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?',cell):
        raise ValueError(f'invalid price table cell {cell!r}')
    return float(cell)


def parse_release(page, title, url, retrieved_at):
    # Match the existing store's second-precision ISO timestamps (pandas infers
    # one array format for the combined historical observation directory).
    retrieved_at = datetime.fromisoformat(retrieved_at.replace('Z','+00:00')).replace(microsecond=0).isoformat()
    match = TITLE.match(title.strip())
    if not match: raise ValueError('not a monthly NBS price release title')
    period = f'{match[1]}-{int(match[2]):02d}'
    document_title = re.search(r'<title[^>]*>(.*?)</title>',page,re.I|re.S)
    actual = TITLE.match(html.unescape(document_title[1]).strip()) if document_title else None
    if not actual or actual.groups() != match.groups():
        raise ValueError('NBS page title disagrees with requested release period/type')
    parser = ingest._Cells(); parser.feed(page)
    if not parser.rows: raise ValueError('no NBS price table (possibly a JavaScript challenge)')
    stamp = re.search(r'(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2})',page)
    if stamp:
        released = f'{stamp[1]}-{stamp[2]}-{stamp[3]}T{stamp[4]}:{stamp[5]}:00+08:00'
        datetime.fromisoformat(released)
        if released[:7] < period: raise ValueError('release date precedes reference month')
    else:
        released = ''
    values = {}
    def put(mid, value):
        if value is None: return
        if mid in values and values[mid] != value: raise ValueError(f'duplicate price tables disagree for {mid}')
        values[mid] = value
    if '采购经理' in match[3]:
        heads = [i for i,row in enumerate(parser.rows) if PMI['cn_pmi_input_price'] in [ingest._label(c) for c in row]]
        if not heads: raise ValueError('manufacturing PMI price header missing')
        for i in heads:
            header = [ingest._label(c) for c in parser.rows[i]]
            if any(header.count(label)!=1 for label in PMI.values()): raise ValueError('ambiguous PMI header')
            for row in parser.rows[i+1:]:
                if len(row)!=len(header): continue
                if ingest._label(row[0]) == f'{int(match[1])}年{int(match[2])}月':
                    for mid,label in PMI.items(): put(mid,_number(row[header.index(label)]))
                    break
    else:
        labels = dict(CPI if '居民消费' in match[3] else PPI)
        # NBS's 2026 CPI classification publishes transport energy, replacing
        # transport fuel. Preserve the official label and disclose the break.
        if 'cn_cpi_fuel' in labels and period >= '2026-01':
            labels['cn_cpi_fuel'] = '交通工具用能源'
        heads = [i for i,row in enumerate(parser.rows) if any('环比' in c for c in row) and any('同比' in c for c in row)]
        if not heads: raise ValueError('monthly MoM/YoY price header missing')
        for i,end in zip(heads,heads[1:]+[len(parser.rows)]):
            header = [re.sub(r'\s+','',c) for c in parser.rows[i]]
            columns = {}
            for change,keyword in (('mom','环比'),('yoy','同比')):
                indexes = [j for j,c in enumerate(header) if keyword in c and '月' not in c]
                if len(indexes)!=1: raise ValueError('ambiguous monthly price header')
                columns[change] = indexes[0]
            for base,label in labels.items():
                hits = [row for row in parser.rows[i+1:end] if row and ingest._label(row[0])==label]
                if not hits: raise ValueError(f'price table label missing: {label}')
                for row in hits:
                    if len(row)!=len(header): raise ValueError(f'price table row width changed: {label}')
                    for change,col in columns.items(): put(base+'_'+change,_number(row[col]))
    if not values: raise ValueError('price table has no current-month values')
    rows = []
    for mid,value in sorted(values.items()):
        row = ingest.row(mid,period,value,'NBS',url,'public',retrieved_at=retrieved_at,calendar={},limitation_if_unknown='Publication timestamp unavailable; availability is retrieval time.')
        if released: row.update(release_date=released,release_date_basis='source_field',limitation='Archived NBS release table; captured at retrieved_at, not an independently captured historical vintage.')
        if mid.startswith('cn_cpi_fuel'):
            row['limitation'] += (' Published transport energy (交通工具用能源); classification break from transport fuel at 2026-01; not broad energy.' if period >= '2026-01' else ' Published transport fuel (交通工具用燃料); classification break to transport energy at 2026-01; not broad energy.')
        rows.append(row)
    return rows


def append_release_rows(rows, directory):
    """Reuse existing value-change vintage rules; never overwrite a captured observation."""
    directory = Path(directory)
    held = load_observations(directory)
    fresh = new_rows(rows,held)
    # An archived first print must not replace newer portal history for existing research metrics.
    latest = held.sort_values('retrieved_at').drop_duplicates(['metric_id','reference_period'],keep='last')
    sources = {(r.metric_id,r.reference_period):r.source_code for r in latest.itertuples()}
    fresh = [r for r in fresh if r['metric_id'] not in LEGACY_METRICS or sources.get((r['metric_id'],r['reference_period']),r['source_code']) == r['source_code']]
    return ingest.append_rows(fresh,directory/'prices_release.csv') if fresh else 0
