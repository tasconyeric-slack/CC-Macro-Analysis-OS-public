"""Small public-news adapters; official observations remain in the existing collectors.

Adapts AIHOT MIT source-normalization/grouping concepts (see docs/research/public-news-sources.md).
No upstream application code, paid research or model-generated reporting.
"""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
import urllib.parse
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from cnmacro.events.intake import plain
from cnmacro.events.store import stamp, BEIJING

SOURCES = {
    'ndrc': {'url':'https://www.ndrc.gov.cn/xwdt/xwfb/', 'publisher':'国家发展改革委', 'tier':'official', 'hosts':['www.ndrc.gov.cn']},
    'mof': {'url':'https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/quanguocaizhengshouzhiqingkuang/', 'publisher':'财政部', 'tier':'official', 'hosts':['www.mof.gov.cn','gks.mof.gov.cn']},
    'wallstreetcn': {'url':'https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=100', 'publisher':'华尔街见闻', 'tier':'reporting', 'hosts':['wallstreetcn.com']},
}
TOPICS = {
    'prices': ('物价与通胀','Prices and inflation',r'CPI|PPI|物价|通胀|居民消费价格|工业生产者', ['cn_cpi_yoy','cn_ppi_yoy']),
    'credit': ('货币与信用','Money and credit',r'央行|货币政策|信贷|社会融资|贷款|降准|LPR|再贷款',['cn_m1_yoy','cn_tsf_stock_yoy']),
    'fiscal': ('财政与投资','Fiscal policy and investment',r'财政|税收|预算|国债|专项债|政府债|发展改革委.*发布会|投资项目',['cn_budget_exp_ytd_yoy','cn_tsf_govbond_flow']),
    'property': ('房地产','Property',r'房地产|楼市|商品房|住房|住宅',['cn_property_sales_area_ytd_yoy']),
    'trade': ('外贸与外需','Trade and external demand',r'出口|进口|进出口|海关|贸易|关税',['cn_exports_usd_yoy','cn_pmi_new_export_orders']),
    'growth': ('增长与消费','Growth and demand',r'经济形势|经济运行|GDP|PMI|工业增加值|消费|零售|就业|服务业|民营企业|生产力',['cn_rgdp_yoy','cn_ip_yoy','cn_retail_sales_yoy']),
}

def canonical(url, source):
    u=urllib.parse.urlsplit(url)
    if u.scheme not in ('http','https') or u.hostname not in SOURCES[source]['hosts'] or u.username:
        raise ValueError('source URL outside publisher')
    return urllib.parse.urlunsplit(('https',u.netloc,u.path,'',''))

def occurrence_key(title,published,url):
    """Only an explicit China release/period can collapse differently worded headlines.

    Combined CPI/PPI roundups stay separate; policy implementation follow-ups are not title-fuzzy merged.
    """
    cpi=bool(re.search(r'CPI|居民消费价格',title,re.I));ppi=bool(re.search(r'PPI|工业生产者',title,re.I))
    period=re.search(r'(?:20\d{2}年)?(\d{1,2})月份?',title)
    china=bool(re.search('中国|国家统计局|居民消费价格|工业生产者|核心CPI',title))
    if cpi!=ppi and period and china:
        at=stamp(published);month=int(period[1]);year=at.year-(month>at.month)
        return f'china-release-{"cpi" if cpi else "ppi"}-{year}-{month:02d}'
    return 'news_event_'+hashlib.sha256((stamp(published).date().isoformat()+re.sub(r'[\W_]+','',title).lower()).encode()).hexdigest() if title else url

def classify(text):
    return next((key for key,value in TOPICS.items() if re.search(value[2],text,re.I)),None)

def normalize(source,title,url,published,summary,now,language='zh'):
    title,summary=plain(title),plain(summary)
    topic=classify(title+' '+summary)
    if not topic or not title or not published: return None
    url=canonical(url,source)
    at=stamp(published)
    if at>stamp(now):return None
    key=re.sub(r'[\W_]+','',title).lower()
    return {'item_id':'news_'+hashlib.sha256(url.encode()).hexdigest()[:20], 'kind':'media' if source=='wallstreetcn' else 'announcement',
            'title_zh':title[:180], 'title_en':None, 'publisher':SOURCES[source]['publisher'], 'source':source,
            'canonical_url':url,'published_at':published,'publication_precision':'second' if 'T' in published else 'date',
            'first_seen_at':now,'retrieved_at':now,'language':language,'summary_zh':summary[:180] or title[:180],
            'source_tier':SOURCES[source]['tier'],'tier':'EVENT','topic':topic,'metric_ids':TOPICS[topic][3],
            'event_group_id':occurrence_key(title,published,url),
            'freshness':'today' if at.astimezone(BEIJING).date()==stamp(now).astimezone(BEIJING).date() else 'latest',
            'relevance':1,'source_hash':hashlib.sha256((title+summary).encode()).hexdigest()}

class DatedList(HTMLParser):
    def __init__(self):super().__init__();self.entries=[];self.row=None;self.link=None;self.parts=[]
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag=='li':self.row={'parts':[],'links':[]}
        if tag=='a' and self.row is not None:self.link=d.get('href');self.parts=[]
    def handle_data(self,data):
        if self.row is not None:self.row['parts'].append(data)
        if self.link:self.parts.append(data)
    def handle_endtag(self,tag):
        if tag=='a' and self.link:
            if self.row is not None:self.row['links'].append((self.link,''.join(self.parts)))
            self.link=None
        if tag=='li' and self.row is not None:self.entries.append(self.row);self.row=None

def parse(source,body,now):
    result=[]
    if source=='wallstreetcn':
        payload=json.loads(body)
        if payload.get('code')!=20000:raise ValueError('reporting API did not return success')
        for row in payload['data']['items']:
            content=plain(row.get('content_text') or row.get('content') or '')
            # Require a China context for international flashes; do not turn a global ticker into the China desk.
            if not re.search('中国|中方|国家统计局|财政部|海关|人民币|商务部|发展改革委|海南|人民银行',content):continue
            if re.search('涨停|涨超|创业板|沪指|板块|收盘|冲高回落',content) and not re.search('国家统计局|CPI|PPI|PMI|社融|进出口|政策',content):continue
            sentences=[x for x in content.split('。') if x.strip()]
            headline=next((x for x in sentences if re.search('商务部|统计局|海关|财政|CPI|PPI|PMI|出口|进口|社融|零售|经济|货币|住房|房地产',x) and not re.search('记者提问|主持例行记者会',x)), sentences[0] if sentences else '')
            if re.search('主持例行记者会',headline):continue
            item=normalize(source,headline[:110],row.get('uri',''),datetime.fromtimestamp(row['display_time'],timezone.utc).isoformat(),content,now)
            if item:result.append(item)
    else:
        p=DatedList();p.feed(body.decode('utf-8'));p.close()
        for row in p.entries:
            day=re.search(r'(20\d{2})[-/](\d{2})[-/](\d{2})',''.join(row['parts']))
            if not day:continue
            for href,title in row['links']:
                if not re.search(r't20\d{6}_',href):continue
                try:item=normalize(source,title,urllib.parse.urljoin(SOURCES[source]['url'],href),'-'.join(day.groups()),title,now)
                except ValueError:continue
                if item:result.append(item)
    if not result:raise ValueError('no dated macro items parsed; source not treated as an empty success')
    return list({x['canonical_url']:x for x in result}.values())

def collect(out=Path('data/news'),fetch=None,now=None):
    now=now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    def network(url):
        # curl uses native platform TLS and is available on the Windows workstation and GitHub Ubuntu runners.
        return subprocess.run(['curl','--fail','--silent','--show-error','--location','--max-time','25',url],capture_output=True,check=True).stdout
    fetch=fetch or network
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    prior=json.loads((out/'latest.json').read_text(encoding='utf-8')) if (out/'latest.json').exists() else {'items':[]}
    items={x['canonical_url']:x for x in prior['items']};statuses=[]
    for source,config in SOURCES.items():
        try:
            body=fetch(config['url']);rows=parse(source,body,now)
            for item in rows:
                if item['canonical_url'] in items:item['first_seen_at']=items[item['canonical_url']]['first_seen_at']
                items[item['canonical_url']]=item
            statuses.append({'source':source,'url':config['url'],'ok':True,'retrieved_at':now,'items':len(rows),'response_sha256':hashlib.sha256(body).hexdigest()})
        except Exception as exc:statuses.append({'source':source,'url':config['url'],'ok':False,'retrieved_at':now,'error':str(exc)[:220]})
    # Canonical URL first; literal normalized title + publication date only for same-occurrence republications.
    groups={}
    for item in sorted(items.values(),key=lambda x:stamp(x['published_at']),reverse=True):
        group=groups.setdefault(item['event_group_id'],{**item,'alternate_sources':[]})
        if group['canonical_url']!=item['canonical_url']:group['alternate_sources'].append({'publisher':item['publisher'],'url':item['canonical_url']})
    snapshot={'as_of':now,'sources':statuses,'items':list(groups.values())[:250]}
    (out/'latest.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return snapshot
