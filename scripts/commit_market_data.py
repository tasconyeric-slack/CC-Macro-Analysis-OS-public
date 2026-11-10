"""Publish the staged market-data refresh through the same verified-commit path as the public refresh.

Reuses scripts/commit_public_refresh.py (GitHub API commit by the Actions bot, verified signature,
fast-forward only, append-only observation files) with a narrower allowlist: only the Tushare
observation files and the cross-check records. A market run never touches the research case, the
evaluation report or the refresh/update history.
"""
import subprocess
import sys

import commit_public_refresh as base

base.ROOTS = ("data/demo/observations/tushare_", "data/market/crosschecks/")
base.IMMUTABLE = ("data/market/crosschecks/",)      # one new file per run; an existing record is never rewritten

# Inputs of a market run: its generator, its fetch specification and its own observation files.
RELEVANT = ("src/", "scripts/", ".github/", "data/dictionary/", "data/demo/observations/tushare_")


def check_movement(start, latest):
    """Fail closed only when something this run depended on moved; hourly news commits under data/news and
    unrelated refreshes do not invalidate a market run."""
    subprocess.run(["git", "merge-base", "--is-ancestor", start, latest], check=True)
    paths = base.git("diff", "--name-only", start, latest, "--").decode().splitlines()
    if any(p.startswith(RELEVANT) or p in {"pyproject.toml", "uv.lock"} for p in paths):
        raise RuntimeError("Market inputs or generator advanced; rerun the market refresh on the latest head")


base.check_movement = check_movement

if __name__ == "__main__":
    sys.exit(base.main())
