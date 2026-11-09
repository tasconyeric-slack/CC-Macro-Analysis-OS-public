"""Publish the single public-news snapshot via the existing verified GitHub commit path."""
import json, os, subprocess, sys
import commit_public_refresh as verified

def main():
    subprocess.run([sys.executable,'scripts/check_secrets.py','--staged'],check=True)
    paths=verified.git('diff','--cached','--name-only').decode().splitlines()
    if not paths:return
    if paths!=['data/news/latest.json']:raise RuntimeError('Only the public-news snapshot may be published')
    content=verified.git('show',':data/news/latest.json');json.loads(content)
    verified.publish(verified.GitHub(),os.environ['GITHUB_REF_NAME'],'news: refresh sourced China macro reporting',verified.git('rev-parse','HEAD').decode().strip(),[('data/news/latest.json',content)])
if __name__=='__main__':main()
