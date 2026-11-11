"""One real research chain, plus the publication/time boundary's failure cases."""
import json
from pathlib import Path

import pandas as pd

from research_editions import build_editions, completed_periods

ROOT = Path(__file__).resolve().parents[1]


def test_real_report_chain_and_fail_closed_inputs(model, built):
    editions = model['research_editions']
    assert {e['edition_type'] for e in editions} == {'weekly', 'monthly'}
    for e in editions:
        assert e['review_status'] == 'draft' and e['signer'] is None and e['approved_at'] is None
        assert len(e['chart_ids']) >= 3
        assert e['thesis_delta'] == 'pending_analyst'
        for c in e['cards']:
            assert c['latest']['ref'].startswith('obs:')
            assert c['latest']['source_url'].startswith('https://')
            if c['delta'] is not None:
                assert abs(c['delta'] - (c['latest']['value']-c['prior']['value'])) < 1e-7
        exported = json.loads((built / f"data/research/{e['edition_id']}.json").read_text())
        assert exported['changes'] == e['changes']
        for loc in ('en', 'zh'):
            html = (built / loc / (e['edition_id']+'.html')).read_text()
            assert '<svg ' in html and 'data/research/' in html
            assert e['cards'][0]['latest']['source_url'] in html
            assert f'../{ "zh" if loc == "en" else "en"}/{e["edition_id"]}.html' in html
            index = (built / loc / 'research.html').read_text()
            assert e['edition_id']+'.html' in index
    # A private/future/bad-quality value must never leak into an edition.
    h = model['observation_history'].copy()
    import pandas as pd
    invalid = []
    for overrides in ({'source_class': 'private'}, {'retrieved_at': '2099-01-01T00:00:00Z'},
                      {'release_date': '2099-01-01'}, {'quality_flag': 'suspect'}):
        row = h[h.metric_id == 'cn_ppi_yoy'].iloc[-1].to_dict()
        row.update(reference_period='2026-10', value=987654321, **overrides)
        invalid.append(row)
    h = pd.concat([h, pd.DataFrame(invalid)], ignore_index=True)
    config = {'weekly_start': '2026-11-02', 'monthly_start': '2026-10-01'}
    got = build_editions(model, h, config)
    assert '987654321' not in json.dumps(got)
    empty = build_editions(model, h.iloc[0:0], config)
    assert all(not e['changes'] and not e['chart_ids'] for e in empty)
    assert build_editions({**model, 'preview': True}, h, config) == []


def test_completed_periods_use_beijing_and_never_partial_week_or_month():
    config = {'weekly_start': '2026-10-26', 'monthly_start': '2026-10-01'}
    before = completed_periods('2026-11-01T15:59:59Z', config)
    after = completed_periods('2026-11-01T16:00:00Z', config)
    assert {e['edition_type'] for e in before} == {'monthly'}
    assert {e['edition_type'] for e in after} == {'weekly', 'monthly'}
    assert next(e for e in after if e['edition_type']=='weekly')['period_end'] == '2026-11-01'
    assert next(e for e in after if e['edition_type']=='monthly')['period_end'] == '2026-10-31'


def test_period_research_inputs_are_published_in_period_and_labelled_when_captured_late(model):
    weekly = next(e for e in model['research_editions'] if e['edition_id'] == 'macro-weekly-2026-W45')
    leads = weekly['research_inputs']
    assert leads, 'the committed 2026-11-10 bundle has material leads published in W45'
    start, end = '2026-11-01T16:00:00Z', weekly['as_of']
    for x in leads:
        assert x['triage'] in ('research_needed', 'monitor')
        assert start <= x['published_at'] and pd.Timestamp(x['published_at']) <= pd.Timestamp(end)
        assert x['source_url'].startswith('http')
        # every W45 lead was captured on/after 2026-11-09, after the BJT week closed
        assert x['retrospective'] is True
    # repetitions/irrelevant items never appear; research_needed ranks first
    assert leads[0]['triage'] == 'research_needed'
    assert len({x['event_id'] for x in leads}) == len(leads)
    # the 2026-11-09 CPI print belongs to W46, not W45
    assert not any('居民消费价格' in x['title'] for x in leads)
    # an unchanged week says so instead of repeating the price-split headline
    assert not weekly['changes'] and 'No selected indicator printed' in weekly['takeaway']['en']


def test_bundles_after_generation_or_invalid_are_ignored(model, tmp_path):
    src = json.loads((ROOT / 'research/cases/cn-nominal/inputs/2026-11-10.json').read_text())
    future = {**src, 'bundle_id': '2099-01-01', 'as_of': '2099-01-01T00:00:00Z'}
    (tmp_path / '2099-01-01.json').write_text(json.dumps(future))
    (tmp_path / 'broken.json').write_text('{"kind": "research_input_bundle"}')
    config = {'weekly_start': '2026-11-02', 'monthly_start': '2026-10-01'}
    got = build_editions(model, model['observation_history'], config, inputs_dir=tmp_path)
    assert all(e['research_inputs'] == [] for e in got)
    assert build_editions(model, model['observation_history'], config, inputs_dir=None)[0]['research_inputs'] == []


def test_series_continuity_on_the_next_completed_week(model):
    # Generation one week later (Mon 2026-11-16 BJT) adds W46 with a link back to W45 and
    # reports the indicators whose reference period moved since then (Oct CPI/PPI printed 11-09).
    later = {**model, 'built_at': '2026-11-16T00:30:00+08:00'}
    config = {'weekly_start': '2026-11-02', 'monthly_start': '2026-10-01'}
    got = {e['edition_id']: e for e in build_editions(later, model['observation_history'], config)}
    w45, w46 = got['macro-weekly-2026-W45'], got['macro-weekly-2026-W46']
    assert w45['previous_edition'] is None and w45['since_previous'] is None and w45['next_edition'] == w46['edition_id']
    assert w46['previous_edition'] == w45['edition_id'] and w46['next_edition'] is None
    moved = {m['metric_id']: m for m in w46['since_previous']}
    assert moved['cn_ppi_yoy']['from_period'] == '2026-09' and moved['cn_ppi_yoy']['to_period'] == '2026-10'
    before = {c['metric_id']: c['latest']['reference_period'] for c in w45['cards']}
    after = {c['metric_id']: c['latest']['reference_period'] for c in w46['cards']}
    assert set(moved) == {m for m in after if before.get(m) != after[m]}
    assert any('居民消费价格' in x['title'] for x in w46['research_inputs'])
    assert got['macro-monthly-2026-10']['next_edition'] is None  # November is not complete yet


def test_edition_pages_render_series_sections(built):
    for loc in ('zh', 'en'):
        html = (built / loc / 'macro-weekly-2026-W45.html').read_text()
        assert 'class="research-inputs"' in html and 'rel="noopener" lang="zh"' in html
        assert ('这是该系列的第一期' if loc == 'zh' else 'This is the first edition') in html
