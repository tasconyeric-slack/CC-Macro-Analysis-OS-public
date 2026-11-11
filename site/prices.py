"""Deterministic price-chain dashboard and dependency-free public XLSX export."""
from __future__ import annotations

import csv
import math
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
from markupsafe import Markup

from charts import comparison_chart

CHAIN = ('cn_ppi_producer_yoy', 'cn_ppi_consumer_yoy', 'cn_core_cpi_yoy')
PMI_PRICES = {'cn_pmi_input_price', 'cn_pmi_output_price'}


def is_price(mid, item):
    return item['category'] == 'prices' or mid in PMI_PRICES


def comparison_period(groups):
    common = None
    for points in groups:
        periods = {p['period'] for p in points}
        common = periods if common is None else common & periods
    return max(common) if common else None


def month_statistics(points, period):
    values = {p['period']: p['value'] for p in points}
    current = pd.Period(period, freq='M')
    latest, prior = values.get(period), values.get(str(current-1))
    window = [v for p,v in values.items() if str(current-35) <= p <= period]
    percentile = (100 * (sum(v < latest for v in window) + .5*sum(v == latest for v in window)) / len(window)
                  if latest is not None and window else None)
    # Extremes of a nonconstant sample use the full 0–100 scale; ties use midrank.
    if latest is not None and len(set(window)) > 1:
        percentile = 100 * (sum(v < latest for v in window) + .5*(sum(v == latest for v in window)-1)) / (len(window)-1)
    return {'latest': latest, 'prior': prior, 'change': latest-prior if latest is not None and prior is not None else None,
            'percentile': percentile, 'count': len(window)}


def prices_context(model, view, explorer):
    series = model['data_portal']['series']
    groups = [series.get(mid, {}).get('points', []) for mid in CHAIN]
    common = comparison_period(groups)
    end = max((p['period'] for mid,item in series.items() if is_price(mid,item) and item['frequency']=='M' for p in item['points']), default=None)
    readings = {mid: next((p['value'] for p in points if p['period']==common), None) for mid,points in zip(CHAIN,groups)}
    ranges = []
    if common:
        for key, years in (('2y',2), ('5y',5), ('all',None)):
            start = str(pd.Period(common,freq='M')-years*12+1) if years else ''
            lines = [(view.metric_name(mid), [(p['period'],p['value']) for p in points if start <= p['period'] <= common]) for mid,points in zip(CHAIN,groups)]
            ranges.append({'key':key, 'plots':[{'size':size, 'svg':Markup(comparison_chart(lines, chart_id=f'chain-{key}-{size}',width=width,label=view.t('prices.chain_title')))} for size,width in (('wide',960),('compact',360))]})
    rows = []
    for card in explorer['cards']:
        item = series[card['id']]
        if item['frequency'] != 'M': continue
        row_period = item['points'][-1]['period'] if item['points'] else end
        comparable = item['points']
        if card['id'].startswith('cn_cpi_fuel_') and row_period and row_period >= '2026-01':
            comparable = [p for p in comparable if p['period'] >= '2026-01']
        rows.append({**card, **month_statistics(comparable,row_period), 'reading_period':row_period} if row_period else {**card,'latest':None,'prior':None,'change':None,'percentile':None,'count':0,'reading_period':None})
    return {'period':end, 'common':common, 'ranges':ranges, 'rows':rows,
            'legend':[{'name':view.metric_name(mid),'value':readings[mid]} for mid in CHAIN],
            'producer_gap':readings[CHAIN[0]]-readings[CHAIN[1]] if common else None,
            'consumer_gap':readings[CHAIN[1]]-readings[CHAIN[2]] if common else None}


def _sheet(rows):
    def column(i):
        result = ''
        while i:
            i, mod = divmod(i-1,26); result = chr(65+mod)+result
        return result
    parts = ['<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
    for r, row in enumerate(rows,1):
        parts.append(f'<row r="{r}">')
        for c,value in enumerate(row,1):
            if value is None: continue
            ref = f'{column(c)}{r}'
            if isinstance(value,(int,float)) and math.isfinite(value):
                parts.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                text = escape(str(value))
                parts.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>')
        parts.append('</row>')
    return ''.join(parts)+'</sheetData></worksheet>'


def write_price_assets(data, out):
    target = Path(out)/'data'; target.mkdir(parents=True,exist_ok=True)
    series = {mid:item for mid,item in data['series'].items() if is_price(mid,item)}
    periods = sorted({p['period'] for item in series.values() for p in item['points']})
    maps = {mid:{p['period']:p['value'] for p in item['points']} for mid,item in series.items()}
    sheets = [('Series', [['period']+list(series)]+[[p]+[maps[mid].get(p) for mid in series] for p in periods])]
    fields = ['metric_id','unit','period','value','ref','release_date','retrieved_at','source','source_code','quality_flag','limitation','inputs']
    sheets.append(('Observations', [fields]+[[mid,item['unit']]+[str(p.get(k,'')) if k=='inputs' else p.get(k) for k in fields[2:]] for mid,item in series.items() for p in item['points']]))
    from cnmacro.store import OBS_COLUMNS
    sheets.append(('Vintages', [OBS_COLUMNS]+[[row.get(k) for k in OBS_COLUMNS] for item in series.values() for row in item['vintages']]))
    sheets.append(('Definitions', [['metric_id','unit','frequency','as_of'], *[[mid,item['unit'],item.get('frequency',''),item.get('as_of','')] for mid,item in series.items()]]))
    ns = 'http://schemas.openxmlformats.org/'
    with zipfile.ZipFile(target/'prices.xlsx','w',zipfile.ZIP_DEFLATED) as book:
        book.writestr('[Content_Types].xml', f'<Types xmlns="{ns}package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'+''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,len(sheets)+1))+'</Types>')
        book.writestr('_rels/.rels', f'<Relationships xmlns="{ns}package/2006/relationships"><Relationship Id="rId1" Type="{ns}officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        book.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}spreadsheetml/2006/main" xmlns:r="{ns}officeDocument/2006/relationships"><sheets>'+''.join(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,_) in enumerate(sheets,1))+'</sheets></workbook>')
        book.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="{ns}package/2006/relationships">'+''.join(f'<Relationship Id="rId{i}" Type="{ns}officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(sheets)+1))+'</Relationships>')
        for i,(_,rows) in enumerate(sheets,1): book.writestr(f'xl/worksheets/sheet{i}.xml',_sheet(rows))
    with (target/'prices-chain.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer = csv.writer(f); writer.writerow(['period',*CHAIN])
        for period in sorted({p for mid in CHAIN for p in maps.get(mid,{})}):
            writer.writerow([period,*[maps.get(mid,{}).get(period) for mid in CHAIN]])
