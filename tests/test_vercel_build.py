"""The Vercel production build: vercel.json is static-only, and scripts/vercel_build.sh builds the
site the way Vercel does (fresh shallow clone, no secrets) on the repository's single Python
baseline (requires-python) without crediting the audit trail to the clone's graft commit."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from conftest import PAGES

ROOT = Path(__file__).resolve().parents[1]
PREREG = "research/cases/cn-nominal/preregistered/"
IMMUTABLE = {"baseline": "2026-10-04-baseline.yaml", "A-01": "2026-10-04-amendment-01-terminal-rules.yaml"}
LOCALES = ["en", "zh"]


def baseline():
    """The one declaration: the lower bound of requires-python in pyproject.toml."""
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return re.fullmatch(r">=(\d+\.\d+),<\d+\.\d+", meta["project"]["requires-python"]).group(1)


def test_python_314_is_the_single_runtime_baseline():
    assert baseline() == "3.14"
    version = tuple(int(p) for p in baseline().split("."))
    assert sys.version_info[:2] == version   # the interpreter running this suite is the baseline
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert meta["project"]["requires-python"] == ">=3.14,<3.15"
    netlify = tomllib.loads((ROOT / "netlify.toml").read_text(encoding="utf-8"))
    assert netlify["build"]["environment"]["PYTHON_VERSION"] == baseline()
    assert netlify["build"]["publish"] == "site/dist"
    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        pins = re.findall(r'python-version:\s*"?([\d.]+)', workflow.read_text(encoding="utf-8"))
        assert set(pins) <= {baseline()}, f"{workflow.name} pins {pins}"


def test_vercel_json_is_static_only():
    cfg = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert cfg["framework"] is None
    assert cfg["outputDirectory"] == "site/dist"
    assert cfg["buildCommand"] == "bash scripts/vercel_build.sh"
    assert (ROOT / "scripts/vercel_build.sh").is_file()
    # nothing that adds a backend, a secret, or a visitor challenge
    banned = {"functions", "builds", "routes", "rewrites", "redirects", "crons", "env", "build", "middleware"}
    assert not banned & cfg.keys()
    assert not (ROOT / "api").exists() and not (ROOT / "middleware.py").exists()
    assert "mitigate" not in json.dumps(cfg)
    assert {h["key"] for g in cfg["headers"] for h in g["headers"]} >= {"X-Content-Type-Options", "Referrer-Policy"}


def test_vercel_build_does_not_bootstrap_another_python():
    script = (ROOT / "scripts/vercel_build.sh").read_text(encoding="utf-8")
    code = "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))
    assert not re.search(r"\buv\b|3\.11|--break-system-packages|curl|wget|pyenv", code)
    # the isolated build venv is made from the interpreter that was just verified
    assert '"$PYTHON" -m venv "$BUILD_VENV"' in code
    assert '"$VENV_PYTHON" -m pip install' in code and '"$VENV_PYTHON" site/build.py' in code
    assert not re.search(r'"\$PYTHON" (-m pip|site/build\.py)', code)   # nothing runs in the platform Python


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def force_rmtree(path):
    """git keeps its pack and object files read-only, which Windows refuses to delete."""
    def writable_then_retry(func, name, _exc):
        os.chmod(name, stat.S_IWRITE)
        func(name)
    shutil.rmtree(path, onexc=writable_then_retry)


# Vercel builds on Linux, where a venv holds bin/python and scripts/vercel_build.sh runs that. A
# Windows host lays the same venv out as Scripts/python.exe, so after `-m venv` the stub adds the
# Linux entry point; on Linux the venv already has it and nothing is added.
LINUX_VENV_LAYOUT = r"""
case " $* " in *" -m venv "*)
  for venv_dir in "$@"; do :; done
  if [ ! -e "$venv_dir/bin/python" ] && [ -e "$venv_dir/Scripts/python.exe" ]; then
    mkdir -p "$venv_dir/bin"
    printf '#!/bin/sh\nexec "%s" "$@"\n' "$venv_dir/Scripts/python.exe" > "$venv_dir/bin/python"
    chmod +x "$venv_dir/bin/python"
  fi;;
esac
"""


def platform_interpreter(bin_dir, name, log=None, refuse_pip=False):
    """Writes `bin_dir/name`, a stand-in for the platform's interpreter on PATH. It runs the
    interpreter that runs this suite (so the build sees the real version) and gives the venvs it
    makes the Linux layout. With `refuse_pip` it refuses `-m pip` the way a PEP 668
    externally-managed interpreter does, and with `log` it records every call, so a build that
    installs into it fails instead of passing silently."""
    lines = ["#!/bin/sh"]
    if log:
        lines.append(f'echo "$*" >> "{log.as_posix()}"')
    if refuse_pip:
        lines.append('case " $* " in *" -m pip "*)\n  echo "error: externally-managed-environment" >&2; exit 1;;\nesac')
    lines.append(f'"{Path(sys.executable).as_posix()}" "$@" || exit $?')
    lines.append(LINUX_VENV_LAYOUT)
    stub = bin_dir / name
    stub.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    stub.chmod(0o755)
    return stub


@pytest.fixture
def platform_python(tmp_path):
    """Stands in for Vercel's platform-managed Python 3.14, which refuses `-m pip`."""
    bin_dir, log = tmp_path / "platform-bin", tmp_path / "platform-calls.log"
    bin_dir.mkdir()
    platform_interpreter(bin_dir, f"python{baseline()}", log=log, refuse_pip=True)
    return bin_dir, log


def vercel_env(bin_dir):
    env = {**os.environ, "VERCEL": "1", "CI": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    for secret in ("GITHUB_TOKEN", "WIND_API_KEY", "VIRTUAL_ENV"):
        env.pop(secret, None)
    return env


def build_on_vercel_like_clone(tmp_path, scenario, platform):
    if subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True).returncode:
        pytest.skip("not a git checkout")
    if not shutil.which("bash"):
        pytest.skip("bash not available")
    clone = tmp_path / "clone"
    depth = "1"   # the clone tip is then never the commit that added a research file
    subprocess.run(["git", "clone", "-q", "--depth", depth, f"file://{ROOT}", str(clone)], check=True)
    if scenario == "unshallow_fails":
        # Vercel's clone has no credentials left for a later fetch
        git("remote", "set-url", "origin", str(tmp_path / "gone"), cwd=clone)
    if scenario == "no_git_dir":
        force_rmtree(clone / ".git")
    done = subprocess.run(["bash", "scripts/vercel_build.sh"], cwd=clone, env=vercel_env(platform[0]),
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"vercel_build: Python {baseline()}." in done.stdout   # built on the baseline interpreter
    assert f"vercel_build: build venv Python {baseline()}." in done.stdout   # ... and its venv
    index = clone / "site/dist/index.html"
    assert index.is_file() and index.stat().st_size > 0
    return clone, done.stdout


def test_vercel_build_installs_only_into_its_own_venv(tmp_path, platform_python):
    clone, out = build_on_vercel_like_clone(tmp_path, "unshallow_fails", platform_python)
    calls = platform_python[1].read_text(encoding="utf-8").splitlines()
    assert any(c.startswith("-m venv ") for c in calls)   # the venv is made from the platform Python
    assert not any("-m pip" in c for c in calls)          # ... which is never installed into
    assert "externally-managed-environment" not in out


def test_vercel_build_stops_when_python_is_not_the_baseline(tmp_path):
    if not shutil.which("bash"):
        pytest.skip("bash not available")
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/vercel_build.sh", tmp_path / "scripts/vercel_build.sh")
    (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.99,<3.100"\n', encoding="utf-8")   # no such interpreter
    bin_dir = tmp_path / "platform-bin"
    bin_dir.mkdir()
    platform_interpreter(bin_dir, "python3")   # the image's python3, here 3.14, is not the 3.99 the build asks for
    done = subprocess.run(["bash", "scripts/vercel_build.sh"], cwd=tmp_path, env=vercel_env(bin_dir),
                          capture_output=True, text=True)
    assert done.returncode != 0
    assert "baseline in pyproject.toml is 3.99" in done.stderr
    assert not (tmp_path / "site").exists()   # nothing was built


@pytest.mark.parametrize("scenario", ["unshallow_fails", "unshallow_works", "no_git_dir"])
def test_vercel_production_build_keeps_the_true_audit_trail(tmp_path, platform_python, scenario):
    clone, out = build_on_vercel_like_clone(tmp_path, scenario, platform_python)
    for loc in LOCALES:   # the same portal pages in each language, built into the one artifact
        assert sorted(p.name for p in (clone / "site/dist" / loc).glob("*.html") if not p.name.startswith(("news-edition-", "news-archive-"))) == PAGES
    if scenario == "unshallow_fails":
        assert "shallow clone = true" in out    # the manifest path is what is being tested
    if scenario == "unshallow_works":
        assert "shallow clone = false" in out   # the real-history path is what is being tested

    audit = json.loads((ROOT / "research/cases/cn-nominal/eval/latest.json").read_text(encoding="utf-8"))["audit"]
    page = (clone / "site/dist/en/updates.html").read_text(encoding="utf-8")
    graft = git("rev-parse", "HEAD", cwd=clone) if scenario != "no_git_dir" else None
    for anchor, name in IMMUTABLE.items():
        shown = re.search(rf'id="{anchor}"[^>]*data-origin-sha="([0-9a-f]+)"', page).group(1)
        assert shown == audit[PREREG + name]["sha"][:7]
        if graft:
            assert shown != graft[:7]   # never the clone's tip
        origin = json.loads((ROOT / "research/cases/cn-nominal/origin_history.json").read_text(encoding="utf-8"))["files"]
        if PREREG + name in origin:   # carried over from the origin repository: its first commit, not this repo's snapshot
            assert shown == origin[PREREG + name]["sha"][:7]
        elif git("rev-parse", "--is-shallow-repository", cwd=ROOT) == "false":
            added = git("log", "--diff-filter=A", "--format=%H", "--", PREREG + name, cwd=ROOT).splitlines()[-1]
            assert shown == added[:7]
