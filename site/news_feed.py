"""Reader-facing public news: source-backed excerpts and clearly separate watch questions."""
from datetime import datetime, timezone
import json
from pathlib import Path
import localization as L
from cnmacro.news_feed import TOPICS, classify, occurrence_key
from cnmacro.events.store import stamp, BEIJING, load_items
ROOT=Path(__file__).resolve().parents[1]
LABELS={
 'zh':dict(title='宏观动态',intro='数据发布、政策进展与值得跟踪的经济变化。',today='今日',latest='最近动态',all='全部主题',digest='今日阅读线索',watch='关注点',source='阅读原文',related='相关数据',updated='更新于',empty='今日暂无新动态，以下为最近可用资料。',more='进入每日宏观',original='中文原文'),
 'en':dict(title='Macro developments',intro='Data releases, policy developments and the economic changes to watch.',today='Today',latest='Latest',all='All topics',digest='Reading brief',watch='What to watch',source='Original source',related='Related data',updated='Updated',empty='No new items today. The latest available items follow.',more='Open the Daily Desk',original='Chinese original')}
WATCH={
 'prices':('关注出厂价格变化能否传导至终端价格，对照 CPI 与 PPI 的历史趋势。','Watch whether factory-gate price changes reach consumer prices; compare the CPI and PPI trends.'),
 'credit':('结合货币与社融数据，观察政策信号是否转化为融资和实际需求。','Compare money and financing data to see whether policy signals translate into funding and demand.'),
 'fiscal':('区分政策安排与实际支出，后续关注财政支出和政府债融资的变化。','Distinguish announced policy from spending; follow fiscal expenditure and government financing.'),
 'trade':('结合出口与新出口订单，跟踪外部需求和贸易条件的变化。','Follow exports and export orders for changes in external demand and trading conditions.'),
 'property':('结合销售面积数据，观察需求变化是否具有持续性。','Compare property sales to assess whether changes in demand persist.'),
 'growth':('结合工业、零售与 GDP 数据，观察经济变化的广度与持续性。','Compare industrial output, retail sales and GDP to assess breadth and persistence.')}

def news_context(model,loc):
    enabled=not model.get('preview') and not model.get('banner') and Path(model.get('case_dir',ROOT/'research/cases/cn-nominal')).resolve()==(ROOT/'research/cases/cn-nominal').resolve()
    file=ROOT/'data/news/latest.json'
    payload=json.loads(file.read_text(encoding='utf-8')) if enabled and file.exists() else {'items':[],'as_of':None}
    cutoff=model.get('built_at') or datetime.now(timezone.utc).isoformat()
    records=list(payload['items'])
    if enabled:
        try:
            from cnmacro.events.store import load_grouped_public_items
            official=load_grouped_public_items(ROOT/'data/events',as_of=cutoff)
        except ImportError:
            official=load_items(ROOT/'data/events',as_of=cutoff)
        records.extend(official)
    records.sort(key=lambda x:1 if x.get('source_tier')=='reporting' else 0)
    unique={}
    for raw in records:
        if not raw.get('published_at') or stamp(raw['published_at'])>stamp(cutoff) or stamp(raw['first_seen_at'])>stamp(cutoff) or raw.get('status')=='rejected':continue
        topic=raw.get('topic') or classify(raw.get('title_zh','')+' '+raw.get('summary_zh',''))
        if topic not in TOPICS:continue
        key=occurrence_key(raw.get('title_zh',''),raw['published_at'],raw['canonical_url'])
        if key in unique:continue
        day=stamp(raw['published_at']).astimezone(BEIJING).date().isoformat()
        mids=raw.get('metric_ids') or TOPICS[topic][3]
        links=[]
        for mid in mids:
            metric=model.get('metrics',{}).get(mid)
            if metric is not None and getattr(metric,'category',None):links.append({'name':L.tidy(metric.name_zh if loc=='zh' else metric.name,loc),'url':f'data-{metric.category}.html#metric-{mid}'})
        unique[key]={**raw,'topic':topic,'topic_name':TOPICS[topic][0 if loc=='zh' else 1],
                     'title':L.tidy(raw.get('title_'+loc) or raw.get('title_zh') or raw.get('title',''),loc),
                     'summary':raw.get('summary_'+loc) or raw.get('summary_zh',''),
                     'original_language':loc=='en' and not raw.get('title_en'),
                     'published_day':day,'display_time':stamp(raw['published_at']).astimezone(BEIJING).strftime('%m-%d %H:%M') if 'T' in raw['published_at'] else day,
                     'why':L.tidy(WATCH[topic][0 if loc=='zh' else 1],loc),'related':links}
    items=sorted(unique.values(),key=lambda x:stamp(x['published_at']),reverse=True)
    day=stamp(cutoff).astimezone(BEIJING).date().isoformat()
    today=[x for x in items if x['published_day']==day]
    return {'enabled':enabled,'items':items[:40], 'home_items':items[:5], 'digest':(today or items)[:8], 'today_count':len(today),
            'today':day,'updated_at':payload.get('as_of'),'labels':LABELS[loc], 'topics':[{'id':k,'name':v[0 if loc=='zh' else 1]} for k,v in TOPICS.items()]}
