#!/usr/bin/env python3
"""Basic secrets and data-boundary check.

Scans tracked (or staged) files for credential patterns and for files that
must never enter git. Exits non-zero on any finding. Run before every commit
and in CI:  python3 scripts/check_secrets.py [--staged]
"""
import re
import subprocess
import sys

SECRET_PATTERNS = [
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"\bsk-[A-Za-z0-9_-]{20,}", "API key (sk-...)"),
    (r"\bgh[pousr]_[A-Za-z0-9]{30,}", "GitHub token"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key"),
    (r"(?i)\b(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9/+_-]{16,}", "credential assignment"),
]
FORBIDDEN_PATHS = [
    (r"^data/private/(?!README\.md$)", "file under data/private"),
    (r"^research/private/(?!README\.md$)", "file under research/private"),
    (r"\.(pdf|xlsx|xls|xlsm)$", "licensed document/spreadsheet type"),
    (r"(^|/)\.env$", ".env file"),
]
SKIP = {"scripts/check_secrets.py"}


def tracked_files(staged: bool) -> list[str]:
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"] if staged else ["git", "ls-files"]
    return [f for f in subprocess.check_output(cmd, text=True).splitlines() if f]


def main() -> int:
    staged = "--staged" in sys.argv
    findings = []
    for path in tracked_files(staged):
        for pat, label in FORBIDDEN_PATHS:
            if re.search(pat, path):
                findings.append(f"{path}: {label}")
        if path in SKIP:
            continue
        try:
            if staged:
                text = subprocess.check_output(
                    ["git", "show", f":{path}"], stderr=subprocess.DEVNULL
                ).decode("utf-8", errors="ignore")
            else:
                text = open(path, encoding="utf-8", errors="ignore").read()
        except (FileNotFoundError, IsADirectoryError):
            continue
        for pat, label in SECRET_PATTERNS:
            for m in re.finditer(pat, text):
                line = text.count("\n", 0, m.start()) + 1
                findings.append(f"{path}:{line}: possible {label}")
    if findings:
        print("Secrets / data-boundary check FAILED:")
        print("\n".join(f"  - {f}" for f in findings))
        return 1
    print("Secrets / data-boundary check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
