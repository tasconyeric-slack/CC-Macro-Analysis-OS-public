"""When an analyst appends an update: the Chinese site must not silently mix languages, and the homepage's
curated view must say it is out of date until it is re-confirmed."""
import shutil
import subprocess
import sys

import pytest
import yaml

from conftest import CASE, ROOT
from htmlutil import parse

UPDATE = {
    "kind": "update", "baseline": "2026-10-04-baseline.yaml", "as_of": "2026-10-15T06:00:00Z",
    "release": "September 2026 CPI and PPI",
    "previous_state": {"probability": 0.3, "conviction": "LOW", "status": "ACTIVE", "last_update_direction": "UNCHANGED"},
    "test_results": {}, "flipped_tests": [{"test": "T-H1-01", "from": "false", "to": "true"}], "terminal_check": "ACTIVE",
    "new_claims": [], "does_this_change_the_thesis": "The PPI print confirms the upstream pattern; the thesis is unchanged.",
    "probability": 0.35, "conviction": "LOW", "status": "ACTIVE", "last_update_direction": "STRENGTHENED",
    "probability_change": {"previous": 0.3, "new": 0.35, "evidence": ["C-H1-01"], "hypotheses": ["H1"],
                           "reasoning": "Price momentum recovered."},
    "terminal_rule_fired": None,
}


def build_with_update(tmp_path, extra=None):
    case = tmp_path / "case"
    shutil.copytree(CASE, case, ignore=shutil.ignore_patterns("__pycache__"))
    (case / "updates").mkdir()
    doc = {**UPDATE, **(extra or {})}
    (case / "updates" / "2026-10-15-september-2026-cpi-and-ppi.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    out = tmp_path / "dist"
    done = subprocess.run([sys.executable, str(ROOT / "site/build.py"), "--case-dir", str(case), "--out", str(out)],
                          cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return out, done.stderr


def test_an_english_only_update_is_shown_in_english_and_marked_on_the_chinese_page(tmp_path):
    out, stderr = build_with_update(tmp_path)
    assert "The PPI print confirms the upstream pattern" in parse(out / "en/updates.html").text()
    zh_html = (out / "zh/updates.html").read_text(encoding="utf-8")
    assert '<span lang="en">The PPI print confirms the upstream pattern; the thesis is unchanged.</span>' in zh_html
    assert '<span lang="en">Price momentum recovered.</span>' in zh_html
    assert "fell back to English" in stderr            # the build says so, naming the texts


def test_an_update_with_chinese_text_shows_it_unmarked(tmp_path):
    out, stderr = build_with_update(tmp_path, {
        "does_this_change_the_thesis_zh": "9月PPI印证了上游主导的特征，命题判断不变。",
        "probability_change": {**UPDATE["probability_change"], "reasoning_zh": "价格动能恢复。"}})
    zh_html = (out / "zh/updates.html").read_text(encoding="utf-8")
    assert "9月PPI印证了上游主导的特征，命题判断不变。" in zh_html and "价格动能恢复。" in zh_html
    assert "The PPI print confirms" not in zh_html
    assert "fell back to English" not in stderr, stderr      # every text of the repository has Chinese


def test_a_newer_update_makes_the_curated_view_say_it_is_out_of_date(tmp_path):
    out, _ = build_with_update(tmp_path)
    en = parse(out / "en/index.html").text()
    assert "A newer analyst update exists than the one this view was written for" in en
    assert "已有比本判断所依据版本更新的分析师更新" in parse(out / "zh/index.html").text()
    # the figures follow the newest judgment, not the baseline
    assert "35%" in en and "Analyst probability 35%" in en


def test_the_repositorys_own_view_is_not_flagged_as_stale(built):
    assert "A newer analyst update exists" not in parse(built / "en/index.html").text()
