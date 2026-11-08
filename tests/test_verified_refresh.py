"""Safety tests; real bot signature acceptance is checked separately in Actions."""
import importlib.util
import urllib.error
from pathlib import Path

import pytest

from test_refresh_workflow import git, main_like_repo, write

spec = importlib.util.spec_from_file_location(
    "commit_public_refresh", Path(__file__).resolve().parents[1] / "scripts/commit_public_refresh.py")
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


@pytest.mark.parametrize("path,content", [
    ("research/cases/cn-nominal/case.yaml", "analyst\n"),
    ("research/cases/cn-nominal/updates/frozen.yaml", "rewritten\n"),
    ("data/demo/observations/cn_cpi.csv", "rewritten\n"),
])
def test_rejects_excluded_paths_and_history_rewrites(main_like_repo, monkeypatch, path, content):
    monkeypatch.chdir(main_like_repo)
    if "/updates/" in path:
        write(main_like_repo, path, "frozen\n")
        git("add", path, cwd=main_like_repo)
        git("commit", "-m", "freeze", cwd=main_like_repo)
    write(main_like_repo, path, content)
    git("add", path, cwd=main_like_repo)
    with pytest.raises(RuntimeError):
        refresh.staged_changes()


def test_rejects_deletions(main_like_repo, monkeypatch):
    monkeypatch.chdir(main_like_repo)
    git("rm", "data/demo/observations/cn_cpi.csv", cwd=main_like_repo)
    with pytest.raises(RuntimeError, match="delete"):
        refresh.staged_changes()


def test_input_movement_aborts_but_unrelated_changes_are_safe(main_like_repo, monkeypatch):
    monkeypatch.chdir(main_like_repo)
    base = refresh.git("rev-parse", "HEAD").decode().strip()
    write(main_like_repo, "README.md", "unrelated\n")
    git("add", ".", cwd=main_like_repo)
    git("commit", "-m", "docs", cwd=main_like_repo)
    refresh.check_movement(base, "HEAD")
    write(main_like_repo, "research/cases/cn-nominal/case.yaml", "new input\n")
    git("add", ".", cwd=main_like_repo)
    git("commit", "-m", "research", cwd=main_like_repo)
    with pytest.raises(RuntimeError, match="advanced"):
        refresh.check_movement(base, "HEAD")


class API:
    def __init__(self, verified=True, race=False):
        self.verified, self.race, self.calls = verified, race, []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/git/blobs":
            return {"sha": "blob"}
        if path.startswith("/git/commits/"):
            return {"tree": {"sha": "base-tree"}}
        if path == "/git/trees":
            return {"sha": "tree"}
        if path == "/git/commits":
            assert set(body) == {"message", "tree", "parents"}
            return {"sha": "commit"}
        if path == "/commits/commit":
            return {"committer": {"login": "github-actions[bot]"}, "commit": {"verification": {
                "verified": self.verified, "reason": "valid" if self.verified else "unsigned"}}}
        if method == "PATCH":
            assert body["force"] is False
            if self.race:
                raise urllib.error.HTTPError(path, 422, "non-fast-forward", {}, None)
            return {}
        raise AssertionError(path)


def test_atomic_tree_and_signature_gate(monkeypatch):
    monkeypatch.setattr(refresh, "current_head", lambda branch: "head")
    monkeypatch.setattr(refresh, "check_movement", lambda *args: None)
    changes = [("a", b"one"), ("b", b"two")]
    api = API()
    assert refresh.publish(api, "test", "message", "base", changes) == "commit"
    trees = [body for method, path, body in api.calls if path == "/git/trees"]
    assert len(trees) == 1 and len(trees[0]["tree"]) == 2
    api = API(verified=False)
    with pytest.raises(RuntimeError, match="unverified"):
        refresh.publish(api, "test", "message", "base", changes)
    assert not any(method == "PATCH" for method, _, _ in api.calls)


def test_branch_races_retry_bounded_without_duplicate_blobs(monkeypatch):
    heads = iter(["one", "two", "two", "three", "three", "four"])
    monkeypatch.setattr(refresh, "current_head", lambda branch: next(heads))
    monkeypatch.setattr(refresh, "check_movement", lambda *args: None)
    api = API(race=True)
    with pytest.raises(RuntimeError, match="kept advancing"):
        refresh.publish(api, "test", "message", "base", [("a", b"one")])
    assert sum(path == "/git/blobs" for _, path, _ in api.calls) == 1
    assert sum(method == "PATCH" for method, _, _ in api.calls) == 3


def test_no_change_never_contacts_github(main_like_repo, monkeypatch):
    monkeypatch.chdir(main_like_repo)
    monkeypatch.setattr(refresh, "GitHub", lambda: pytest.fail("API called for no change"))
    refresh.main()
