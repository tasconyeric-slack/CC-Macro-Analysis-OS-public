"""Fetch the Issue #28 official series into append-only public CSVs."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cnmacro.expanded_data import refresh_expanded
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--start',default='2019-01');p.add_argument('--summary',default='expanded-summary.json');a=p.parse_args()
    result=refresh_expanded(Path(__file__).resolve().parents[1],a.start)
    Path(a.summary).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(bool(result['errors']))
