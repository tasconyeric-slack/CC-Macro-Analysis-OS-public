"""python -m cnmacro.views compare [--case DIR] [--to REFRESH] [--json OUT] [--md OUT] [--lang en|zh]

Read-only. Prints the Markdown comparison when no output file is given. Exits 1 if an
external-view file fails validation (bad records are never shown)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .compare import build_comparison, render_markdown

ROOT = Path(__file__).resolve().parents[3]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m cnmacro.views")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("compare", help="latest signed view vs. the evidence in the refresh records since")
    s.add_argument("--case", default=str(ROOT / "research/cases/cn-nominal"))
    s.add_argument("--to", dest="to_refresh", help="compare up to this refresh record (file name); default latest")
    s.add_argument("--external", default=str(ROOT / "data/external/views"))
    s.add_argument("--access", default=str(ROOT / "data/external/access.yaml"))
    s.add_argument("--json", help="write the comparison object here")
    s.add_argument("--md", help="write the Markdown rendering here")
    s.add_argument("--lang", choices=["en", "zh"], default="en")
    a = p.parse_args(argv)
    c = build_comparison(a.case, to_refresh=a.to_refresh, external_dir=a.external, access_file=a.access)
    if a.json:
        Path(a.json).write_text(json.dumps(c, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if a.md:
        Path(a.md).write_text(render_markdown(c, a.lang), encoding="utf-8")
    if not a.json and not a.md:
        sys.stdout.write(render_markdown(c, a.lang))
    for e in c["external"]["errors"]:
        print(f"external view rejected: {e}", file=sys.stderr)
    return 1 if c["external"]["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
