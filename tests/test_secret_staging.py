"""The pre-commit check must inspect the index, not later working-tree edits."""
import shutil
import subprocess
from pathlib import Path


def test_staged_secret_cannot_be_hidden_by_unstaged_edit(tmp_path):
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / 'scripts').mkdir()
    shutil.copy(root / 'scripts/check_secrets.py', tmp_path / 'scripts/check_secrets.py')
    target = tmp_path / 'sample.txt'
    target.write_text('api_key = ' + 'x' * 24, encoding='utf-8')
    subprocess.run(['git', 'add', 'sample.txt'], cwd=tmp_path, check=True)
    target.write_text('clean', encoding='utf-8')
    result = subprocess.run(['python3', 'scripts/check_secrets.py', '--staged'], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'possible credential assignment' in result.stdout


def test_rename_into_private_directory_is_rejected(tmp_path):
    """A rename is R100, not A/M: staged scans must inspect the new path."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "config", "user.name", "CI Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "ci@example.invalid"], cwd=tmp_path, check=True)
    (tmp_path / "scripts").mkdir()
    shutil.copy(Path(__file__).resolve().parents[1] / "scripts/check_secrets.py",
                tmp_path / "scripts/check_secrets.py")
    old = tmp_path / "benign.txt"
    old.write_text("ordinary fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "benign.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=tmp_path, check=True)
    (tmp_path / "data/private").mkdir(parents=True)
    subprocess.run(["git", "mv", "benign.txt", "data/private/exposed.txt"], cwd=tmp_path, check=True)
    result = subprocess.run(
        ["python3", "scripts/check_secrets.py", "--staged"],
        cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "file under data/private" in result.stdout
