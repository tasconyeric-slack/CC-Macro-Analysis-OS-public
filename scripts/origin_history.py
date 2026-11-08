"""Write the origin-history anchor for research files carried over from the private origin repository.

This repository started from a one-commit snapshot (92d7ff0, 2026-11-02) of the private origin repository, so
git history here cannot show when the baseline, amendment and early refresh records were first committed. E4
(preregistration) and the site's audit trail read those first commits from this anchor instead.

The anchor is built once, from a full clone of the origin repository, and is itself immutable:

    python scripts/origin_history.py --origin ../CC-Macro-Analysis-OS --origin-commit 0d86522

For every immutable file in this checkout it records the origin's first commit (sha and commit time), how many
origin commits touched it (must be 1), and the git blob of the file at `--origin-commit`, which must equal the
file here. Anything that does not match is an error and nothing is written.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE = Path("research/cases/cn-nominal")
OUT = CASE / "origin_history.json"


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def immutable_files(repo: Path) -> list[str]:
    pats = [f"{CASE}/preregistered/*.yaml", f"{CASE}/updates/*.yaml", f"{CASE}/refreshes/*.json"]
    return sorted(git(repo, "ls-files", "--", *pats).splitlines())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origin", required=True, type=Path, help="full (non-shallow) clone of the origin repository")
    ap.add_argument("--origin-commit", required=True, help="origin commit this repository's snapshot was taken from")
    ap.add_argument("--origin-repo", default="tasconyeric-slack/CC-Macro-Analysis-OS")
    a = ap.parse_args()
    origin = a.origin.resolve()
    if git(origin, "rev-parse", "--is-shallow-repository") == "true":
        sys.exit("origin clone is shallow: first commits would be wrong")
    snap = git(origin, "rev-parse", a.origin_commit)
    files, commits, errors = {}, {}, []
    for rel in immutable_files(ROOT):
        log = git(origin, "log", "--format=%H|%cI", snap, "--", rel).splitlines()
        if not log:
            errors.append(f"{rel}: not in origin history at {snap[:7]}")
            continue
        sha, at = log[-1].split("|")
        origin_blob = git(origin, "rev-parse", f"{snap}:{rel}")
        here_blob = git(ROOT, "hash-object", rel)
        if origin_blob != here_blob:
            errors.append(f"{rel}: differs from origin {snap[:7]}")
        if len(log) != 1:
            errors.append(f"{rel}: {len(log)} origin commits, expected 1")
        files[rel] = {"sha": sha, "at": at, "blob": origin_blob, "origin_commits": len(log)}
        commits[sha] = at
    for rel in files:                       # baseline commits named inside amendments must resolve too
        if "-amendment-" in rel:
            import yaml
            base = (yaml.safe_load((ROOT / rel).read_text(encoding="utf-8")) or {}).get("baseline_commit")
            if base:
                commits[git(origin, "rev-parse", base)] = git(origin, "show", "-s", "--format=%cI", base)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    doc = {"origin_repo": a.origin_repo, "origin_commit": snap,
           "origin_commit_at": git(origin, "show", "-s", "--format=%cI", snap),
           "note": "First commits of research files carried over from the origin repository's full history. "
                   "Written once by scripts/origin_history.py; never edited.",
           "files": files, "commits": dict(sorted(commits.items(), key=lambda kv: kv[1]))}
    (ROOT / OUT).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {len(files)} files, {len(commits)} commits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
