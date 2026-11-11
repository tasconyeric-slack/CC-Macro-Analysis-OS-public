"""Prices must compare the same period and preserve gaps/lineage in downloads."""
import csv
import io
import json
import xml.etree.ElementTree as ET
import zipfile

import pytest

from prices import comparison_period, month_statistics, write_price_assets
from charts import comparison_chart, line_chart


def test_previous_month_and_trailing_calendar_window():
    points = [{'period': '2023-10', 'value': -99}, {'period': '2023-11', 'value': 0},
              {'period': '2026-08', 'value': 1}, {'period': '2026-10', 'value': 2}]
    row = month_statistics(points, '2026-10')
    assert row['latest'] == 2
    assert row['prior'] is None and row['change'] is None
    assert row['count'] == 3 and row['percentile'] == 100
    assert month_statistics(points, '2026-09')['latest'] is None


def test_percentile_ties_use_midrank_and_no_fake_full_history():
    row = month_statistics([{'period': '2026-09', 'value': 2}, {'period': '2026-10', 'value': 2}], '2026-10')
    assert row['percentile'] == 50 and row['count'] == 2
    assert row['change'] == 0


def test_composite_common_period_and_empty_intersection():
    groups = [[{'period': '2026-09', 'value': 1}, {'period': '2026-10', 'value': 2}],
              [{'period': '2026-09', 'value': 3}]]
    assert comparison_period(groups) == '2026-09'
    assert comparison_period(groups + [[]]) is None


def test_chart_breaks_missing_months_and_shares_one_scale():
    svg = line_chart([('2026-01', 1), ('2026-03', 3)], '%', monthly=True)
    assert svg.count('M44.0,') == 1
    assert ' L' not in svg.split('<path class="series"')[1].split('/>')[0]
    svg = comparison_chart([('A', [('2026-01', -10), ('2026-03', 10)]),
                            ('B', [('2026-01', 0), ('2026-03', 0)])], chart_id='chain')
    assert svg.count('class="series price-line-') == 2
    assert 'data-for="chain"' in svg
    assert 'A: -10.0%' in svg and 'B: 0.0%' in svg
    svg = line_chart([('2025-12',1),('2026-01',2)],'%',monthly=True,break_before=('2026-01',))
    assert ' L' not in svg.split('<path class="series"')[1].split('/>')[0]
    svg = line_chart([('2025-12',1),('2026-02',2)],'%',break_before=('2026-01',))
    assert ' L' not in svg.split('<path class="series"')[1].split('/>')[0]


def test_workbook_has_all_price_series_and_lineage_without_formula_injection(tmp_path):
    data = {'series': {'p': {'category': 'prices', 'unit': '%', 'points': [
        {'period': '2026-10', 'value': 1.2, 'source_code': '=bad()', 'ref': 'obs:p@2026-10',
         'release_date': '2026-11-09', 'retrieved_at': '2026-11-09T02:00:00Z'}], 'vintages': []},
        'private': {'category': 'credit', 'points': []}}}
    write_price_assets(data, tmp_path)
    with zipfile.ZipFile(tmp_path/'data/prices.xlsx') as book:
        for name in book.namelist():
            if name.endswith('.xml'): ET.fromstring(book.read(name))
        xml = book.read('xl/worksheets/sheet2.xml').decode()
        assert 'obs:p@2026-10' in xml and '=bad()' in xml and '<f>' not in xml
        assert 'private' not in xml
        assert '1.2' in xml


def test_prices_page_has_chain_table_exports_and_every_metric_anchor(built, model):
    for loc in ('en', 'zh'):
        page = (built/loc/'data-prices.html').read_text(encoding='utf-8')
        assert 'id="price-chain"' in page and 'id="price-month"' in page
        assert '../data/prices.xlsx' in page and '../data/prices-chain.csv' in page
        for mid in ('cn_pmi_input_price','cn_pmi_output_price'):
            assert f'id="metric-{mid}"' in page
        for mid, item in model['data_portal']['series'].items():
            if item['category'] == 'prices':
                assert f'id="metric-{mid}"' in page
    assert (built/'data/prices.xlsx').exists()
