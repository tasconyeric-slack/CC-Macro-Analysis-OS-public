"""Check GitHub's own verification verdict for a commit before relying on it to deploy.

    python scripts/check_commit_verified.py [REF] [--repo OWNER/NAME]

REF is a SHA, branch or tag (default: HEAD, which must already be pushed). One API
request, no retries. Exit 0 = GitHub reports verified/valid; 1 = unsigned or invalid,
with the responsible commit path printed; 2 = could not be determined (never treat as
verified). This script only reports; it never signs, pushes or changes any setting.
Reads the public repo anonymously, or with GITHUB_TOKEN / GH_TOKEN when set.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

NEXT_STEPS = """\
Do not retry the push or deploy in a loop, and do not disable Require Verified Commits.
  - Agent branch (codex/* or claude/*) with a PR into main: the 'verified Codex previews'
    workflow appends a GitHub-verified checkpoint on opened/synchronize/reopened/ready.
    Open or update the PR and check again after it finishes.
  - Any other branch: rename it to codex/<topic> or claude/<topic> and open a PR.
  - Local clone: commit with SSH signing (docs/ops/codex-verified-previews.md).
  - main itself: stop and report to the Owner; fix via a PR squash/merge on GitHub.
    (Never rebase-merge: that leaves unsigned commits.)"""


def assess(commit):
    """Classify a GitHub commit object. Returns (status, report) with status in
    {'verified', 'unsigned'}; the caller maps those to exit codes 0 and 1."""
    proof = (commit.get("commit") or {}).get("verification") or {}
    who = lambda key: (commit.get(key) or {}).get("login") or "unknown"
    subject = ((commit.get("commit") or {}).get("message") or "").split("\n", 1)[0]
    facts = (f"commit {str(commit.get('sha'))[:12]}: {subject!r}\n"
             f"  author={who('author')} committer={who('committer')}\n"
             f"  verified={proof.get('verified')} reason={proof.get('reason')}")
    if proof.get("verified") is True and proof.get("reason") == "valid":
        return "verified", "VERIFIED " + facts
    path = ("pushed from a git client without a valid signature"
            if who("committer") not in {"web-flow", "github-actions[bot]"}
            else "created through GitHub but not reported as valid")
    return "unsigned", f"NOT VERIFIED ({path})\n{facts}\n{NEXT_STEPS}"


def repo_slug(explicit):
    slug = explicit or os.environ.get("GITHUB_REPOSITORY")
    if not slug:
        url = subprocess.check_output(["git", "remote", "get-url", "origin"], text=True).strip()
        match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
        if not match:
            raise RuntimeError("cannot derive OWNER/NAME; pass --repo")
        slug = match.group(1)
    return slug


def fetch_commit(slug, ref):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    url = f"https://api.github.com/repos/{slug}/commits/{urllib.parse.quote(ref, safe='')}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        return json.load(response)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("ref", nargs="?", help="SHA, branch or tag (default: HEAD)")
    parser.add_argument("--repo", help="OWNER/NAME (default: origin remote)")
    args = parser.parse_args(argv)
    try:
        ref = args.ref or subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        commit = fetch_commit(repo_slug(args.repo), ref)
    except urllib.error.HTTPError as error:
        hint = " (is it pushed to GitHub?)" if error.code in {404, 422} else ""
        print(f"UNDETERMINED: GitHub returned HTTP {error.code}{hint}. Not verified; no retry.")
        return 2
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"UNDETERMINED: {error}. Not verified; no retry.")
        return 2
    status, report = assess(commit)
    print(report)
    return 0 if status == "verified" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
