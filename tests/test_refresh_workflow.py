"""The scheduled public refresh stages its new artifacts with `git add` in an unattended job.

Two requirements, both checked by running the commit step's own staging script (read from the workflow
file, in the runner's shell) against a repository laid out like main:

* it must not fail when the append-only research/cases/cn-nominal/refreshes/ and updates/ directories do
  not exist (git fails a pathspec that matches nothing, which broke the scheduled `no_new_data` run);
* it must stage ONLY what a refresh writes: observation files, the eval report, refresh records and
  update records. The rest of the case root is analyst-controlled and a bot must never auto-commit it.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/refresh.yml"
STEP = "Commit new public artifacts"
CASE = "research/cases/cn-nominal"
# where a refresh writes; everything staged must be under one of these
OUTPUT_ROOTS = ("data/demo/observations/", f"{CASE}/eval/", f"{CASE}/refreshes/", f"{CASE}/updates/")
# representative analyst/research-controlled files under the same case root, tracked on main
ANALYST_FILES = {
    f"{CASE}/case.yaml": "id: cn-nominal\n",
    f"{CASE}/preregistered/2026-10-04-baseline.yaml": "frozen: true\n",
    f"{CASE}/preregistered/2026-10-04-amendment-01-terminal-rules.yaml": "amends: baseline\n",
    f"{CASE}/baseline_draft.yaml": "draft: true\n",
    f"{CASE}/claims.jsonl": '{"id": "C1"}\n',
    f"{CASE}/presentation.yaml": "layout: default\n",
    f"{CASE}/frozen_zh.yaml": "zh: frozen\n",
    f"{CASE}/policy_events.yaml": "events: []\n",
    f"{CASE}/memo.en.md.j2": "memo\n",
}

pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="bash not available")


def commit_step_script() -> str:
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["refresh"]["steps"]
    (step,) = [s for s in steps if s.get("name") == STEP]
    return step["run"]


def staging_script() -> str:
    """The step up to where it decides whether anything was staged."""
    script, marker = commit_step_script(), "if git diff --cached --quiet"
    assert marker in script
    return script.split(marker)[0]


def clean_env():
    return {k: v for k, v in os.environ.items() if k not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"}}


def git(*args, cwd, check=True):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "commit.gpgsign=false", *args],
                          cwd=cwd, env=clean_env(), capture_output=True, text=True, check=check)


def write(repo: Path, rel: str, text: str = "x\n"):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def run_script(repo: Path, script: str):
    (repo / "step.sh").write_text(script, encoding="utf-8", newline="\n")
    return subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "step.sh"], cwd=repo,
                          env=clean_env(), capture_output=True, text=True)


def staged(repo: Path) -> set[str]:
    return set(git("diff", "--cached", "--name-only", cwd=repo).stdout.split())


@pytest.fixture
def main_like_repo(tmp_path):
    """The tracked layout of main: observations, the eval report, and the analyst-controlled case files,
    with no refreshes/ or updates/ directory (nothing has been refreshed yet)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    (repo / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/check_secrets.py", repo / "scripts/check_secrets.py")
    write(repo, "data/demo/observations/cn_cpi.csv", "metric_id,value\ncn_cpi_yoy,0.8\n")
    write(repo, f"{CASE}/eval/latest.json", "{}\n")
    for rel, text in ANALYST_FILES.items():
        write(repo, rel, text)
    write(repo, ".gitignore", "step.sh\n")   # the harness's own script, not part of the layout under test
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "main", cwd=repo)
    assert not (repo / CASE / "refreshes").exists() and not (repo / CASE / "updates").exists()
    return repo


@pytest.mark.parametrize("present", [(), ("refreshes",), ("updates",)], ids=["neither", "only-refreshes", "only-updates"])
def test_staging_succeeds_when_refreshes_or_updates_directory_is_absent(main_like_repo, present):
    for name in present:   # an empty directory: present, but with nothing new in it
        (main_like_repo / CASE / name).mkdir()
    done = run_script(main_like_repo, staging_script())
    assert done.returncode == 0, done.stdout + done.stderr
    assert "did not match any files" not in done.stderr
    assert staged(main_like_repo) == set()   # nothing new: nothing staged
    for name in ("refreshes", "updates"):
        assert (main_like_repo / CASE / name).exists() == (name in present)   # no placeholder directories created


def test_no_new_data_reports_nothing_to_commit_and_exits_zero(main_like_repo):
    """The step as GitHub runs it (`bash -eo pipefail`), up to where it would build the commit message."""
    script = commit_step_script()
    assert "MSG=$(" in script, "the commit message is built after the no-data exit"
    done = run_script(main_like_repo, script.split("MSG=$(")[0])
    assert done.returncode == 0, done.stdout + done.stderr
    assert "No new public data; nothing to commit." in done.stdout


def test_new_refresh_outputs_are_staged(main_like_repo):
    write(main_like_repo, "data/demo/observations/cn_cpi_2026-10-14.csv", "metric_id,value\ncn_cpi_yoy,0.9\n")
    write(main_like_repo, f"{CASE}/refreshes/2026-10-14T0200Z.json", "{}\n")
    write(main_like_repo, f"{CASE}/updates/2026-10-14-update.yaml", "terminal: false\n")
    write(main_like_repo, f"{CASE}/eval/latest.json", '{"changed": true}\n')
    done = run_script(main_like_repo, staging_script())
    assert done.returncode == 0, done.stdout + done.stderr
    assert staged(main_like_repo) == {"data/demo/observations/cn_cpi_2026-10-14.csv",
                                      f"{CASE}/refreshes/2026-10-14T0200Z.json",
                                      f"{CASE}/updates/2026-10-14-update.yaml",
                                      f"{CASE}/eval/latest.json"}


def test_nothing_outside_the_refresh_outputs_is_ever_staged(main_like_repo):
    # a legitimate refresh output, so the step has real work to do ...
    write(main_like_repo, "data/demo/observations/cn_cpi_2026-10-14.csv", "metric_id,value\ncn_cpi_yoy,0.9\n")
    write(main_like_repo, f"{CASE}/refreshes/2026-10-14T0200Z.json", "{}\n")
    # ... alongside the job's scratch output and private data
    write(main_like_repo, "refresh-summary.json", "{}\n")
    write(main_like_repo, "data/private/observations/wind_x.csv", "secret\n")
    write(main_like_repo, "research/private/notes.md", "secret\n")
    # ... and accidental edits, deletions and additions across the analyst-controlled case files
    for rel in ANALYST_FILES:
        write(main_like_repo, rel, "tampered\n")
    (main_like_repo / f"{CASE}/memo.en.md.j2").unlink()
    write(main_like_repo, f"{CASE}/preregistered/2026-10-15-amendment-02.yaml", "new: true\n")
    write(main_like_repo, f"{CASE}/notes.md", "scratch\n")
    write(main_like_repo, f"{CASE}/claims.new.jsonl", "{}\n")

    done = run_script(main_like_repo, staging_script())
    assert done.returncode == 0, done.stdout + done.stderr
    now = staged(main_like_repo)
    assert now == {"data/demo/observations/cn_cpi_2026-10-14.csv", f"{CASE}/refreshes/2026-10-14T0200Z.json"}
    assert all(p.startswith(OUTPUT_ROOTS) for p in now), now
    # the guard above is the allowed set; these name what it protects
    assert not now & set(ANALYST_FILES) and "refresh-summary.json" not in now
    assert not any(p.startswith(("data/private/", "research/private/")) for p in now)


def test_generated_secret_blocks_refresh_commit(main_like_repo):
    write(main_like_repo, "data/demo/observations/new.csv", "api_key = " + "x" * 24)
    done = run_script(main_like_repo, staging_script())
    assert done.returncode != 0
    assert "possible credential assignment" in done.stdout
