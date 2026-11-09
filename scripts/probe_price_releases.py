"""Runner-only diagnostic: archive official NBS price release bodies, never publish values."""
import concurrent.futures
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

BASE = 'https://www.stats.gov.cn/sj/zxfb/'


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=35) as r:
        body = r.read()
        return body, {'url': url, 'status': r.status, 'bytes': len(body)}


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.items = []; self.href = None; self.title = ''; self.text = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            a = dict(attrs); self.href = a.get('href'); self.title = a.get('title', ''); self.text = []
    def handle_data(self, value):
        if self.href: self.text.append(value)
    def handle_endtag(self, tag):
        if tag == 'a' and self.href:
            self.items.append((self.href, self.title or ''.join(self.text))); self.href = None


def main(target):
    out = Path(target); out.mkdir(parents=True, exist_ok=True)
    report = {'retrieved_at': datetime.now(timezone.utc).isoformat(), 'requests': [], 'releases': [], 'errors': []}
    links = {}
    # About 20 monthly releases per listing. 100 pages comfortably spans 36 months.
    def listing(i):
        url = BASE + (f'index_{i}.html' if i else 'index.html')
        body, metadata = fetch(url)
        parser = Links(); parser.feed(body.decode('utf-8'))
        return metadata, parser.items
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for future in [pool.submit(listing, i) for i in range(100)]:
            try:
                metadata, items = future.result(); report['requests'].append(metadata)
                for href, title in items:
                    if any(x in title for x in ('居民消费价格', '工业生产者出厂价格', '采购经理指数运行情况')):
                        url = urljoin(BASE, href)
                        if re.fullmatch(r'https://www.stats.gov.cn/sj/zxfb/20\d{4}/t\d{8}_\d+\.html', url): links[url] = title.strip()
            except Exception as e: report['errors'].append(str(e))
    def release(item):
        url, title = item; body, metadata = fetch(url)
        if b'<table' not in body:
            body, transport = fetch(url+'?v=1')
            metadata['transport_url'] = transport['url']
            metadata['bytes'] = len(body)
        filename = url.rsplit('/', 1)[1]; (out/filename).write_bytes(body)
        return {**metadata, 'title': title, 'file': filename}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for future in [pool.submit(release, item) for item in sorted(links.items())]:
            try: report['releases'].append(future.result())
            except Exception as e: report['errors'].append(str(e))
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'listings': len(report['requests']), 'releases': len(report['releases']), 'errors': report['errors']}, ensure_ascii=False))


if __name__ == '__main__': main(sys.argv[1])
