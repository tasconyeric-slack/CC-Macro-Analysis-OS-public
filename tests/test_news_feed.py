"""Public reporting stays source-bound and independent of the observation plane."""
import json
from pathlib import Path
from cnmacro.news_feed import collect, normalize, parse

NOW='2026-11-09T10:00:00Z'

def test_reporting_filters_future_and_irrelevant_rows():
    rows={'code':20000,'data':{'items':[{'uri':'https://wallstreetcn.com/livenews/1','display_time':1794210000,'content_text':'中国10月CPI同比上涨0.7%，国家统计局发布。'},{'uri':'https://wallstreetcn.com/livenews/2','display_time':1794210000,'content_text':'A股零售股涨停。'}]}}
    result=parse('wallstreetcn',json.dumps(rows).encode(),NOW)
    assert len(result)==1 and result[0]['topic']=='prices'
    assert result[0]['summary_zh'].startswith('中国10月CPI')
    assert normalize('ndrc','经济运行','https://www.ndrc.gov.cn/x','2099-01-01','',NOW) is None

def test_fetch_failure_preserves_the_last_real_snapshot(tmp_path):
    source=Path(__file__).resolve().parents[1]/'data/news/latest.json'
    original=json.loads(source.read_text(encoding='utf-8'))
    (tmp_path/'latest.json').write_text(json.dumps(original),encoding='utf-8')
    def failed(_):raise RuntimeError('source unavailable')
    result=collect(tmp_path,fetch=failed,now=NOW)
    assert len(result['items'])==len(original['items'])
    assert all(not s['ok'] for s in result['sources'])

def test_real_snapshot_has_three_independent_families_and_real_links():
    data=json.loads((Path(__file__).resolve().parents[1]/'data/news/latest.json').read_text(encoding='utf-8'))
    assert {s['source'] for s in data['sources'] if s['ok']}=={'mof','ndrc','wallstreetcn'}
    assert all(s['items']>0 for s in data['sources'])
    assert all(x['canonical_url'].startswith('https://') and x['published_at'] and x['summary_zh'] for x in data['items'])
    assert len({x['event_group_id'] for x in data['items']})==len(data['items'])

def test_partial_renders_real_items_and_topic_controls(model):
    from news_feed import news_context
    from build import make_env
    from cnmacro.events.store import stamp
    model={**model,'built_at':NOW}
    data=news_context(model,'zh')
    assert data['home_items'] and len(data['digest'])<=8
    html=make_env('zh').get_template('news-feed.html').render(macro_news=data,page='daily')
    assert 'data-news-topic' in html and 'data-news-period="today"' in html
    assert data['items'][0]['canonical_url'] in html

def test_same_release_collapses_but_roundup_and_followup_stay_distinct():
    from cnmacro.news_feed import occurrence_key
    assert occurrence_key('中国10月CPI同比增长0.7%',NOW,'https://one') == occurrence_key('国家统计局：10月份核心CPI同比上涨0.8%',NOW,'https://two')
    assert occurrence_key('中国10月CPI与PPI报告',NOW,'https://three') != occurrence_key('中国10月CPI同比增长0.7%',NOW,'https://one')
    assert occurrence_key('国务院通过投资政策',NOW,'https://one') != occurrence_key('财政部发布投资政策实施细则',NOW,'https://two')
