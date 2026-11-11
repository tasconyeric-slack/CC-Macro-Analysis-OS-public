"""Completed-BJT-period research drafts, from the existing public observation contract.

No LLM, signing or thesis mutation. Retrospective editions use captured public data,
not a claim to an independently archived historical vintage. One object serves both locales.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yaml
from markupsafe import Markup

from charts import line_chart
from cnmacro.store import available_at, as_of, utc_naive
from data_portal import clean_row, public_history, source_url

BJT = ZoneInfo('Asia/Shanghai')
# Editorial selection follows the existing nominal-growth question, never news popularity.
LENSES = [
    ('cn_ppi_yoy', '生产端涨价能否传到需求？', 'Can producer-price gains reach demand?',
     '出厂价格是名义修复的价格端线索；上游成本冲击也能带来同样结果，需与核心通胀及零售交叉验证。',
     'Factory-gate prices trace the price leg of nominal repair. An upstream cost shock can produce the same pattern; cross-check core inflation and retail demand.'),
    ('cn_core_cpi_yoy', '消费端是否确认价格修复？', 'Are consumer prices confirming the repair?',
     '剔除食品和能源后的价格用于检验修复广度。单一同比读数不能区分需求增强、供给变化与基数效应。',
     'Prices excluding food and energy test the breadth of repair. A single year-on-year reading cannot separate demand, supply and base effects.'),
    ('cn_pmi_new_orders', '新订单能否持续扩张？', 'Can new orders sustain expansion?',
     '新订单是前瞻需求线索；荣枯线附近的单月变动需后续活动数据确认，不等同于产出增速。',
     'New orders offer a forward demand cross-check. A monthly move around the expansion line needs confirmation in activity data and is not an output growth rate.'),
    ('cn_retail_sales_yoy', '零售能否确认内需广度？', 'Does retail confirm broader domestic demand?',
     '零售增速检验商品需求传导，但不覆盖全部消费；补贴时点与基数可能影响边际变化。',
     'Retail growth tests goods-demand transmission, but does not cover all consumption. Subsidy timing and base effects may influence the change.'),
    ('cn_property_sales_area_ytd_yoy', '地产拖累是否收窄？', 'Is the property drag narrowing?',
     '销售面积反映地产需求的数量端。累计同比可能掩盖最新单月变化，不能据此认定地产已经企稳。',
     'Sales area captures the volume side of property demand. Cumulative growth can mask the latest month and cannot establish stabilization by itself.'),
]
CREDIT = ('cn_m1_yoy', '货币活化是否形成传导？', 'Is monetary activation transmitting?',
          '货币指标需结合信贷与支出验证；统计口径、发布日期和传导时滞限制解释，不将其视为需求的直接证据。',
          'Money needs confirmation in credit and spending. Definitions, release timing and transmission lags limit interpretation; it is not direct proof of demand.')


def bi(zh, en):
    return {'zh': zh, 'en': en}


def completed_periods(now, config):
    """Monday–Sunday weeks and calendar months; end is inclusive, as_of is BJT EOD."""
    today = pd.Timestamp(now).tz_convert(BJT).date()
    week_stop = today - timedelta(days=today.weekday())
    month_stop = today.replace(day=1)
    periods = []
    for kind, start, stop in [('weekly', config['weekly_start'], week_stop),
                              ('monthly', config['monthly_start'], month_stop)]:
        day = pd.Timestamp(start).date()
        if (kind == 'weekly' and day.weekday() != 0) or (kind == 'monthly' and day.day != 1):
            raise ValueError('edition archive starts must be Monday / first of month')
        while day < stop:
            nxt = day + timedelta(days=7) if kind == 'weekly' else (pd.Timestamp(day) + pd.offsets.MonthBegin()).date()
            end = nxt - timedelta(days=1)
            if nxt <= stop:
                key = f'{day.isocalendar().year}-W{day.isocalendar().week:02}' if kind == 'weekly' else day.strftime('%Y-%m')
                periods.append({'edition_id': f'macro-{kind}-{key}', 'edition_type': kind,
                                'period_start': str(day), 'period_end': str(end),
                                'as_of': datetime.combine(nxt, datetime.min.time(), BJT).isoformat(),
                                'key': key})
            day = nxt
    # Exclusive next-midnight -> inclusive end of period, shared with existing as_of path.
    for p in periods:
        p['as_of'] = (pd.Timestamp(p['as_of']) - pd.Timedelta(seconds=1)).isoformat()
    return sorted(periods, key=lambda p: (p['period_end'], p['edition_type']), reverse=True)


def build_editions(model, history, config):
    if model['preview']:
        return []  # synthetic layout runs must never produce research artifacts
    generated = model['built_at']
    # All vintages must already be captured at generation time. Exclude bad/caliber-break points.
    history = public_history(history, model['metrics'])
    history = history[history.metric_id.isin([row[0] for row in LENSES + [CREDIT]])]
    history = history[(pd.to_datetime(history.retrieved_at, utc=True).dt.tz_localize(None) <= utc_naive(generated))
                      & history.quality_flag.isin(['ok', 'revised'])]
    editions = []
    for period in completed_periods(generated, config):
        cutoff = utc_naive(period['as_of'])
        # Existing as_of semantics, point by point: prefer held vintages; where no held vintage
        # exists, a later public capture is allowed but prominently labelled retrospective.
        available = history[history.apply(available_at, axis=1) <= cutoff] if not history.empty else history
        groups = [as_of(g, cutoff) for _, g in available.groupby(['metric_id', 'reference_period'])]
        store = pd.concat(groups, ignore_index=True) if groups else available.copy()
        cards = []
        for mid, zhq, enq, zhw, enw in LENSES + [CREDIT]:
            if mid not in model['metrics']:
                continue
            m = model['metrics'][mid]
            sub = store[store.metric_id == mid].sort_values('reference_period').tail(24)
            if sub.empty:
                continue
            points = []
            for _, r in sub.iterrows():
                p = clean_row(r)
                p.update(ref=f'obs:{mid}@{r.reference_period}', available_at=available_at(r).isoformat() + 'Z')
                p['source_url'] = source_url(p, m, model['sources'].get('sources', []))
                points.append(p)
            latest = points[-1]
            prior = points[-2] if len(points) > 1 else None
            # Difference only between adjacent reference periods, never silently across a gap.
            adjacent = prior and pd.Period(latest['reference_period'], freq=m.frequency) - 1 == pd.Period(prior['reference_period'], freq=m.frequency)
            delta = round(latest['value'] - prior['value'], 8) if adjacent else None
            latest_at = utc_naive(latest['available_at'])
            new = utc_naive(period['period_start'] + 'T00:00:00+08:00') <= latest_at <= cutoff
            cards.append({'metric_id': mid, 'question': bi(zhq, enq), 'interpretation': bi(zhw, enw),
                          'hypotheses': m.hypotheses, 'unit': m.unit, 'frequency': m.frequency,
                          'category': m.category, 'points': points, 'latest': latest,
                          'prior': prior if adjacent else None, 'delta': delta, 'new_in_period': bool(new),
                          'name': bi(m.name_zh or m.name, m.name),
                          'retrospective': any(utc_naive(p['retrieved_at']) > cutoff for p in points)})
        changes = [c['metric_id'] for c in cards if c['new_in_period'] and c['delta'] != 0][:3]
        by = {c['metric_id']: c for c in cards}
        ppi, core = by.get('cn_ppi_yoy'), by.get('cn_core_cpi_yoy')
        # Conditional, explicitly draft synthesis; no new thesis, probability or conviction.
        split = ppi and core and ppi['latest']['value'] > core['latest']['value']
        takeaway = bi('生产端与消费端价格信号分化，持续性仍需内需确认。' if split else '价格与需求需要交叉验证，现有证据尚不能独立确认持续拐点。',
                      'Producer and consumer price signals diverge; durability still needs domestic-demand confirmation.' if split else 'Prices and demand require cross-checking; the available evidence alone cannot confirm a durable turn.')
        events = []
        for e in model.get('policy', {}).get('events', []):
            if str(e['published']) <= period['period_end'] and str(e.get('reviewed', e['published'])) <= str(generated)[:10]:
                events.append({'event_id': e['event_id'], 'published': str(e['published']),
                               'title': e['title'], 'source_url': e['source']['url'], 'stage': e['stage'],
                               'hypotheses': [e['hypothesis']] + e.get('also', []),
                               'interpretation': e['interpretation'],
                               'new_in_period': period['period_start'] <= str(e['published'])})
        refreshes = [{'id': r['_file'], 'as_of': r['as_of']} for r in model.get('refreshes', [])
                     if utc_naive(period['period_start']+'T00:00:00+08:00') <= utc_naive(r['as_of']) <= cutoff]
        # A baseline is an existing frozen prior, not a new signed decision. #52 owns approval.
        prior_doc = model.get('baseline')
        if prior_doc and utc_naive(prior_doc['as_of']) > cutoff:
            prior_doc = None
        editions.append({**period, 'schema': 1, 'generated_at': generated,
                         'review_status': 'draft', 'approved_at': None, 'signer': None,
                         'takeaway': takeaway, 'changes': changes, 'cards': cards,
                         'chart_ids': [c['metric_id'] for c in cards if len(c['points']) >= 2][:5],
                         'policy_events': events[:2], 'refresh_records': refreshes,
                         'prior_view': {'document': prior_doc['_file'], 'as_of': str(prior_doc['as_of'])} if prior_doc else None,
                         'upcoming': [{**r, 'name': str(r['name'])} for r in model.get('release_calendar', [])
                                      if utc_naive(r['release']) > cutoff and str(r.get('verified_on','')) <= period['period_end']][:5],
                         'claims': [c['id'] for c in model.get('claims', {}).values()
                                    if not c['withheld'] and utc_naive(c['as_of']) <= cutoff],
                         'thesis_delta': 'pending_analyst', 'retrospective': any(c['retrospective'] for c in cards)})
    return editions


def edition_context(edition, v):
    loc = v.loc
    cards = []
    for c in edition['cards']:
        latest, prior = c['latest'], c['prior']
        unit = v.unit(c['unit'])
        number = f"{latest['value']:,.2f} {unit}"
        comparison = (f"{prior['reference_period']}：{prior['value']:,.2f}；变化 {c['delta']:+.2f}" if loc == 'zh'
                      else f"{prior['reference_period']}: {prior['value']:,.2f}; change {c['delta']:+.2f}") if prior else ('无可比上期' if loc == 'zh' else 'No adjacent comparison')
        if prior:
            comparison += ' 个百分点' if loc == 'zh' and c['unit'] == '%' else (' pp' if c['unit'] == '%' else (' 点' if loc == 'zh' else ' points'))
        svg = None
        if c['metric_id'] in edition['chart_ids']:
            svg = Markup(line_chart([(p['reference_period'], p['value']) for p in c['points']], c['unit'],
                                    50 if c['unit'].startswith('index') else 0 if c['unit'] == '%' else None,
                                    'research-'+c['metric_id'], label=c['question'][loc], monthly=c['frequency']=='M'))
        cards.append({**c, 'question': c['question'][loc], 'interpretation': c['interpretation'][loc],
                      'name': c['name'][loc], 'number': number, 'comparison': comparison, 'svg': svg})
    return {**edition, 'title': f"Macro {'Weekly' if edition['edition_type']=='weekly' else 'Monthly'} · {edition['key']}",
            'takeaway': edition['takeaway'][loc], 'cards': cards,
            'change_cards': [c for c in cards if c['metric_id'] in edition['changes']],
            'policy_events': [{**e, 'title': e['title'][loc], 'interpretation': e['interpretation'][loc]} for e in edition['policy_events']]}


def write_editions(editions, out):
    target = Path(out) / 'data/research'
    target.mkdir(parents=True, exist_ok=True)
    for edition in editions:
        (target / (edition['edition_id']+'.json')).write_text(json.dumps(edition, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    (target / 'index.json').write_text(json.dumps([{k: e[k] for k in ('edition_id', 'edition_type', 'period_start', 'period_end', 'review_status', 'as_of')} for e in editions], ensure_ascii=False, indent=2), encoding='utf-8')
