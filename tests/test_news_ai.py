"""Optional DeepSeek enrichment for News (issue #34): switches, cache, validation, fail-open, display gate. No paid calls."""
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest
from jinja2 import ChoiceLoader, DictLoader

from cnmacro import news_ai
from cnmacro.news_feed import SOURCES, collect

KEY = 'placeholder-not-a-secret'  # not a credential; the tests prove it never reaches a file
NOW = '2026-11-09T10:00:00Z'
LATER = '2026-11-09T11:00:00Z'
BJT = timezone(timedelta(hours=8))
PPI_TITLE = '中国10月PPI同比上涨5.7%'
RRR_TITLE = '央行宣布降准0.5个百分点'
CANNED = {  # what a well-behaved model returns for each headline below
    PPI_TITLE: {'title_en': "China's October PPI rises 5.7% year on year", 'why_zh': '出厂价格走势反映工业部门的价格压力。',
                'why_en': 'Producer prices show the price pressure inside the industrial sector.'},
    RRR_TITLE: {'title_en': 'PBOC cuts the reserve requirement ratio by 0.5 percentage points from November 15',
                'why_zh': '存款准备金率下调会改变银行可用于放贷的资金。', 'why_en': 'A lower reserve requirement changes how much money banks can lend.'},
}


def epoch(hour, day=9):
    return int(datetime(2026, 11, day, hour, 0, tzinfo=BJT).timestamp())


def feed():
    """Two real-looking releases: the PPI print falls in the closed 11-09 edition, the reserve cut in the open one."""
    rows = [{'uri': 'https://wallstreetcn.com/livenews/101', 'display_time': epoch(5),
             'content_text': f'【{PPI_TITLE}】国家统计局数据显示，10月PPI同比上涨5.7%，创2022年6月以来最高。'},
            {'uri': 'https://wallstreetcn.com/livenews/102', 'display_time': epoch(10),
             'content_text': f'【{RRR_TITLE}】中国人民银行决定自2026年11月15日起下调金融机构存款准备金率0.5个百分点。'}]
    body = json.dumps({'code': 20000, 'data': {'items': rows}}).encode()

    def fetch(url):
        if url == SOURCES['wallstreetcn']['url']:
            return body
        raise RuntimeError('source unavailable')
    return fetch


class FakeApi:
    """A stand-in for urllib.request.urlopen: records every request and answers like the DeepSeek Messages API."""
    def __init__(self, answer=None, fail=None):
        self.requests, self.answer, self.fail = [], answer or self.well_behaved, fail

    @staticmethod
    def well_behaved(items):
        return {'items': [{'id': i['id'], **next(v for k, v in CANNED.items() if k in i['title_zh'])} for i in items]}

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if self.fail:
            raise self.fail
        items = json.loads(json.loads(req.data)['messages'][0]['content'])['items']
        text = self.answer(items)
        payload = json.dumps({'id': 'msg_1', 'type': 'message', 'model': 'deepseek-flash', 'role': 'assistant', 'stop_reason': 'end_turn',
                              'content': [{'type': 'text', 'text': text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)}],
                              'usage': {'input_tokens': 700, 'output_tokens': 300}}).encode()
        return _Response(payload)

    @property
    def calls(self):
        return len(self.requests)


class _Response:
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.payload


@pytest.fixture
def api(monkeypatch):
    fake = FakeApi()
    monkeypatch.setattr(urllib.request, 'urlopen', fake)
    for var in ('NEWS_AI_ENABLED', 'NEWS_AI_DISPLAY_ENABLED', 'NEWS_AI_MODEL', 'NEWS_AI_MAX_ITEMS'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('DEEPSEEK_API_KEY', KEY)
    return fake


def on(monkeypatch, **extra):
    monkeypatch.setenv('NEWS_AI_ENABLED', 'true')
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def snapshot_of(tmp_path, now=NOW):
    return collect(tmp_path, fetch=feed(), now=now)


def events_with(snap, text):
    return [e for e in snap['events'] if text in e['title_zh']]


# ---------------------------------------------------------------- switches
@pytest.mark.parametrize('value', [None, '', 'false', 'FALSE', 'True', 'TRUE', '1', 'yes', ' true', 'true '])
def test_anything_but_exactly_true_makes_no_http_call(api, monkeypatch, tmp_path, value):
    if value is not None:
        monkeypatch.setenv('NEWS_AI_ENABLED', value)
    monkeypatch.setattr(news_ai, 'make_client', lambda cfg: pytest.fail('client built while calls are off'))
    snap = snapshot_of(tmp_path)
    assert api.calls == 0
    assert snap['ai']['calls'] == 0 and snap['ai']['status'] == 'disabled' and snap['ai']['enabled'] is False
    assert snap['ai_display'] is False
    assert not (tmp_path / 'ai_cache.json').exists() and not any('ai' in e for e in snap['events'])


def test_enabled_without_a_key_makes_no_call_and_the_run_succeeds(api, monkeypatch, tmp_path):
    on(monkeypatch)
    monkeypatch.delenv('DEEPSEEK_API_KEY')
    snap = snapshot_of(tmp_path)
    assert api.calls == 0 and snap['ai']['status'] == 'no_credential' and snap['ai']['errors'] == ['no_credential']
    assert snap['events'] and (tmp_path / 'editions' / '2026-11-10.json').exists()


def test_display_defaults_to_enabled_and_can_be_set_independently():
    assert news_ai.settings({}).display is False
    assert news_ai.settings({'NEWS_AI_ENABLED': 'true'}).display is True
    assert news_ai.settings({'NEWS_AI_ENABLED': 'true', 'NEWS_AI_DISPLAY_ENABLED': 'false'}).display is False
    assert news_ai.settings({'NEWS_AI_ENABLED': 'false', 'NEWS_AI_DISPLAY_ENABLED': 'true'}).display is True
    assert news_ai.settings({'NEWS_AI_ENABLED': 'true', 'NEWS_AI_DISPLAY_ENABLED': 'TRUE'}).display is False  # only exactly "true" shows
    assert [news_ai.settings({'NEWS_AI_MAX_ITEMS': v}).max_items for v in ('', 'x', '5', '0', '-3', '9999')] == [12, 12, 5, 0, 0, news_ai.MAX_ITEMS_CEILING]
    assert news_ai.settings({'NEWS_AI_MODEL': ' deepseek-v4-pro '}).model == 'deepseek-v4-pro'


# ---------------------------------------------------------------- enrichment, cache
def test_on_with_a_fake_transport_stores_validated_text_and_caches_it(api, monkeypatch, tmp_path):
    on(monkeypatch)
    snap = snapshot_of(tmp_path)
    ai = snap['ai']
    assert api.calls == 1 and ai['calls'] == 1 and ai['items_sent'] == 2 and ai['items_enriched'] == 2 and ai['cache_hits'] == 0
    assert (ai['input_tokens'], ai['output_tokens']) == (700, 300) and ai['estimated_cost_usd'] == pytest.approx((700 * 0.30 + 300 * 1.20) / 1e6)
    assert ai['status'] == 'ok' and snap['ai_display'] is True
    body = json.loads(api.requests[0].data)
    assert body['model'] == 'deepseek-flash' and body['thinking'] == {'type': 'disabled'} and 'output_config' not in body
    sent = json.loads(body['messages'][0]['content'])['items']
    assert sorted(sent[0]) == ['id', 'published_at', 'publisher', 'summary_zh', 'title_zh', 'url']  # nothing else leaves the building
    assert all(len(i['summary_zh']) <= 220 for i in sent)
    cache = json.loads((tmp_path / 'ai_cache.json').read_text(encoding='utf-8'))
    assert len(cache['entries']) == 2
    entry = next(v for v in cache['entries'].values() if v['title_en'].startswith("China's October"))
    assert entry['prompt_version'] == news_ai.PROMPT_VERSION and entry['model'] == 'deepseek-flash' and entry['why_zh'] and entry['why_en']
    ev = events_with(snap, PPI_TITLE)[0]
    assert ev['ai']['title_en'] == entry['title_en'] and ev['title_zh'].startswith('中国10月PPI')  # the official title is never replaced
    open_edition = json.loads((tmp_path / 'editions' / '2026-11-10.json').read_text(encoding='utf-8'))
    assert [r['ai']['title_en'] for r in open_edition['body'] if r.get('ai')], 'the open edition carries the text'


def test_unchanged_content_is_not_sent_again(api, monkeypatch, tmp_path):
    on(monkeypatch)
    snapshot_of(tmp_path)
    assert api.calls == 1
    snap2 = snapshot_of(tmp_path, LATER)
    assert api.calls == 1, 'a second run over the same content must not bill again'
    assert snap2['ai']['calls'] == 0 and snap2['ai']['cache_hits'] == 2 and snap2['ai']['input_tokens'] == 0
    assert all(events_with(snap2, t)[0]['ai']['title_en'] for t in (PPI_TITLE, RRR_TITLE)), 'cached text is still attached'


def test_changed_content_or_prompt_or_model_is_a_new_key():
    src = {'title_zh': PPI_TITLE, 'summary_zh': 'a', 'publisher': 'p', 'published_at': 't', 'url': 'u'}
    h = news_ai.content_hash(src)
    assert h != news_ai.content_hash({**src, 'summary_zh': 'b'}) and h == news_ai.content_hash(dict(reversed(list(src.items()))))
    assert news_ai.cache_key('i', h, 'deepseek-flash') != news_ai.cache_key('i', h, 'deepseek-v4-pro')
    assert news_ai.PROMPT_VERSION in news_ai.cache_key('i', h, 'deepseek-flash')


def test_input_is_limited_to_title_summary_publisher_time_and_url():
    item = {'title_zh': '标题', 'summary_zh': '摘' * 400, 'publisher': '新华社', 'published_at': 't', 'canonical_url': 'https://x/1', 'score': 99, 'topic': 'prices'}
    src = news_ai.source_input(item)
    assert set(src) == {'title_zh', 'summary_zh', 'publisher', 'published_at', 'url'} and len(src['summary_zh']) == 220
    assert news_ai.source_input({**item, 'summary_zh': '标题'})['summary_zh'] == ''  # a summary that only repeats the title is not sent


def fake_events(n):
    items = [{'item_id': f'news_{i:02d}', 'title_zh': f'政策事项{chr(65 + i)}', 'summary_zh': '', 'publisher': '新华社', 'published_at': '2026-11-09T09:00:00+08:00',
              'canonical_url': f'https://x/{i}'} for i in range(n)]
    events = [{'event_id': f'evt-{i:02d}', 'rep_id': f'news_{i:02d}', 'selected': True, 'importance': float(100 - i), 'last_at': '2026-11-09T09:00:00+08:00'} for i in range(n)]
    return {'events': events, 'items': items}


class ScriptedClient:
    def __init__(self, text=None, fail=None):
        self.sent, self.text, self.fail = [], text, fail

    def call(self, system, user):
        from cnmacro.copilot.llm import Reply
        if self.fail:
            raise self.fail
        rows = json.loads(user)['items']
        self.sent.append([r['id'] for r in rows])
        text = self.text if self.text is not None else json.dumps({'items': [{'id': r['id'], 'title_en': 'Policy item', 'why_zh': '政策背景说明。', 'why_en': 'Context for policy readers.'} for r in rows]})
        return Reply(text, {}, {'input_tokens': 10, 'output_tokens': 5}, 0, 'end_turn')


def test_cap_batching_and_open_edition_priority():
    snap, client = fake_events(30), ScriptedClient()
    cfg = news_ai.settings({'NEWS_AI_ENABLED': 'true', 'NEWS_AI_MAX_ITEMS': '10'})
    cache = news_ai.load_cache('does-not-exist')
    record = news_ai.enrich(snap, cache, cfg=cfg, client=client, now=NOW, priority=['evt-29', 'evt-28'])
    sent = [i for batch in client.sent for i in batch]
    assert len(sent) == 10 and record['items_sent'] == 10 and record['calls'] == len(client.sent) == 3
    assert max(len(b) for b in client.sent) == news_ai.BATCH
    assert sent[:2] == ['news_29', 'news_28'], 'open-edition events go first'
    assert sent[2:4] == ['news_00', 'news_01'], 'then by importance'
    record2 = news_ai.enrich(snap, cache, cfg=cfg, client=client, now=NOW, priority=[])
    assert record2['cache_hits'] == 10 and record2['items_sent'] == 10 and not set(sent) & {i for b in client.sent[3:] for i in b}


def test_old_or_unselected_events_are_not_candidates():
    snap = fake_events(3)
    snap['events'][0]['selected'] = False
    snap['events'][1]['last_at'] = '2026-11-01T09:00:00+08:00'
    client = ScriptedClient()
    record = news_ai.enrich(snap, news_ai.load_cache('x'), cfg=news_ai.settings({'NEWS_AI_ENABLED': 'true'}), client=client, now=NOW)
    assert record['candidates'] == 1 and client.sent == [['news_02']]


# ---------------------------------------------------------------- failure and fail-open
@pytest.mark.parametrize('failure', [urllib.error.URLError('down'), urllib.error.HTTPError('u', 503, 'busy', {}, None), TimeoutError()])
def test_api_failure_falls_back_cleanly(api, monkeypatch, tmp_path, failure):
    on(monkeypatch)
    api.fail = failure
    snap = snapshot_of(tmp_path)
    assert api.calls == 1, 'the first failure stops the run: no hammering a dead endpoint'
    assert snap['ai']['status'] == 'error' and snap['ai']['errors'] and snap['ai']['items_enriched'] == 0
    assert not any('ai' in e for e in snap['events'])
    assert not news_ai.load_cache(tmp_path)['entries'], 'a failed call caches nothing'
    assert sum(s['ok'] for s in snap['sources']) == 1 and snap['events'] and (tmp_path / 'editions' / '2026-11-10.json').exists()
    api.fail = None
    snap2 = snapshot_of(tmp_path, LATER)
    assert snap2['ai']['status'] == 'ok' and snap2['ai']['items_enriched'] == 2, 'the next run simply tries again'


@pytest.mark.parametrize('text', ['not json at all', '{"items": "no"}', '[]', ''])
def test_unusable_replies_are_not_cached_and_do_not_break_the_run(api, monkeypatch, tmp_path, text):
    on(monkeypatch)
    api.answer = lambda items: text
    snap = snapshot_of(tmp_path)
    assert snap['ai']['status'] == 'error' and snap['ai']['items_enriched'] == 0 and not any('ai' in e for e in snap['events'])
    assert not news_ai.load_cache(tmp_path)['entries']


def test_a_fenced_json_reply_is_accepted():
    assert news_ai.parse_reply('```json\n{"items":[{"id":"a","title_en":"x"}]}\n```') == {'a': {'id': 'a', 'title_en': 'x'}}


def test_enrichment_never_raises_into_the_pipeline(monkeypatch, tmp_path):
    monkeypatch.setenv('NEWS_AI_ENABLED', 'true')
    monkeypatch.setattr(news_ai, 'enrich', lambda *a, **k: 1 / 0)
    record = news_ai.run(tmp_path, {'events': [], 'items': []}, now=NOW)
    assert record['status'] == 'error' and record['errors'] == ['ZeroDivisionError']


def test_secret_never_reaches_a_file_or_the_record(api, monkeypatch, tmp_path):
    on(monkeypatch)
    snap = snapshot_of(tmp_path)
    assert api.requests[0].get_header('X-api-key') == KEY, 'the client does send it'
    assert KEY not in json.dumps(snap)
    for f in tmp_path.rglob('*'):
        if f.is_file():
            assert KEY not in f.read_text(encoding='utf-8', errors='ignore'), f
    api.fail = urllib.error.HTTPError('u', 401, 'bad ' + KEY, {}, None)
    snap = snapshot_of(tmp_path, LATER)
    assert KEY not in json.dumps(snap)


def test_a_rejected_reply_is_cached_so_it_is_not_billed_twice(api, monkeypatch, tmp_path):
    on(monkeypatch)
    api.answer = lambda items: {'items': [{'id': i['id'], 'title_en': 'PPI rises 9.9%', 'why_zh': '', 'why_en': ''} for i in items]}
    snap = snapshot_of(tmp_path)
    assert snap['ai']['items_rejected'] == 2 and snap['ai']['rejections'] == {'number': 2} and not any('ai' in e for e in snap['events'])
    snapshot_of(tmp_path, LATER)
    assert api.calls == 1


# ---------------------------------------------------------------- closed editions
def test_closed_editions_are_never_rewritten(api, monkeypatch, tmp_path):
    snapshot_of(tmp_path)  # run 1, calls off: writes the closed 11-09 edition (PPI) and the open 11-10 one (reserve cut)
    closed = tmp_path / 'editions' / '2026-11-09.json'
    before = closed.read_bytes()
    assert PPI_TITLE in before.decode('utf-8') and b'"ai"' not in before
    on(monkeypatch)
    snap = snapshot_of(tmp_path, LATER)
    assert api.calls == 1 and events_with(snap, PPI_TITLE)[0].get('ai'), 'the PPI event itself is enriched in the live snapshot'
    assert closed.read_bytes() == before, 'but the closed edition keeps exactly what it was closed with'
    open_rows = json.loads((tmp_path / 'editions' / '2026-11-10.json').read_text(encoding='utf-8'))['body']
    assert any(r.get('ai') for r in open_rows) and 'ai' not in json.dumps(json.loads(before))
    assert json.loads(before)['body'][0]['title_zh'].startswith('中国10月PPI')


def test_display_off_keeps_model_text_out_of_the_published_snapshot(api, monkeypatch, tmp_path):
    on(monkeypatch, NEWS_AI_DISPLAY_ENABLED='false')
    snap = snapshot_of(tmp_path)
    assert snap['ai_display'] is False and snap['ai']['items_enriched'] == 2, 'calls still happen, text is cached'
    assert not any('ai' in e for e in snap['events'])
    published = (tmp_path / 'latest.json').read_text(encoding='utf-8') + (tmp_path / 'editions' / '2026-11-10.json').read_text(encoding='utf-8')
    assert not any(v in published for c in CANNED.values() for v in c.values()), 'no model text in the public snapshot or edition'
    assert '"ai"' not in json.dumps(json.loads((tmp_path / 'editions' / '2026-11-10.json').read_text(encoding='utf-8')))
    monkeypatch.setenv('NEWS_AI_DISPLAY_ENABLED', 'true')
    monkeypatch.delenv('NEWS_AI_ENABLED')  # display only: no calls, cached text comes back
    before = api.calls
    snap2 = snapshot_of(tmp_path, LATER)
    assert api.calls == before and snap2['ai_display'] is True and snap2['ai']['status'] == 'disabled'
    assert events_with(snap2, PPI_TITLE)[0]['ai']['title_en']


# ---------------------------------------------------------------- the site
def stub_env(loc):
    import build
    env = build.make_env(loc)
    env.loader = ChoiceLoader([DictLoader({'base.html': '{% block body %}{% endblock %}'}), env.loader])
    return env


@pytest.fixture
def site_data(tmp_path, monkeypatch, api):
    """A data/news folder after one AI run, wired into the site generator."""
    import news_feed
    on(monkeypatch)
    snap = snapshot_of(tmp_path)
    monkeypatch.setattr(news_feed, 'NEWS', tmp_path)
    return news_feed, tmp_path, snap


def render_all(news_feed, model, loc):
    env = stub_env(loc)
    N = news_feed.news_context({**model, 'built_at': '2026-11-09T12:00:00Z'}, loc)
    parts = [env.get_template('news-feed.html').render(macro_news=N, page='index', loc=loc),
             env.get_template('news-edition.html').render(edition=news_feed.edition_context('2026-11-10', loc), loc=loc),
             env.get_template('news-archive.html').render(archive=news_feed.archive_context('2026-11', loc), loc=loc)]
    return N, parts


def set_display(tmp_path, value):
    f = tmp_path / 'latest.json'
    data = json.loads(f.read_text(encoding='utf-8'))
    data['ai_display'] = value
    f.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def test_display_off_means_no_model_text_in_the_built_html(site_data, model):
    news_feed, tmp_path, snap = site_data
    set_display(tmp_path, False)  # the Owner's switch as the last run wrote it; the data below still contains model text
    assert CANNED[RRR_TITLE]['title_en'] in (tmp_path / 'editions' / '2026-11-10.json').read_text(encoding='utf-8')
    for loc in ('en', 'zh'):
        _, parts = render_all(news_feed, model, loc)
        html = '\n'.join(parts)
        for canned in CANNED.values():
            assert not any(canned[k] in html for k in canned)
        assert 'ai-tag' not in html and 'news-why' not in html
        assert PPI_TITLE in html or 'PPI' in html


def test_display_on_shows_the_english_title_and_a_labelled_why_it_matters(site_data, model):
    news_feed, tmp_path, snap = site_data
    N, (feed_html, edition_html, archive_html) = render_all(news_feed, model, 'en')
    ev = next(e for e in N['events'] if e['title'].startswith("China's October"))
    assert ev['title_is_zh'] is False and ev['orig'].startswith('中国10月PPI') and ev['why'] == CANNED[PPI_TITLE]['why_en']
    shown = {'feed': (feed_html, PPI_TITLE), 'edition': (edition_html, RRR_TITLE), 'archive': (archive_html, PPI_TITLE)}  # open edition 11-10 holds the reserve cut
    for name, (html, key) in shown.items():
        c = CANNED[key]
        assert c['title_en'].replace("'", '&#39;') in html, name
        assert 'Why it matters' in html and 'class="ai-tag"' in html and c['why_en'] in html and c['why_zh'] not in html, name
    assert 'title="Original: 中国10月PPI' in feed_html and 'title="Original: 央行宣布降准' in edition_html
    N_zh, (feed_zh, edition_zh, archive_zh) = render_all(news_feed, model, 'zh')
    for name, (html, key) in {'feed': (feed_zh, PPI_TITLE), 'edition': (edition_zh, RRR_TITLE), 'archive': (archive_zh, PPI_TITLE)}.items():
        c = CANNED[key]
        assert '为什么重要' in html and c['why_zh'] in html and c['why_en'] not in html and c['title_en'] not in html, name
        assert key in html, 'the Chinese page keeps the official Chinese headline'


def test_without_a_headline_the_chinese_title_is_marked_as_chinese(site_data, model):
    news_feed, tmp_path, snap = site_data
    for f in [tmp_path / 'latest.json', tmp_path / 'editions' / '2026-11-10.json', tmp_path / 'editions' / '2026-11-09.json']:
        text = f.read_text(encoding='utf-8')
        f.write_text(text.replace('"title_en"', '"title_x"'), encoding='utf-8')
    cache = json.loads((tmp_path / 'ai_cache.json').read_text(encoding='utf-8'))
    for entry in cache['entries'].values():
        entry.pop('title_en')
    (tmp_path / 'ai_cache.json').write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
    N, (feed_html, edition_html, archive_html) = render_all(news_feed, model, 'en')
    ev = next(e for e in N['events'] if 'PPI' in e['title'])
    assert ev['title'].startswith('中国10月PPI') and ev['title_is_zh'] is True and ev['why'], 'Chinese headline, but the explanation is still shown'
    assert '<h3 lang="zh-Hans"><a href' in feed_html and 'lang="zh-Hans"' in edition_html


# ---------------------------------------------------------------- validation
SRC = {'title_zh': '国家统计局：10月份PPI同比上涨5.7%，2026年前10个月累计上涨2.1%', 'summary_zh': '工业企业利润预计增长100亿元，涉及5000万元专项资金。', 'publisher': '国家统计局',
       'published_at': '2026-11-09T09:30:00+08:00', 'url': 'https://www.stats.gov.cn/x'}


def judged(**fields):
    return news_ai.validate(SRC, fields)


@pytest.mark.parametrize('field, text', [
    ('title_en', 'PPI rises 5.7% year on year in October'),
    ('title_en', 'PPI up 2.1% in the first 10 months of 2026'),
    ('title_en', 'NBS: October PPI up 5.7%'),
    ('title_en', 'Industrial profits expected to grow by 10 billion yuan'),    # 100亿 = 10 billion
    ('title_en', 'A 50 million yuan special fund is involved'),                # 5000万 = 50 million
    ('title_en', 'National Bureau of Statistics says PPI rose 5.7 percent'),
    ('why_en', 'Producer prices feed into industrial profits and the CPI-PPI gap.'),
    ('why_zh', '出厂价格影响工业企业利润，统计局数据显示PPI上涨。'),
])
def test_faithful_text_passes(field, text):
    ok, dropped = judged(**{field: text})
    assert ok == {field: text} and not dropped


@pytest.mark.parametrize('field, text, reason', [
    ('title_en', 'PPI rises 6.7% year on year', 'number'),
    ('title_en', 'Industrial profits expected to grow by 100 billion yuan', 'number'),       # unit error, 100亿 is 10 billion
    ('title_en', 'PPI up 5.7% in October 2025', 'number'),
    ('why_zh', '预计第三季度增长3%', 'number'),
    ('title_en', 'PPI rises 5.7% in December', 'date'),
    ('title_en', 'PPI rises 5.7% on Monday', 'date'),
    ('title_en', 'Federal Reserve notes PPI rises 5.7%', 'name'),
    ('title_en', 'PPI rises 5.7% says Goldman Sachs', 'name'),
    ('why_en', 'The data point to a Politburo response.', 'name'),
    ('why_zh', '这可能促使美联储调整政策。', 'name'),
    ('why_zh', '这与OPEC的决定有关。', 'name'),
    ('why_en', 'Investors should buy industrial stocks.', 'advice'),
    ('why_en', 'There is a high probability of a rate cut.', 'advice'),
    ('why_zh', '建议增持工业板块。', 'advice'),
    ('title_en', '国家统计局：PPI上涨', 'language'),
    ('why_zh', 'PPI is up', 'language'),
    ('title_en', 'See https://example.com for PPI 5.7%', 'markup'),
    ('title_en', 'x' * 400, 'length'),
])
def test_invented_numbers_dates_names_and_advice_are_dropped(field, text, reason):
    ok, dropped = judged(**{field: text})
    assert not ok and dropped == {field: reason}


@pytest.mark.parametrize('bad_title', [
    'Industrial profits grow by 100 yuan',
    'Industrial profits grow by 100 billion yuan',
])
def test_magnitude_unit_cannot_be_dropped_or_mis_scaled(bad_title):
    src = {'title_zh': '工业企业利润增长100亿元', 'summary_zh': '', 'publisher': '统计局',
           'published_at': '2026-11-09T09:30:00+08:00'}
    assert news_ai.validate(src, {'title_en': bad_title}) == ({}, {'title_en': 'number'})
    assert news_ai.validate(src, {'title_en': 'Industrial profits grow by 10 billion yuan'})[0]


def test_publication_date_numbers_never_authorize_factual_quantities():
    src = {'title_zh': '央行宣布降准', 'summary_zh': '', 'publisher': '央行',
           'published_at': '2026-11-09T09:30:00+08:00'}
    assert news_ai.validate(src, {'title_en': 'PBOC cuts reserve requirements by 9 percentage points'}) == ({}, {'title_en': 'number'})
    assert news_ai.validate(src, {'why_en': 'A 30 percent cut affects liquidity'}) == ({}, {'why_en': 'number'})
    assert news_ai.validate(src, {'title_en': 'PBOC announces reserve requirement cut'})[0]


def test_a_bad_field_is_omitted_and_the_good_ones_survive():
    ok, dropped = judged(title_en='PPI rises 5.7% in October', why_zh='出厂价格走势很重要。', why_en='PPI rose 9.9% in October.')
    assert set(ok) == {'title_en', 'why_zh'} and dropped == {'why_en': 'number'}


def test_empty_or_missing_fields_are_abstentions_not_rejections():
    ok, dropped = judged(title_en='  ', why_zh=None)
    assert ok == {} and dropped == {}
    assert news_ai.validate(SRC, 'not a dict') == ({}, {})
    assert news_ai.validate(SRC, {'title_en': ['list']}) == ({}, {'title_en': 'type'})


def test_names_in_the_item_itself_are_allowed():
    src = {**SRC, 'title_zh': '美联储主席鲍威尔表示将维持利率不变，OPEC+减产', 'summary_zh': ''}
    ok, dropped = news_ai.validate(src, {'title_en': 'Fed chair says rates unchanged as OPEC+ cuts output', 'why_zh': '美联储的利率立场影响全球流动性。'})
    assert set(ok) == {'title_en', 'why_zh'} and not dropped
    ok, dropped = news_ai.validate(src, {'title_en': 'Fed chair Yellen says rates unchanged'})
    assert dropped == {'title_en': 'name'}, 'a glossary spelling only counts when its Chinese form is in the item (耶伦 is not)'
    ok, dropped = news_ai.validate(src, {'title_en': 'Fed chair Wang Yi says rates unchanged'})
    assert dropped == {'title_en': 'name'}, 'a name that is in neither the item nor the glossary is dropped'


REAL = [  # headlines from the live feed with the kind of rendering a good model gives
    ('国务院关税税则委员会发布公告调整对原产于美国的进口商品加征关税措施', 'State Council Tariff Commission announces adjustment of additional tariffs on US imports', 'ok'),
    ('中国人民银行决定上调金融机构外汇存款准备金率', 'PBOC raises the foreign-currency reserve requirement ratio for financial institutions', 'ok'),
    ('李强主持召开国务院常务会议', 'Li Qiang chairs State Council executive meeting', 'ok'),
    ('财政部将在加拿大发行人民币绿色主权债券', 'Ministry of Finance to issue RMB green sovereign bonds in Canada', 'ok'),
    ('国家外汇管理局公布2026年10月末外汇储备规模数据', 'SAFE publishes end-October 2026 foreign exchange reserve data', 'ok'),
    ('《出口中国能力发展报告》在第九届虹桥国际经济论坛首次发布', 'Export China capability report debuts at the Hongqiao International Economic Forum', 'ok'),
    ('国家发展改革委举行奋进“十五五”系列新闻发布会介绍培育壮大新动能有关情况', 'NDRC briefs on new growth drivers at its 15th Five-Year Plan press series', 'ok'),
    ('2026年10月份工业生产者出厂价格同比上涨5.7% 环比上涨0.7%', 'Producer prices rose 5.7% year on year and 0.7% month on month in October 2026', 'ok'),
    ('中国人民银行与印度尼西亚银行举行联合工作机制工作会议', 'PBOC and Bank Indonesia hold joint working mechanism meeting', 'ok'),
    ('国家发展改革委召开“六张网”重大项目建设总体调度会议', 'NDRC convenes coordination meeting on six-network major projects', 'ok'),
    ('中国人民银行金融监管总局中国证监会召开支持资本市场两项工具座谈会', 'PBOC, regulators and CSRC hold symposium on two capital market support tools', 'ok'),
    ('财政部将在加拿大发行人民币绿色主权债券', 'Ministry of Finance to issue RMB green bonds in Toronto', 'name'),
    ('中国人民银行决定上调金融机构外汇存款准备金率', 'PBOC raises the reserve requirement ratio by 1 percentage point', 'number'),
]


@pytest.mark.parametrize('zh, en, verdict', REAL)
def test_the_validator_accepts_faithful_renderings_of_real_headlines(zh, en, verdict):
    src = {'title_zh': zh, 'summary_zh': zh, 'publisher': '国家统计局', 'published_at': '2026-11-09T09:30:00+08:00', 'url': 'u'}
    ok, dropped = news_ai.validate(src, {'title_en': en})
    assert (list(dropped.values()) or ['ok'])[0] == verdict, (en, ok, dropped)


# ---------------------------------------------------------------- the shared client
def test_deepseek_client_thinking_option_leaves_the_copilot_record_shape_alone():
    from cnmacro.copilot.llm import DeepSeekClient, ModelUnavailable
    plain = DeepSeekClient(api_key='k')
    assert 'thinking' not in plain.identity()
    assert DeepSeekClient(api_key='k', effort=None, thinking='disabled').identity()['thinking'] == 'disabled'
    with pytest.raises(ModelUnavailable):
        DeepSeekClient(api_key='k', thinking='enabled')
