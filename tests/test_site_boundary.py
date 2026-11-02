"""The public site build must never read private data or ship preview content."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_build_source_never_references_private_paths():
    src = (ROOT / "site/build.py").read_text(encoding="utf-8")
    assert "data/private" not in src.replace("Never reads data/private", "")
    assert "research/private" not in src


def test_public_build_has_no_synthetic_content(tmp_path):
    subprocess.run([sys.executable, str(ROOT / "site/build.py")], check=True, cwd=ROOT)
    pages = list((ROOT / "site/dist").rglob("*.html"))
    assert len(pages) >= 12   # both languages, not just the root
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert "SYNTHETIC" not in html, str(page)
