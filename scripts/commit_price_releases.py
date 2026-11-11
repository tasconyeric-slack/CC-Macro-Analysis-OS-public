"""Publish only append-only official price observations through the verified bot writer."""
import csv
import io
import os
import subprocess
import sys

import commit_public_refresh as verified
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]/'src'))
from cnmacro.price_releases import PRICE_METRICS


def main():
    subprocess.run([sys.executable,'scripts/check_secrets.py','--staged'],check=True)
    paths = verified.git('diff','--cached','--name-only').decode().splitlines()
    if not paths: return
    if paths != ['data/demo/observations/prices_release.csv']:
        raise RuntimeError('Only the append-only public price observation file may be published')
    path = paths[0]; content = verified.git('show',':'+path)
    exists = verified.git('ls-tree','HEAD','--',path).strip()
    old = verified.git('show','HEAD:'+path) if exists else b''
    if old and not content.startswith(old): raise RuntimeError('Price observations must be append-only')
    rows = list(csv.DictReader(io.StringIO(content.decode('utf-8'))))
    if any(row['metric_id'] not in PRICE_METRICS or row['source_class']!='public' or row['source']!='NBS' or not row['source_code'].startswith('https://www.stats.gov.cn/sj/zxfb/') for row in rows):
        raise RuntimeError('Only original public NBS release table facts may be published')
    verified.publish(verified.GitHub(),os.environ['GITHUB_REF_NAME'],'data: append official NBS price release observations',verified.git('rev-parse','HEAD').decode().strip(),[(path,content)])


if __name__=='__main__': main()
