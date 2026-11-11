"""One real research chain, plus the publication/time boundary's failure cases."""
import json

from research_editions import build_editions, completed_periods


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
