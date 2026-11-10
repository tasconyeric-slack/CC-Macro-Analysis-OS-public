"""Guardrails for the Vercel preview checkpoint on Codex-authored PRs.

The actual GitHub signing / Vercel acceptance is an integration behavior, not
something local tests can fake with an invented verification response.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/codex-verified-preview.yml"
CHECKS = ROOT / ".github/workflows/checks.yml"


def test_only_trusted_same_repo_codex_prs_can_get_checkpoints():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "head.repo.full_name == github.repository" in text
    assert "head.repo.id !== context.payload.repository.id" in text
    assert "startsWith(github.event.pull_request.head.ref, 'codex/')" in text
    assert "startsWith(github.event.pull_request.head.ref, 'claude/')" in text
    assert "pr.base.ref !== \"main\"" in text
    assert "actions/checkout" not in text
    assert "exec(" not in text
    assert "eval(" not in text


def test_checkpoint_is_verified_before_non_forced_update():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "originalSha !== pr.head.sha" in text
    assert "original.data.verification?.verified === true" in text
    assert "tree: original.data.tree.sha" in text
    assert "parents: [originalSha]" in text
    assert "github.rest.git.createCommit" in text
    assert "github.rest.repos.getCommit" in text
    assert "proof?.verified !== true" in text
    assert 'proof.reason !== "valid"' in text
    assert 'signed.data.author?.login !== "github-actions[bot]"' in text
    assert "signed.data.commit.tree.sha !== original.data.tree.sha" in text
    assert "force: false" in text
    assert "force: true" not in text


def test_signed_checkpoint_receives_fresh_checks():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    checks = CHECKS.read_text(encoding="utf-8")
    assert 'workflow_id: "checks.yml"' in workflow
    assert "workflow_dispatch:" in checks
    assert "actions: write" in workflow
    assert "types: [opened, reopened, ready_for_review]" in checks
