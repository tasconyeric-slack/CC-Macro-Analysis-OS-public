"""Publish the public-news snapshot, editions and archive via the existing verified GitHub commit path."""
import json, os, subprocess, sys
import commit_public_refresh as verified

def main():
    subprocess.run([sys.executable,'scripts/check_secrets.py','--staged'],check=True)
    paths=verified.git('diff','--cached','--name-only').decode().splitlines()
    if not paths:return
    if any(not p.startswith('data/news/') or not p.endswith('.json') for p in paths):raise RuntimeError('Only public-news JSON files may be published')
    files=[]
    for p in paths:
        content=verified.git('show',':'+p);json.loads(content);files.append((p,content))
    verified.publish(verified.GitHub(),os.environ['GITHUB_REF_NAME'],'news: refresh China macro news, editions and archive',verified.git('rev-parse','HEAD').decode().strip(),files)
if __name__=='__main__':main()
