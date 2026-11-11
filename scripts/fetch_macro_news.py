"""Fetch public macro news, update the archive, rank events and write the daily editions."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cnmacro.news_feed import collect
if __name__=='__main__':
    result=collect()
    for s in result['sources']:print(s['source'],'ok' if s['ok'] else 'FAILED',s.get('items',0),s.get('new',0),s.get('error',''))
    ok=sum(s['ok'] for s in result['sources'])
    ai=result.get('ai',{})  # optional model enrichment: counts only, never the key; a failure there never changes the exit code
    print('news_ai',' '.join(f'{k}={ai.get(k)}' for k in ('enabled','display','model','status','candidates','cache_hits','calls','items_enriched','items_rejected','input_tokens','output_tokens','estimated_cost_usd')),'errors='+(','.join(ai.get('errors',[])) or 'none'))
    for ev in [e for e in result.get('events',[]) if e.get('ai')][:3]:print('news_ai sample',ev['title_zh'],'|',ev['ai'].get('title_en',''),'|',ev['ai'].get('why_zh',''),'|',ev['ai'].get('why_en',''))
    # a few unreachable sources are normal; most of them failing means the run is not trustworthy
    raise SystemExit(0 if ok*2>=len(result['sources']) else 1)
