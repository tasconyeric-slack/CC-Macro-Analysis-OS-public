"""Render the raster brand assets from their sources. Development tool only: the site build does not
run it, and the PNGs are committed. Needs `pip install playwright` and a Chromium.

    python site/assets-src/render_assets.py
"""
import os
import struct
from pathlib import Path

from playwright.sync_api import sync_playwright

SRC = Path(__file__).resolve().parent
OUT = SRC.parent / "static"


def ico_from_png(png: bytes, size: int) -> bytes:
    """A one-image .ico that embeds the PNG as is (supported by every current browser)."""
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(png), 6 + 16)
    return header + entry + png


with sync_playwright() as p:
    # CHROMIUM=/path/to/chrome lets a machine whose Playwright build does not match its browser use the one it has
    b = p.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
    for lang in ("en", "zh"):
        pg = b.new_page(viewport={"width": 1200, "height": 630})
        pg.goto(f"file://{SRC / 'og.html'}#{lang}")
        pg.screenshot(path=str(OUT / f"og-{lang}.png"))
    svg = (OUT / "favicon.svg").read_text(encoding="utf-8")
    for name, px in (("favicon-32.png", 32), ("apple-touch-icon.png", 180)):
        pg = b.new_page(viewport={"width": px, "height": px})
        pg.set_content(f'<body style="margin:0;background:transparent">{svg.replace("<svg ", f"<svg width=\"{px}\" height=\"{px}\" ")}</body>')
        pg.screenshot(path=str(OUT / name), omit_background=True)
    b.close()
(OUT / "favicon.ico").write_bytes(ico_from_png((OUT / "favicon-32.png").read_bytes(), 32))
print("wrote", sorted(p.name for p in OUT.glob("*.png")) + ["favicon.ico"])
