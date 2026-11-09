"""China macro news intake: free public sources, macro prefilter, dedup, append-only archive.

Selective reuse of AIHOT (MIT, https://github.com/KKKKhazix/AIHOT; see NOTICE): source tiers with
per-tier selection thresholds, a pre-screen before scoring, canonical-URL + content dedup, event
heat and the daily-edition rules. Re-implemented in Python, deterministic, no model calls and no
database: snapshots and the archive are JSON files committed by the scheduled workflow.
"""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
import urllib.parse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from cnmacro.events.intake import plain
from cnmacro.events.store import stamp, BEIJING

# tier: T1 official first-hand · T2 media. kind: how the body is parsed.
SOURCES = {
    'nbs': {'url': 'https://www.stats.gov.cn/sj/zxfb/rss.xml', 'publisher': '国家统计局', 'tier': 'T1', 'kind': 'rss', 'hosts': ['www.stats.gov.cn']},
    'nbs_jd': {'url': 'https://www.stats.gov.cn/sj/sjjd/', 'publisher': '国家统计局', 'tier': 'T1', 'kind': 'html', 'hosts': ['www.stats.gov.cn']},
    'pbc': {'url': 'https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html', 'publisher': '中国人民银行', 'tier': 'T1', 'kind': 'html', 'hosts': ['www.pbc.gov.cn']},
    'mof': {'url': 'https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/', 'publisher': '财政部', 'tier': 'T1', 'kind': 'html', 'hosts': ['www.mof.gov.cn', 'gss.mof.gov.cn', 'gks.mof.gov.cn', 'yss.mof.gov.cn', 'zcgls.mof.gov.cn', 'jrs.mof.gov.cn', 'zyhj.mof.gov.cn']},
    'ndrc': {'url': 'https://www.ndrc.gov.cn/xwdt/xwfb/', 'publisher': '国家发展改革委', 'tier': 'T1', 'kind': 'html', 'hosts': ['www.ndrc.gov.cn']},
    'mofcom': {'url': 'https://www.mofcom.gov.cn/xwfb/index.html', 'publisher': '商务部', 'tier': 'T1', 'kind': 'html', 'hosts': ['www.mofcom.gov.cn']},
    'safe': {'url': 'https://www.safe.gov.cn/safe/whxw/index.html', 'publisher': '国家外汇管理局', 'tier': 'T1', 'kind': 'html', 'hosts': ['www.safe.gov.cn']},
    'nfra': {'url': 'https://www.nfra.gov.cn/cbircweb/DocInfo/SelectDocByItemIdAndChild?itemId=915&pageSize=18&pageIndex=1', 'publisher': '金融监管总局', 'tier': 'T1', 'kind': 'nfra', 'hosts': ['www.nfra.gov.cn']},
    'wallstreetcn': {'url': 'https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=100', 'publisher': '华尔街见闻', 'tier': 'T2', 'kind': 'wallstreetcn', 'hosts': ['wallstreetcn.com']},
    'sina': {'url': 'https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=60&zhibo_id=152', 'publisher': '新浪财经', 'tier': 'T2', 'kind': 'sina', 'hosts': ['finance.sina.cn', 'finance.sina.com.cn']},
    'eastmoney': {'url': 'https://np-weblist.eastmoney.com/comm/web/getFastNewsList?client=web&biz=web_724&fastColumn=102&sortEnd=&pageSize=50&req_trace=1', 'publisher': '东方财富', 'tier': 'T2', 'kind': 'eastmoney', 'hosts': ['finance.eastmoney.com']},
    'yicai': {'url': 'https://www.yicai.com/api/ajax/getjuhelist?action=news&page=1&pagesize=25', 'publisher': '第一财经', 'tier': 'T2', 'kind': 'yicai', 'hosts': ['www.yicai.com']},
    'chinanews': {'url': 'https://www.chinanews.com.cn/rss/finance.xml', 'publisher': '中国新闻网', 'tier': 'T2', 'kind': 'rss', 'hosts': ['www.chinanews.com.cn', 'www.chinanews.com']},
}

# Topic order matters: the first match wins. (zh, en, pattern, related public metrics)
TOPICS = {
    'prices': ('物价与通胀', 'Prices', r'CPI|PPI|物价|通胀|通缩|居民消费价格|工业生产者|出厂价格|猪肉价格|油价', ['cn_cpi_yoy', 'cn_ppi_yoy']),
    'credit': ('货币与信用', 'Money and credit', r'央行|人民银行|货币政策|信贷|社会融资|社融|贷款|降准|降息|LPR|再贷款|M1|M2|存款准备金|逆回购|MLF|流动性', ['cn_m1_yoy', 'cn_tsf_stock_yoy']),
    'fiscal': ('财政', 'Fiscal policy', r'财政|税收|预算|国债|专项债|政府债|特别国债|赤字|关税税则', ['cn_budget_exp_ytd_yoy', 'cn_tsf_govbond_flow']),
    'property': ('房地产', 'Property', r'房地产|楼市|商品房|住房|住宅|房价|保交房|城中村', ['cn_property_sales_area_ytd_yoy']),
    'trade': ('外贸', 'Trade', r'出口|进口|进出口|海关|外贸|贸易|关税|外汇储备|国际收支|跨境', ['cn_exports_usd_yoy', 'cn_pmi_new_export_orders']),
    'growth': ('增长与需求', 'Growth and demand', r'GDP|国内生产总值|PMI|采购经理|工业增加值|工业企业利润|消费品零售|社零|消费|固定资产投资|投资|就业|失业率|经济运行|经济形势', ['cn_rgdp_yoy', 'cn_ip_yoy', 'cn_retail_sales_yoy']),
    'policy': ('政策与改革', 'Policy', r'国务院常务会议|国常会|政治局|中央经济工作会议|十五五|稳增长|扩大内需|民营经济|改革|新质生产力|金融监管|监管总局', []),
    'markets': ('市场与汇率', 'Markets', r'人民币|汇率|中间价|国债收益率|债市|收益率|A股|沪指|上证指数|恒生指数|大宗商品|铜价|铁矿石', []),
    'global': ('海外宏观', 'Global macro', r'美联储|美国CPI|非农|美债|欧洲央行|日本央行|美国经济|美国GDP|鲍威尔', []),
}

# AIHOT prefilter: block what is clearly not macro, before any scoring.
BLOCK = re.compile(r'任免|干部|党组(?:传达|理论)|党建|巡视|网站与政务新媒体|政务新媒体检查|招聘|涨停|跌停|龙虎榜|主力资金|午评|收评|早盘|尾盘|盘中|板块|概念股|个股|股份有限公司|评级从|上调至“|下调至“|目标价|公告臻选|直播|演唱会|体育|婚|获奖|表彰')
MAX_AGE_DAYS = 30
OFFICIAL_LEAD = re.compile(r'国家统计局|统计局|央行|人民银行|商务部|财政部|海关|外汇局|发改委|发展改革委|国务院|国常会|证监会|金融监管总局|工信部|住建部|中共中央|政治局|新华社|美联储|中国|国家')
# media only: company news and foreign-country items outside the global-macro topic
CORPORATE = re.compile(r'定增|回购|董事长|总裁|股东|减持|增持|募资|募集资金|IPO|上市公司|净利润|营收|财报|股价|市值|^[^，。：]{2,10}(?:股份|集团|科技|电力|新材|药业|银行)：')
FOREIGN = re.compile(r'^(?:以色列|美国|日本|欧元区|欧盟|英国|德国|法国|韩国|印度|俄罗斯|澳大利亚|加拿大|巴西|土耳其|伊朗|乌克兰|越南|泰国|新加坡|意大利|西班牙|瑞士)')
CHINA = re.compile(r'中国|中方|我国|国务院|国家统计局|财政部|海关|人民币|商务部|发展改革委|人民银行|央行|外汇局|金融监管|证监会|全国|A股|沪|深|港股|内地')


def canonical(url, source):
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ('http', 'https') or (u.hostname or '') not in SOURCES[source]['hosts'] or u.username:
        raise ValueError('source URL outside publisher')
    return urllib.parse.urlunsplit(('https', u.netloc, u.path, '', ''))


def occurrence_key(title, published, url):
    """Only an explicit China release/period collapses differently worded headlines (kept for the site)."""
    cpi = bool(re.search(r'CPI|居民消费价格', title, re.I)); ppi = bool(re.search(r'PPI|工业生产者', title, re.I))
    period = re.search(r'(?:20\d{2}年)?(\d{1,2})月份?', title)
    china = bool(re.search('中国|国家统计局|居民消费价格|工业生产者|核心CPI', title))
    if cpi != ppi and period and china:
        at = stamp(published); month = int(period[1]); year = at.year - (month > at.month)
        return f'china-release-{"cpi" if cpi else "ppi"}-{year}-{month:02d}'
    return 'news_event_' + hashlib.sha256((stamp(published).date().isoformat() + re.sub(r'[\W_]+', '', title).lower()).encode()).hexdigest() if title else url


def classify(text):
    return next((key for key, value in TOPICS.items() if re.search(value[2], text, re.I)), None)


def headline_of(text):
    """Flash items have no title: use the lead in 【】 or the first sentence."""
    text = plain(text)
    m = re.match(r'\s*【([^】]{6,80})】', text)
    if m:
        return m[1]
    first = re.split(r'[。！？\n]', text, maxsplit=1)[0]
    first = re.sub(r'^(?:财联社|新浪财经|东方财富|格隆汇|智通财经)?\d{1,2}月\d{1,2}日(?:电|讯)?[，,]?', '', first)
    return first[:90]


def beijing(value):
    """'2026-11-09 19:12:44' (Beijing wall clock) or an ISO string → ISO with offset."""
    value = value.strip().replace('/', '-')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return value
    if 'T' not in value and '+' not in value:
        return datetime.strptime(value[:19], '%Y-%m-%d %H:%M:%S' if len(value) >= 19 else '%Y-%m-%d %H:%M').replace(tzinfo=BEIJING).isoformat()
    return value


def tidy_zh(text):
    """Collapse whitespace; drop spaces between Chinese characters (table cells, padded names)."""
    text = re.sub(r'\s+', ' ', text or '').strip()
    return re.sub(r'(?<=[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef])\s+(?=[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef])', '', text)


def passes_prefilter(item):
    title, text = item.get('title_zh', ''), item.get('title_zh', '') + ' ' + item.get('summary_zh', '')
    if BLOCK.search(title):
        return False
    if SOURCES.get(item.get('source'), {}).get('tier') == 'T2':
        lead = re.match(r'^([^，。：:]{2,12})[：:]', title)
        if (lead and not OFFICIAL_LEAD.search(lead[1])) or CORPORATE.search(title):
            return False
        if item.get('topic') != 'global' and FOREIGN.match(title):
            return False
    return True


def normalize(source, title, url, published, summary, now, language='zh'):
    title, summary = tidy_zh(plain(title)), tidy_zh(plain(summary))
    if not title or not published:
        return None
    text = title + ' ' + summary
    if BLOCK.search(title):
        return None
    topic = classify(text)
    if not topic:
        return None
    cfg = SOURCES[source]
    lead = re.match(r'^([^，。：:]{2,12})[：:]', title)
    if cfg['tier'] == 'T2' and lead and not OFFICIAL_LEAD.search(lead[1]):
        return None  # "某公司：…" / "某市：…" headlines are company or local news
    if cfg['tier'] == 'T2' and (CORPORATE.search(title) or (topic != 'global' and (not CHINA.search(text) or FOREIGN.match(title)))):
        return None
    url = canonical(url, source)
    published = beijing(published)
    at = stamp(published)
    if at > stamp(now) or (stamp(now) - at).days > MAX_AGE_DAYS:
        return None
    return {'item_id': 'news_' + hashlib.sha256(url.encode()).hexdigest()[:20],
            'kind': 'announcement' if cfg['tier'] == 'T1' else 'media',
            'title_zh': title[:180], 'title_en': None, 'publisher': cfg['publisher'], 'source': source,
            'canonical_url': url, 'published_at': published, 'publication_precision': 'second' if 'T' in published else 'date',
            'first_seen_at': now, 'retrieved_at': now, 'language': language, 'summary_zh': (summary or title)[:220],
            'source_tier': cfg['tier'], 'tier': 'EVENT', 'topic': topic, 'metric_ids': TOPICS[topic][3],
            'event_group_id': occurrence_key(title, published, url),
            'content_hash': hashlib.sha256(re.sub(r'[\W_]+', '', title + summary[:120]).encode()).hexdigest()[:16]}


class Links(HTMLParser):
    """Anchors with the text that follows them inside the same list row (for a nearby date)."""

    def __init__(self):
        super().__init__(); self.links = []; self.href = None; self.text = []; self.tail = None

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            if self.tail is not None:
                self.links.append(self.tail); self.tail = None
            self.href = dict(attrs).get('href'); self.text = []
        elif tag in ('li', 'tr') and self.tail is not None:
            self.links.append(self.tail); self.tail = None

    def handle_data(self, data):
        if self.href is not None:
            self.text.append(data)
        elif self.tail is not None:
            self.tail[2].append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.href is not None:
            self.tail = [self.href, ''.join(self.text), []]; self.href = None

    def close(self):
        super().close()
        if self.tail is not None:
            self.links.append(self.tail)


DATE = re.compile(r'(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})')


def dated_links(source, body):
    p = Links(); p.feed(body.decode('utf-8', 'ignore')); p.close()
    out = []
    for href, text, tail in p.links:
        title = re.sub(r'\s+', '', text)
        if len(title) < 8 or not re.search(r'[一-鿿]', title) or not href or href.startswith(('javascript', '#')):
            continue
        url = urllib.parse.urljoin(SOURCES[source]['url'], href)
        m = re.search(r't(20\d{2})(\d{2})(\d{2})_', url) or re.search(r'/(20\d{2})(\d{2})(\d{2})\d{6,}/', url) \
            or DATE.search(''.join(tail)[:80]) or re.search(r'/(20\d{2})/(\d{2})(\d{2})/', url)
        if not m:
            continue
        out.append((title, url, f'{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}'))
    return out


def rss_items(body):
    """Regex RSS reader: tolerant of a truncated or slightly malformed feed."""
    text = body.decode('utf-8', 'ignore')
    def g(block, tag):
        m = re.search(rf'<{tag}>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</{tag}>', block, re.S)
        return (m[1] if m else '').strip()
    for block in re.findall(r'<item>(.*?)</item>', text, re.S):
        when = g(block, 'pubTime') or g(block, 'pubDate')
        if when and not re.match(r'\d{4}-', when):
            from email.utils import parsedate_to_datetime
            when = parsedate_to_datetime(when).isoformat()
        yield g(block, 'title'), g(block, 'link'), when, g(block, 'description')


def parse(source, body, now):
    kind = SOURCES[source]['kind']; result = []
    add = lambda *a: result.append(normalize(source, *a, now))
    if kind == 'wallstreetcn':
        payload = json.loads(body)
        if payload.get('code') != 20000:
            raise ValueError('reporting API did not return success')
        for row in payload['data']['items']:
            content = plain(row.get('content_text') or row.get('content') or '')
            title = plain(row.get('title') or '') or headline_of(content)
            add(title, row.get('uri', ''), datetime.fromtimestamp(row['display_time'], timezone.utc).isoformat(), content)
    elif kind == 'sina':
        for row in json.loads(body)['result']['data']['feed']['list']:
            content = plain(row.get('rich_text', ''))
            add(headline_of(content), row.get('docurl', ''), row['create_time'], content)
    elif kind == 'eastmoney':
        for row in json.loads(body)['data']['fastNewsList']:
            add(row.get('title') or headline_of(row.get('summary', '')), f"https://finance.eastmoney.com/a/{row['code']}.html", row['showTime'], row.get('summary', ''))
    elif kind == 'yicai':
        for row in json.loads(body):
            if row.get('url'):
                add(row.get('NewsTitle', ''), urllib.parse.urljoin('https://www.yicai.com', row['url']), row.get('CreateDate', '').replace('T', ' '), row.get('NewsNotes') or '')
    elif kind == 'nfra':
        for row in json.loads(body)['data']['rows']:
            add(row['docTitle'], f"https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html?docId={row['docId']}&itemId=915", row['publishDate'], row.get('docSummary') or '')
    elif kind == 'rss':
        for title, link, when, desc in rss_items(body):
            try:
                add(title, link, when, desc)
            except ValueError:
                continue
    else:
        for title, url, day in dated_links(source, body):
            try:
                add(title, url, day, title)
            except ValueError:
                continue
    result = [x for x in result if x]
    return list({x['canonical_url']: x for x in result}.values())


def month_of(item):
    return stamp(item['published_at']).astimezone(BEIJING).strftime('%Y-%m')


def load_archive(out: Path, months=None):
    items = {}
    for f in sorted((out / 'archive').glob('*.json')):
        if months and f.stem not in months:
            continue
        for x in json.loads(f.read_text(encoding='utf-8')):
            items[x['canonical_url']] = x
    return items


def write_archive(out: Path, items):
    by_month = {}
    for x in items.values():
        by_month.setdefault(month_of(x), []).append(x)
    (out / 'archive').mkdir(parents=True, exist_ok=True)
    written = []
    for month, rows in by_month.items():
        rows.sort(key=lambda x: (stamp(x['published_at']), x['canonical_url']), reverse=True)
        f = out / 'archive' / f'{month}.json'
        text = json.dumps(rows, ensure_ascii=False, indent=0) + '\n'
        if not f.exists() or f.read_text(encoding='utf-8') != text:
            f.write_text(text, encoding='utf-8'); written.append(f)
    return written


def collect(out=Path('data/news'), fetch=None, now=None):
    """Fetch every source, merge into the archive, rank, and write the snapshot and editions."""
    from cnmacro.news_rank import rank_and_publish
    now = now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def network(url):
        import urllib.request
        ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129 Safari/537.36'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': ua, 'Accept-Language': 'zh-CN,zh;q=0.9'})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read()
        except Exception:  # some hosts accept only one client stack; curl uses the platform TLS
            return subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location', '--max-time', '25', '-A', ua, url],
                                  capture_output=True, check=True).stdout
    fetch = fetch or network
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    prior = json.loads((out / 'latest.json').read_text(encoding='utf-8')) if (out / 'latest.json').exists() else {'items': []}
    archive = load_archive(out)
    for x in prior.get('items', []):  # migrate recent items from the single-snapshot era
        if (stamp(now) - stamp(x['published_at'])).days <= MAX_AGE_DAYS:
            archive.setdefault(x['canonical_url'], x)
    # filters improve over time: re-apply the current prefilter to what is already archived
    archive = {u: x for u, x in archive.items() if passes_prefilter(x)}
    hashes = {x.get('content_hash') for x in archive.values() if x.get('content_hash')}
    statuses = []
    for source, config in SOURCES.items():
        try:
            body = fetch(config['url']); rows = parse(source, body, now); new = 0
            for item in rows:
                old = archive.get(item['canonical_url'])
                if old:
                    item['first_seen_at'] = old.get('first_seen_at', item['first_seen_at'])
                elif item['content_hash'] in hashes:
                    continue  # same text republished under another URL
                else:
                    new += 1
                archive[item['canonical_url']] = item; hashes.add(item['content_hash'])
            statuses.append({'source': source, 'publisher': config['publisher'], 'tier': config['tier'], 'url': config['url'], 'ok': True,
                             'retrieved_at': now, 'items': len(rows), 'new': new, 'response_sha256': hashlib.sha256(body).hexdigest()})
        except Exception as exc:
            statuses.append({'source': source, 'publisher': config['publisher'], 'tier': config['tier'], 'url': config['url'], 'ok': False,
                             'retrieved_at': now, 'error': str(exc)[:220]})
    write_archive(out, archive)
    return rank_and_publish(out, archive, statuses, now)
