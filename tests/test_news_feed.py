"""Public macro news: free sources, prefilter, dedup, deterministic ranking, editions and pages."""
import json
from pathlib import Path
from cnmacro.news_feed import collect, normalize, parse, headline_of, SOURCES
from cnmacro import news_rank as R

NOW = '2026-11-09T10:00:00Z'


def item(title, source='wallstreetcn', published='2026-11-09T09:40:00+08:00', summary=''):
    x = normalize(source, title, 'https://' + SOURCES[source]['hosts'][0] + '/a/' + str(abs(hash(title))), published, summary or title, NOW)
    if x:
        x['content_type'], x['score'] = R.score(x)
    return x


def test_prefilter_blocks_noise_and_keeps_macro():
    rows = {'code': 20000, 'data': {'items': [
        {'uri': 'https://wallstreetcn.com/livenews/1', 'display_time': 1794210000, 'content_text': '中国10月CPI同比上涨0.7%，国家统计局发布。'},
        {'uri': 'https://wallstreetcn.com/livenews/2', 'display_time': 1794210000, 'content_text': 'A股零售股涨停。'},
        {'uri': 'https://wallstreetcn.com/livenews/3', 'display_time': 1794210000, 'content_text': '恒坤新材：董事长提议回购5000万元-1亿元公司股份。'},
        {'uri': 'https://wallstreetcn.com/livenews/4', 'display_time': 1794210000, 'content_text': '以色列财政部数据显示，10月预算赤字占GDP的3.3%。'},
        {'uri': 'https://wallstreetcn.com/livenews/5', 'display_time': 1794210000, 'content_text': '东易日盛：设立全资子公司华彧科技，注册资本5000万元，助力消费升级。'}]}}
    result = parse('wallstreetcn', json.dumps(rows).encode(), NOW)
    assert [r['topic'] for r in result] == ['prices']
    assert normalize('ndrc', '经济运行', 'https://www.ndrc.gov.cn/x', '2099-01-01', '', NOW) is None
    assert normalize('ndrc', '国家统计局任免一批司厅级干部', 'https://www.ndrc.gov.cn/y', '2026-11-08', '', NOW) is None


def test_flash_headline_uses_the_bracketed_lead():
    assert headline_of('【伊朗说美取消制裁是谈判前提】伊朗外交部发言人表示') == '伊朗说美取消制裁是谈判前提'


def test_scores_put_policy_and_releases_above_ceremony():
    rrr = item('中国人民银行决定上调金融机构外汇存款准备金率', 'pbc', '2026-11-08')
    meeting = item('中国人民银行行长潘功胜会见摩根士丹利集团董事长彭泰德', 'pbc', '2026-11-05')
    cpi = item('2026年10月份居民消费价格同比上涨0.7%', 'nbs', '2026-11-09T09:30:00+08:00')
    assert rrr['score'] > meeting['score'] and cpi['score'] >= R.THRESHOLDS['T1']
    assert all(0 <= x['score'] <= 100 for x in (rrr, meeting, cpi))


def test_same_release_groups_across_publishers_and_heat_counts_publishers_once():
    a = item('2026年10月份居民消费价格同比上涨0.7%', 'nbs', '2026-11-09T09:30:00+08:00')
    b = item('中国10月CPI同比增0.7%，中国10月PPI同比增5.7%', 'wallstreetcn', '2026-11-09T09:31:00+08:00')
    c = item('中国10月CPI同比增长0.7%', 'sina', '2026-11-09T09:32:00+08:00')
    d = item('国务院关税税则委员会关于调整对原产于美国的进口商品加征关税措施的公告', 'mof', '2026-11-09')
    groups = R.group([a, b, c, d])
    sizes = sorted(len(g) for g in groups)
    assert sizes == [1, 3]
    from cnmacro.events.store import stamp
    h = R.heat([a, b, c], stamp(NOW))
    assert abs(h - 3 * 0.5 ** (8.5 / 24)) < 0.05  # three publishers, each once, 8.5h old


def test_collect_writes_snapshot_archive_and_editions(tmp_path):
    bodies = {SOURCES['wallstreetcn']['url']: json.dumps({'code': 20000, 'data': {'items': [
        {'uri': 'https://wallstreetcn.com/livenews/9', 'display_time': 1794193800, 'content_text': '【中国10月PPI同比上涨5.7%】国家统计局数据显示，10月PPI同比上涨5.7%，创2022年6月以来最高。'}]}}).encode()}

    def fetch(url):
        if url in bodies:
            return bodies[url]
        raise RuntimeError('source unavailable')
    snap = collect(tmp_path, fetch=fetch, now=NOW)
    assert sum(s['ok'] for s in snap['sources']) == 1
    assert snap['events'] and snap['events'][0]['selected']
    assert (tmp_path / 'archive' / '2026-11.json').exists()
    eds = sorted(p.stem for p in (tmp_path / 'editions').glob('*.json'))
    assert eds == ['2026-11-09', '2026-11-10']
    # rerun with every source down keeps the archive and does not rewrite the closed edition
    closed = (tmp_path / 'editions' / '2026-11-09.json').read_text()
    snap2 = collect(tmp_path, fetch=lambda u: (_ for _ in ()).throw(RuntimeError('down')), now='2026-11-09T11:00:00Z')
    assert len(snap2['items']) == 1 and (tmp_path / 'editions' / '2026-11-09.json').read_text() == closed


def test_edition_caps_lines_per_publisher():
    from cnmacro.events.store import stamp
    items = [item(f'国务院常务会议部署第{i}项稳增长政策措施', 'mofcom', '2026-11-09T0%d:00:00+08:00' % (i % 7)) for i in range(5)]
    items = [x for x in items if x]
    events = R.build_events(items, stamp(NOW))
    ed = R.build_edition('2026-11-09', {x['item_id']: x for x in items}, events, [])
    assert sum(r['publisher'] == '商务部' for r in ed['body']) <= R.PER_PUBLISHER


def test_news_page_renders_ranked_events(model):
    from news_feed import news_context
    from build import make_env
    data = news_context({**model, 'built_at': '2026-11-09T12:00:00Z'}, 'zh')
    html = make_env('zh').get_template('news-feed.html').render(macro_news=data, page='index')
    assert data['enabled'] and 'news.html' in html
    for e in data['home_events']:
        assert e['url'] in html
