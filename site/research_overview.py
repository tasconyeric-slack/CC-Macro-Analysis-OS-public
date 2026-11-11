"""Current factual presentation of the stable research card interface (#57).

This is a view projection, never a new edition or a signed research judgment.
"""
from copy import deepcopy

import pandas as pd

from cnmacro.store import available_at, utc_naive
from data_portal import build_data_portal, source_url
from research_editions import edition_context


def overview_context(model, v):
    editions = model.get('research_editions', [])
    if not editions:
        return None
    snapshot = deepcopy(editions[0])
    cutoff = min(utc_naive(model['built_at']), utc_naive(model['evidence_as_of']))
    history = model['observation_history']
    history = history[(pd.to_datetime(history.retrieved_at, utc=True).dt.tz_localize(None) <= cutoff)
                      & history.quality_flag.isin(['ok', 'revised'])]
    current = build_data_portal(history, model['metrics'], [], cutoff)['series']
    cards = []
    since = cutoff - pd.Timedelta(days=7)
    for card in snapshot['cards']:
        mid = card['metric_id']
        points = current.get(mid, {}).get('points', [])[-24:]
        if not points:
            continue
        c = deepcopy(card)
        c['points'] = [{'reference_period': p['period'], **p,
                        'source_url': source_url(p, model['metrics'][mid], model['sources'].get('sources', []))} for p in points]
        c['latest'] = c['points'][-1]
        prior = c['points'][-2] if len(points) > 1 else None
        adjacent = prior and pd.Period(c['latest']['reference_period'], freq=c['frequency']) - 1 == pd.Period(prior['reference_period'], freq=c['frequency'])
        c['prior'] = prior if adjacent else None
        c['delta'] = round(c['latest']['value'] - prior['value'], 8) if adjacent else None
        c['new_in_period'] = bool(since <= available_at(c['latest']) <= cutoff)
        cards.append(c)
    snapshot.update(cards=cards, as_of=cutoff.isoformat()+'Z',
                    changes=[c['metric_id'] for c in cards if c['new_in_period'] and c['delta'] != 0][:3],
                    chart_ids=[c['metric_id'] for c in cards if len(c['points']) >= 2][:5])
    result = edition_context(snapshot, v)
    result['next_releases'] = sorted([r for r in model['release_calendar']
                                      if utc_naive(r['release']) > cutoff and str(r.get('verified_on','')) <= str(cutoff)[:10]],
                                     key=lambda r: utc_naive(r['release']))[:3]
    return result
