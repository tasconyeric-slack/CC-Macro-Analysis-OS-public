"""Additional public series using the existing NBS contract and original PBOC text."""
from __future__ import annotations
import concurrent.futures
import html
import json
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import urljoin
from . import ingest
from .store import load_dictionary

NEW_METRICS = frozenset({'cn_pmi_nonmfg','cn_pmi_services','cn_pmi_construction','cn_pmi_composite',
    'cn_unemployment','cn_imports_usd_yoy','cn_trade_balance_usd','cn_budget_rev_ytd_yoy','cn_m2_yoy'})
METRICS = NEW_METRICS | {'cn_pmi_mfg'}
PBOC_LIST = 'https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/'


def request(url, payload=None):
    """Public-data transport. curl also handles the Windows TLS route used by the collectors."""
    binary = shutil.which('curl.exe') or shutil.which('curl')
    if not binary:
        raise RuntimeError('curl is required for the expanded official-data fetch')
    with tempfile.TemporaryDirectory(prefix='cnmacro-public-fetch-') as temporary:
        jar = str(Path(temporary)/'cookies.txt')
        args = [binary, '-f', '-sS', '--max-time', '60', '--retry', '2', '-L',
                '--max-redirs', '5', '-c', jar, '-b', jar, url]
        if payload is not None:
            body = Path(temporary)/'query.json'
            body.write_text(json.dumps(payload), encoding='utf-8')
            args += ['-H','Content-Type: application/json','--data-binary','@'+str(body)]
        result = subprocess.run(args, capture_output=True, check=True)
        return result.stdout


def nbs_values(metric, start='2019-01'):
    cid, iid, idx100 = ingest.parse_nbs_code(metric.source_code)[0]
    today = date.today()
    payload = {'cid':cid, 'indicatorIds':[iid], 'daCatalogId':'',
        'das':[{'text':'全国','value':'000000000000'}], 'showType':'1',
        'dts':[start.replace('-','')+'MM-'+f'{today.year}{today.month:02d}MM'],
        'rootId':ingest.NBS2_ROOTS['M'][1]}
    data = json.loads(request(ingest.NBS2+'stream/esData',payload))
    if not data.get('success', True) or not isinstance(data.get('data'), list):
        raise ValueError('NBS data query returned an invalid response')
    values = []
    for node in data['data']:
        for value in node['values']:
            if value.get('_id') == iid and value.get('value') not in (None,''):
                number = float(value['value']) - (100 if idx100 else 0)
                values.append((ingest.nbs_period(node['code'],'M'),number))
    if len(values) < 2:
        raise ValueError(f'{metric.metric_id}: insufficient official history')
    return sorted(set(values))


def parse_pboc_m2(page, url):
    title = re.search(r'<meta\s+name=["\']ArticleTitle["\']\s+content=["\']([^"\']+)',page,re.I)
    published = re.search(r'<meta\s+name=["\']PubDate["\']\s+content=["\']([^"\']+)',page,re.I)
    if not title or not published or '金融统计数据报告' not in title[1]:
        raise ValueError('not a dated PBOC financial statistics release')
    text = html.unescape(re.sub('<[^>]*>','',page))
    text = re.sub(r'\s+','',text)
    # Restrict to a literal month-end M2 paragraph. TSF growth elsewhere is not M2.
    match = re.search(r'(\d{1,2})月末[，,]广义货币[（(]M2[）)]余额[^。]*?同比增长([\d.]+)%',text)
    if not match:
        raise ValueError('M2 month-end value not found')
    year = int(published[1][:4])
    month = int(match[1])
    if month > int(published[1][5:7]):
        year -= 1
    return {'period':f'{year}-{month:02d}','value':float(match[2]),
            'release_date':published[1], 'url':url, 'title':title[1]}


def pboc_m2():
    links = {}
    for page in ['index.html']+[f'11040-{i}.html' for i in range(2,5)]:
        listing = request(PBOC_LIST+page).decode('utf-8')
        for href,title in re.findall(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*title=["\']([^"\']*金融统计数据报告)["\']',listing):
            url = urljoin(PBOC_LIST,href)
            if url.startswith(PBOC_LIST):
                links[url] = title
    if not links:
        raise ValueError('No PBOC monetary statistics release found')
    records = [parse_pboc_m2(request(url).decode('utf-8'),url) for url in sorted(links,reverse=True)[:2]]
    return sorted(records,key=lambda r:r['period'])


def refresh_expanded(root=Path('.'), start='2019-01'):
    root = Path(root)
    metrics = load_dictionary(root/'data/dictionary/metrics.yaml')
    calendar = ingest.load_calendar(root/'data/dictionary/release_calendar.yaml')
    got = ingest.now_iso()
    selected = [metrics[mid] for mid in sorted(METRICS)]
    summary = {'retrieved_at':got,'sources':{},'metrics':{},'errors':[]}
    pboc = []
    try:
        pboc = pboc_m2()
        summary['sources']['pboc_release'] = {'ok':True,'items':len(pboc),'urls':[r['url'] for r in pboc]}
    except Exception as exc:
        summary['sources']['pboc_release'] = {'ok':False,'error':str(exc)}
        summary['errors'].append('PBOC direct release failed; NBS-republished M2 remains available')
    def collect(metric):
        values = nbs_values(metric,start)
        rows = [ingest.row(metric.metric_id,p,v,metric.source_primary,metric.source_code,'public',
            retrieved_at=got,calendar=calendar,
            limitation_if_unknown='Historical first-publication time not recorded; availability is retrieval time. Official statistic via NBS portal.') for p,v in values]
        if metric.metric_id == 'cn_m2_yoy':
            official = {r['period']:r for r in pboc}
            rows = [r for r in rows if r['reference_period'] not in official]
            for p,r in official.items():
                row = ingest.row(metric.metric_id,p,r['value'],'PBOC',r['url'],'public',retrieved_at=got,
                    calendar={},limitation_if_unknown='')
                row.update(release_date=r['release_date'],release_date_basis='source_field',
                    limitation='Original PBOC publication date; time of day not provided.')
                rows.append(row)
        path = root/'data/demo/observations'/f'expanded_{metric.metric_id}.csv'
        added = ingest.append_rows(rows,path)
        return metric.metric_id,{'rows':len(rows),'added':added,'latest_period':max(r['reference_period'] for r in rows)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        for future in [pool.submit(collect,m) for m in selected]:
            try:
                mid, result = future.result()
                summary['metrics'][mid] = result
            except Exception as exc:
                summary['errors'].append(str(exc))
    summary['sources']['nbs_portal'] = {'ok':len(summary['metrics'])==len(selected),'series':len(summary['metrics'])}
    return summary
