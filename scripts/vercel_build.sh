#!/usr/bin/env bash
# Vercel build for the static site (vercel.json -> buildCommand). Publishes site/dist/.
#
# Runs on the build image's own Python, which must be the repository baseline declared by
# requires-python in pyproject.toml (the same one local development, CI and Netlify use).
# That interpreter is managed by the platform (PEP 668: pip refuses to install into it), so
# the project is installed into a throwaway venv made from it. No second Python is
# downloaded or installed. No backend, no function, no secret: it reads tracked public files
# and writes static HTML.
#
# Audit trail: Vercel clones shallowly (about 10 commits), where `git log` would credit every
# immutable research file to the clone's graft commit. site/build.py detects a shallow clone
# and takes the first-commit SHAs from the audit manifest in research/cases/cn-nominal/eval/
# latest.json instead. Unshallowing first is only an attempt to get the same answer from git.
set -euo pipefail
cd "$(dirname "$0")/.."

# 1. Full history if the host allows it (credentials are often absent after the clone, so
#    never prompt and never fail the build over it).
if [ "$(git rev-parse --is-shallow-repository 2>/dev/null || true)" = "true" ]; then
  GIT_TERMINAL_PROMPT=0 timeout 120 git fetch --unshallow --quiet \
    || echo "vercel_build: could not unshallow; audit trail comes from the eval manifest"
fi
echo "vercel_build: shallow clone = $(git rev-parse --is-shallow-repository 2>/dev/null || echo 'no git')"

# 2. The interpreter must be the baseline version; report it, and stop if it is not.
WANT="$(sed -n 's/^requires-python *= *">=\([0-9]*\.[0-9]*\).*/\1/p' pyproject.toml)"
[ -n "$WANT" ] || { echo "vercel_build: no requires-python lower bound in pyproject.toml" >&2; exit 1; }
PYTHON="$(command -v "python$WANT" || command -v python3 || true)"
[ -n "$PYTHON" ] || { echo "vercel_build: no python$WANT or python3 on PATH" >&2; exit 1; }
"$PYTHON" - "$WANT" <<'PY'
import sys
want = sys.argv[1]
have = "{}.{}".format(*sys.version_info[:2])
print("vercel_build: Python", sys.version.split()[0], "at", sys.executable)
if have != want:
    sys.exit(f"vercel_build: building on Python {have}, but the baseline in pyproject.toml is {want}")
PY

# 3. Dependencies go into an isolated venv of that same interpreter, never into the platform
#    Python; the build then runs from the venv (the same command Netlify runs).
BUILD_VENV="$(mktemp -d "${TMPDIR:-/tmp}/ccmacro-build-venv.XXXXXX")"
trap 'rm -rf "$BUILD_VENV"' EXIT
"$PYTHON" -m venv "$BUILD_VENV"
VENV_PYTHON="$BUILD_VENV/bin/python"
echo "vercel_build: build venv Python $("$VENV_PYTHON" -c 'import sys; print(sys.version.split()[0])') at $BUILD_VENV"
"$VENV_PYTHON" -m pip install --quiet .
"$VENV_PYTHON" site/build.py

test -s site/dist/index.html || { echo "vercel_build: site/dist/index.html missing or empty" >&2; exit 1; }
