"""Publish the staged public refresh atomically with GitHub's verified bot identity.

Uses only GITHUB_TOKEN (contents: write). Never supplies author/committer/signature
metadata, never force-pushes, and refuses to publish stale research outputs.
"""
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


ROOTS = ("data/demo/observations/", "research/cases/cn-nominal/eval/",
         "research/cases/cn-nominal/refreshes/", "research/cases/cn-nominal/updates/",
         "research/cases/cn-nominal/reviews/")
IMMUTABLE = ROOTS[2:]


def git(*args):
    return subprocess.check_output(["git", *args])


class GitHub:
    def __init__(self):
        self.base = "https://api.github.com/repos/" + os.environ["GITHUB_REPOSITORY"]

    def request(self, method, path, body=None):
        request = urllib.request.Request(
            self.base + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)


def staged_changes():
    fields = git("diff", "--cached", "--name-status", "--no-renames", "-z").decode().split("\0")
    changes = []
    for status, path in zip(fields[0::2], fields[1::2]):
        if not path.startswith(ROOTS):
            raise RuntimeError(f"Outside public refresh allowlist: {path}")
        if status == "D":
            raise RuntimeError(f"Refresh cannot delete public artifacts: {path}")
        if status != "A" and path.startswith(IMMUTABLE):
            raise RuntimeError(f"Cannot rewrite historical record: {path}")
        content = git("show", ":" + path)
        mode = git("ls-files", "-s", "--", path).split()[0]
        if mode != b"100644":
            raise RuntimeError(f"Refresh output must be a regular data file: {path}")
        if status != "A" and path.startswith(ROOTS[0]):
            if not content.startswith(git("show", "HEAD:" + path)):
                raise RuntimeError(f"Observations must be append-only: {path}")
        changes.append((path, content))
    return changes


def current_head(branch):
    git("fetch", "--quiet", "origin", "refs/heads/" + branch)
    return git("rev-parse", "FETCH_HEAD").decode().strip()


def check_movement(base, latest):
    subprocess.run(["git", "merge-base", "--is-ancestor", base, latest], check=True)
    paths = git("diff", "--name-only", base, latest, "--").decode().splitlines()
    # A changed input, generator, frozen record or output invalidates this run's
    # validation. Fail closed; the next scheduled run will regenerate once.
    if any(p.startswith(("data/", "research/", "src/", "scripts/", ".github/"))
           or p in {"pyproject.toml", "uv.lock"} for p in paths):
        raise RuntimeError("Research inputs or outputs advanced; rerun refresh on latest head")


def publish(api, branch, message, base, changes):
    entries = []
    for path, content in changes:
        blob = api.request("POST", "/git/blobs", {
            "content": base64.b64encode(content).decode(), "encoding": "base64"})
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    ref = "/git/refs/heads/" + urllib.parse.quote(branch, safe="/")
    for attempt in range(3):
        latest = current_head(branch)
        check_movement(base, latest)
        parent = api.request("GET", "/git/commits/" + latest)
        tree = api.request("POST", "/git/trees", {"base_tree": parent["tree"]["sha"], "tree": entries})
        commit = api.request("POST", "/git/commits", {
            "message": message, "tree": tree["sha"], "parents": [latest]})
        sha = commit["sha"]
        actual = api.request("GET", "/commits/" + sha)
        verification = actual["commit"]["verification"]
        if verification["verified"] is not True or verification["reason"] != "valid":
            raise RuntimeError(f"Refusing unverified commit {sha}: {verification['reason']}")
        author = (actual.get("author") or {}).get("login")
        committer = (actual.get("committer") or {}).get("login")
        if author != "github-actions[bot]" or committer not in {"web-flow", "github-actions[bot]"}:
            raise RuntimeError(f"Unexpected commit identity {sha}: author={author}, committer={committer}")
        try:
            api.request("PATCH", ref, {"sha": sha, "force": False})
        except urllib.error.HTTPError as error:
            if error.code not in {409, 422} or current_head(branch) == latest:
                raise
            print(f"Non-fast-forward branch movement; retry {attempt + 1}/3")
            continue
        print(json.dumps({"sha": sha, "verification": {
            "verified": verification["verified"], "reason": verification["reason"]}}))
        return sha
    raise RuntimeError("Branch kept advancing; rerun refresh on latest head")


def main():
    subprocess.run([sys.executable, "scripts/check_secrets.py", "--staged"], check=True)
    changes = staged_changes()
    if not changes:
        print("No new public data; nothing to commit.")
        return
    publish(GitHub(), os.environ["GITHUB_REF_NAME"], sys.argv[1],
            git("rev-parse", "HEAD").decode().strip(), changes)


if __name__ == "__main__":
    main()
