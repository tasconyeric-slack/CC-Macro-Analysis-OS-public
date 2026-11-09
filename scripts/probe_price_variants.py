"""One-off runner transport diagnosis for the same original NBS release URLs."""
import concurrent.futures
import json
import urllib.request
from pathlib import Path

URLS = ['https://www.stats.gov.cn/sj/zxfb/202611/t20261109_1965795.html',
        'https://www.stats.gov.cn/sj/zxfb/202611/t20261109_1965794.html',
        'https://www.stats.gov.cn/sj/zxfb/202610/t20261031_1965718.html']


def one(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=15) as r:
            body = r.read(); text = body.decode('utf-8',errors='replace')
            return {'url':url,'status':r.status,'table':'<table' in text,'body':text}
    except Exception as e:return {'url':url,'error':str(e)}


if __name__=='__main__':
    out=Path('.prices-variants');out.mkdir(exist_ok=True)
    urls=[variant for url in URLS for variant in (url+'?v=1',url+'?_=20261109',url.replace('https:','http:'),url.replace('www.stats','stats'),url.replace('www.stats','m.stats'))]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool: rows=list(pool.map(one,urls))
    for i,row in enumerate(rows):
        if 'body' in row:(out/f'{i}.html').write_text(row.pop('body'),encoding='utf-8')
    (out/'report.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rows,ensure_ascii=False))
