from pathlib import Path

import pytest

from cnmacro.price_releases import parse_release, release_links, append_release_rows, fetch_release
from cnmacro.store import load_observations, as_of

FIXTURES = Path(__file__).parent/'fixtures/prices'


def page(kind):
    return (FIXTURES/f'{kind}.html').read_text(encoding='utf-8')


def test_runner_verified_cache_transport_keeps_canonical_identity(monkeypatch):
    calls=[]
    def get(url,**kwargs):
        calls.append(url)
        return page('cpi').encode() if url.endswith('?v=1') else b'<script>challenge</script>'
    monkeypatch.setattr('cnmacro.ingest._get',get)
    text,transport=fetch_release('https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901421.html')
    assert '<table' in text and transport.endswith('?v=1') and len(calls)==2


def test_runner_verified_direct_official_transport_and_complete_failure(monkeypatch):
    monkeypatch.setattr('cnmacro.ingest._get',lambda url,**kw:page('ppi').encode() if url.startswith('http:') else b'<script>challenge</script>')
    _,transport=fetch_release('https://www.stats.gov.cn/sj/zxfb/202611/t20261109_1965794.html')
    assert transport=='http://www.stats.gov.cn/sj/zxfb/202611/t20261109_1965794.html'
    monkeypatch.setattr('cnmacro.ingest._get',lambda *a,**kw:b'<script>challenge</script>')
    with pytest.raises(ValueError,match='transports failed'):fetch_release('https://www.stats.gov.cn/a')


def test_existing_portal_cli_does_not_treat_release_labels_as_portal_codes(monkeypatch,capsys):
    from cnmacro import cli
    from types import SimpleNamespace
    monkeypatch.setattr('cnmacro.ingest.sync_clock',lambda:None)
    def wrong_route(*args): raise AssertionError('release labels are not NBS portal indicator codes')
    monkeypatch.setattr('cnmacro.ingest.ingest_nbs',wrong_route)
    assert cli.cmd_ingest_nbs(SimpleNamespace(agenda=False,metric='cn_cpi_food_yoy',start='2023-01'))==0
    assert 'fetch_price_releases.py' in capsys.readouterr().out


def test_real_cpi_table_columns_and_exact_food_label():
    result = parse_release(page('cpi'), '2022年3月份居民消费价格', 'https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901421.html', '2026-11-09T12:00:00Z')
    values = {r['metric_id']:r for r in result}
    assert len(values) == 14
    assert values['cn_cpi_food_yoy']['value'] == -1.5
    assert values['cn_cpi_food_mom']['value'] == -1.2
    assert values['cn_core_cpi_mom']['value'] == -.1
    assert values['cn_cpi_fuel_yoy']['value'] == 24.1
    assert values['cn_cpi_yoy']['release_date'].startswith('2022-04-11')


def test_2026_published_transport_energy_is_explicitly_marked_as_a_break():
    rows=parse_release(page('cpi-2026'),'2026年10月份居民消费价格','https://www.stats.gov.cn/sj/zxfb/202611/t20261109_1965795.html','2026-11-09T17:00:00Z')
    fuel=next(r for r in rows if r['metric_id']=='cn_cpi_fuel_yoy')
    assert fuel['value']==20.2 and 'classification break' in fuel['limitation']
    assert '交通工具用能源' in fuel['limitation']


def test_ppi_mining_raw_processing_and_pmi_current_month_only():
    rows = parse_release(page('ppi'), '2022年3月份工业生产者出厂价格', 'https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901422.html', '2026-11-09T12:00:00Z')
    values = {r['metric_id']:r['value'] for r in rows}
    assert len(values) == 12 and values['cn_ppi_mining_yoy'] == 38
    assert values['cn_ppi_raw_materials_mom'] == 2.9
    rows = parse_release(page('pmi'), '2022年3月中国采购经理指数运行情况', 'https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901418.html', '2026-11-09T12:00:00Z')
    assert {r['reference_period'] for r in rows} == {'2022-03'}
    assert {r['metric_id']:r['value'] for r in rows} == {'cn_pmi_input_price':66.1,'cn_pmi_output_price':56.7}


def test_missing_cell_stays_missing_and_schema_conflicts_fail():
    s = page('cpi').replace('<td>-0.1</td>', '<td>—</td>')
    rows = parse_release(s,'2022年3月份居民消费价格','https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901421.html','2026-11-09T12:00:00Z')
    assert 'cn_core_cpi_mom' not in {r['metric_id'] for r in rows}
    with pytest.raises(ValueError,match='header'):
        parse_release(page('cpi').replace('环比','口径改变'),'2022年3月份居民消费价格','https://www.stats.gov.cn/a','2026-11-09T12:00:00Z')
    with pytest.raises(ValueError,match='title|table'):
        parse_release('<script>challenge</script>','2026年10月份居民消费价格','https://www.stats.gov.cn/a','2026-11-09T12:00:00Z')
    with pytest.raises(ValueError,match='title'):
        parse_release(page('cpi'),'2022年4月份居民消费价格','https://www.stats.gov.cn/a','2026-11-09T12:00:00Z')
    with pytest.raises(ValueError,match='disagree'):
        parse_release(page('cpi')+page('cpi').replace('<td>24.1</td>','<td>25.1</td>'),'2022年3月份居民消费价格','https://www.stats.gov.cn/a','2026-11-09T12:00:00Z')


def test_links_accept_mixed_quotes_and_reject_non_nbs_and_commentary():
    s = '''<a href="./202611/t20261109_1.html" title='2026年10月份居民消费价格同比上涨'>x</a>
    <a href="https://evil.test/202611/t20261109_2.html">2026年10月份工业生产者出厂价格</a>
    <a href="./202611/t20261109_3.html">解读2026年10月份居民消费价格</a>'''
    links = release_links(s)
    assert len(links)==1 and links[0]['period']=='2026-10'


def test_idempotent_and_revisions_available_only_from_retrieval(tmp_path):
    rows = parse_release(page('cpi'),'2022年3月份居民消费价格','https://www.stats.gov.cn/a','2026-11-09T12:00:00Z')
    assert append_release_rows(rows,tmp_path)==14
    before = (tmp_path/'prices_release.csv').read_bytes()
    assert append_release_rows(rows,tmp_path)==0
    assert before == (tmp_path/'prices_release.csv').read_bytes()
    revised = [{**rows[0],'value':99,'retrieved_at':'2026-11-10T00:00:00Z'}]
    assert append_release_rows(revised,tmp_path)==1
    obs = load_observations(tmp_path)
    assert len(obs)==15
    assert 99 not in as_of(obs,'2026-11-09T23:00:00Z').value.tolist()


def test_legacy_release_corrections_are_kept_but_do_not_replace_portal_vintages(tmp_path):
    rows = parse_release(page('ppi'),'2022年3月份工业生产者出厂价格','https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901422.html','2026-11-09T12:00:00Z')
    original = next(r for r in rows if r['metric_id']=='cn_ppi_producer_yoy')
    assert append_release_rows([original],tmp_path)==1
    corrected = {**original,'value':12,'retrieved_at':'2026-11-10T00:00:00Z'}
    assert append_release_rows([corrected],tmp_path)==1
    portal = {**corrected,'source_code':'nbs:official-portal','value':13,'retrieved_at':'2026-11-11T00:00:00Z'}
    from cnmacro.ingest import append_rows
    append_rows([portal],tmp_path/'nbs.csv')
    assert append_release_rows([{**corrected,'retrieved_at':'2026-11-12T00:00:00Z'}],tmp_path)==0


def test_capture_times_are_compatible_with_existing_second_precision_store(tmp_path):
    rows=parse_release(page('ppi'),'2022年3月份工业生产者出厂价格','https://www.stats.gov.cn/a','2026-11-09T17:10:51.545790+00:00')
    from cnmacro.ingest import append_rows
    append_rows([{**rows[0],'reference_period':'2022-02','retrieved_at':'2026-11-09T12:00:00+00:00'}],tmp_path/'older.csv')
    append_release_rows(rows,tmp_path)
    assert len(as_of(load_observations(tmp_path),'2026-11-09T18:00:00Z'))==13


def test_new_series_have_at_least_36_published_months_with_original_lineage():
    from cnmacro.price_releases import NEW_PRICE_METRICS
    from conftest import ROOT
    obs=load_observations(ROOT/'data/demo/observations')
    for mid in NEW_PRICE_METRICS:
        rows=obs[obs.metric_id==mid]
        assert rows.reference_period.nunique()>=36,mid
        assert set(rows.source_class)=={'public'} and set(rows.source)=={'NBS'}
        assert rows.source_code.str.startswith('https://www.stats.gov.cn/sj/zxfb/').all()
        assert rows.release_date.ne('').all()
