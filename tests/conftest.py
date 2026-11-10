"""Shared fixtures. The site generator lives in site/ (not a package); tests import its modules from there."""
import argparse
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "site"))

CASE = ROOT / "research/cases/cn-nominal"
LOCALES = ("en", "zh")
PAGES = sorted(["charts.html", "evidence.html", "index.html", "memo.html", "method.html", "updates.html", "daily.html", "news.html", "data.html", "policy.html"] + [f"data-{c}.html" for c in ("growth", "prices", "pmi", "trade", "credit", "fiscal", "external", "markets")])


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    """The dictionary loader refuses a route-history record dated after "now" (an activation is an event, never a
    scheduled switch). The suite's synthetic scenarios are set in October 2026, so the loader's clock is pinned after
    all of them: no test depends on the wall clock. Tests of the rule itself pass `now=` or move this pin."""
    from cnmacro import store
    monkeypatch.setattr(store, "now_utc", lambda: store.utc_naive("2026-12-31T00:00:00Z"))


@pytest.fixture(scope="session")
def built(tmp_path_factory) -> Path:
    """The public site, built once per test session into a temporary directory."""
    out = tmp_path_factory.mktemp("site") / "dist"
    done = subprocess.run([sys.executable, str(ROOT / "site/build.py"), "--out", str(out)], cwd=ROOT,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    return out


@pytest.fixture(scope="session")
def model():
    """The language-neutral research state the site is built from."""
    import build
    ns = argparse.Namespace(preview=False, banner=None, case_dir=str(CASE),
                            obs_dir=str(ROOT / "data/demo/observations"),
                            calendar=str(ROOT / "data/dictionary/release_calendar.yaml"),
                            dictionary=str(ROOT / "data/dictionary/metrics.yaml"))
    return build.build_model(ns)
