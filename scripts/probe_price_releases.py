"""Small-batch GitHub-runner archive reading from an already verified NBS index."""
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def main(out, shard):
    out=Path(out);out.mkdir(exist_ok=True)
    links=json.loads(Path('docs/design/prices/release-index.json').read_text(encoding='utf-8'))
    report={'retrieved_at':datetime.now(timezone.utc).isoformat(),'releases':[],'errors':[]}
    for item in links[shard::12]:
        error='no real table'
        for transport in (item['url']+'?_=20261109',item['url']+'?v=1',item['url'].replace('https:','http:')):
            try:
                request=urllib.request.Request(transport,headers={'User-Agent':'Mozilla/5.0'})
                with urllib.request.urlopen(request,timeout=20) as response:body=response.read()
                if b'<table' in body.lower():
                    (out/item['file']).write_bytes(body)
                    report['releases'].append({**item,'transport_url':transport,'status':200,'bytes':len(body),'has_table':True})
                    break
            except Exception as exc:error=str(exc)
            time.sleep(1)
        else:report['errors'].append({'url':item['url'],'error':error})
        time.sleep(1)
    (out/f'report-{shard}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('shard',shard,'tables',len(report['releases']),'errors',len(report['errors']))


if __name__=='__main__':main(sys.argv[1],int(sys.argv[2]))
