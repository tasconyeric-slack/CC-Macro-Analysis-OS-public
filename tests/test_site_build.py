"""The public site, built the way a static host builds it: from a fresh shallow clone."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PREREG = "research/cases/cn-nominal/preregistered/"
from conftest import PAGES


def test_shallow_clone_build_keeps_the_true_audit_trail(tmp_path):
    if subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True).returncode:
        pytest.skip("not a git checkout")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{ROOT}", str(clone)], check=True)
    subprocess.run([sys.executable, "site/build.py"], cwd=clone, check=True, capture_output=True)
    dist = clone / "site/dist"
    assert sorted(p.name for p in (dist / "en").glob("*.html") if not p.name.startswith(("news-edition-", "news-archive-"))) == PAGES
    assert sorted(p.name for p in (dist / "zh").glob("*.html") if not p.name.startswith(("news-edition-", "news-archive-"))) == PAGES
    audit = json.loads((clone / "research/cases/cn-nominal/eval/latest.json").read_text(encoding="utf-8"))["audit"]
    page = (dist / "en/updates.html").read_text(encoding="utf-8")

    def shown(anchor):
        return re.search(rf'id="{anchor}"[^>]*data-origin-sha="([0-9a-f]+)"', page).group(1)
    # each entry is credited to the commit that first added its file, not to the clone's graft commit
    assert shown("baseline") == audit[PREREG + "2026-10-04-baseline.yaml"]["sha"][:7]
    assert shown("A-01") == audit[PREREG + "2026-10-04-amendment-01-terminal-rules.yaml"]["sha"][:7]
    # the Chinese page credits the very same commits
    zh = (dist / "zh/updates.html").read_text(encoding="utf-8")
    assert re.search(r'id="baseline"[^>]*data-origin-sha="%s"' % audit[PREREG + "2026-10-04-baseline.yaml"]["sha"][:7], zh)
