"""Fetch the public macro reporting snapshot without touching observations or research state."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cnmacro.news_feed import collect
if __name__=='__main__':
    result=collect()
    print([(s['source'],s['ok'],s.get('items',0),s.get('error')) for s in result['sources']])
    raise SystemExit(0 if all(s['ok'] for s in result['sources']) else 1)
