"""Optional model enrichment for News: an English headline and a short "Why it matters" per selected event.

Owner decision (docs/PRODUCT_STRATEGY.md section 0, issue #34): DeepSeek may translate headlines and explain
already-collected facts. It is an enrichment layer, never part of fact ingestion, ranking or research judgment.

Two Owner kill switches, both GitHub repository variables read in .github/workflows/news.yml:
- NEWS_AI_ENABLED          exactly "true" allows model calls. Anything else (unset, "false", "TRUE", "1") means zero HTTP calls.
- NEWS_AI_DISPLAY_ENABLED  exactly "true" lets the site show model text. Unset means "same as NEWS_AI_ENABLED".
The API key is the secret DEEPSEEK_API_KEY. It is read by the client from the environment, never stored or printed here.

The deterministic pipeline imports nothing from the Copilot unless calls are enabled, and every failure fails open:
the run still collects, ranks, publishes editions and builds the site, just without model text.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from cnmacro.events.store import stamp

PROMPT_VERSION = 'news-ai-prompt/2'
CACHE_VERSION = 2
CACHE_NAME = 'ai_cache.json'
DEFAULT_MODEL = 'deepseek-flash'
DEFAULT_MAX_ITEMS = 12
MAX_ITEMS_CEILING = 60
BATCH = 4                 # items per request: the system prompt is paid once per call
SUMMARY_CHARS = 220
WINDOW_H = 72             # only events that moved in the last three days are worth a call
MAX_TOKENS = 2000
TIMEOUT_S = 60
FIELDS = ('title_en', 'why_zh', 'why_en')
# Peak-hour, cache-miss list prices in USD per 1M tokens (https://api-docs.deepseek.com/quick_start/pricing/, checked 2026-11-09).
# Actual billing can be lower (off-peak halves it, cache hits are cheaper), so the figure is an upper bound.
PRICES = {'deepseek-flash': (0.30, 0.006, 1.20), 'deepseek-v4-pro': (1.32, 0.044, 3.96)}  # miss, cache hit, output
COST_BASIS = 'peak list price, cache miss: upper bound'

SYSTEM = f'''You prepare headlines for a bilingual China-macro news page. For every item in the input produce:
- title_en: a faithful English rendering of title_zh only. Sentence case, at most 22 words, no publisher name.
- why_zh: ONE Chinese sentence, at most 70 characters, saying why a reader following China's economy should care.
- why_en: the same point as ONE English sentence, at most 40 words.
Hard rules:
1. Use only what the item states. Add no number, date, year, name, organisation, cause, forecast or market view that the item does not contain.
2. Copy every number, unit, date, name, attribution and hedge exactly. Keep certainty and policy modality unchanged ("plans to" is not "will"). Write numbers as digits.
3. No investment advice, no price predictions, no probabilities, no claim about market consensus.
4. If a field cannot be written without breaking a rule, return an empty string for that field.
5. Reply with one JSON object and nothing else, no markdown: {{"items":[{{"id":"<id from the input>","title_en":"...","why_zh":"...","why_en":"..."}}]}}
Prompt version: {PROMPT_VERSION}.'''


# ---------------------------------------------------------------- switches
@dataclass(frozen=True)
class Settings:
    enabled: bool
    display: bool
    model: str
    max_items: int


def settings(env=None) -> Settings:
    """Read the Owner switches. Calls are on only for the exact string "true"; a bad value never turns them on."""
    env = os.environ if env is None else env
    enabled = env.get('NEWS_AI_ENABLED') == 'true'
    shown = (env.get('NEWS_AI_DISPLAY_ENABLED') or '').strip()
    display = enabled if not shown else shown == 'true'
    try:
        cap = int((env.get('NEWS_AI_MAX_ITEMS') or '').strip() or DEFAULT_MAX_ITEMS)
    except ValueError:
        cap = DEFAULT_MAX_ITEMS
    return Settings(enabled, display, (env.get('NEWS_AI_MODEL') or '').strip() or DEFAULT_MODEL, max(0, min(cap, MAX_ITEMS_CEILING)))


# ---------------------------------------------------------------- cache
def load_cache(out) -> dict:
    f = Path(out) / CACHE_NAME
    try:
        cache = json.loads(f.read_text(encoding='utf-8'))
        if cache.get('version') == CACHE_VERSION and isinstance(cache.get('entries'), dict):
            return cache
    except (OSError, ValueError, AttributeError):
        pass
    return {'version': CACHE_VERSION, 'entries': {}}


def save_cache(out, cache) -> None:
    from cnmacro.news_rank import write_json
    write_json(Path(out) / CACHE_NAME, cache)


def tidy(text):
    text = re.sub(r'\s+', ' ', text or '').strip()
    return re.sub(r'(?<=[　-〿一-鿿＀-￯])\s+(?=[　-〿一-鿿＀-￯])', '', text)


def source_input(item) -> dict:
    """Exactly what the model may see: title, short summary, publisher, release time, URL. No web retrieval."""
    title = tidy(item.get('title_zh'))
    summary = tidy(item.get('summary_zh'))
    return {'title_zh': title, 'summary_zh': '' if summary == title else summary[:SUMMARY_CHARS], 'publisher': item.get('publisher', ''),
            'published_at': item.get('published_at', ''), 'url': item.get('canonical_url') or item.get('url', '')}


def content_hash(src) -> str:
    return hashlib.sha256(json.dumps(src, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:16]


def cache_key(item_id, chash, model) -> str:
    return f'{item_id}|{chash}|{PROMPT_VERSION}|{model}'


def index_cache(cache) -> dict:
    """(item_id, content_hash) -> newest entry that carries text. Used by pages that show items outside the live snapshot."""
    index = {}
    for entry in cache.get('entries', {}).values():
        if any(entry.get(k) for k in FIELDS):
            k = (entry['item_id'], entry['content_hash'])
            if k not in index or entry.get('created_at', '') >= index[k].get('created_at', ''):
                index[k] = entry
    return index


def shown_fields(entry) -> dict:
    ai = {k: entry[k] for k in FIELDS if entry.get(k)}
    return {**ai, 'model': entry.get('model'), 'prompt_version': entry.get('prompt_version')} if ai else {}


# ---------------------------------------------------------------- validation
# Chinese term in the item -> English forms that may then appear in model text. An English or Chinese proper noun the
# item does not contain (directly, or through this glossary) is treated as invented and the field is dropped.
GLOSSARY = {
    '中国': 'China Chinese', '美国': 'US United States American America', '欧盟': 'EU European Union Europe', '欧洲': 'Europe European',
    '日本': 'Japan Japanese', '韩国': 'South Korea Korean', '印度': 'India Indian', '俄罗斯': 'Russia Russian', '乌克兰': 'Ukraine',
    '伊朗': 'Iran Iranian', '以色列': 'Israel Israeli', '沙特': 'Saudi Arabia', '英国': 'UK Britain British United Kingdom',
    '德国': 'Germany German', '法国': 'France French', '加拿大': 'Canada', '澳大利亚': 'Australia', '巴西': 'Brazil', '东盟': 'ASEAN',
    '香港': 'Hong Kong', '台湾': 'Taiwan', '澳门': 'Macao', '北京': 'Beijing', '上海': 'Shanghai', '深圳': 'Shenzhen',
    '国务院': 'State Council', '国常会': 'State Council', '政治局': 'Politburo', '中共中央': 'Communist Party CPC Central Committee',
    '中央经济工作会议': 'Central Economic Work Conference', '全国人大': "National People's Congress NPC", '人大常委会': "NPC Standing Committee",
    '人民银行': "People's Bank of China PBOC", '央行': 'central bank PBOC', '国家统计局': 'National Bureau of Statistics NBS',
    '统计局': 'Statistics NBS', '财政部': 'Ministry of Finance MOF', '商务部': 'Ministry of Commerce MOFCOM', '海关总署': 'General Administration of Customs customs',
    '外汇局': 'State Administration of Foreign Exchange SAFE', '国家外汇管理局': 'State Administration of Foreign Exchange SAFE',
    '发展改革委': 'National Development and Reform Commission NDRC', '发改委': 'National Development and Reform Commission NDRC',
    '金融监管总局': 'National Financial Regulatory Administration NFRA', '证监会': 'China Securities Regulatory Commission CSRC',
    '工信部': 'Ministry of Industry and Information Technology MIIT', '住建部': 'Ministry of Housing and Urban-Rural Development',
    '税务总局': 'State Taxation Administration', '市场监管总局': 'State Administration for Market Regulation',
    '关税税则委员会': 'Customs Tariff Commission Tariff', '上交所': 'Shanghai Stock Exchange', '深交所': 'Shenzhen Stock Exchange', '港交所': 'Hong Kong Exchanges',
    '美联储': 'Federal Reserve Fed FOMC', '欧洲央行': 'European Central Bank ECB', '日本央行': 'Bank of Japan BOJ', '英国央行': 'Bank of England BOE',
    '国际货币基金组织': 'International Monetary Fund IMF', '世界银行': 'World Bank', '世贸组织': 'World Trade Organization WTO', '世界贸易组织': 'World Trade Organization WTO',
    '石油输出国组织': 'OPEC', '欧佩克': 'OPEC', '二十国集团': 'G20', '联合国': 'United Nations UN', '白宫': 'White House', '国会': 'Congress', '美国财政部': 'US Treasury',
    '人民币': 'Renminbi RMB yuan', '美元': 'US dollar USD', '欧元': 'euro EUR', '日元': 'yen JPY', '纳斯达克': 'Nasdaq', '道琼斯': 'Dow Jones',
    '一带一路': 'Belt and Road', '十五五': '15th Five-Year Plan', '十四五': '14th Five-Year Plan', '虹桥国际经济论坛': 'Hongqiao International Economic Forum',
    '印度尼西亚银行': 'Bank Indonesia', '印度尼西亚': 'Indonesia', '新加坡': 'Singapore', '泰国': 'Thailand', '越南': 'Vietnam', '马来西亚': 'Malaysia',
    '阿联酋': 'UAE United Arab Emirates', '瑞士': 'Switzerland', '意大利': 'Italy', '西班牙': 'Spain', '墨西哥': 'Mexico', '土耳其': 'Turkey',
    # romanisations of officials' names (a spelling, not a claim about their office)
    '习近平': 'Xi Jinping', '李强': 'Li Qiang', '何立峰': 'He Lifeng', '丁薛祥': 'Ding Xuexiang', '潘功胜': 'Pan Gongsheng', '蓝佛安': "Lan Fo'an",
    '王文涛': 'Wang Wentao', '郑栅洁': 'Zheng Shanjie', '李云泽': 'Li Yunze', '吴清': 'Wu Qing', '鲍威尔': 'Powell', '特朗普': 'Trump', '拜登': 'Biden',
    '耶伦': 'Yellen', '贝森特': 'Bessent', '拉加德': 'Lagarde',
}
ALWAYS_OK = {'china', 'chinese', 'cpi', 'ppi', 'gdp', 'pmi', 'lpr', 'mlf', 'yuan', 'rmb', 'cny', 'yoy', 'mom', 'qoq'}
GENERIC_ZH = {'中国'}
SYNONYMS = [('人民银行', '央行'), ('国家统计局', '统计局'), ('发展改革委', '发改委'), ('外汇局', '国家外汇管理局'), ('世贸组织', '世界贸易组织'),
            ('石油输出国组织', '欧佩克'), ('国务院', '国常会')]
MONTHS = {m: i + 1 for i, m in enumerate('january february march april may june july august september october november december'.split())}
MONTHS |= {m[:3]: i for m, i in list(MONTHS.items())} | {'sept': 9}
WEEKDAYS = {'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'}
UNITS = {'万亿': 1e12, '亿': 1e8, '万': 1e4, '千': 1e3, 'trillion': 1e12, 'tn': 1e12, 'billion': 1e9, 'bn': 1e9, 'million': 1e6, 'mn': 1e6, 'thousand': 1e3, 'k': 1e3}
NUMBER = re.compile(r'(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?:\s*(万亿|亿|万|千|trillion|billion|million|thousand|tn|bn|mn|k)(?![A-Za-z]))?', re.I)
CN_DIGIT = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
CN_NUMBER = re.compile(r'[零〇一二两三四五六七八九十]+')
CN_COUNTED = re.compile(r'([零〇一二两三四五六七八九十]+)(?=年|月|日|季度|个月|个百分点|倍|成|亿|万)')
QUARTER = re.compile(r'\b(first|second|third|fourth)[- ](quarter|half)\b', re.I)
ORDINAL = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4}
ADVICE_EN = re.compile(r'\b(buy|sell|bullish|bearish|overweight|underweight|price target|recommend\w*|probabilit\w*|likelihood|consensus|odds)\b', re.I)
ADVICE_ZH = re.compile(r'建议(?:买入|卖出|增持|减持|配置|关注)|看多|看空|买入|卖出|增持|减持|目标价|大概率|概率|一致预期|市场共识')
CJK = re.compile(r'[一-鿿]')


def cn_int(s):
    """Small Chinese numerals: 三, 十二, 二十三, 二〇二六."""
    if not s:
        return None
    if '十' in s:
        head, _, tail = s.partition('十')
        tens = CN_DIGIT.get(head, 1) if head else 1
        return tens * 10 + (CN_DIGIT.get(tail, 0) if tail else 0) if len(head) <= 1 and len(tail) <= 1 else None
    return int(''.join(str(CN_DIGIT[c]) for c in s)) if all(c in CN_DIGIT for c in s) else None


def canon(value, unit):
    return round(value * UNITS.get((unit or '').lower(), 1), 6)


def number_set(text):
    out = set()
    for m in NUMBER.finditer(text or ''):
        n = float(m[1].replace(',', '') + (m[2] or ''))
        out.add(canon(n, m[3]))
    return out


def source_numbers(src):
    # Only factual source text licenses quantities. Publication timestamps do not
    # authorize arbitrary percentages or amounts (e.g. the day "9" is not 9%).
    text = ' '.join(str(src.get(k, '')) for k in ('title_zh', 'summary_zh'))
    # Keep magnitude normalization: 100亿元 = 10 billion yuan, not 100 yuan.
    # Never whitelist the unscaled mantissa of an amount with a Chinese unit.
    nums = number_set(text)
    for m in CN_NUMBER.finditer(text):
        v = cn_int(m[0])
        if v is not None:
            nums.add(float(v))
    for m in re.finditer(r'十([一二三四五六七八九])五', text):  # 十四五, 十五五: the 14th and 15th Five-Year Plans
        nums.add(float(10 + CN_DIGIT[m[1]]))
    if '上半年' in text:
        nums.add(1.0)
    if '下半年' in text:
        nums.add(2.0)
    return nums


def output_numbers(text):
    nums = number_set(text)
    for m in re.finditer(r'(?<![A-Za-z])Q([1-4])(?!\d)|\bH([12])\b', text):
        nums.add(float(m[1] or m[2]))
    for m in QUARTER.finditer(text):
        nums.add(float(ORDINAL[m[1].lower()]))
    for m in CN_COUNTED.finditer(text):
        v = cn_int(m[1])
        if v is not None:
            nums.add(float(v))
    return nums


def norm(word):
    return re.sub(r"'s$", '', word.replace('’', "'").lower())


def group_of(term):
    return next((g for g in SYNONYMS if term in g), (term,))


def allowed_names(src):
    """Latin tokens of the item plus the English forms of glossary terms the item actually contains."""
    text = ' '.join(str(src.get(k, '')) for k in ('title_zh', 'summary_zh', 'publisher'))
    tokens = {norm(t) for t in re.findall(r"[A-Za-z][A-Za-z0-9&'’]*", text)}
    for zh, en in GLOSSARY.items():
        if any(t in text for t in group_of(zh)):
            tokens |= {norm(t) for t in re.findall(r"[A-Za-z][A-Za-z0-9&'’]*", en)}
    return tokens | ALWAYS_OK


def english_names(text):
    """Acronyms and capitalised words that do not start a sentence."""
    found = []
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9&'’]*", text):
        word = m[0]
        before = text[:m.start()].rstrip()
        starts = not before or before[-1] in '.!?:;"“(['
        if re.fullmatch(r'[QH]\d', word):
            continue  # quarters and halves are checked as numbers
        if re.fullmatch(r"[A-Z][A-Z0-9&]+", word) or (word[0].isupper() and not starts):
            found.append(norm(word))
    return found


def zh_names_missing(value, text):
    """Glossary entities named in Chinese model text that the item itself does not contain."""
    for term in sorted(GLOSSARY, key=len, reverse=True):
        if term in value and term not in GENERIC_ZH:
            if not any(t in text for t in group_of(term)):
                return True
            value = value.replace(term, ' ')
    return False


def check_field(name, value, src, allowed_nums, names):
    """None when the text is acceptable, else the short reason it was dropped."""
    english = name != 'why_zh'
    if not isinstance(value, str):
        return 'type'
    if re.search(r'https?://|[<>{}\[\]\\]|\n', value):
        return 'markup'
    if english and CJK.search(value):
        return 'language'
    if not english and not CJK.search(value):
        return 'language'
    if len(value) > {'title_en': 200, 'why_zh': 140, 'why_en': 320}[name]:
        return 'length'
    if (ADVICE_EN if english else ADVICE_ZH).search(value):
        return 'advice'
    extra = output_numbers(value) - allowed_nums
    if extra:
        return 'number'
    if english:
        low = value.lower()
        for word, month in MONTHS.items():
            if re.search(rf'\b{word}\b', low) and not (word == 'may' and not re.search(r'\bMay\b', value)) and float(month) not in allowed_nums:
                return 'date'
        if any(re.search(rf'\b{d}\b', low) for d in WEEKDAYS) and not re.search(r'周|星期', src.get('title_zh', '') + src.get('summary_zh', '')):
            return 'date'
        calendar = set(MONTHS) | WEEKDAYS
        if any(n not in names and n not in calendar for n in english_names(value)):
            return 'name'
    else:
        if zh_names_missing(value, src.get('title_zh', '') + src.get('summary_zh', '') + src.get('publisher', '')):
            return 'name'
        if any(norm(t) not in names for t in re.findall(r'[A-Za-z][A-Za-z0-9]+', value)):
            return 'name'
    return None


def validate(src, raw) -> tuple[dict, dict]:
    """(fields that passed, {field: reason} for those dropped). A field the model left empty is not a rejection."""
    nums, names = source_numbers(src), allowed_names(src)
    ok, dropped = {}, {}
    for name in FIELDS:
        value = raw.get(name) if isinstance(raw, dict) else None
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        reason = check_field(name, value.strip() if isinstance(value, str) else value, src, nums, names)
        if reason:
            dropped[name] = reason
        else:
            ok[name] = value.strip()
    return ok, dropped


def parse_reply(text) -> dict:
    """{id: raw dict}. Tolerates a markdown fence around the JSON; anything else that is not the schema raises ValueError."""
    body = re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$', '', text or '')
    data = json.loads(body)
    rows = data.get('items') if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError('no items list')
    return {str(r['id']): r for r in rows if isinstance(r, dict) and 'id' in r}


# ---------------------------------------------------------------- run
def make_client(cfg):
    """Imported here, never at module load: with calls off the news pipeline touches no Copilot code."""
    from cnmacro.copilot.llm import DeepSeekClient
    return DeepSeekClient(model=cfg.model, effort=None, max_tokens=MAX_TOKENS, timeout=TIMEOUT_S, thinking='disabled')


def new_record(cfg) -> dict:
    return {'enabled': cfg.enabled, 'display': cfg.display, 'model': cfg.model, 'prompt_version': PROMPT_VERSION, 'max_items': cfg.max_items,
            'status': 'disabled' if not cfg.enabled else 'ok', 'candidates': 0, 'cache_hits': 0, 'items_sent': 0, 'items_enriched': 0, 'items_rejected': 0,
            'calls': 0, 'input_tokens': 0, 'output_tokens': 0, 'cache_read_tokens': 0, 'estimated_cost_usd': 0.0, 'cost_basis': COST_BASIS,
            'rejections': {}, 'errors': []}


def add_usage(record, usage, model):
    miss, hit, out_price = PRICES.get(model, PRICES[DEFAULT_MODEL])
    i, o, c = (int(usage.get(k) or 0) for k in ('input_tokens', 'output_tokens', 'cache_read_input_tokens'))
    record['input_tokens'] += i
    record['output_tokens'] += o
    record['cache_read_tokens'] += c
    record['estimated_cost_usd'] = round(record['estimated_cost_usd'] + (i * miss + c * hit + o * out_price) / 1e6, 6)


def enrich(snapshot, cache, *, cfg=None, client=None, now=None, priority=()) -> dict:
    """Attach model text to the selected events of `snapshot` and return this run's usage record.

    snapshot: {'events': [...with 'rep_id'], 'items': [...]}. Selected events that moved recently are candidates, those in
    the open edition (`priority`, a list of event ids) first. Cached text is attached without a call; only unseen content
    is sent, at most cfg.max_items per run. Events get an 'ai' dict only when cfg.display is on. Never raises for a model
    or network problem: the first failed request stops further requests and the run carries on without text.
    """
    cfg = cfg or settings()
    record = new_record(cfg)
    by_id = {x['item_id']: x for x in snapshot.get('items', [])}
    rank = {e: i for i, e in enumerate(priority)}
    horizon = stamp(now) - timedelta(hours=WINDOW_H) if now else None
    pool = [e for e in snapshot.get('events', []) if e.get('selected') and e.get('rep_id') in by_id and (horizon is None or stamp(e['last_at']) >= horizon)]
    pool.sort(key=lambda e: (rank.get(e['event_id'], len(rank)), -e.get('importance', 0)))
    record['candidates'] = len(pool)
    rows, pending = [], []  # (event, item_id, source, hash, key)
    for ev in pool:
        item = by_id[ev['rep_id']]
        src = source_input(item)
        chash = content_hash(src)
        row = (ev, item['item_id'], src, chash, cache_key(item['item_id'], chash, cfg.model))
        rows.append(row)
        if row[4] in cache['entries']:
            record['cache_hits'] += 1
        elif cfg.enabled and len(pending) < cfg.max_items:
            pending.append(row)
    if pending:
        _call_all(pending, cache, cfg, client, now, record)
    if cfg.display:
        index = index_cache(cache)
        for ev, item_id, _src, chash, key in rows:
            # text made under another model or prompt version still reads fine until the next run replaces it
            ai = shown_fields(cache['entries'].get(key, {})) or shown_fields(index.get((item_id, chash), {}))
            if ai:
                ev['ai'] = ai
    return record


def _bump(record, reason):
    record['rejections'][reason] = record['rejections'].get(reason, 0) + 1


def _call_all(pending, cache, cfg, client, now, record):
    try:
        client = client or make_client(cfg)
    except Exception as exc:  # no key, unsupported model name: zero calls, the run goes on
        record['status'] = str(getattr(exc, 'kind', type(exc).__name__))[:40]
        record['errors'].append(record['status'])
        return
    for start in range(0, len(pending), BATCH):
        batch = pending[start:start + BATCH]
        user = json.dumps({'items': [{'id': item_id, **src} for _, item_id, src, _, _ in batch]}, ensure_ascii=False)
        record['items_sent'] += len(batch)
        record['calls'] += 1
        try:
            reply = client.call(SYSTEM, user)
        except Exception as exc:  # network, HTTP, quota, refusal, truncation: stop calling, keep what we have
            record['status'] = 'error'
            record['errors'].append(str(getattr(exc, 'kind', type(exc).__name__))[:40])
            return
        add_usage(record, getattr(reply, 'usage', None) or {}, cfg.model)
        try:
            parsed = parse_reply(getattr(reply, 'text', ''))
        except (ValueError, KeyError, TypeError):  # not the agreed JSON: nothing cached, so the next run may retry
            record['status'] = 'error'
            record['errors'].append('invalid_json')
            return
        for _ev, item_id, src, chash, key in batch:
            if item_id not in parsed:
                _bump(record, 'missing')
                continue
            fields, dropped = validate(src, parsed[item_id])
            for reason in dropped.values():
                _bump(record, reason)
            # The model did answer, so this content is never sent again, even if every field was dropped.
            cache['entries'][key] = {'item_id': item_id, 'content_hash': chash, 'prompt_version': PROMPT_VERSION, 'model': cfg.model,
                                     'created_at': now, **fields, **({'rejected': dropped} if dropped else {})}
            record['items_enriched' if fields else 'items_rejected'] += 1


def run(out, snapshot, *, env=None, client=None, now=None, priority=()) -> dict:
    """The pipeline hook: settings, cache, enrichment, cache write. Fails open and always returns a record."""
    cfg = settings(env)
    record = new_record(cfg)
    try:
        cache = load_cache(out)
        record = enrich(snapshot, cache, cfg=cfg, client=client, now=now, priority=priority)
        if cfg.enabled:
            save_cache(out, cache)
    except Exception as exc:
        record['status'] = 'error'
        record['errors'].append(type(exc).__name__)
    return record
