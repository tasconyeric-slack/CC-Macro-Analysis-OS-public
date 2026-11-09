"""Refresh public NBS price release tables, or import a runner-probed archive."""
import argparse
import concurrent.futures
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from cnmacro import ingest
from cnmacro.price_releases import BASE, PRICE_METRICS, append_release_rows, fetch_release, parse_release, release_links


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--pages',type=int,default=4)
    parser.add_argument('--start',default='2022-11')
    parser.add_argument('--summary',default='prices-summary.json')
    parser.add_argument('--out',type=Path,default=ROOT/'data/demo/observations')
    args = parser.parse_args()
    summary = {'retrieved_at':datetime.now(timezone.utc).isoformat(),'releases':[],'errors':[],'metrics':{}}
    if args.archive:
        manifest = json.loads((args.archive/'report.json').read_text(encoding='utf-8'))
        links = manifest['releases']
        summary['retrieved_at'] = manifest['retrieved_at']
    else:
        links = {}
        for i in range(args.pages):
            url = BASE+(f'index_{i}.html' if i else 'index.html')
            try:
                for link in release_links(ingest._get(url,timeout=20,retries=2).decode('utf-8')):
                    links[link['url']] = link
            except Exception as exc: summary['errors'].append({'url':url,'error':str(exc)})
        links = list(links.values())
    from cnmacro.price_releases import TITLE
    links = [item for item in links if TITLE.match(item['title']) and f'{TITLE.match(item["title"])[1]}-{int(TITLE.match(item["title"])[2]):02d}' >= args.start]
    if not links: summary['errors'].append({'error':'No monthly NBS price releases found'})
    rows, blocked = [], []
    def collect(item):
        if args.archive:
            text,transport = (args.archive/item['file']).read_text(encoding='utf-8'),item.get('transport_url',item['url'])
        else:
            text,transport = fetch_release(item['url'])
        return parse_release(text,item['title'],item['url'],summary['retrieved_at']),transport
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = [(item,pool.submit(collect,item)) for item in links]
        for item,future in futures:
            try:
                extracted,transport = future.result(); rows.extend(extracted)
                summary['releases'].append({'url':item['url'],'transport_url':transport,'rows':len(extracted)})
            except Exception as exc: blocked.append((item,str(exc)))
    summary['errors'] += [{'url':item['url'],'error':error[:300]} for item,error in blocked]
    summary['added'] = append_release_rows(rows,args.out)
    from cnmacro.store import load_observations
    obs = load_observations(args.out)
    for mid in sorted(PRICE_METRICS):
        periods = sorted(set(obs[obs.metric_id==mid].reference_period))
        summary['metrics'][mid] = {'months':len(periods),'first':periods[0] if periods else None,'latest':periods[-1] if periods else None}
    Path(args.summary).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'added':summary['added'],'releases':len(summary['releases']),'errors':summary['errors']},ensure_ascii=False))
    return bool(summary['errors'])


if __name__=='__main__': raise SystemExit(main())
