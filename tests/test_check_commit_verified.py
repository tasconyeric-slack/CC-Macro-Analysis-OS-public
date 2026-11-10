"""Classification logic of the pre-deploy commit verification check.

These feed GitHub-shaped commit objects to the pure classifier; they do not claim
anything about what GitHub would actually verify (that is observed live).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_commit_verified as check  # noqa: E402


def commit(verified, reason, author="someone", committer="someone"):
    return {"sha": "a" * 40, "author": {"login": author}, "committer": {"login": committer},
            "commit": {"message": "subject\n\nbody",
                       "verification": {"verified": verified, "reason": reason}}}


def test_github_verified_commit_passes():
    status, report = check.assess(commit(True, "valid", "github-actions[bot]", "web-flow"))
    assert status == "verified" and report.startswith("VERIFIED")


def test_unsigned_commit_reports_path_and_next_steps_without_retry_advice():
    status, report = check.assess(commit(False, "unsigned"))
    assert status == "unsigned"
    assert "pushed from a git client" in report
    assert "author=someone committer=someone" in report
    assert "Do not retry" in report and "Require Verified Commits" in report


def test_verified_with_non_valid_reason_is_not_accepted():
    assert check.assess(commit(True, "unknown_key"))[0] == "unsigned"
    assert check.assess(commit(False, "invalid", committer="web-flow"))[0] == "unsigned"


def test_missing_verification_block_fails_closed():
    status, _ = check.assess({"sha": "b" * 40, "commit": {"message": "x"}})
    assert status == "unsigned"
