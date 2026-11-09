"""Fetch public macro news, update the archive, rank events and write the daily editions."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cnmacro.news_feed import collect
if __name__=='__main__':
    result=collect()
    for s in result['sources']:print(s['source'],'ok' if s['ok'] else 'FAILED',s.get('items',0),s.get('new',0),s.get('error',''))
    ok=sum(s['ok'] for s in result['sources'])
    # a few unreachable sources are normal; most of them failing means the run is not trustworthy
    raise SystemExit(0 if ok*2>=len(result['sources']) else 1)
