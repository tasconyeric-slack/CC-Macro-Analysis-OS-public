"""Deterministic macro relevance scoring, event grouping, heat and daily editions.

Adapted from AIHOT (MIT, https://github.com/KKKKhazix/AIHOT; see NOTICE):
- industry/prompts/selection-score.md: five axes (significance, novelty, evidence, resonance,
  actionability) scored 0-10 and combined with per-content-type weights that sum to 10, so the
  score lands on 0-100. Here the axes come from rules instead of a model.
- industry/selection.ts: per-tier thresholds (official first-hand lower than media) and a browse floor.
- events/hot.ts: heat counts each independent publisher once in a 48-hour window, halved every 24 hours.
- docs/selection.md: daily edition covers 08:00 to 08:00 Beijing, one line per event, best source
  first, at most two lines per publisher, 12 lines plus 10 quick items, and nothing that already led
  one of the last 7 editions unless the official side acted again or 4+ publishers carried it.
"""
from __future__ import annotations
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cnmacro.events.store import stamp, BEIJING

RULE_VERSION = 'macro-rank-v1'
THRESHOLDS = {'T1': 55, 'T2': 65}
# source class → threshold floor (only raises): general-interest feeds carry features and op-eds
CLASS_FLOOR = {'chinanews': 76, 'yicai': 70}
BROWSE_FLOOR = 35
HEAT_WINDOW_H, HALF_LIFE_H = 48, 24
SNAPSHOT_DAYS = 7
EDITION_BODY, EDITION_QUICK, PER_PUBLISHER, REPEAT_EDITIONS = 12, 10, 2, 7

TYPES = {
    'data_release': r'(?:同比|环比|比上年|比上月|累计)(?:增长|下降|上涨|持平|回落|上升)|公布.{0,20}(?:数据|情况)|居民消费价格|工业生产者|采购经理指数|外汇储备规模|社会融资规模|金融统计数据|国内生产总值|工业增加值|消费品零售总额|固定资产投资|工业企业利润|进出口',
    'policy_action': r'国务院常务会议|政治局会议|中央经济工作会议|中央财经委员会|印发|出台|发布.{0,12}(?:通知|意见|办法|方案|规定|公告)|降准|降息|下调|上调|加征|暂停实施|调整.{0,8}关税|特别国债|专项债|设立|启动|实施.{0,6}(?:措施|政策)|批复|发行',
    'meeting': r'会议|座谈会|讲话|会见|调研|出席|主持|发布会|访问|论坛|峰会',
    'market': r'汇率|中间价|收益率|指数|期货|人民币兑|收于|报\d',
    'commentary': r'解读|点评|认为|表示|分析|预计|评论|专家|观点',
}
WEIGHTS = {  # sig, nov, cred, reson, act — each row sums to 10
    'data_release': (3, 3, 2, 1, 1), 'policy_action': (4, 2, 2, 1, 1), 'meeting': (3, 2, 2, 2, 1),
    'market': (2, 3, 1, 2, 2), 'commentary': (2, 3, 1, 3, 1), 'other': (3, 2, 1, 3, 1)}
SIG_BASE = {'data_release': 7, 'policy_action': 7, 'meeting': 4, 'market': 4, 'commentary': 3, 'other': 3}
ACT = {'data_release': 8, 'policy_action': 7, 'market': 6, 'meeting': 3, 'commentary': 4, 'other': 3}
RESON = {'prices': 8, 'credit': 8, 'fiscal': 8, 'growth': 8, 'policy': 8, 'trade': 7, 'property': 7, 'markets': 6, 'global': 5}
TOP_ACTORS = r'国务院|中共中央|政治局|国常会|国务院常务会议|总理|国家主席|中央经济工作会议|央行行长|人民银行行长|财政部部长'
INSTRUMENT = r'存款准备金率|降准|降息|LPR|贷款市场报价利率|政策利率|关税|特别国债|专项债额度|赤字率|逆回购利率|MLF'
CEREMONIAL = r'会见|会谈|签署.{0,10}(?:合作|备忘录)|出席.{0,12}(?:论坛|峰会|开幕|博览会)|消费月|博览会|活动|启动仪式|调研'
CORE = r'存款准备金率|GDP|国内生产总值|CPI|PPI|PMI|社融|社会融资|M2|M1|LPR|降准|降息|关税|专项债|特别国债|外汇储备|进出口|工业增加值|消费品零售|固定资产投资|工业企业利润|房价|失业率'
OFFICIAL_ATTRIB = r'国家统计局|人民银行|央行|财政部|商务部|海关总署|外汇局|发展改革委|国务院|金融监管总局|证监会'


def content_type(text):
    return next((k for k, p in TYPES.items() if re.search(p, text)), 'other')


def axes(item):
    text = item.get('title_zh', '') + ' ' + item.get('summary_zh', '')
    title = item.get('title_zh', '')
    kind = content_type(text)
    sig = SIG_BASE[kind] + 2 * bool(re.search(TOP_ACTORS, title)) + bool(re.search(CORE, title)) + 2 * bool(re.search(INSTRUMENT, title)) \
        - 3 * bool(re.search(CEREMONIAL, title))
    if re.match(r'^(?:财政部)?[一-鿿]{2,3}(?:省|市|监管局)', title) or re.search(r'[省市]财政|监管局：', title):
        sig -= 3  # local administration, not national macro
    nov = (7 if re.search(r'\d+(?:\.\d+)?\s*(?:%|个百分点|亿|万亿|基点)', text) else 4) \
        + 2 * bool(re.search(r'首次|创.{0,6}(?:新高|新低)|以来(?:最高|最低|首次)|超预期|不及预期', text)) \
        - bool(re.search(r'将于|拟|预计|有望', title))
    cred = 9 if item.get('source_tier') == 'T1' else (7 if re.search(OFFICIAL_ATTRIB, text) else 5)
    reson = RESON.get(item.get('topic'), 5)
    act = ACT[kind]
    clamp = lambda v: max(0, min(10, v))
    return kind, tuple(clamp(v) for v in (sig, nov, cred, reson, act))


def score(item):
    kind, ax = axes(item)
    total = sum(a * w for a, w in zip(ax, WEIGHTS[kind]))
    if re.search(CEREMONIAL, item.get('title_zh', '')):
        total = min(total, 50)  # courtesy meetings, launches, forums: browse, not top stories
    return kind, total


# ---------------------------------------------------------------- grouping
def norm_title(t):
    t = re.sub(r'^【[^】]{0,12}】', '', t or '')
    return re.sub(r'[\W_]+', '', t).lower()


def bigrams(t):
    return {t[i:i + 2] for i in range(len(t) - 1)} or {t}


def numbers(t):
    return set(re.findall(r'\d+(?:\.\d+)?(?:%|个百分点|亿元|万亿元)', t))


RELEASES = [('cpi', r'CPI|居民消费价格'), ('ppi', r'PPI|工业生产者出厂'), ('pmi', r'PMI|采购经理指数'), ('gdp', r'GDP|国内生产总值'),
            ('credit', r'社会融资|社融|金融统计数据|新增人民币贷款|M2'), ('fx_reserves', r'外汇储备'), ('trade', r'进出口|出口.{0,4}同比'),
            ('ip', r'工业增加值'), ('retail', r'消费品零售'), ('fai', r'固定资产投资'), ('profits', r'工业企业利润'), ('lpr', r'LPR|贷款市场报价利率'), ('house', r'房价|商品住宅销售价格')]


def release_keys(item):
    """Same official release (indicator + month) → same event, whoever reports it."""
    title = item.get('title_zh', '')
    hits = [k for k, p in RELEASES if re.search(p, title)]
    period = re.search(r'(?:(20\d{2})年)?(\d{1,2})月(?:份|末)?', title)
    if not hits or not period or not re.search(r'中国|我国|国家统计局|全国|居民消费价格|工业生产者|人民银行|央行|外汇|海关|社会融资|贷款市场', title + item.get('summary_zh', '')[:60]):
        return []
    at = stamp(item['published_at']).astimezone(BEIJING); month = int(period[2])
    year = int(period[1]) if period[1] else at.year - (month > at.month)
    return [f'release-{h}-{year}-{month:02d}' for h in hits]


def release_key(item):
    keys = release_keys(item)
    return keys[0] if keys and len(keys) == 1 else None


def group(items, window_h=72):
    """Union-find over items: same release key, or similar titles close in time."""
    items = sorted(items, key=lambda x: stamp(x['published_at']))
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    feats = [(frozenset(release_keys(x)), bigrams(norm_title(x['title_zh'])), numbers(x['title_zh'] + x.get('summary_zh', '')[:80]), stamp(x['published_at']),
              set(re.findall(INSTRUMENT, x['title_zh'] + x.get('summary_zh', '')[:160])), bigrams(norm_title(x['title_zh'] + x.get('summary_zh', '')[:160]))) for x in items]
    by_key = {}
    for i, (keys, *_rest) in enumerate(feats):
        for key in keys:
            if key in by_key:
                parent[find(i)] = find(by_key[key])
            else:
                by_key[key] = i
    for i in range(len(items)):
        ki, bi, ni, ti, ii, wi = feats[i]
        for j in range(i - 1, -1, -1):
            kj, bj, nj, tj, ij, wj = feats[j]
            if (ti - tj).total_seconds() > window_h * 3600:
                break
            if ki and kj and not ki & kj:
                continue
            jac = len(bi & bj) / len(bi | bj)
            same_instrument = ii & ij and (ti - tj).total_seconds() <= 48 * 3600 and len(wi & wj) / len(wi | wj) >= 0.2
            if jac >= 0.5 or (jac >= 0.3 and ni & nj) or same_instrument:
                parent[find(i)] = find(j)
    groups = {}
    for i, x in enumerate(items):
        groups.setdefault(find(i), []).append(x)
    return list(groups.values())


def representative(members):
    return sorted(members, key=lambda x: (x.get('source_tier') != 'T1', -x.get('score', 0), stamp(x['published_at'])))[0]


def heat(members, now):
    first = {}
    for x in members:
        at = stamp(x['published_at']); p = x['publisher']
        if (now - at).total_seconds() <= HEAT_WINDOW_H * 3600 and (p not in first or at < first[p]):
            first[p] = at
    return round(sum(0.5 ** (max(0.0, (now - at).total_seconds()) / 3600 / HALF_LIFE_H) for at in first.values()), 3)


def event_id(members):
    key = next((release_key(x) for x in members if release_key(x)), None)
    return key or 'evt-' + sorted(members, key=lambda x: stamp(x['published_at']))[0]['item_id'][5:17]


def build_events(items, now):
    events = []
    for members in group(items):
        rep = representative(members)
        publishers = sorted({x['publisher'] for x in members})
        best = max(x['score'] for x in members)
        selected = any(x['score'] >= threshold(x) for x in members)
        h = heat(members, now)
        official = any(x.get('source_tier') == 'T1' for x in members)
        events.append({
            'event_id': event_id(members), 'topic': rep['topic'], 'title_zh': rep['title_zh'], 'summary_zh': rep.get('summary_zh', ''),
            'url': rep['canonical_url'], 'publisher': rep['publisher'], 'source_tier': rep.get('source_tier'),
            'first_at': min(x['published_at'] for x in members), 'last_at': max(x['published_at'] for x in members),
            'score': best, 'heat': h, 'publishers': publishers, 'official': official, 'selected': selected,
            'importance': round(best + 6 * math.log1p(len(publishers)) + 3 * official + 4 * h, 2),
            'items': [x['item_id'] for x in sorted(members, key=lambda x: stamp(x['published_at']))]})
    return events


# ---------------------------------------------------------------- editions
def edition_window(day):
    end = datetime.strptime(day, '%Y-%m-%d').replace(hour=8, tzinfo=BEIJING)
    return end - timedelta(days=1), end


def build_edition(day, items_by_id, events, previous):
    start, end = edition_window(day)
    inside = lambda x: start <= stamp(x['published_at']) < end
    led = {e for ed in previous[-REPEAT_EDITIONS:] for e in ed.get('lead_events', [])}
    rows = []
    for ev in events:
        window_items = [items_by_id[i] for i in ev['items'] if i in items_by_id and inside(items_by_id[i])]
        if not window_items or not ev['selected']:
            continue
        pubs = {x['publisher'] for x in window_items}
        if ev['event_id'] in led and not (any(x.get('source_tier') == 'T1' for x in window_items) or len(pubs) >= 4):
            continue
        rows.append({'event_id': ev['event_id'], 'title_zh': ev['title_zh'], 'summary_zh': ev.get('summary_zh', ''), 'url': ev['url'],
                     'publisher': ev['publisher'], 'topic': ev['topic'], 'publishers': sorted(pubs), 'score': ev['score'],
                     'rank_key': max(x['score'] for x in window_items) + 6 * math.log1p(len(pubs)) + 3 * any(x.get('source_tier') == 'T1' for x in window_items)})
    rows.sort(key=lambda r: -r['rank_key'])
    body, quick, per = [], [], {}
    for r in rows:
        if len(body) < EDITION_BODY and per.get(r['publisher'], 0) < PER_PUBLISHER:
            body.append(r); per[r['publisher']] = per.get(r['publisher'], 0) + 1
        elif len(quick) < EDITION_QUICK:
            quick.append(r)
    return {'date': day, 'window': [start.isoformat(), end.isoformat()], 'rule_version': RULE_VERSION,
            'lead_events': [r['event_id'] for r in body[:4]], 'body': body, 'quick': quick}


def write_json(path: Path, payload):
    text = json.dumps(payload, ensure_ascii=False, indent=1) + '\n'
    if not path.exists() or path.read_text(encoding='utf-8') != text:
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding='utf-8')


def threshold(item):
    return max(THRESHOLDS.get(item.get('source_tier'), 99), CLASS_FLOOR.get(item.get('source'), 0))


def rank_and_publish(out: Path, archive: dict, statuses, now_iso):
    from cnmacro.news_feed import SOURCES, tidy_zh
    now = stamp(now_iso)
    for x in archive.values():
        x['title_zh'], x['summary_zh'] = tidy_zh(x.get('title_zh')), tidy_zh(x.get('summary_zh'))
        if x.get('source') in SOURCES:
            x['source_tier'] = SOURCES[x['source']]['tier']
        x['content_type'], x['score'] = score(x)
    recent = [x for x in archive.values() if (now - stamp(x['published_at'])).days < SNAPSHOT_DAYS + 1]
    events = build_events(recent, now)
    ev_of = {i: e['event_id'] for e in events for i in e['items']}
    for x in recent:
        x['event_id'] = ev_of.get(x['item_id'])
    by_id = {x['item_id']: x for x in recent}
    # editions: today's (still open) and yesterday's; a closed edition already on disk is never rewritten
    ed_dir = out / 'editions'
    previous = [json.loads(f.read_text(encoding='utf-8')) for f in sorted(ed_dir.glob('*.json'))] if ed_dir.exists() else []
    today = now.astimezone(BEIJING)
    first = today if today.hour >= 8 else today - timedelta(days=1)
    days = [first.date().isoformat(), (first + timedelta(days=1)).date().isoformat()]  # last closed edition, open one
    for day in days:
        f = ed_dir / f'{day}.json'
        _, end = edition_window(day)
        if f.exists() and end <= now:
            continue
        prior = [p for p in previous if p['date'] < day]
        ed = build_edition(day, by_id, events, prior)
        ed['final'] = end <= now
        write_json(f, ed)
    snapshot = {'as_of': now_iso, 'rule_version': RULE_VERSION, 'thresholds': THRESHOLDS, 'browse_floor': BROWSE_FLOOR, 'sources': statuses,
                'events': sorted(events, key=lambda e: -e['importance']),
                'items': sorted(recent, key=lambda x: stamp(x['published_at']), reverse=True)}
    write_json(out / 'latest.json', snapshot)
    return snapshot
