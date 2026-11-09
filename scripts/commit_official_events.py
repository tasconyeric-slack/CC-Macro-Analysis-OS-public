"""Publish only official event artifacts using the proven verified GitHub bot path.

The public-refresh writer and its allowlist are unchanged. Inbox/status/review
logs cannot be truncated/replaced; only the successful-source cursor is mutable.
"""
import json
import os
import re
import subprocess
import sys

import commit_public_refresh as verified


def staged_changes():
    fields = verified.git("diff", "--cached", "--name-status", "--no-renames", "-z").decode().split("\0")
    changes = []
    for status, path in zip(fields[0::2], fields[1::2]):
        log_path = (path.startswith("data/events/inbox/") and path.endswith(".jsonl")) or path in {
            "data/events/source_status.jsonl", "data/events/reviews.jsonl", "data/events/events.jsonl"}
        model_record = bool(re.fullmatch(r"data/events/relation_model/runs/[a-zA-Z0-9_-]+/(record|context)\.json", path))
        if not log_path and path != "data/events/cursors.json" and not model_record:
            raise RuntimeError(f"Outside official event allowlist: {path}")
        if model_record and status != "A":
            raise RuntimeError(f"Model run records are write-once: {path}")
        if status not in {"A", "M"}:
            raise RuntimeError(f"Events cannot delete or rename artifacts: {path}")
        content = verified.git("show", ":" + path)
        if verified.git("ls-files", "-s", "--", path).split()[0] != b"100644":
            raise RuntimeError(f"Event output must be a regular data file: {path}")
        if log_path and status != "A" and not content.startswith(verified.git("show", "HEAD:" + path)):
            raise RuntimeError(f"Official event log must be append-only: {path}")
        if log_path:
            for line in content.decode("utf-8").splitlines():
                if line.strip():
                    json.loads(line)
        else:
            json.loads(content)
        changes.append((path, content))
    return changes


def main():
    subprocess.run([sys.executable, "scripts/check_secrets.py", "--staged"], check=True)
    changes = staged_changes()
    if not changes:
        print("No new official event artifacts; nothing to commit.")
        return
    verified.publish(verified.GitHub(), os.environ["GITHUB_REF_NAME"], sys.argv[1],
                     verified.git("rev-parse", "HEAD").decode().strip(), changes)


if __name__ == "__main__":
    main()
