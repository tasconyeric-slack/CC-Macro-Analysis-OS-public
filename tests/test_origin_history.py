"""E4 on a repository that started from a one-commit snapshot of the origin repository: first commits of
carried-over research files come from research/cases/cn-nominal/origin_history.json, not from this history."""
import json
import subprocess
from pathlib import Path

import yaml

from cnmacro import checks

ROOT = Path(__file__).resolve().parents[1]


def _git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def _snapshot_repo(tmp_path, edit_baseline=False):
    """A one-commit repo dated after the release, with an anchor saying the files were first committed earlier."""
    case = tmp_path / "case"
    (case / "preregistered").mkdir(parents=True)
    base = case / "preregistered/2026-10-04-baseline.yaml"
    amend = case / "preregistered/2026-10-04-amendment-01-terminal-rules.yaml"
    base.write_text("probability: 0.3\n", encoding="utf-8")
    amend.write_text(yaml.safe_dump({"baseline_commit": "b" * 40, "effective_before": {
        "release": "September 2026 CPI and PPI", "at": "2026-10-14T09:30:00+08:00"}}), encoding="utf-8")
    _git(tmp_path, "init", "-q")
    blobs = {p: _git(tmp_path, "hash-object", str(p)) for p in (base, amend)}
    anchor = {"origin_repo": "o/r", "files": {
        "case/preregistered/2026-10-04-baseline.yaml": {"sha": "b" * 40, "at": "2026-10-04T07:15:31+00:00",
                                                       "blob": blobs[base], "origin_commits": 1},
        "case/preregistered/2026-10-04-amendment-01-terminal-rules.yaml": {
            "sha": "a" * 40, "at": "2026-10-04T07:45:53+00:00", "blob": blobs[amend], "origin_commits": 1}},
        "commits": {"b" * 40: "2026-10-04T07:15:31+00:00", "a" * 40: "2026-10-04T07:45:53+00:00"}}
    (case / "origin_history.json").write_text(json.dumps(anchor), encoding="utf-8")
    if edit_baseline:
        base.write_text("probability: 0.5\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "snapshot"], cwd=tmp_path,
                   check=True, env={"GIT_COMMITTER_DATE": "2026-11-02T17:10:52Z", "GIT_AUTHOR_DATE": "2026-11-02T17:10:52Z",
                                    "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)})
    return case


def test_snapshot_without_anchor_fails_as_it_did_on_the_public_repo(tmp_path, monkeypatch):
    case = _snapshot_repo(tmp_path)
    (case / "origin_history.json").unlink()
    _git(tmp_path, "commit", "-qam", "drop anchor")
    monkeypatch.chdir(tmp_path)
    c = checks.preregistration(Path("case"))
    assert c.status == "fail"
    assert any("not found in history" in m for m in c.details)


def test_anchored_files_take_their_first_commit_from_the_origin(tmp_path, monkeypatch):
    case = _snapshot_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    c = checks.preregistration(Path("case"))
    assert c.status == "pass", c.details
    audit = checks.audit_manifest(Path("case"))
    assert audit["case/preregistered/2026-10-04-baseline.yaml"]["sha"] == "b" * 40


def test_an_anchored_file_edited_after_the_snapshot_still_fails(tmp_path, monkeypatch):
    _snapshot_repo(tmp_path, edit_baseline=True)
    monkeypatch.chdir(tmp_path)
    c = checks.preregistration(Path("case"))
    assert c.status == "fail"
    assert any("differs from the content first committed" in m for m in c.details)


def test_the_committed_anchor_matches_this_checkout():
    anchor = json.loads((ROOT / "research/cases/cn-nominal/origin_history.json").read_text(encoding="utf-8"))
    for rel, v in anchor["files"].items():
        assert _git(ROOT, "hash-object", rel) == v["blob"], rel
        assert v["origin_commits"] == 1
    assert anchor["files"]["research/cases/cn-nominal/preregistered/2026-10-04-baseline.yaml"]["sha"].startswith("bbd0b35")


def test_an_anchored_file_changed_and_restored_here_still_fails(tmp_path, monkeypatch):
    """Restoring the anchored content does not erase the edit: this repo's history is append-only too."""
    case = _snapshot_repo(tmp_path)
    base = case / "preregistered/2026-10-04-baseline.yaml"
    original = base.read_text(encoding="utf-8")
    base.write_text("probability: 0.5\n", encoding="utf-8")
    _git(tmp_path, "commit", "-qam", "edit")
    base.write_text(original, encoding="utf-8")
    _git(tmp_path, "commit", "-qam", "restore")
    monkeypatch.chdir(tmp_path)
    c = checks.preregistration(Path("case"))
    assert c.status == "fail"
    assert any("modified in this repository after the snapshot" in m for m in c.details)
